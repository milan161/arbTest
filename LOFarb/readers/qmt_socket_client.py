# 银河QMT Socket 客户端类
# 基于 Test_read_data/Test_QMT_socket_client.py 的思路

import socket
import threading
import time

class QmtSocketClient:
    """银河QMT Socket长连接客户端"""
    
    def __init__(self, host='127.0.0.1', port=8888, on_price_update=None):
        self.host = host
        self.port = port
        self.sock = None
        self.running = False
        self.recv_thread = None
        self.heartbeat_thread = None
        
        # 存储实时价格
        self.prices = {}
        self.order_books = {}  # 存储完整盘口字典，供沙盘推演冲击成本使用
        self.lock = threading.Lock()
        
        # 价格更新回调函数
        self.on_price_update = on_price_update
    
    def connect(self) -> bool:
        """仅建立socket连接，不启动后台线程"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5.0)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            print(f"✅ [银河QMT] 已建立到 {self.host}:{self.port} 的 Socket 通道")
            return True
        except Exception as e:
            print(f"❌ [银河QMT] 连接失败: {e}")
            return False
    
    def single_shot_query(self, cmd: str, timeout: float = 5.0) -> str:
        """短链接查询"""
        if not self.sock:
            return ""
        try:
            if not cmd.endswith('\n'):
                cmd += '\n'
            self.sock.sendall(cmd.encode('utf-8'))
            self.sock.settimeout(timeout)
            response = self.sock.recv(4096).decode('utf-8').strip()
            self.sock.settimeout(None)
            return response
        except Exception as e:
            return f"查询异常: {e}"
    
    def start_long_connection(self):
        """启动后台线程，正式进入长连接模式"""
        self.running = True
        self.recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        
        self.recv_thread.start()
        self.heartbeat_thread.start()
        
        print("✅ [银河QMT] 已成功转为长连接接收模式")
    
    def _recv_loop(self):
        """接收数据的后台线程"""
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(4096).decode('utf-8')
                if not data:
                    print("❌ [银河QMT] 服务器断开连接")
                    self.running = False
                    break
                
                buffer += data
                while '\n' in buffer:
                    msg, buffer = buffer.split('\n', 1)
                    msg = msg.strip()
                    if not msg:
                        continue
                    
                    self._process_message(msg)
            except Exception as e:
                if self.running:
                    print(f"❌ [银河QMT] 接收异常: {e}")
                    self.running = False
    
    def _heartbeat_loop(self):
        """心跳线程"""
        while self.running:
            time.sleep(20)
            self.send_msg("PING\n")
    
    def send_msg(self, msg):
        """发送消息"""
        if self.sock:
            try:
                if not msg.endswith('\n'):
                    msg += '\n'
                self.sock.sendall(msg.encode('utf-8'))
            except Exception as e:
                print(f"❌ [银河QMT] 发送异常: {e}")
    
    def subscribe(self, codes):
        """订阅实时行情"""
        cmd = f"SUBSCRIBE,{','.join(codes)}"
        self.send_msg(cmd)
        print(f"✅ [银河QMT] 已订阅: {codes}")
    
    def _process_message(self, msg: str):
        """处理接收到的消息"""
        if msg.startswith("TICK,"):
            parts = msg.split(',')
            # 兼容新版全量盘口格式: TICK, code, last, vol, ask_p1, ask_v1, ask_p2, ask_v2, bid_p1, bid_v1, bid_p2, bid_v2, timetag
            if len(parts) >= 12:
                code_full = parts[1]
                last_price = float(parts[2]) if parts[2] else 0
                volume = float(parts[3]) if parts[3] else 0
                ask_p1 = float(parts[4]) if parts[4] else 0
                ask_v1 = float(parts[5]) if parts[5] else 0
                ask_p2 = float(parts[6]) if parts[6] else 0
                ask_v2 = float(parts[7]) if parts[7] else 0
                bid_p1 = float(parts[8]) if parts[8] else 0
                bid_v1 = float(parts[9]) if parts[9] else 0
                bid_p2 = float(parts[10]) if parts[10] else 0
                bid_v2 = float(parts[11]) if parts[11] else 0
                
                code = code_full.split('.')[0] if '.' in code_full else code_full
                
                # 优先使用卖一价，如果卖一价为0（比如涨停），则使用最新成交价作为替代
                price_to_use = ask_p1 if ask_p1 > 0 else last_price

                if price_to_use > 0:
                    with self.lock:
                        # 记录完整盘口，供 LOF04 沙盘推演滑点和冲击成本使用
                        self.order_books[code] = {
                            'last_price': last_price, 'volume': volume,
                            'ask_p1': ask_p1, 'ask_v1': ask_v1,
                            'ask_p2': ask_p2, 'ask_v2': ask_v2,
                            'bid_p1': bid_p1, 'bid_v1': bid_v1,
                            'bid_p2': bid_p2, 'bid_v2': bid_v2
                        }
                        
                        old_price = self.prices.get(code, 0)
                        self.prices[code] = price_to_use
                        if old_price != price_to_use:
                            print(f"⚡ [银河] {code} 价格更新: {price_to_use} (卖一: {ask_p1}, 最新: {last_price})")
                            if self.on_price_update:
                                try:
                                    self.on_price_update(code, price_to_use)
                                except Exception as e:
                                    print(f"❌ [银河QMT] 回调执行失败: {e}")
            # 兼容老版本格式回退，以防万一服务端还没重启
            elif len(parts) >= 5:
                code_full = parts[1]
                last_price = float(parts[2]) if parts[2] else 0
                ask_price = float(parts[4]) if parts[4] else 0
                code = code_full.split('.')[0] if '.' in code_full else code_full
                price_to_use = ask_price if ask_price > 0 else last_price
                if price_to_use > 0:
                    with self.lock:
                        old_price = self.prices.get(code, 0)
                        self.prices[code] = price_to_use
                        if old_price != price_to_use:
                            print(f"⚡ [银河] {code} 价格更新: {price_to_use} (卖一: {ask_price}, 最新: {last_price})")
                            if self.on_price_update:
                                try:
                                    self.on_price_update(code, price_to_use)
                                except Exception as e:
                                    print(f"❌ [银河QMT] 回调执行失败: {e}")
        elif msg not in ["SUBSCRIBE_OK", "PONG", "OK"]:
            print(f"📬 [银河QMT] {msg}")
    
    def get_price(self, code: str) -> float:
        """获取指定代码的实时价格"""
        with self.lock:
            return self.prices.get(code, 0)
    
    def get_order_book(self, code: str) -> dict:
        """获取指定代码的完整盘口数据"""
        with self.lock:
            return self.order_books.get(code, {})
            
    def ping(self) -> bool:
        """心跳检测"""
        resp = self.single_shot_query("PING", timeout=5.0)
        return resp == "PONG"
    
    def stop(self):
        """停止客户端"""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        print("🛑 [银河QMT] 已断开连接")
