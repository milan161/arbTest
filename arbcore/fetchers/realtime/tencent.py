import requests
import time
import logging
import threading
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher

logger = logging.getLogger(__name__)

class TencentRealtimeFetcher(BaseRealtimeFetcher):
    """
    腾讯财经实时行情抓取器（HTTP 轮询模式）。
    """
    
    def __init__(self):
        super().__init__("Tencent")
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        self.symbols = []
        self.quotes = {}
        self.running = False
        self._thread = None
        self.interval = 3.0  # 腾讯接口较快，默认 3 秒

    def connect(self) -> bool:
        self.is_connected = True
        self.running = True
        self._thread = threading.Thread(target=self._polling_loop, daemon=True)
        self._thread.start()
        return True

    def disconnect(self):
        self.running = False
        self.is_connected = False

    def subscribe(self, symbols: List[str]):
        new_symbols = [s for s in symbols if s not in self.symbols]
        self.symbols.extend(new_symbols)
        logger.info(f"✅ 腾讯订阅池已更新，当前总数: {len(self.symbols)}")

    def unsubscribe(self, symbols: List[str]):
        self.symbols = [s for s in self.symbols if s not in symbols]

    def _polling_loop(self):
        while self.running:
            if not self.symbols:
                time.sleep(1)
                continue
                
            # 分批轮询
            for i in range(0, len(self.symbols), 50):
                batch = self.symbols[i:i+50]
                self._fetch_batch(batch)
            
            time.sleep(self.interval)

    def _fetch_batch(self, batch: List[str]):
        tencent_codes = [self.normalize_symbol(s) for s in batch]
        url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
        
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            res.encoding = 'gbk'
            if res.status_code == 200:
                self._process_response(res.text)
        except Exception as e:
            logger.error(f"腾讯轮询异常: {e}")

    def _process_response(self, text: str):
        lines = text.strip().split(';')
        for line in lines:
            if '="' not in line:
                continue
            
            # 格式: v_sh600000="1~浦发银行~600000~10.15~10.15~10.16~..."
            # 腾讯接口字段非常多，第3个是最新价，第4个是昨收
            try:
                code_part, data_part = line.split('="')
                code = code_part.split('_')[-1]
                fields = data_part.replace('"', '').split('~')
                
                if len(fields) > 10:
                    last_price = float(fields[3])
                    pre_close = float(fields[4])
                    price_change = float(fields[32]) if len(fields) > 32 else 0
                    
                    # 5档盘口
                    # 买1-买5: fields[9], fields[11], fields[13], fields[15], fields[17]
                    # 买1量-买5量: fields[10], fields[12], fields[14], fields[16], fields[18]
                    # 卖1-卖5: fields[19], fields[21], fields[23], fields[25], fields[27]
                    # 卖1量-卖5量: fields[20], fields[22], fields[24], fields[26], fields[28]
                    
                    quote = {
                        "symbol": code[2:] if len(code) > 6 else code,
                        "price": last_price,
                        "last_price": last_price,
                        "price_change": price_change,
                        "time": fields[30],
                        "source": self.name
                    }
                    # 尝试添加盘口
                    try:
                        quote["ask"] = [float(fields[19]), float(fields[21]), float(fields[23]), float(fields[25]), float(fields[27])]
                        quote["bid"] = [float(fields[9]), float(fields[11]), float(fields[13]), float(fields[15]), float(fields[17])]
                    except: pass

                    clean_code = code[2:] if len(code) > 2 and code[2:].isdigit() else code
                    self.quotes[clean_code] = quote
                    self._notify_update(clean_code, quote)
            except Exception:
                continue

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        clean_symbol = symbol.split('.')[0]
        return self.quotes.get(clean_symbol)

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if s.startswith('SH') or s.startswith('SZ'):
            return s.lower()
        if s.startswith('5') or s.startswith('6'):
            return f"sh{s}"
        if s.startswith('0') or s.startswith('3') or s.startswith('1'):
            return f"sz{s}"
        return s.lower()
