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
        # 周末免打扰：如果是周末，直接返回 False 拒绝连接行情推送长连接，防止端口被无意义的长连接常驻抢占
        import datetime
        now = datetime.datetime.now()
        if now.weekday() >= 5:
            logger.info("📅 [周末避让] 今天是周末，行情引擎拒绝建立与银河QMT Socket的长连接，以确保下单通道绝对干净空闲。")
            return False
            
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
            logger.debug(f"✅ 银河QMT 已发送订阅请求: {qmt_codes}")
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
            symbol_full = parts[1]
            symbol = symbol_full.split('.')[0]
            
            # v4.0 push_ticks 短格式: TICK,code,lastPrice,volume,timetag (5字段)
            if len(parts) == 5:
                last_price = float(parts[2]) if parts[2] else 0
                volume = float(parts[3]) if parts[3] else 0
                quote = {
                    "symbol": symbol,
                    "price": last_price,
                    "last_price": last_price,
                    "price_change": 0,
                    "volume": volume,
                    "amount": 0,
                    "ask": [last_price, 0, 0, 0, 0],
                    "ask_vol": [0, 0, 0, 0, 0],
                    "bid": [last_price, 0, 0, 0, 0],
                    "bid_vol": [0, 0, 0, 0, 0],
                    "time": time.time(),
                    "source": self.name
                }
                with self.lock:
                    self.quotes[symbol] = quote
                self._notify_update(symbol, quote)
                return
            
            # 完整版 TICK 消息有 25+ 字段 (含5档买卖盘口)
            if len(parts) >= 25:
                last_price = float(parts[2]) if parts[2] else 0
                volume = float(parts[3]) if parts[3] else 0
                ask1 = float(parts[4]) if parts[4] else 0
                
                pre_close = float(parts[24]) if parts[24] else 0
                amount = float(parts[25]) if parts[25] else 0
                
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
