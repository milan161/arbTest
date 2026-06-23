import logging
import re
import time
from typing import List, Dict, Any, Optional
from arbcore.fetchers.realtime import RealtimeMarketManager
from arbcore.fetchers.historical import HistoricalDataManager
from arbcore.fetchers.ib_reader import IBReader
from arbcore.fetchers.futu_reader import FutuReader

logger = logging.getLogger(__name__)

# 美股 ETF 代码模式（纯字母，2-6个字符）
US_SYMBOL_PATTERN = re.compile(r'^[A-Z]{2,6}$')

class MarketDataService:
    # [V10.1] 熔断器：连续失败 N 次后自动 disabled
    CIRCUIT_BREAKER_THRESHOLD = 5

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
            # [V10.11] 非夜盘时段直接跳过，避免无限刷"IB正在获取"日志
            if self.ib_reader and hasattr(self.ib_reader, 'is_us_night_session'):
                if not self.ib_reader.is_us_night_session():
                    return None
            # [V10.1] 熔断检查
            if self._circuit_is_tripped('IB'):
                logger.debug(f"🔴 IB 已熔断，跳过 {symbol}")
                return None

            # 1. 尝试从 IB 获取
            if self.ib_reader and self.ib_reader.connected:
                # 直接访问IBReader的prices字典
                prices = getattr(self.ib_reader, 'prices', {})
                if symbol in prices and prices[symbol]:
                    price_data = prices[symbol]
                    bid = price_data.get('bid', 0) if isinstance(price_data, dict) else 0
                    ask = price_data.get('ask', 0) if isinstance(price_data, dict) else 0
                    if bid > 0:
                        self._circuit_record_success('IB')
                        return {
                            'symbol': symbol,
                            'price': price_data.get('last', bid) if price_data.get('last', 0) > 0 else bid,
                            'bid': bid,
                            'ask': ask if ask > 0 else bid,
                            'amount': price_data.get('bid_size', 0) if isinstance(price_data, dict) else 0,
                            'source': 'IB'
                        }
                # IB已连接但prices中没有该symbol，启动轮询线程获取数据
                if not getattr(self.ib_reader, 'running', False):
                    self.ib_reader.start_polling()
                logger.info(f"⏳ IB正在获取{symbol}，请稍后...")
                return None
            elif self.ib_reader and not self.ib_reader.connected:
                # [V10.12] IB 未连接不算失败（用户尚未点击连接按钮），不触发熔断
                logger.debug(f"⚠️ IB未连接（待手动连接），美股ETF{symbol}尝试回退至富途")
            else:
                logger.debug(f"⚠️ IB Reader未初始化，美股ETF{symbol}尝试回退至富途")
            
            # 2. [NEW] IB 不可用时，兜底尝试富途
            if self.futu_reader:
                # [V10.1] 熔断检查
                if self._circuit_is_tripped('富途'):
                    logger.debug(f"🔴 富途已熔断，跳过兜底 {symbol}")
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
                            'source': '富途(兜底)'
                        }
                    else:
                        self._circuit_record_failure('富途')
                        # [V10.1] 去重：同一 symbol 300 秒内只记一次 warning
                        now = time.time()
                        last_warn = self._futu_warn_cooldown.get(symbol, 0)
                        if now - last_warn > 300:
                            logger.warning(f"⚠️ 富途兜底获取{symbol}失败: {msg}")
                            self._futu_warn_cooldown[symbol] = now
                except Exception as e:
                    self._circuit_record_failure('富途')
                    logger.error(f"⚠️ 富途兜底获取{symbol}异常: {e}")
            return None # [FIX] 无论如何，美股不能继续往下走A股引擎
                    
        elif source == 'FUTU':
            # [V10.1] 熔断检查
            if self._circuit_is_tripped('富途'):
                logger.debug(f"🔴 富途已熔断，跳过 {symbol}")
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
                        self._circuit_record_failure('富途')
                        # [V10.1] 去重：同一 symbol 300 秒内只记一次 warning
                        now = time.time()
                        last_warn = self._futu_warn_cooldown.get(f'futu_{symbol}', 0)
                        if now - last_warn > 300:
                            logger.warning(f"⚠️ 富途获取{symbol}失败: {msg}")
                            self._futu_warn_cooldown[f'futu_{symbol}'] = now
                except Exception as e:
                    self._circuit_record_failure('富途')
                    # [V10.1] 异常也加去重
                    now = time.time()
                    last_err = self._futu_warn_cooldown.get(f'futu_err_{symbol}', 0)
                    if now - last_err > 300:
                        logger.error(f"⚠️ 富途获取{symbol}异常: {e}")
                        self._futu_warn_cooldown[f'futu_err_{symbol}'] = now
            return None # [FIX] 无论如何，美股不能继续往下走A股引擎
        
        # A股/港股/期货从RealtimeMarketManager获取
        if symbol not in self.realtime_manager.symbols:
            self.realtime_manager.subscribe([symbol])
            
        return self.realtime_manager.get_quote(symbol)

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
        # 实时检测富途 OpenD 端口的真实连接状态（避免因 IB 优先级高未触发富途连接而导致状态不显示的问题）
        if self.futu_reader is not None and not any("富途" in s for s in sources):
            import socket
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.1)
                is_futu_online = (sock.connect_ex((self.futu_reader.host, self.futu_reader.port)) == 0)
                sock.close()
                if is_futu_online:
                    sources.append("富途 (Ready)")
            except:
                pass
        return sources
