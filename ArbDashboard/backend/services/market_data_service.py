import os
import logging
import re
import time
import threading
from typing import List, Dict, Any, Optional
from arbcore.fetchers.realtime import RealtimeMarketManager
from arbcore.fetchers.historical import HistoricalDataManager
from arbcore.fetchers.ib_reader import IBReader
from arbcore.fetchers.futu_reader import FutuReader
from arbcore.fetchers.data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

# 美股 ETF 代码模式（纯字母，2-6个字符）
US_SYMBOL_PATTERN = re.compile(r'^[A-Z]{2,6}$')

class MarketDataService:
    # [V10.1] 熔断器：连续失败 N 次后自动 disabled
    CIRCUIT_BREAKER_THRESHOLD = 2

    def __init__(self, db_manager):
        self.db = db_manager
        # 初始化管理器
        self.realtime_manager = RealtimeMarketManager(db_manager=db_manager)
        self.historical_manager = HistoricalDataManager(db_manager=db_manager)
        
        # [FIX] 初始化 IB Reader（用于美股ETF实时行情）
        self.ib_reader = None
        # [AI-2026-08-02] 看板模式不连 IB（美股走 OpenD 内网），直接置 None 省资源且明确无 IB 源
        if os.environ.get('ARB_DASHBOARD_MODE', '0') == '1':
            logger.info("[DASHBOARD_MODE] IB Reader 已禁用（看板美股走 OpenD）")
        else:
            try:
                # [V10.0] IBReader 启动时不自动连接，用户点击页面"IB"按钮才重连
                self.ib_reader = IBReader(db_manager=db_manager)
                logger.info("IB Reader 已初始化，待用户手动连接")
            except Exception as e:
                logger.warning(f"IB Reader 初始化失败: {e}")
                self.ib_reader = None
        
        # [NEW] 初始化富途 Reader（IB 的备用数据源）
        self.futu_reader = None
        try:
            # [V10.0] FutuReader 启动时不自动连接，用户点击页面"富途"按钮才重连
            # [AI-2026-08-02] 云端看板模式：富途 OpenD 地址经 FUTU_HOST 环境变量覆盖（默认本地 127.0.0.1，ARM 设 10.0.0.83 走内网）
            futu_host = os.environ.get('FUTU_HOST', '127.0.0.1')
            self.futu_reader = FutuReader(host=futu_host)
            logger.info("富途 Reader 已初始化，待用户手动连接")
        except Exception as e:
            logger.warning(f"富途 Reader 初始化失败: {e}")
            self.futu_reader = None

        # [白银] 初始化 DataFetcher（新浪数据源）
        self.data_fetcher = DataFetcher()
        
        # [V10.1] 富途兜底日志去重：每 symbol 每 300 秒最多记一次 warning
        self._futu_warn_cooldown: Dict[str, float] = {}

        # [V10.1] 熔断器状态：{source_key: consecutive_failures}
        self._source_failures: Dict[str, int] = {}
        # [V10.1] 熔断器冷却：{source_key: tripped_at_timestamp}
        self._source_tripped: Dict[str, float] = {}

        # [AI-2026-08-03] 云端看板模式（ARM 无人值守）：富途必须自动连接且断线自愈。
        # 原实现只在启动时 reconnect 一次，OpenD 若晚起/重启/掉线就永久 disabled，无人可点按钮 → 看板实时源全废。
        # 改为常驻守护线程：巡检 disabled/connected，掉线即重连（重连前顺带清富途熔断），失败指数退避。
        # 必须放在熔断器状态字典初始化之后（守护线程会调用 _circuit_reset）。
        if os.environ.get('ARB_DASHBOARD_MODE', '0') == '1' and self.futu_reader is not None:
            threading.Thread(target=self._futu_autoconnect_loop, daemon=True,
                             name='futu-autoconnect').start()
            logger.info("[DASHBOARD_MODE] 富途 OpenD 自动连接守护线程已启动（断线自愈）")
        
        # 启动实时引擎（A股数据源）
        # [V4.2] 移至 lifespan 异步启动，避免与 TradingService 冲突
        # self.realtime_manager.start()

    # ── [AI-2026-08-03] 富途 OpenD 自动连接守护（仅 ARB_DASHBOARD_MODE=1 无头看板启用）──
    FUTU_AUTOCONNECT_OK_INTERVAL = 60    # 连接健康时的巡检间隔（秒）
    FUTU_AUTOCONNECT_MIN_BACKOFF = 30    # 重连失败首次退避（秒）
    FUTU_AUTOCONNECT_MAX_BACKOFF = 300   # 重连失败最大退避（秒）

    def _futu_autoconnect_loop(self):
        """常驻守护：保证无人值守环境下富途 OpenD 始终在线。

        触发重连的两种情况：
          1) 启动时 OpenD 尚未就绪（reconnect 失败被置 disabled）
          2) 运行中 OpenD 重启/网络抖动（get_prices 异常把 connected 置 False 或 disabled 置 True）
        重连前必须先清富途熔断，否则连上了也会被 _circuit_is_tripped 挡住取不到价。
        """
        backoff = self.FUTU_AUTOCONNECT_MIN_BACKOFF
        while True:
            try:
                reader = self.futu_reader
                if reader is None:
                    time.sleep(self.FUTU_AUTOCONNECT_OK_INTERVAL)
                    continue

                healthy = (not getattr(reader, 'disabled', True)) and getattr(reader, 'connected', False)
                if healthy:
                    backoff = self.FUTU_AUTOCONNECT_MIN_BACKOFF
                    time.sleep(self.FUTU_AUTOCONNECT_OK_INTERVAL)
                    continue

                self._circuit_reset('富途')
                ok, msg = reader.reconnect()
                if ok:
                    backoff = self.FUTU_AUTOCONNECT_MIN_BACKOFF
                    logger.info(f"[DASHBOARD_MODE] 富途 OpenD 自动连接成功: {msg}")
                    time.sleep(self.FUTU_AUTOCONNECT_OK_INTERVAL)
                else:
                    logger.warning(f"[DASHBOARD_MODE] 富途 OpenD 自动连接失败: {msg}；{backoff}s 后重试")
                    time.sleep(backoff)
                    backoff = min(backoff * 2, self.FUTU_AUTOCONNECT_MAX_BACKOFF)
            except Exception as e:
                logger.warning(f"[DASHBOARD_MODE] 富途自动连接守护异常: {e}")
                time.sleep(self.FUTU_AUTOCONNECT_MAX_BACKOFF)

    # ── 熔断器方法 ──
    # [AI-2026-08-03] 熔断半开：原实现一旦 tripped 就 return None 永不再试，
    # 也就永远等不到 _circuit_record_success 复位 → 无人值守环境等同永久失明。
    # 超过冷却时长后自动放行一次（半开），成功则由 _circuit_record_success 彻底恢复。
    CIRCUIT_HALF_OPEN_SEC = 180

    def _circuit_is_tripped(self, source_key: str) -> bool:
        """检查数据源是否被熔断（超过冷却时长自动半开重试）"""
        tripped_at = self._source_tripped.get(source_key)
        if tripped_at is None:
            return False
        if time.time() - tripped_at >= self.CIRCUIT_HALF_OPEN_SEC:
            self._source_failures.pop(source_key, None)
            self._source_tripped.pop(source_key, None)
            logger.info(f"🟡 [半开] {source_key} 熔断冷却 {self.CIRCUIT_HALF_OPEN_SEC}s 到期，放行重试")
            return False
        return True

    def _circuit_record_failure(self, source_key: str):
        """记录一次失败，达到阈值则熔断"""
        self._source_failures[source_key] = self._source_failures.get(source_key, 0) + 1
        if self._source_failures[source_key] >= self.CIRCUIT_BREAKER_THRESHOLD:
            self._source_tripped[source_key] = time.time()
            logger.warning(f"🔴 [熔断] {source_key} 连续失败 {self._source_failures[source_key]} 次，已自动禁用")

    def _circuit_record_success(self, source_key: str):
        """记录一次成功，重置失败计数"""
        self._source_failures.pop(source_key, None)
        # 如果之前被熔断，现在恢复
        if source_key in self._source_tripped:
            del self._source_tripped[source_key]
            logger.info(f"🟢 [恢复] {source_key} 已恢复正常")

    def _circuit_reset(self, source_key: str):
        """手动重置熔断器（用户点击重连按钮时调用）"""
        self._source_failures.pop(source_key, None)
        self._source_tripped.pop(source_key, None)
        logger.info(f"🔄 [重置] {source_key} 熔断器已重置")

    def get_circuit_status(self) -> Dict[str, Any]:
        """获取所有数据源的熔断状态"""
        return {
            'threshold': self.CIRCUIT_BREAKER_THRESHOLD,
            'failures': dict(self._source_failures),
            'tripped': {k: v for k, v in self._source_tripped.items()},
        }

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情
        
        [统一格式] 处理完整符号（如 ^INDA-EU → INDA）
        - 去掉 ^ 前缀
        - 去掉 -EU, -JP, -HK 等地区后缀
        """
        import datetime
        from arbcore.utils import is_a_share_trading_day
        # [V10.4] A 股休市日（含法定节假日）不获取实时数据
        if not is_a_share_trading_day():
            return None
            
        symbol = symbol.strip().upper().lstrip('^')
        # 去掉地区后缀（如 -EU, -JP, -HK）
        for suffix in ['-EU', '-JP', '-HK']:
            if symbol.endswith(suffix):
                symbol = symbol[:-len(suffix)]
                break
        
        from arbcore.config.source_routing import get_symbol_source
        source = get_symbol_source(symbol)
        
        # [FIX] 根据 source 决定是否走美股通道
        if source == 'IB':
            # 判断当前是否为 IB 夜盘时段（IB 仅在夜盘有免费实时数据）
            is_ib_night = False
            if self.ib_reader and hasattr(self.ib_reader, 'is_us_night_session'):
                is_ib_night = self.ib_reader.is_us_night_session()
            # [V10.1] 熔断检查
            if self._circuit_is_tripped('IB'):
                logger.debug(f"🔴 IB 已熔断，跳过 {symbol}")
                return None

            # 1. 尝试从 IB 获取（仅夜盘时段，IB 没有行情订阅）
            if is_ib_night and self.ib_reader and self.ib_reader.connected:
                prices = getattr(self.ib_reader, 'prices', {})
                if symbol in prices and prices[symbol]:
                    price_data = prices[symbol]
                    bid = price_data.get('bid', 0) if isinstance(price_data, dict) else 0
                    ask = price_data.get('ask', 0) if isinstance(price_data, dict) else 0
                    last = price_data.get('last', 0) if isinstance(price_data, dict) else 0
                    # [AI-2026-08-03] 仅当长连接推送了真实盘口（买一价≠卖一价）才返回 IB 实时盘口。
                    # bid==ask 说明长连接未推送真实盘口（仅历史成交价快照或无数据），严禁把成交价
                    # 伪装成买一卖一返回（违反 014 文档红线11：禁止只保留 tickType=4 丢弃 1/2）。
                    # 无真实盘口时不返回 IB，让前端走其他数据源或显示"等待数据"，避免误导。
                    if bid > 0 and bid != ask:
                        self._circuit_record_success('IB')
                        # [AI-2026-08-03] 补齐买一/卖一盘口数量：bid_size(买一量)/ask_size(卖一量)
                        # 均来自 IB tickSize 回调写入 prices[sym]。amount 保持兼容(=买一量)。
                        bid_size = price_data.get('bid_size', 0) if isinstance(price_data, dict) else 0
                        ask_size = price_data.get('ask_size', 0) if isinstance(price_data, dict) else 0
                        return {
                            'symbol': symbol,
                            'price': last if last > 0 else bid,
                            'bid': bid,
                            'ask': ask,
                            'bid_size': bid_size,
                            'ask_size': ask_size,
                            'amount': bid_size,
                            'source': 'IB'
                        }
                    # bid==ask 或 bid<=0：无真实盘口，不返回 IB（不伪装成交价）
                # IB已连接但prices中没有该symbol，启动轮询线程
                if not getattr(self.ib_reader, 'running', False):
                    self.ib_reader.start_polling()
                now = time.time()
                if not hasattr(self, '_ib_wait_log_time'):
                    self._ib_wait_log_time = {}
                last_log = self._ib_wait_log_time.get(symbol, 0)
                if now - last_log > 30:
                    logger.info(f"⏳ IB正在获取{symbol}，请稍后...")
                    self._ib_wait_log_time[symbol] = now
                # IB 有数据但没盘口 → 不返回，继续走富途兜底
            elif not is_ib_night and self.ib_reader and self.ib_reader.connected:
                logger.debug(f"[MDS] 非夜盘时段，跳过IB直接走富途 {symbol}")
            elif self.ib_reader and not self.ib_reader.connected:
                logger.debug(f"⚠️ IB未连接（待手动连接），美股ETF{symbol}尝试回退至富途")
            else:
                logger.debug(f"⚠️ IB Reader未初始化，美股ETF{symbol}尝试回退至富途")
            
            # 2. 富途兜底（全时段可用）
            if self.futu_reader:
                if self._circuit_is_tripped('富途') or getattr(self.futu_reader, 'disabled', False):
                    # [AI-2026-07-15] 熔断或禁用状态直接跳过，避免调 get_prices 返回"禁用"产生刷屏 WARNING
                    logger.debug(f"🔴 富途已熔断/禁用，跳过兜底 {symbol}")
                    return None
                try:
                    success, msg, prices = self.futu_reader.get_prices([symbol])
                    if success and symbol in prices:
                        quote = prices[symbol]
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        last = quote.get('last', 0)
                        # [AI-2026-08-03] 富途刚连上、订阅尚未推送真实盘口时，get_prices 会返回
                        # success=True 但 bid/ask/last 全为 0。若照常返回，前端会显示“富途”来源
                        # + 0 价格/数量，误导用户（典型现象：点“富途连接”后沙盘美股盘口全 0，
                        # 几秒后 IB 接管才正常）。全 0 视为无数据，落到下方“都拿不到”分支，
                        # 与“源头不产生错价”原则一致；且不计失败，避免热身期误触发熔断。
                        if bid > 0 or ask > 0 or last > 0:
                            self._circuit_record_success('富途')
                            return {
                                'symbol': symbol,
                                'price': last if last > 0 else bid,
                                'bid': bid,
                                'ask': ask if ask > 0 else bid,
                                'amount': 0,
                                'source': '富途'
                            }
                    else:
                        # [AI-2026-07-15] 禁用状态不计数（用户未手动连接）
                        if not getattr(self.futu_reader, 'disabled', False):
                            self._circuit_record_failure('富途')
                        now = time.time()
                        last_warn = self._futu_warn_cooldown.get(symbol, 0)
                        if now - last_warn > 300:
                            logger.warning(f"⚠️ 富途兜底获取{symbol}失败: {msg}")
                            self._futu_warn_cooldown[symbol] = now
                except Exception as e:
                    if not getattr(self.futu_reader, 'disabled', False):
                        self._circuit_record_failure('富途')
                    logger.error(f"⚠️ 富途兜底获取{symbol}异常: {e}")
            
            # 3. 都拿不到数据：区分原因返回
            if is_ib_night:
                return None  # 夜盘：IB+富途都失败，正常返回None
            if self.ib_reader and self.ib_reader.connected:
                return {       # 非夜盘：IB有连接但没行情，富途也无数据
                    'symbol': symbol,
                    'price': 0,
                    'bid': None,
                    'ask': None,
                    'amount': 0,
                    'source': '非夜盘时段'
                }
            return None # [FIX] 美股不能继续往下走A股引擎
                    
        elif source == 'FUTU':
            # [V10.1] 熔断检查
            # [AI-2026-07-15] 增加 disabled 检查，避免禁用状态下调 get_prices 产生刷屏 WARNING
            if self._circuit_is_tripped('富途') or getattr(self.futu_reader, 'disabled', False):
                logger.debug(f"🔴 富途已熔断/禁用，跳过 {symbol}")
                return None
            # 直接走富途通道
            if self.futu_reader:
                try:
                    success, msg, prices = self.futu_reader.get_prices([symbol])
                    if success and symbol in prices:
                        quote = prices[symbol]
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        last = quote.get('last', 0)
                        # [AI-2026-08-03] 同 IB 分支兜底：富途全 0 视为无数据，不返回错误 0 价。
                        if bid > 0 or ask > 0 or last > 0:
                            self._circuit_record_success('富途')
                            return {
                                'symbol': symbol,
                                'price': last if last > 0 else bid,
                                'bid': bid,
                                'ask': ask if ask > 0 else bid,
                                'amount': 0,
                                'source': '富途'
                            }
                    else:
                        # [AI-2026-07-15] 禁用状态不计数（用户未手动连接）
                        if not getattr(self.futu_reader, 'disabled', False):
                            self._circuit_record_failure('富途')
                        # [V10.1] 去重：同一 symbol 300 秒内只记一次 warning
                        now = time.time()
                        last_warn = self._futu_warn_cooldown.get(f'futu_{symbol}', 0)
                        if now - last_warn > 300:
                            logger.warning(f"⚠️ 富途获取{symbol}失败: {msg}")
                            self._futu_warn_cooldown[f'futu_{symbol}'] = now
                except Exception as e:
                    if not getattr(self.futu_reader, 'disabled', False):
                        self._circuit_record_failure('富途')
                    # [V10.1] 异常也加去重
                    now = time.time()
                    last_err = self._futu_warn_cooldown.get(f'futu_err_{symbol}', 0)
                    if now - last_err > 300:
                        logger.error(f"⚠️ 富途获取{symbol}异常: {e}")
                        self._futu_warn_cooldown[f'futu_err_{symbol}'] = now
            return None # [FIX] 无论如何，美股不能继续往下走A股引擎
        
        elif source == 'SINA':
            # 国际期货（CME 微合约 MGC/MCL/MES/MNQ 等）从新浪 hf_ API 直取
            # [AI-2026-07-21] 加 NK（日经225期货）：新浪 hf_NK 有延期行情，富途无期货、IB 期货行情暂未购买
            if re.match(r'^(MGC|MCL|MES|MNQ|GC|CL|SI|HG|ES|NQ|NK)$', symbol):
                return self._get_sina_futures_quote(symbol)
            # 其他 SINA 源标的走 RealtimeMarketManager 兜底
            if symbol not in self.realtime_manager.symbols:
                self.realtime_manager.subscribe([symbol])
            return self.realtime_manager.get_quote(symbol)

        # A股/港股从RealtimeMarketManager获取
        if symbol not in self.realtime_manager.symbols:
            self.realtime_manager.subscribe([symbol])
        return self.realtime_manager.get_quote(symbol)

    # [AI-2026-08-03] 双源盘口对比（仅展示用，不改任何计算路径）。
    # 实时估值计算仍只用 IB（见 get_realtime_quote 的 IB 优先逻辑），本方法把 IB 与富途
    # 两支行情源的原始盘口都返回，供用户对比时效/准确性。富途此处不做「全0当无数据」门禁
    # （门禁只用于估值路径），以便用户看到「富途刚连上仍在热身、暂时为0」这类对比信息。
    def get_dual_quote(self, symbol: str) -> Dict[str, Any]:
        """同时返回 IB 与富途两支行情源的原始盘中盘口，供前端对比展示。

        返回: {'symbol': str, 'ib': dict|None, 'futu': dict|None}
        每张盘口: {'price','bid','ask','bid_size','ask_size'}（均无门禁，原始值）
        """
        symbol = (symbol or '').strip().upper().lstrip('^')
        for suffix in ['-EU', '-JP', '-HK']:
            if symbol.endswith(suffix):
                symbol = symbol[:-len(suffix)]
                break

        # IB 原始盘口（仅夜盘有免费实时；其余时段 prices 可能为空/滞后，原样返回供对比）
        ib_q = None
        if self.ib_reader and getattr(self.ib_reader, 'connected', False):
            prices = getattr(self.ib_reader, 'prices', {}) or {}
            d = prices.get(symbol)
            if isinstance(d, dict):
                bid = d.get('bid', 0) or 0
                ask = d.get('ask', 0) or 0
                last = d.get('last', 0) or 0
                if bid > 0 or ask > 0 or last > 0:
                    ib_q = {
                        'price': last if last > 0 else bid,
                        'bid': bid,
                        'ask': ask,
                        'bid_size': d.get('bid_size', 0) or 0,
                        'ask_size': d.get('ask_size', 0) or 0,
                    }

        # 富途原始盘口（全时段，展示对比不做门禁）
        futu_q = None
        if self.futu_reader and not getattr(self.futu_reader, 'disabled', False):
            try:
                success, _msg, prices = self.futu_reader.get_prices([symbol])
                if success and symbol in prices:
                    d = prices[symbol] or {}
                    bid = d.get('bid', 0) or 0
                    ask = d.get('ask', 0) or 0
                    last = d.get('last', 0) or 0
                    futu_q = {
                        'price': last if last > 0 else bid,
                        'bid': bid,
                        'ask': ask,
                        'bid_size': d.get('bid_size', 0) or 0,
                        'ask_size': d.get('ask_size', 0) or 0,
                    }
            except Exception as e:
                logger.debug(f"[dual] 富途获取{symbol}异常: {e}")

        return {'symbol': symbol, 'ib': ib_q, 'futu': futu_q}

    # [AI-2026-07-13] 新浪 hf_ 期货盘口直取（含微合约兜底）
    # 微合约新浪不提供直接数据，从母合约取同价（报价单位相同）
    _MICRO_TO_PARENT = {
        'MGC': 'GC',
        'MCL': 'CL',
        'MES': 'ES',
        'MNQ': 'NQ',
    }

    def _get_sina_futures_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """从新浪 hf_ API 获取 CME 期货实时数据（最新价用作 bid/ask）"""
        try:
            import requests
            headers = {'Referer': 'https://finance.sina.com.cn/'}

            # 尝试取目标合约（微合约可能为空，后续从母合约兜底）
            targets = [symbol]
            if symbol in self._MICRO_TO_PARENT:
                targets.append(self._MICRO_TO_PARENT[symbol])

            last_price = 0.0
            used_symbol = symbol
            for t in targets:
                url = f"http://hq.sinajs.cn/list=hf_{t}"
                r = requests.get(url, headers=headers, timeout=5.0, proxies={"http": None, "https": None})
                r.encoding = 'gbk'
                if r.status_code == 200 and '="' in r.text:
                    parts = r.text.split('"')[1].split(',')
                    # [AI-2026-07-23] hf_NK 实际格式（NK连续合约）:
                    # parts[0]=最新价, parts[1]=今开(空), parts[2]=最高, parts[3]=最低
                    # parts[5]=成交量, parts[9]=持仓量
                    # 注意: parts[4] 是最高价，不是最新价！
                    if len(parts) >= 1:
                        price = float(parts[0]) if parts[0] else 0.0
                        if price > 0:
                            last_price = price
                            used_symbol = t
                            break

            if last_price > 0:
                source = '新浪 hf_' if used_symbol == symbol else f'新浪 hf_({used_symbol})'
                # [AI-2026-07-23] NK 盘口: parts[3]=买价/卖价, 用于前端显示
                bid = float(parts[3]) if len(parts) > 3 and parts[3] else last_price
                ask = bid  # NK 连续合约买卖价相同
                logger.debug(f"[MDS] {symbol} 最新价 {last_price}, 买价 {bid} (来源 {source})")
                return {
                    'symbol': symbol,
                    'price': last_price,
                    'bid': bid,
                    'ask': ask,
                    'source': source
                }
            logger.warning(f"[MDS] {symbol} 新浪 hf_ 无有效最新价")
        except Exception as e:
            logger.error(f"[MDS] {symbol} 新浪 hf_ 异常: {e}")
        return None

    def get_historical_nav(self, symbol: str, **kwargs) -> List[Dict[str, Any]]:
        """获取历史净值"""
        df = self.historical_manager.get_nav(symbol, **kwargs)
        if not df.empty:
            # 转换日期格式方便前端
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            return df.to_dict(orient='records')
        return []

    def get_historical_prices(self, symbol: str, **kwargs) -> List[Dict[str, Any]]:
        """获取历史价格"""
        df = self.historical_manager.get_prices(symbol, **kwargs)
        if not df.empty:
            df['date'] = df['date'].dt.strftime('%Y-%m-%d')
            return df.to_dict(orient='records')
        return []
        
    def restart_realtime_engine(self):
        """重新启动实时引擎（通常用于配置修改后）"""
        self.realtime_manager.stop()
        # 清除旧实例，重新读配置启动
        self.realtime_manager = RealtimeMarketManager(db_manager=self.db)
        self.realtime_manager.start()
        return {"status": "ok", "message": "Realtime engine restarted with new config"}

    def get_active_source_names(self) -> List[str]:
        """获取当前活跃的数据源名称（仅返回真正已连接的）"""
        sources = []
        for name, fetcher in self.realtime_manager.active_fetchers.items():
            # 跳过 disabled（连接失败 3 次后熔断）的 fetcher
            if getattr(fetcher, 'disabled', False):
                continue
            sources.append(name)
        # 实时检测 IB 的真实连接状态
        if self.ib_reader is not None and getattr(self.ib_reader, 'connected', False) and not any("IB" in s for s in sources):
            sources.append("IB (Ready)")
        else:
            sources.append("IB (未运行)")
        # 检测富途真实数据状态：使用 connected 标志（与 IB 一致），避免旧缓存误标为 Ready
        if self.futu_reader is not None and not any("富途" in s for s in sources):
            if getattr(self.futu_reader, 'disabled', False):
                pass  # 已禁用，不加入列表 → 前端显示灰色
            elif getattr(self.futu_reader, 'connected', False):
                futu_prices = getattr(self.futu_reader, 'prices', {})
                if futu_prices and len(futu_prices) > 0:
                    sources.append("富途 (Ready)")
                else:
                    sources.append("富途 (无数据)")
            else:
                sources.append("富途 (未运行)")
        return sources
    
    # [AI-2026-07-03] 修复 SI 实时估值公式：对齐 Woody — 将 SI 转 CNY/kg 后与 AG0 昨结算比，而非直接用 SI 百分比涨跌幅
    def get_si_based_valuation(self, nav_t1: float, calibration_factor: float = 1.0, position: float = 0.95,
                                ag0_prev_settle: float = 0, ag0_realtime: float = 0) -> Optional[Dict]:
        """基于 SI 国际银价的实时估值（和 Woody GetRealtimeNetValue 一致）
        
        Woody 公式（PHP）：
            ① _RealtimeCallback():
               $fPairVal = 1000.0 * hf_SI(美元/盎司) * fx_susdcnh(汇率) / 31.1035
               将 SI 从美元/盎司转为人民币/千克，和 AG0 同单位
            ② EstFromPair():
               $fVal = QdiiGetVal($fPairVal, $fCny, $this->fFactor)
               用 calibrationhistory 校准因子映射到基金净值
            ③ FundAdjustPosition():
               return FundAdjustPosition($position, $fVal, $lastCalibrationVal)
        
        本程序实现（无 calibrationhistory 表时）：
            si_cny_per_kg = SI(USD/oz) × CNH × 1000 / 31.1035   ← 同 Woody ①
            ratio = si_cny_per_kg / ag0_prev_settle              ← 与 AG0 昨结算比
            rt_val = nav_t1 × ratio                               ← 同 AG0 参考估值逻辑
        
        Args:
            nav_t1: T-1 日基金净值
            calibration_factor: 校准因子（暂未使用，保留参数）
            position: 仓位比率（默认 0.95）
            ag0_prev_settle: AG0 昨结算价（必需！做比值基准）
            ag0_realtime: AG0 实时价格（用于参考）
        
        Returns:
            dict { 'nav', 'si_usd_oz', 'si_cny_per_kg', 'cnh_rate', 'ag0_prev_settle', 'position', 'source' } 或 None
        """
        try:
            # 1. 获取 SI 实时价格（美元/盎司）
            si_data = self.data_fetcher.fetch_si_from_sina()
            if not si_data or si_data['price'] <= 0:
                logger.warning("SI 实时价格获取失败")
                return None
            
            si_usd_oz = si_data['price']
            
            # 2. 获取 CNH 离岸汇率（和 Woody fx_susdcnh 一致）
            cnh_data = self.data_fetcher.fetch_cnh_from_sina()
            if not cnh_data or cnh_data['rate'] <= 0:
                logger.warning("CNH 汇率获取失败")
                return None
            cnh_rate = cnh_data['rate']
            
            # 3. 需要 AG0 昨结算价做比值基准
            if ag0_prev_settle <= 0:
                logger.warning("AG0 昨结算价为 0，无法计算 SI 实时估值")
                return None
            
            # 4. 把 SI 从美元/盎司转为人民币/千克（同 Woody ①）
            #    1000 g/kg × CNH ¥/$ ÷ 31.1035 g/oz = 转换因子
            si_cny_per_kg = si_usd_oz * cnh_rate * 1000.0 / 31.1035
            
            # 5. 用 SI 折算人民币价与 AG0 昨结算的比值推算净值（同参考估值逻辑）
            ratio = si_cny_per_kg / ag0_prev_settle
            rt_val = nav_t1 * ratio
            
            logger.debug(f"[SI估值] SI={si_usd_oz}$/oz CNH={cnh_rate} → {si_cny_per_kg:.2f}¥/kg "
                        f"AG0昨结算={ag0_prev_settle} ratio={ratio:.6f} NAV={nav_t1} → val={rt_val:.4f}")
            
            return {
                'nav': round(rt_val, 4),
                'si_usd_oz': si_usd_oz,
                'si_cny_per_kg': round(si_cny_per_kg, 2),
                'cnh_rate': cnh_rate,
                'ag0_prev_settle': ag0_prev_settle,
                'si_ratio': round(ratio, 6),
                'position': position,
                'source': '新浪 hf_SI + fx_susdcnh'
            }
        except Exception as e:
            logger.error(f"SI 实时估值计算失败: {e}")
            return None
