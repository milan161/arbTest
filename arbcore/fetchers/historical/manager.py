import logging
from typing import List, Dict, Optional, Any
import pandas as pd
from .eastmoney import EastMoneyHistoricalFetcher
from .sina import SinaHistoricalFetcher
from .xueqiu import XueqiuHistoricalFetcher
from .tencent import TencentHistoricalFetcher
from arbcore.config.symbol_source_map import get_symbol_source

logger = logging.getLogger(__name__)

class HistoricalDataManager:
    """
    历史数据管理器。
    负责协调多个数据源，实现优先级排序。
    """
    
    def __init__(self, db_manager=None):
        self.fetchers = {
            "eastmoney": EastMoneyHistoricalFetcher(),
            "sina": SinaHistoricalFetcher(),
            "xueqiu": XueqiuHistoricalFetcher(),
            "tencent": TencentHistoricalFetcher(),
            "east_money": EastMoneyHistoricalFetcher(), # 别名
            "sina_finance": SinaHistoricalFetcher()     # 别名
        }
        self.db_manager = db_manager

    def get_nav(self, symbol: str, source: str = None, **kwargs) -> pd.DataFrame:
        """获取历史净值"""
        if not source:
            # 默认净值从东财获取
            source = "eastmoney"
            
        fetcher = self.fetchers.get(source.lower())
        if fetcher:
            return fetcher.fetch_nav(symbol, **kwargs)
        return pd.DataFrame()

    def get_prices(self, symbol: str, source: str = None, **kwargs) -> pd.DataFrame:
        """获取历史 K 线价格"""
        if not source:
            # 根据 symbol_source_map 自动选择
            source = get_symbol_source(symbol)
            
        # 如果 source 是 TDX 或 SINA，统一用 sina 抓取历史
        if source in ["TDX", "SINA"]:
            source = "sina"
        elif source == "IB":
            # IB 历史数据获取较复杂，目前暂未实现 historical_ib
            source = "sina" # 降级到新浪
        elif source == "FUTU":
            source = "sina" # 降级到新浪
            
        fetcher = self.fetchers.get(source.lower())
        if fetcher:
            return fetcher.fetch_prices(symbol, **kwargs)
        
        # 兜底用 sina
        return self.fetchers["sina"].fetch_prices(symbol, **kwargs)

    def get_historical_data_with_priority(self, symbol: str, data_type: str = "prices") -> pd.DataFrame:
        """
        根据优先级获取历史数据。
        """
        if data_type == "nav":
            return self.get_nav(symbol)
        else:
            return self.get_prices(symbol)
