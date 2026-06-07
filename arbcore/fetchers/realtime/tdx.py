import logging
import threading
import time
import os
import sys
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher

logger = logging.getLogger(__name__)

class TdxRealtimeFetcher(BaseRealtimeFetcher):
    """
    通达信 (tqcenter) 实时行情抓取器。
    要求本地运行通达信客户端并配置 tqcenter 插件。
    """
    
    def __init__(self):
        super().__init__("Tongdaxin")
        self.tq = None
        self.quotes = {}
        self._lock = threading.Lock()

    def connect(self) -> bool:
        try:
            # 尝试从常见路径导入 tqcenter
            tdx_api_path = r'D:\new_tdx_test\PYPlugins\user'
            if os.path.exists(tdx_api_path) and tdx_api_path not in sys.path:
                sys.path.insert(0, tdx_api_path)
            
            from tqcenter import tq
            self.tq = tq
            tq.initialize(__file__)
            self.is_connected = True
            logger.info("✅ 通达信 (tqcenter) 适配器加载成功")
            return True
        except ImportError:
            logger.warning("未找到 tqcenter 模块，通达信适配器停用")
            return False
        except Exception as e:
            logger.error(f"通达信连接失败: {e}")
            return False

    def disconnect(self):
        if self.tq:
            try: self.tq.close()
            except: pass
        self.is_connected = False

    def subscribe(self, symbols: List[str]):
        if not self.is_connected: return
        tdx_codes = [self.normalize_symbol(s) for s in symbols]
        try:
            self.tq.subscribe_hq(stock_list=tdx_codes, callback=self._internal_callback)
            logger.info(f"✅ 通达信已订阅: {tdx_codes}")
        except Exception as e:
            logger.error(f"通达信订阅失败: {e}")

    def unsubscribe(self, symbols: List[str]):
        if not self.is_connected: return
        tdx_codes = [self.normalize_symbol(s) for s in symbols]
        try:
            self.tq.unsubscribe_hq(stock_list=tdx_codes)
        except: pass

    def _internal_callback(self, data_str):
        """通达信价格跳动回调"""
        try:
            import json
            data = json.loads(data_str)
            stock_code = data.get('Code')
            if stock_code:
                # 获取完整快照
                snap = self.tq.get_market_snapshot(stock_code=stock_code)
                if snap:
                    quote = self._format_snap(stock_code, snap)
                    if quote:
                        symbol = stock_code.split('.')[0]
                        with self._lock:
                            self.quotes[symbol] = quote
                        self._notify_update(symbol, quote)
        except:
            pass

    def _format_snap(self, symbol_full: str, snap: Dict) -> Optional[Dict[str, Any]]:
        try:
            ask1 = float(snap.get('Sell1', 0))
            last_price = float(snap.get('Now', 0))
            symbol = symbol_full.split('.')[0]

            # 提取成交额（通达信 snapshot 中的 Amount 通常已经是万元单位）
            amount = float(snap.get('Amount', 0))
            # 提取成交量（通常是手）
            volume = float(snap.get('Volume', 0))

            return {
                "symbol": symbol,
                "price": ask1 if ask1 > 0 else last_price,
                "last_price": last_price,
                "amount": amount,
                "volume": volume,
                "ask": [ask1, float(snap.get('Sell2', 0)), float(snap.get('Sell3', 0))],
                "bid": [float(snap.get('Buy1', 0)), float(snap.get('Buy2', 0)), float(snap.get('Buy3', 0))],
                "time": snap.get('Time', time.time()),
                "source": self.name
            }
        except:
            return None

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        # 优先从缓存取，如果缓存没有，尝试主动拉取快照
        clean_symbol = symbol.split('.')[0]
        with self._lock:
            if clean_symbol in self.quotes:
                return self.quotes[clean_symbol]
        
        if self.is_connected:
            tdx_code = self.normalize_symbol(symbol)
            snap = self.tq.get_market_snapshot(stock_code=tdx_code)
            if snap:
                return self._format_snap(tdx_code, snap)
        return None

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if '.' in s: return s
        if len(s) == 5 and s.isdigit(): return f"{s}.HK"
        if s.startswith('5') or s.startswith('6'):
            return f"{s}.SH"
        return f"{s}.SZ"
