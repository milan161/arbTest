import requests
import pandas as pd
import logging
import json
import re
from typing import List, Dict, Optional, Any
from .base import BaseHistoricalFetcher
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class SinaHistoricalFetcher(BaseHistoricalFetcher):
    """
    新浪财经历史数据抓取器（主要用于 K 线价格）。
    """
    
    def __init__(self):
        super().__init__("Sina")
        self.headers = {
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        }

    def fetch_nav(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        # 新浪通常不作为净值首选源
        return pd.DataFrame()

    def fetch_prices(self, symbol: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """获取 A 股/港股/美股/期货/指数历史价格"""
        logger.info(f"[{self.name}] 获取 {symbol} 历史价格")
        
        # 1. 期货处理 (如 GC2412, CL2501, AU2412)
        if re.match(r'^[A-Z]{2}\d{4}$', symbol):
            return self._fetch_futures(symbol, start_date, end_date)
        
        # 2. 指数处理 (如 .INX, .NDX, .HSI, .SSEC)
        if symbol.startswith('.'):
            return self._fetch_index(symbol, start_date, end_date)

        # 3. 股票/ETF 处理
        if symbol.startswith('5') or symbol.startswith('6'):
            return self._fetch_a_share(symbol, start_date, end_date, 'sh')
        elif symbol.startswith('0') or symbol.startswith('1') or symbol.startswith('3') or symbol.startswith('15') or symbol.startswith('16'):
             return self._fetch_a_share(symbol, start_date, end_date, 'sz')
        elif len(symbol) == 5 and symbol.isdigit():
            return self._fetch_hk_share(symbol, start_date, end_date)
        else:
            return self._fetch_us_share(symbol, start_date, end_date)

    def _fetch_futures(self, symbol: str, start_date, end_date) -> pd.DataFrame:
        """获取内盘/外盘期货历史日线"""
        # 判断是内盘还是外盘
        if symbol.startswith(('GC', 'CL', 'SI', 'HG')):
            # 外盘期货
            url = f"https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol={symbol}"
        else:
            # 内盘期货
            url = f"https://stock.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}=/InnerFuturesService.getInnerFuturesDailyKLine?symbol={symbol}"
        
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            text = res.text
            # 解析 JSONP
            json_str = text.split('=(')[-1].split(');')[0]
            data = json.loads(json_str)
            
            df = pd.DataFrame(data)
            if not df.empty:
                df = df.rename(columns={'d': 'date', 'c': 'close'})
                df['date'] = pd.to_datetime(df['date'])
                df['close'] = pd.to_numeric(df['close'])
                
                if start_date:
                    df = df[df['date'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['date'] <= pd.to_datetime(end_date)]
            return df[['date', 'close']].sort_values('date', ascending=False)
        except Exception as e:
            logger.error(f"获取期货 {symbol} 失败: {e}")
            return pd.DataFrame()

    def _fetch_index(self, symbol: str, start_date, end_date) -> pd.DataFrame:
        """获取指数历史价格"""
        # [AI-2026-07-20] 美股指数 .NDX/.INX 新浪认原样带点符号（如 .ndx），
        # 不再转 gb_ 前缀（gb_ndx 新浪返回空，导致 .NDX/.INX 历史长期停更）。
        # 实测 https://stock.finance.sina.com.cn/usstock/api/json_v2.php/
        #        US_MinKService.getDailyK?symbol=.ndx 可正常返回多日历史。
        sina_code = symbol.lstrip('.')
        if sina_code in ['INX', 'NDX', 'DJI', 'IXIC']:
            return self._fetch_us_share(symbol.lower(), start_date, end_date)
        elif sina_code == 'SSEC':
            return self._fetch_a_share('000001', start_date, end_date, 'sh')
        elif sina_code == 'SZSC':
            return self._fetch_a_share('399001', start_date, end_date, 'sz')
        elif sina_code == 'HSI':
            return self._fetch_hk_share('HSI', start_date, end_date)
        
        return pd.DataFrame()

    def _fetch_a_share(self, symbol: str, start_date, end_date, market: str) -> pd.DataFrame:
        # 新浪 K 线接口，scale=240 表示日线
        days_to_fetch = 100
        if start_date:
            try:
                delta = datetime.now() - datetime.strptime(start_date, '%Y-%m-%d')
                days_to_fetch = max(100, delta.days + 5)
            except: pass
            
        url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}{symbol}&scale=240&ma=no&datalen={days_to_fetch}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            data = res.json()
            if not data or not isinstance(data, list): return pd.DataFrame()
            
            df = pd.DataFrame(data)
            df = df.rename(columns={'day': 'date', 'close': 'close'})
            df['date'] = pd.to_datetime(df['date'])
            df['close'] = pd.to_numeric(df['close'])
            
            if start_date:
                df = df[df['date'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['date'] <= pd.to_datetime(end_date)]
            
            return df[['date', 'close']].sort_values('date', ascending=False)
        except:
            return pd.DataFrame()

    def _fetch_hk_share(self, symbol: str, start_date, end_date) -> pd.DataFrame:
        # 借用腾讯接口
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param=hk{symbol},day,,,100,qfq&r=0.1"
        try:
            res = requests.get(url, timeout=10, proxies={"http": None, "https": None})
            text = res.text.split('kline_dayqfq=')[-1]
            data = json.loads(text)
            day_data = data.get('data', {}).get(f'hk{symbol}', {}).get('day', [])
            df = pd.DataFrame(day_data).iloc[:, [0, 4]]
            df.columns = ['date', 'close']
            df['date'] = pd.to_datetime(df['date'])
            df['close'] = pd.to_numeric(df['close'])
            
            if start_date:
                df = df[df['date'] >= pd.to_datetime(start_date)]
            if end_date:
                df = df[df['date'] <= pd.to_datetime(end_date)]
                
            return df.sort_values('date', ascending=False)
        except:
            return pd.DataFrame()

    def _fetch_us_share(self, symbol: str, start_date, end_date) -> pd.DataFrame:
        # 美股接口
        url = f"https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK?symbol={symbol.lower()}"
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            data = res.json()
            df = pd.DataFrame(data)
            if not df.empty:
                df = df.rename(columns={'d': 'date', 'c': 'close'})
                df['date'] = pd.to_datetime(df['date'])
                df['close'] = pd.to_numeric(df['close'])
                
                if start_date:
                    df = df[df['date'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['date'] <= pd.to_datetime(end_date)]
                    
            return df[['date', 'close']].sort_values('date', ascending=False)
        except:
            return pd.DataFrame()
