import logging
import time
import threading
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher

logger = logging.getLogger(__name__)

class GuojinQmtFetcher(BaseRealtimeFetcher):
    """
    国金证券 QMT (xtquant) 实时行情抓取器。
    要求本地运行国金极速交易终端。
    """
    
    def __init__(self):
        super().__init__("Guojin_QMT")
        self.xtdata = None
        self._subscribed_symbols = set()

    def connect(self) -> bool:
        try:
            from xtquant import xtdata
            self.xtdata = xtdata
            # 尝试获取一个行情来验证连接是否真的可用
            try:
                test_tick = self.xtdata.get_full_tick(['000001.SZ'])
                if test_tick and '000001.SZ' in test_tick and test_tick['000001.SZ']:
                    self.is_connected = True
                    logger.info("✅ 国金QMT (xtquant) 适配器加载成功，连接验证通过")
                    return True
                else:
                    logger.warning("⚠️ 国金QMT xtdata 已加载但无法获取行情（QMT终端可能未启动）")
                    self.is_connected = False
                    return False
            except Exception as probe_e:
                logger.warning(f"⚠️ 国金QMT xtdata 连接验证失败（QMT终端可能未启动）: {probe_e}")
                self.is_connected = False
                return False
        except ImportError:
            logger.error("❌ 未安装 xtquant 库，请运行 'pip install xtquant'")
            return False
        except Exception as e:
            logger.error(f"❌ 国金QMT 连接异常: {e}")
            return False

    def disconnect(self):
        self.is_connected = False
        self.xtdata = None

    def subscribe(self, symbols: List[str]):
        if not self.is_connected: return
        
        qmt_symbols = [self.normalize_symbol(s) for s in symbols]
        for s in qmt_symbols:
            self.xtdata.subscribe_quote(s, period='tick', count=1, callback=self._internal_callback)
            self._subscribed_symbols.add(s)
        logger.info(f"✅ 国金QMT 已订阅: {qmt_symbols}")

    def unsubscribe(self, symbols: List[str]):
        if not self.is_connected: return
        qmt_symbols = [self.normalize_symbol(s) for s in symbols]
        for s in qmt_symbols:
            # xtquant 没有显式的单代码退订，通常是通过 subscribe 控制
            if s in self._subscribed_symbols:
                self._subscribed_symbols.remove(s)

    def _internal_callback(self, data):
        """xtquant 的内部回调处理器"""
        for symbol, tick in data.items():
            normalized_quote = self._format_tick(symbol, tick)
            if normalized_quote:
                self._notify_update(symbol.split('.')[0], normalized_quote)

    def _format_tick(self, symbol: str, tick: Any) -> Optional[Dict[str, Any]]:
        """将 xtquant 的数据结构转换为标准格式"""
        try:
            if not tick: return None
            
            # xtquant 核心字段解析
            last_price = float(tick.get('lastPrice', 0))
            pre_close = float(tick.get('lastClose', 0)) # QMT 的 lastClose 即昨日收盘价
            amount = float(tick.get('amount', 0))       # 成交额(元)
            volume = float(tick.get('volume', 0))       # 成交量(股)
            
            # 处理卖一价逻辑 (套利核心)
            ask_prices = tick.get('askPrice', [0])
            ask1 = float(ask_prices[0]) if ask_prices else 0
            price = ask1 if ask1 > 0 else last_price
            
            # 计算实时涨跌幅
            price_change = ((price / pre_close) - 1) * 100 if pre_close > 0 else 0
            
            return {
                "symbol": symbol.split('.')[0],
                "price": price,
                "last_price": last_price,
                "price_change": round(price_change, 2),
                "amount": round(amount / 10000, 2), # 转换为万元
                "volume": volume,
                "ask": tick.get('askPrice', []),
                "ask_vol": tick.get('askVol', []),
                "bid": tick.get('bidPrice', []),
                "bid_vol": tick.get('bidVol', []),
                "time": tick.get('time', time.time()),
                "source": self.name
            }
        except Exception as e:
            logger.error(f"格式化数据错误 ({symbol}): {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        if not self.is_connected: return None
        try:
            qmt_symbol = self.normalize_symbol(symbol)
            full_tick = self.xtdata.get_full_tick([qmt_symbol])
            if qmt_symbol in full_tick:
                tick = full_tick[qmt_symbol]
                if isinstance(tick, dict):
                    return self._format_tick(qmt_symbol, tick)
            return None
        except Exception as e:
            logger.warning(f"国金QMT 获取行情失败 ({symbol}): {e}")
            return None

    def normalize_symbol(self, symbol: str) -> str:
        """QMT 格式: 510300.SH, 000001.SZ"""
        s = symbol.upper()
        if '.' in s: return s
        if s.startswith('5') or s.startswith('6'):
            return f"{s}.SH"
        return f"{s}.SZ"
