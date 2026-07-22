import logging
import re
import time
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
            self.futu_reader = FutuReader()
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
        
        # 启动实时引擎（A股数据源）
        # [V4.2] 移至 lifespan 异步启动，避免与 TradingService 冲突
        # self.realtime_manager.start()

    # ── 熔断器方法 ──
    def _circuit_is_tripped(self, source_key: str) -> bool:
        """检查数据源是否被熔断"""
        return source_key in self._source_tripped

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
        
        from arbcore.config.symbol_source_map import get_symbol_source
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
                    # [AI-2026-07-07] 无买一卖一但有最近成交价时使用成交价（INDA夜盘低流动性）
                    if last > 0 and bid <= 0:
                        self._circuit_record_success('IB')
                        return {
                            'symbol': symbol,
                            'price': last,
                            'bid': last,
                            'ask': last,
                            'amount': 0,
                            'source': 'IB(最近成交价)'
                        }
                    if bid > 0:
                        # bid==ask 说明没有有效价差，返回 None 让前端显示"—"而非错误价格
                        if bid == ask:
                            logger.debug(f"[MDS] {symbol} bid=ask={bid}，无有效价差，跳过")
                            return None
                        self._circuit_record_success('IB')
                        return {
                            'symbol': symbol,
                            'price': price_data.get('last', bid) if price_data.get('last', 0) > 0 else bid,
                            'bid': bid,
                            'ask': ask if ask > 0 else bid,
                            'amount': price_data.get('bid_size', 0) if isinstance(price_data, dict) else 0,
                            'source': 'IB'
                        }
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
                        self._circuit_record_success('富途')
                        quote = prices[symbol]
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        last = quote.get('last', 0)
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
                        self._circuit_record_success('富途')
                        quote = prices[symbol]
                        bid = quote.get('bid', 0)
                        ask = quote.get('ask', 0)
                        last = quote.get('last', 0)
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
                    # hf_ 格式: 昨收盘,今开,最高,最低,最新价,成交量,持仓量,结算价,昨结算,涨跌,涨跌幅
                    if len(parts) >= 8:
                        price = float(parts[4]) if parts[4] else 0.0
                        if price > 0:
                            last_price = price
                            used_symbol = t
                            break

            if last_price > 0:
                source = '新浪 hf_' if used_symbol == symbol else f'新浪 hf_({used_symbol})'
                logger.debug(f"[MDS] {symbol} 最新价 {last_price} (来源 {source})")
                return {
                    'symbol': symbol,
                    'price': last_price,
                    'bid': last_price,
                    'ask': last_price,
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
