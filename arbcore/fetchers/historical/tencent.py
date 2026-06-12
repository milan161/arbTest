import requests
import pandas as pd
import logging
import json
from typing import List, Dict, Optional, Any
from .base import BaseHistoricalFetcher
from datetime import datetime

logger = logging.getLogger(__name__)

class TencentHistoricalFetcher(BaseHistoricalFetcher):
    """
    腾讯财经历史数据抓取器（主要用于 A 股和国内指数）。
    """
    
    def __init__(self):
        super().__init__("Tencent")
        self.headers = {
            'User-Agent': 'Mozilla/5.0',
        }

    def fetch_nav(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        return pd.DataFrame()

    def fetch_prices(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取 A 股/国内指数历史价格"""
        logger.info(f"[{self.name}] 获取 {symbol} 历史价格")
        
        # 转换符号
        tencent_code = self.normalize_symbol(symbol)
        
        days_to_fetch = 100
        if start_date:
            try:
                delta = datetime.now() - datetime.strptime(start_date, '%Y-%m-%d')
                days_to_fetch = max(100, delta.days + 5)
            except: pass

        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param={tencent_code},day,,,{days_to_fetch},qfq&r=0.1"
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            text = res.text.split('kline_dayqfq=')[-1]
            data = json.loads(text)
            
            # 腾讯接口数据结构: data -> tencent_code -> day
            target_data = data.get('data', {}).get(tencent_code, {})
            day_data = target_data.get('day', [])
            
            if not day_data:
                # 尝试不带 qfq
                day_data = target_data.get('qfqday', [])
            
            if not day_data: return pd.DataFrame()
            
            # 腾讯K线格式: [日期, 开盘, 收盘, 最高, 最低, 成交量(手)]
            # 例如: ['2026-06-12', '1.875', '1.864', '1.875', '1.860', '29251.000']
            df = pd.DataFrame(day_data).iloc[:, [0, 2, 5]]
            df.columns = ['date', 'close', 'volume_hands']
            df['date'] = pd.to_datetime(df['date'])
            df['close'] = pd.to_numeric(df['close'])
            df['volume_hands'] = pd.to_numeric(df['volume_hands'])
            
            # 转换为股/份
            df['volume'] = df['volume_hands'] * 100
            # 估算成交额(万元) = 份数 * 收盘价 / 10000
            df['turnover_rate'] = (df['volume'] * df['close']) / 10000.0  # 用 turnover_rate 暂存成交额万元，因为 DB 接口这样写
            
            if start_date:
                df = df[df['date'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['date'] <= pd.to_datetime(end_date)]
                
            return df.sort_values('date', ascending=False)
        except Exception as e:
            logger.error(f"腾讯获取 {symbol} 失败: {e}")
            return pd.DataFrame()

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if s.startswith('SH') or s.startswith('SZ'):
            return s.lower()
        if s.startswith('5') or s.startswith('6'):
            return f"sh{s}"
        if s.startswith('0') or s.startswith('3') or s.startswith('1'):
            return f"sz{s}"
        # 指数处理 (如 000001.SH -> sh000001)
        if '.' in s:
            parts = s.split('.')
            return f"{parts[1].lower()}{parts[0]}"
        return s.lower()
