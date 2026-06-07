from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
import pandas as pd

class BaseHistoricalFetcher(ABC):
    """
    历史数据抓取器基类。
    """
    
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def fetch_nav(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取历史净值"""
        pass

    @abstractmethod
    def fetch_prices(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取历史 K 线价格"""
        pass

    def normalize_symbol(self, symbol: str) -> str:
        """统一 Symbol 转换"""
        return symbol.upper()
