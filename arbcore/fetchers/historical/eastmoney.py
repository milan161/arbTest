import requests
import pandas as pd
import logging
from typing import List, Dict, Optional, Any
from .base import BaseHistoricalFetcher
from datetime import datetime

logger = logging.getLogger(__name__)

class EastMoneyHistoricalFetcher(BaseHistoricalFetcher):
    """
    东方财富历史数据抓取器（主要用于净值）。
    """
    
    def __init__(self):
        super().__init__("EastMoney")
        self.headers = {'Referer': 'http://fundf10.eastmoney.com/'}

    def fetch_nav(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取基金历史净值"""
        logger.info(f"[{self.name}] 获取 {symbol} 历史净值")
        nav_data = []
        
        # 默认获取最近 100 条
        url = f"http://api.fund.eastmoney.com/f10/lsjz?fundCode={symbol}&pageIndex=1&pageSize=100"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=10, verify=False, proxies={"http": None, "https": None})
            data = response.json()
            
            if data.get('Data') and data['Data'].get('LSJZList'):
                for item in data['Data']['LSJZList']:
                    date = item.get('FSRQ')
                    nav = item.get('DWJZ')
                    if date and nav:
                        nav_data.append({
                            'date': date,
                            'nav': float(nav)
                        })
            
            df = pd.DataFrame(nav_data)
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                if start_date:
                    df = df[df['date'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['date'] <= pd.to_datetime(end_date)]
                df = df.sort_values('date', ascending=False)
            return df
        except Exception as e:
            logger.error(f"[{self.name}] 获取净值失败: {e}")
            return pd.DataFrame()

    def fetch_prices(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        # 东财历史价格通常通过另一个接口，暂不实现
        return pd.DataFrame()
