import logging
import re
from typing import List, Dict, Any, Optional
from arbcore.fetchers.realtime import RealtimeMarketManager
from arbcore.fetchers.historical import HistoricalDataManager
from arbcore.fetchers.ib_reader import IBReader
from arbcore.fetchers.futu_reader import FutuReader

logger = logging.getLogger(__name__)

# 美股 ETF 代码模式（纯字母，2-6个字符）
US_SYMBOL_PATTERN = re.compile(r'^[A-Z]{2,6}$')

class MarketDataService:
    def __init__(self, db_manager):
        self.db = db_manager
        # 初始化管理器
        self.realtime_manager = RealtimeMarketManager(db_manager=db_manager)
        self.historical_manager = HistoricalDataManager(db_manager=db_manager)
        
        # [FIX] 初始化 IB Reader（用于美股ETF实时行情）
        self.ib_reader = None
        try:
            self.ib_reader = IBReader(db_manager=db_manager)
            if self.ib_reader.connect_to_ib():
                logger.info("✅ IB Reader 已初始化，可用于美股ETF实时行情")
            else:
                logger.warning("⚠️ IB Reader 连接失败，美股ETF将无法获取实时价格")
                self.ib_reader = None
        except Exception as e:
            logger.warning(f"⚠️ IB Reader 初始化失败: {e}")
            self.ib_reader = None
        
        # [NEW] 初始化富途 Reader（IB 的备用数据源）
        self.futu_reader = None
        try:
            self.futu_reader = FutuReader()
            logger.info("✅ 富途 Reader 已初始化，作为 IB 的备用数据源")
        except Exception as e:
            logger.warning(f"⚠️ 富途 Reader 初始化失败: {e}")
            self.futu_reader = None
        
        # 启动实时引擎（A股数据源）
        # [V4.2] 移至 lifespan 异步启动，避免与 TradingService 冲突
        # self.realtime_manager.start()

    def get_realtime_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取实时行情
        
        [统一格式] 处理完整符号（如 ^INDA-EU → INDA）
        - 去掉 ^ 前缀
        - 去掉 -EU, -JP, -HK 等地区后缀
        """
        symbol = symbol.strip().upper().lstrip('^')
        # 去掉地区后缀（如 -EU, -JP, -HK）
        for suffix in ['-EU', '-JP', '-HK']:
            if symbol.endswith(suffix):
                symbol = symbol[:-len(suffix)]
                break
        
        # [FIX] 美股ETF优先从IB获取，IB失败则使用富途
        if US_SYMBOL_PATTERN.match(symbol):
            # 1. 尝试从 IB 获取
            if self.ib_reader and self.ib_reader.connected:
                # 直接访问IBReader的prices字典
                prices = getattr(self.ib_reader, 'prices', {})
                if symbol in prices and prices[symbol]:
                    price_data = prices[symbol]
                    bid = price_data.get('bid', 0) if isinstance(price_data, dict) else 0
                    ask = price_data.get('ask', 0) if isinstance(price_data, dict) else 0
                    if bid > 0:
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
                logger.debug(f"⚠️ IB未连接，美股ETF{symbol}将无法获取实时价格")
            else:
                logger.debug(f"⚠️ IB Reader未初始化，美股ETF{symbol}将无法获取实时价格")
            
            # 2. [NEW] IB 不可用时，尝试富途
            if self.futu_reader:
                try:
                    success, msg, prices = self.futu_reader.get_prices([symbol])
                    if success and symbol in prices:
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
                        logger.warning(f"⚠️ 富途获取{symbol}失败: {msg}")
                except Exception as e:
                    logger.error(f"⚠️ 富途获取{symbol}异常: {e}")
        
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
        """获取当前活跃的数据源名称"""
        sources = list(self.realtime_manager.active_fetchers.keys())
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
