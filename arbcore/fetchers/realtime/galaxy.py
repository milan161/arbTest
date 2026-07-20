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
        # [AI-2026-07-20] 下单同步回执：recv_loop 收到 OK 后放入，send_order 等待
        import queue as _queue_mod
        self._ack_queue = _queue_mod.Queue()
        
        # [V10.0] 连接控制：启动时不自动连接，用户点击页面"银河QMT"按钮才重连
        self.disabled = True
        self.max_retries = 3
        self.last_connect_time = 0
        # [V10.0] 不再启动后台连接线程，用户手动触发 reconnect() 即可

    def connect(self) -> bool:
        if self.disabled:
            logger.debug("[QMT银河] 已禁用，跳过连接")
            return False
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

    def _try_connect_silent(self):
        """静默尝试连接银河QMT，最多 max_retries 次"""
        if self.disabled:
            return
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.connect():
                    logger.info(f"{'='*50}\n[QMT银河] 连接成功 (第 {attempt} 次尝试)\n{'='*50}")
                    self.disabled = False
                    return
            except Exception as e:
                logger.debug(f"[QMT银河] 连接尝试 {attempt}/{self.max_retries} 失败: {e}")
                time.sleep(1)
        logger.warning("[QMT银河] 连接失败（已尝试 {} 次），已禁用银河QMT读取器。如需启用，请点击页面顶部的'银河QMT'标签重试。".format(self.max_retries))
        self.disabled = True
        self.is_connected = False
    
    def reconnect(self):
        """手动重连（供用户点击"银河QMT"按钮时调用）"""
        if self.is_connected:
            logger.info("[QMT银河] 已经连接，跳过重复重连")
            return True, "银河QMT已经连接"
        logger.info("[QMT银河] 用户手动触发重连...")
        self.disabled = False
        self.is_connected = False
        self.last_connect_time = 0
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.connect():
                    logger.info(f"[QMT银河] 手动重连成功 (第 {attempt} 次)")
                    self.disabled = False
                    return True, f"银河QMT连接成功 (第 {attempt} 次尝试)"
            except Exception as e:
                logger.warning(f"[QMT银河] 重连失败 (第 {attempt}/{self.max_retries} 次): {e}")
                time.sleep(1)
        self.disabled = True
        logger.warning("[QMT银河] 手动重连失败（已尝试 {} 次），请确认银河QMT终端已启动".format(self.max_retries))
        return False, f"银河QMT重连失败（已尝试 {self.max_retries} 次），请确认银河QMT终端已启动"

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
                if not data:
                    logger.warning("[QMT银河] Socket 收到空数据，连接可能已关闭")
                    break
                buffer += data
                while '\n' in buffer:
                    msg, buffer = buffer.split('\n', 1)
                    try:
                        self._process_message(msg.strip())
                    except Exception as e:
                        logger.warning(f"[QMT银河] 消息处理异常 (丢弃): {e} | msg={msg[:80]}")
            except socket.timeout:
                continue  # 超时正常，继续等
            except Exception as e:
                logger.error(f"[QMT银河] 接收循环异常: {e}")
                break
        self.is_connected = False
        logger.warning("[QMT银河] 接收循环已退出")

    def _process_message(self, msg: str):
        # [AI-2026-07-20] 下单同步回执：脚本对 BUY/SELL 回 "OK"，放入队列供 send_order 等待
        if msg == "OK":
            try:
                self._ack_queue.put_nowait(True)
            except Exception:
                pass
            return
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

    def send_order(self, action: str, code: str, price: float, volume: int) -> tuple:
        """
        通过 QMT Socket 发送买卖指令，并同步等待脚本回执确认。
        Args:
            action: 'BUY' 或 'SELL'
            code: 股票代码（如 162411 或 162411.SZ，内部统一去后缀）
            price: 委托价格
            volume: 委托数量（股）
        Returns:
            (success: bool, msg: str)
        """
        if not self.is_connected:
            return False, "银河QMT 未连接"
        if action not in ('BUY', 'SELL'):
            return False, f"无效指令: {action}"
        # [AI-2026-07-20] passorder 市场参数(1101/1102)已指定市场，带 .SZ/.SH 后缀会被拒单，统一去后缀
        qmt_code = code.split('.')[0]
        try:
            # 清空过期回执，避免读到上一次的 OK
            while not self._ack_queue.empty():
                try:
                    self._ack_queue.get_nowait()
                except Exception:
                    break
            cmd = f"{action},{qmt_code},{price},{volume}\n"
            with self.lock:
                self.sock.sendall(cmd.encode('utf-8'))
            logger.info(f"✅ [QMT银河] 指令已发送: {action} {qmt_code} {volume}股 @ {price}")
            # [AI-2026-07-20] 同步等待脚本回执 OK（入队确认）。超时=未收到，视为失败
            try:
                self._ack_queue.get(timeout=3.0)
            except Exception:
                logger.error(f"❌ [QMT银河] 下单后未收到回执(OK)，可能通道异常: {action} {qmt_code}")
                return False, f"下单指令已发送但未收到银河回执(OK)，下单可能未生效"
            return True, f"指令已发送并确认: {action} {qmt_code} {volume}股 @ {price}"
        except Exception as e:
            logger.error(f"❌ [QMT银河] 下单失败: {e}")
            return False, f"下单失败: {e}"

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.is_connected = False
        logger.info("🔌 银河QMT Socket 已断开")
