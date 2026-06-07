import logging
from typing import List, Dict, Optional, Any
import pandas as pd
from .eastmoney import EastMoneyHistoricalFetcher
from .sina import SinaHistoricalFetcher

logger = logging.getLogger(__name__)

class HistoricalDataManager:
    """
    历史数据管理器。
    """
    
    def __init__(self, db_manager=None):
        self.fetchers = {
            "eastmoney": EastMoneyHistoricalFetcher(),
            "sina": SinaHistoricalFetcher()
        }
        self.db_manager = db_manager

    def get_nav(self, symbol: str, source: str = "eastmoney", **kwargs) -> pd.DataFrame:
        """获取历史净值"""
        fetcher = self.fetchers.get(source)
        if fetcher:
            return fetcher.fetch_nav(symbol, **kwargs)
        return pd.DataFrame()

    def get_prices(self, symbol: str, source: str = "sina", **kwargs) -> pd.DataFrame:
        """获取历史 K 线价格"""
        fetcher = self.fetchers.get(source)
        if fetcher:
            return fetcher.fetch_prices(symbol, **kwargs)
        return pd.DataFrame()

    def get_historical_data_with_priority(self, symbol: str, data_type: str = "prices") -> pd.DataFrame:
        """
        根据数据库配置的优先级获取历史数据。
        (此部分逻辑可参考 RealtimeMarketManager 实现自动切换)
        """
        # 默认实现
        if data_type == "nav":
            return self.get_nav(symbol, source="eastmoney")
        else:
            return self.get_prices(symbol, source="sina")
