import socket
import threading
import time
import logging
import json
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher

logger = logging.getLogger(__name__)

class GalaxyQmtFetcher(BaseRealtimeFetcher):
    """
    银河证券 QMT Socket 实时行情抓取器。
    通过 Socket 8888 端口连接到 QMT 终端。
    """
    
    def __init__(self, host='127.0.0.1', port=8888):
        super().__init__("Galaxy_QMT")
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.recv_thread = None
        self.lock = threading.RLock()
        self.quotes = {}

    def connect(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.running = True
            self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self.recv_thread.start()
            self.is_connected = True
            logger.info(f"✅ 银河QMT Socket 已连接 ({self.host}:{self.port})")
            return True
        except Exception as e:
            logger.error(f"❌ 银河QMT 连接失败: {e}")
            return False

    def disconnect(self):
        self.running = False
        if self.sock:
            try: self.sock.close()
            except: pass
        self.is_connected = False

    def subscribe(self, symbols: List[str]):
        if not self.is_connected: return
        qmt_codes = [self.normalize_symbol(s) for s in symbols]
        cmd = f"SUBSCRIBE,{','.join(qmt_codes)}\n"
        try:
            self.sock.sendall(cmd.encode('utf-8'))
            logger.info(f"✅ 银河QMT 已发送订阅请求: {qmt_codes}")
        except Exception as e:
            logger.error(f"银河QMT 订阅失败: {e}")

    def unsubscribe(self, symbols: List[str]):
        # QMT Socket 协议通常是增量订阅，暂不支持显式退订
        pass

    def _recv_loop(self):
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(4096).decode('utf-8')
                if not data: break
                
                buffer += data
                while '\n' in buffer:
                    msg, buffer = buffer.split('\n', 1)
                    self._process_message(msg.strip())
            except:
                break
        self.is_connected = False

    def _process_message(self, msg: str):
        if msg.startswith("TICK,"):
            parts = msg.split(',')
            # 新版 TICK 消息有 15 个字段 (0-14)
            if len(parts) >= 15:
                symbol_full = parts[1]
                symbol = symbol_full.split('.')[0]
                last_price = float(parts[2]) if parts[2] else 0
                volume = float(parts[3]) if parts[3] else 0
                ask1 = float(parts[4]) if parts[4] else 0
                
                # 提取昨收和成交额
                pre_close = float(parts[13]) if parts[13] else 0
                amount = float(parts[14]) if parts[14] else 0
                
                # 核心逻辑：卖一价优先
                price = ask1 if ask1 > 0 else last_price
                price_change = ((price / pre_close) - 1) * 100 if pre_close > 0 else 0
                
                quote = {
                    "symbol": symbol,
                    "price": price,
                    "last_price": last_price,
                    "price_change": round(price_change, 2),
                    "volume": volume,
                    "amount": round(amount / 10000, 2), 
                    "ask": [float(parts[4]), float(parts[6]), float(parts[8]), float(parts[10]), float(parts[12])],
                    "ask_vol": [int(float(parts[5])), int(float(parts[7])), int(float(parts[9])), int(float(parts[11])), int(float(parts[13]))],
                    "bid": [float(parts[14]), float(parts[16]), float(parts[18]), float(parts[20]), float(parts[22])],
                    "bid_vol": [int(float(parts[15])), int(float(parts[17])), int(float(parts[19])), int(float(parts[21])), int(float(parts[23]))],
                    "time": time.time(),
                    "source": self.name
                }
                
                with self.lock:
                    self.quotes[symbol] = quote
                
                self._notify_update(symbol, quote)

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.quotes.get(symbol)

    def normalize_symbol(self, symbol: str) -> str:
        s = symbol.upper()
        if '.' in s: return s
        # 港股处理 (5位数字)
        if len(s) == 5 and s.isdigit(): return f"{s}.HK"
        if s.startswith('5') or s.startswith('6'):
            return f"{s}.SH"
        return f"{s}.SZ"
