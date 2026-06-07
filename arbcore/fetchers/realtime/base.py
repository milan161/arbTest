from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import pandas as pd

class BaseRealtimeFetcher(ABC):
    """
    实时行情抓取器基类。
    所有具体的数据源实现（如新浪、QMT、通达信）都必须继承此类。
    """
    
    def __init__(self, name: str):
        self.name = name
        self.is_connected = False
        self._on_update_callback = None

    @abstractmethod
    def connect(self) -> bool:
        """建立连接"""
        pass

    @abstractmethod
    def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    def subscribe(self, symbols: List[str]):
        """订阅行情"""
        pass

    @abstractmethod
    def unsubscribe(self, symbols: List[str]):
        """取消订阅"""
        pass

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单个标的的最新行情快照"""
        pass

    def set_on_update(self, callback):
        """设置实时跳动回调函数"""
        self._on_update_callback = callback

    def _notify_update(self, symbol: str, quote: Dict[str, Any]):
        """触发回调"""
        if self._on_update_callback:
            self._on_update_callback(symbol, quote)

    def normalize_symbol(self, symbol: str) -> str:
        """
        统一转换 Symbol 格式。
        输入可能是 '510300', 'sh510300', '510300.SH'
        输出统一为纯数字或带市场后缀的格式，取决于具体实现的子类。
        """
        # 基类提供基础逻辑，子类可重写
        clean_symbol = symbol.upper()
        if '.' in clean_symbol:
            return clean_symbol
        if clean_symbol.startswith('SH') or clean_symbol.startswith('SZ'):
            return f"{clean_symbol[2:]}.{clean_symbol[:2]}"
        return clean_symbol
