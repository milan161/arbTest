import requests
import re
import time
import logging
import threading
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher

logger = logging.getLogger(__name__)

class SinaRealtimeFetcher(BaseRealtimeFetcher):
    """
    新浪财经实时行情抓取器（HTTP 轮询模式）。
    作为终极兜底方案。
    """
    
    def __init__(self):
        super().__init__("Sina")
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/'
        }
        self.symbols = []
        self.quotes = {}
        self.running = False
        self._thread = None
        self.interval = 5.0  # 默认 5 秒轮询一次

    def connect(self) -> bool:
        # 新浪 API 不需要维持长连接
        self.is_connected = True
        self.running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()
        return True

    def disconnect(self):
        self.running = False
        self.is_connected = False

    def subscribe(self, symbols: List[str]):
        # 转换并排重
        new_symbols = [s for s in symbols if s not in self.symbols]
        self.symbols.extend(new_symbols)
        logger.info(f"✅ 新浪订阅池已更新，当前总数: {len(self.symbols)}")

    def unsubscribe(self, symbols: List[str]):
        self.symbols = [s for s in self.symbols if s not in symbols]

    def _polling_loop(self):
        while self.running:
            if not self.symbols:
                time.sleep(1)
                continue
                
            # 分批轮询，新浪单次请求建议不超过 40 个
            for i in range(0, len(self.symbols), 40):
                batch = self.symbols[i:i+40]
                self._fetch_batch(batch)
            
            time.sleep(self.interval)

    def _fetch_batch(self, batch: List[str]):
        sina_codes = [self.normalize_symbol(s) for s in batch]
        url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
        
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            res.encoding = 'gbk'
            if res.status_code == 200:
                self._process_response(res.text)
        except Exception as e:
            logger.error(f"新浪轮询异常: {e}")

    def _process_response(self, text: str):
        lines = text.strip().split('\n')
        for line in lines:
            # A股匹配: hq_str_sh600000="..."
            match_a = re.search(r'hq_str_([a-z]{2})(\d{6})="([^"]+)"', line)
            # 港股匹配: hq_str_rt_hk00700="..."
            match_hk = re.search(r'hq_str_rt_hk(\d{5})="([^"]+)"', line)
            
            if match_a:
                code = match_a.group(2)
                parts = match_a.group(3).split(',')
                if len(parts) > 9:
                    pre_close = float(parts[2])
                    last_price = float(parts[3])
                    ask1 = float(parts[7])
                    volume = float(parts[8]) # 股数
                    amount = float(parts[9]) # 成交额(元)
                    
                    # 现价逻辑：由于是套利，卖一价更有参考意义
                    price = ask1 if ask1 > 0 else last_price
                    # 计算涨跌幅
                    price_change = ((price / pre_close) - 1) * 100 if pre_close > 0 else 0
                    
                    quote = {
                        "symbol": code,
                        "price": price,
                        "last_price": last_price,
                        "price_change": round(price_change, 2),
                        "volume": volume,
                        "amount": round(amount / 10000, 2), # 转换为了万元
                        "ask": [float(parts[21]), float(parts[23]), float(parts[25]), float(parts[27]), float(parts[29])],
                        "ask_vol": [int(parts[20]), int(parts[22]), int(parts[24]), int(parts[26]), int(parts[28])],
                        "bid": [float(parts[11]), float(parts[13]), float(parts[15]), float(parts[17]), float(parts[19])],
                        "bid_vol": [int(parts[10]), int(parts[12]), int(parts[14]), int(parts[16]), int(parts[18])],
                        "time": f"{parts[30]} {parts[31]}",
                        "source": self.name
                    }
                    self.quotes[code] = quote
                    self._notify_update(code, quote)
            elif match_hk:
                code = match_hk.group(1)
                parts = match_hk.group(2).split(',')
                if len(parts) > 6:
                    price = float(parts[6])
                    quote = {
                        "symbol": code,
                        "price": price,
                        "last_price": price,
                        "price_change": 0, # 港股实时涨跌幅解析较复杂，暂缺
                        "amount": 0,
                        "time": f"{parts[17]} {parts[18]}",
                        "source": self.name
                    }
                    self.quotes[code] = quote
                    self._notify_update(code, quote)

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.quotes.get(symbol)

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if len(s) == 5 and s.isdigit(): return f"rt_hk{s}"
        if s.startswith('5') or s.startswith('6'):
            return f"sh{s}"
        return f"sz{s}"
