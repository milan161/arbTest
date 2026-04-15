# 02_fetch_trade_data.py - 生成LOF基金交易数据和分析报告
# 版本: 2.1.0
# 最后修改时间: 2026-03-17

import requests
import re
import os
import sys
import subprocess
import threading
import pandas as pd
from datetime import datetime, timedelta
import json
import yaml
import sqlite3
import random
import ssl
import socket
import time
import atexit
import logging

# 设置ibapi模块的日志级别，避免大量DEBUG信息刷屏
logging.getLogger('ibapi').setLevel(logging.WARNING)
logging.getLogger('ibapi.client').setLevel(logging.WARNING)
logging.getLogger('ibapi.wrapper').setLevel(logging.WARNING)
logging.getLogger('ibapi.utils').setLevel(logging.WARNING)

from flask import Flask, Response, jsonify, request, render_template, send_from_directory, redirect
from flask_socketio import SocketIO, emit
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

# 导入QMT Socket客户端
from readers.qmt_socket_client import QmtSocketClient

# 禁用SSL验证
ssl._create_default_https_context = ssl._create_unverified_context
import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='urllib3.connectionpool')
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 屏蔽 Eventlet 弃用警告，保持控制台清爽
warnings.filterwarnings('ignore', message='.*Eventlet is deprecated.*')

print("SUCCESS: 已配置数据源：东财SSE接口、新浪和IB Gateway")

# ====== [架构重构] 将庞杂的A股下单引擎与配置全部托管给独立的 TradeManager ======
try:
    from readers.trade_manager import TradeManager
    trade_manager = TradeManager()
    TDX_AVAILABLE = trade_manager.tdx_available
    tq = trade_manager.tq if TDX_AVAILABLE else None
except Exception as e:
    print(f"ERROR: TradeManager 加载异常 ({e})，交易功能可能不可用")
    trade_manager = None
    TDX_AVAILABLE = False

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# 基础目录与状态文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
ADMIN_STATUS_PATH = os.path.join(LOGS_DIR, "admin_status.json")
LOF00_PORT = int(os.environ.get("LOF00_PORT", "5001"))
LOF00_URL = os.environ.get("LOF00_URL", f"http://localhost:{LOF00_PORT}/")
os.makedirs(LOGS_DIR, exist_ok=True)

def _is_port_listening(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0

def _ensure_lof00_running():
    if _is_port_listening(LOF00_PORT):
        return True
    try:
        script_path = os.path.join(BASE_DIR, "LOF00_input_LOF_info.py")
        subprocess.Popen(
            [sys.executable, script_path],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(0.5)
        return _is_port_listening(LOF00_PORT)
    except Exception:
        return False

def _load_admin_status():
    if os.path.exists(ADMIN_STATUS_PATH):
        try:
            with open(ADMIN_STATUS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "011": {"status": "unknown", "last_run": None, "message": ""},
        "012": {"status": "unknown", "last_run": None, "message": ""},
        "woody": {"status": "unknown", "last_run": None, "message": ""},
    }

def _save_admin_status(status):
    try:
        with open(ADMIN_STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _set_admin_status(task, status, message=""):
    data = _load_admin_status()
    if task not in data:
        data[task] = {"status": "unknown", "last_run": None, "message": ""}
    data[task]["status"] = status
    data[task]["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data[task]["message"] = message
    _save_admin_status(data)

def _run_script_async(script_name, task_key, force_woody=False):
    def _runner():
        _set_admin_status(task_key, "running", "执行中")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # 强制禁用 Python 缓冲机制，实现实时输出
        env["PYTHONUNBUFFERED"] = "1"
        if force_woody:
            env["FORCE_WOODY_UPDATE"] = "1"
        script_path = os.path.join(BASE_DIR, script_name)
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", "-X", "utf8", script_path],
                cwd=BASE_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = proc.communicate()
            
            def smart_decode(b):
                if not b: return ""
                try: return b.decode('utf-8')
                except: pass
                try: return b.decode('gbk')
                except: return b.decode('utf-8', errors='replace')
                
            stdout = smart_decode(stdout_bytes)
            stderr = smart_decode(stderr_bytes)
            
            if proc.returncode == 0:
                _set_admin_status(task_key, "success", "完成")
            else:
                msg = (stderr or stdout or "执行失败").strip()[:200]
                _set_admin_status(task_key, "failed", msg)
        except Exception as e:
            _set_admin_status(task_key, "failed", str(e))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    return response

# ==========================================
# IB持久化连接与轮询类
# ==========================================
class IBReader(EWrapper, EClient):
    def __init__(self, client_id=5026):
        EClient.__init__(self, self)
        self.client_id = client_id
        # 🚀 优先尝试 Gateway(4001/4002) 获取纯净流，其次 TWS(7496/7497)
        self.target_ports = [4001, 4002, 7496, 7497] 
        self.current_port_index = 0
        self.connected = False
        self.retry_delay = 1.0 
        self.max_retry_delay = 60.0 
        self.polling_interval = 15 # 每 15 秒更新一次

        self.prices = {} 
        self.prev_closes = {} 
        self.sources = {} 
        self.last_update_time = None
        self.symbols = ["GLD", "USO", "XOP", "SLV"]
        self.req_id_counter = 1000 

        self.next_order_id = None
        self.req_events = {} 
        self.req_data = {} 
        
        # 内存长连接订阅池
        self.mkt_req_ids = {}      # reqId -> symbol
        self.symbol_req_ids = {}   # symbol -> reqId
        self.last_tick_time = {}   # symbol -> timestamp
        self.running = False
        self.polling_thread = None

    def _get_next_req_id(self):
        self.req_id_counter += 1
        return self.req_id_counter

    def connect_to_ib(self):
        target_port = self.target_ports[self.current_port_index]
        print(f"[IBReader] 尝试连接 IB Gateway/TWS (端口: {target_port}, ClientId: {self.client_id})...")
        try:
            self.connect("127.0.0.1", target_port, clientId=self.client_id)
            api_thread = threading.Thread(target=self.run, daemon=True)
            api_thread.start()
            time.sleep(2)
            if self.isConnected():
                self.connected = True
                self.retry_delay = 1.0
                print(f"[IBReader] ✅ 连接成功 (端口: {target_port})")
                return True
            else:
                print(f"[IBReader] ❌ 连接失败 (端口: {target_port})")
                self.disconnect()
                self.connected = False
                self.current_port_index = (self.current_port_index + 1) % len(self.target_ports)
                return False
        except Exception as e:
            print(f"[IBReader] ❌ 连接异常 (端口: {target_port}): {e}")
            self.disconnect()
            self.connected = False
            self.current_port_index = (self.current_port_index + 1) % len(self.target_ports)
            return False

    def disconnect_from_ib(self):
        if self.isConnected():
            self.disconnect()
            self.connected = False
            print("[IBReader] 🔌 已断开连接")

    def fetch_prev_closes_once(self):
        """如果昨收数据为空，则尝试获取一次。"""
        if not self.connected or self.prev_closes:
            return

        print("[IBReader] 昨收数据为空，尝试获取一次...")
        current_prev_closes = {}
        req_ids = []
        for sym in self.symbols:
            req_id_prev = self._get_next_req_id()
            req_ids.append(req_id_prev)
            c_prev = Contract()
            c_prev.symbol, c_prev.secType, c_prev.exchange, c_prev.currency = sym, "STK", "SMART", "USD"
            self.req_events[req_id_prev] = threading.Event()
            self.reqHistoricalData(req_id_prev, c_prev, "", "1 D", "1 day", "TRADES", 1, 1, False, [])

        # 等待所有请求完成，最多5秒
        start_time = time.time()
        while not all(self.req_events.get(req_id, threading.Event()).is_set() for req_id in req_ids) and (time.time() - start_time < 5):
            time.sleep(0.1)

        for req_id, sym in zip(req_ids, self.symbols):
             prev_close_bar = self.req_data.get(req_id)
             if prev_close_bar: current_prev_closes[sym] = prev_close_bar
        
        if current_prev_closes:
            self.prev_closes = current_prev_closes
            print(f"[IBReader] 📊 已获取昨日收盘价: " + ", ".join([f"{k}=${v:.2f}" for k, v in self.prev_closes.items()]))

    def start_polling(self):
        if not self.running:
            self.running = True
            self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.polling_thread.start()
            print("[IBReader] 启动 IB 后台轮询线程")

    def stop_polling(self):
        self.running = False
        if self.polling_thread:
            self.polling_thread.join(timeout=5)

    def _polling_loop(self):
        while self.running:
            # 动态更新IB监听标的，自动抓取新加的 ETF（如 SPY, QQQ 等）的夜盘行情
            try:
                with open('lof_config.yaml', 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f)
                    syms = set(["GLD", "USO", "XOP", "SLV", "SPY", "QQQ"])
                    for fund in cfg.get('funds', []):
                        for h in fund.get('valuation_portfolio', []):
                            sym = h.get('symbol', '').split('-')[0].replace('^', '')
                            if sym: syms.add(sym)
                        trade_etf = fund.get('trade_etf', '')
                        if trade_etf:
                            syms.add(trade_etf)
                    self.symbols = list(syms)
            except: pass

            if not self.connected:
                print(f"[IBReader] 未连接，等待 {self.retry_delay:.1f}s 后重试...")
                if self.connect_to_ib():
                    self.retry_delay = 1.0
                    # 重连后清空订阅池，触发重新订阅
                    self.mkt_req_ids.clear()
                    self.symbol_req_ids.clear()
                else:
                    time.sleep(self.retry_delay)
                    self.retry_delay = min(self.retry_delay * 2, self.max_retry_delay)
                continue
            
            self.fetch_prev_closes_once()

            now = datetime.now()
            current_time = now.time()
            is_summer_time = 3 <= now.month <= 11
            if is_summer_time:
                night_start = datetime.strptime("08:00", "%H:%M").time()
                night_end = datetime.strptime("16:00", "%H:%M").time()
                session_name = "夏令时"
            else:
                night_start = datetime.strptime("09:00", "%H:%M").time()
                night_end = datetime.strptime("17:00", "%H:%M").time()
                session_name = "冬令时"
            
            is_night = night_start <= current_time < night_end
            message = f"当前为美股{session_name}夜盘时段" if is_night else f"当前非夜盘时段({night_start.strftime('%H:%M')}-{night_end.strftime('%H:%M')})"
            
            if not is_night:
                self.prices, self.sources, self.last_update_time = {}, {}, datetime.now()
                # 非夜盘期间，取消所有订阅以释放资源
                for req_id in list(self.mkt_req_ids.keys()):
                    self.cancelMktData(req_id)
                self.mkt_req_ids.clear()
                self.symbol_req_ids.clear()
                time.sleep(self.polling_interval * 2) # 非夜盘时段降低轮询频率
                continue

            for sym in self.symbols:
                # 1. 建立并维持内存长连接订阅 (零违规风险)
                if sym not in self.symbol_req_ids:
                    req_id = self._get_next_req_id()
                    self.symbol_req_ids[sym] = req_id
                    self.mkt_req_ids[req_id] = sym
                    
                    c = Contract()
                    c.symbol, c.secType, c.exchange, c.currency = sym, "STK", "OVERNIGHT", "USD"
                    # snapshot=False 开启持续长连接推送
                    self.reqMktData(req_id, c, "", False, False, [])
                    self.sources[sym] = "订阅请求中..."
                    # 💡 核心修复：初始化时间戳，给予长连接 60 秒的建立宽限期，防止开局就误触兜底机制
                    self.last_tick_time[sym] = time.time()
                    print(f"[IBReader] 📡 已发起 {sym} 夜盘长连接订阅 (ReqId: {req_id})")
            
            # 2. 安全兜底看门狗 (Watchdog) - 检查长连接是否生效
            current_timestamp = time.time()
            fallback_needed = []
            for sym in self.symbols:
                last_tick = self.last_tick_time.get(sym, 0)
                # 如果超过 60 秒没收到真实推送，说明账号无此权限或行情断流，加入兜底队列
                if current_timestamp - last_tick > 60:
                    fallback_needed.append(sym)

            if fallback_needed:
                for sym in fallback_needed:
                    req_id_snap = self._get_next_req_id()
                    c_snap = Contract()
                    c_snap.symbol, c_snap.secType, c_snap.exchange, c_snap.currency = sym, "STK", "OVERNIGHT", "USD"
                    self.req_events[req_id_snap] = threading.Event()
                    # 兜底请求必须是 BID，获取无滑点盘口
                    self.reqHistoricalData(req_id_snap, c_snap, "", "1800 S", "1 min", "BID", 0, 1, False, [])
                    
                    self.req_events[req_id_snap].wait(timeout=3.0)
                    price = self.req_data.get(req_id_snap)
                    if price:
                        if sym not in self.prices or not isinstance(self.prices[sym], dict):
                            self.prices[sym] = {'bid': 0.0, 'ask': 0.0}
                        self.prices[sym]['bid'] = price
                        self.prices[sym]['ask'] = price # 快照拿不到Ask，用Bid平替
                        self.sources[sym] = "安全快照"
                        self.last_update_time = datetime.now()
            
            if self.prices:
                log_msg = ", ".join([f"{k}=${v.get('bid',0):.2f}({self.sources.get(k,'')})" for k, v in self.prices.items() if isinstance(v, dict)])
                print(f"[IBReader] 📊 已更新: {log_msg}")
            
            # 长连接模式下，循环短暂停留即可，底层的 tickPrice 会毫秒级疯狂更新字典。只有走到兜底才需要长休眠防封禁。
            time.sleep(30 if fallback_needed else 5)

    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.next_order_id = orderId
        print(f"[IBReader] ✅ 获取到下一个可用订单 ID: {orderId}")

    def error(self, reqId, *args):
        if len(args) >= 2:
            if isinstance(args[0], int) and args[0] > 1000000000:
                errorCode, errorString = args[1], (args[2] if len(args) > 2 else "")
            else:
                errorCode, errorString = args[0], args[1]
        else:
            return
        # 🤫 彻底屏蔽 10089(延时警告) 和 10346(持仓通道被TWS强制抢占警告)
        if errorCode in [2103, 2104, 2105, 2106, 2107, 2108, 2157, 2158, 10091, 10197, 10089, 10346]:
            return
            
        # 智能诊断：拦截典型的“无行情订阅权限”错误码
        if errorCode in [354, 10090, 10167, 10168]:
            print(f"[IBReader] 💡 提示 (代码 {errorCode}): 您的账号无美股实时行情订阅权限，系统已自动转入【安全快照】兜底模式，不影响套利运行。")
            return
            
        print(f"[IBReader] ⚠️ Error {errorCode}: {errorString}")
        if errorCode in [502, 504, 1100, 1101, 1102]:
            self.connected = False
            self.disconnect_from_ib()
            self.mkt_req_ids.clear()
            self.symbol_req_ids.clear()
            if reqId in self.req_events:
                self.req_events[reqId].set()

    def tickPrice(self, reqId, tickType, price, attrib):
        if price > 0:
            sym = self.mkt_req_ids.get(reqId)
            if sym:
                if sym not in self.prices or not isinstance(self.prices[sym], dict):
                    self.prices[sym] = {'bid': 0.0, 'ask': 0.0}
                
                # 💡 只要长连接有任何跳动，都喂一口看门狗，重置30秒倒计时
                if tickType in [1, 2, 4, 66, 67, 68]:
                    self.last_tick_time[sym] = time.time()
                
                # 实时价格类型映射
                tick_names = {
                    1: "Bid(实时买一)", 2: "Ask(实时卖一)", 4: "Last(实时最新)",
                    66: "Bid(延迟买一)", 67: "Ask(延迟卖一)", 68: "Last(延迟最新)"
                }
                
                if tickType in [1, 66]: # Bid
                    self.prices[sym]['bid'] = price
                    self.sources[sym] = "长连接"
                elif tickType in [2, 67]: # Ask
                    self.prices[sym]['ask'] = price
                elif tickType in [4, 68] and self.prices[sym]['bid'] == 0.0: # 如果买卖一价为空，用最新价兜底
                    self.prices[sym]['bid'] = price
                    self.prices[sym]['ask'] = price
                
                self.last_update_time = datetime.now()
                
                # WebSocket推送实时价格更新
                if tickType in tick_names:
                    now_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    socketio.emit('ib_price_update', {
                        'symbol': sym,
                        'price': price,
                        'tickType': tickType,
                        'tickName': tick_names[tickType],
                        'timestamp': now_str,
                        'prices': self.prices
                    })
            else:
                if tickType in [1, 66]:
                    self.req_data[reqId] = price
                    if reqId in self.req_events: self.req_events[reqId].set()

    def historicalData(self, reqId, bar):
        self.req_data[reqId] = bar.close

    def historicalDataEnd(self, reqId, start, end):
        if reqId in self.req_events: self.req_events[reqId].set()

    def place_us_order(self, symbol, action, quantity, price):
        if not self.isConnected():
            return False, "IB 未连接"
            
        if self.next_order_id is None:
            self.reqIds(-1)
            for _ in range(10):
                if self.next_order_id is not None: break
                time.sleep(0.1)
                
        if self.next_order_id is None:
            return False, "无法获取有效订单 ID，请检查 TWS 是否开启了 '只读API' 限制"
            
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        contract.exchange = "OVERNIGHT"
        contract.currency = "USD"
        
        order = Order()
        order.action = action # 'BUY' 或 'SELL'
        order.orderType = "LMT"
        order.totalQuantity = float(quantity)
        order.lmtPrice = float(price)
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        order.outsideRth = True # 允许在盘前盘后(夏令时夜盘)成交
        
        order_id = self.next_order_id
        self.placeOrder(order_id, contract, order)
        self.next_order_id += 1 # 内部自增以便连续下单
        
        return True, f"指令已发送: {action} {quantity}股 {symbol} @ {price}"

# 创建唯一的实例，使用随机 Client ID 防止僵尸进程占用冲突
ib_reader_instance = IBReader(client_id=random.randint(5000, 9999))
atexit.register(ib_reader_instance.disconnect_from_ib)

# ==========================================
# 数据获取模块 DataFetcher
# ==========================================
class DataFetcher:
    def __init__(self):
        self.data_path = "data/"
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)

        self.sina_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/'
        }
        self.eastmoney_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://quote.eastmoney.com/',
            'Cookie': 'qgqt=1'
        }
        self.a_stock_holidays_2026 = ['2026-01-01', '2026-02-16', '2026-04-04'] # 节选
    
    def is_us_night_session(self):
        now = datetime.now()
        current_time = now.time()
        is_summer_time = 3 <= now.month <= 11
        if is_summer_time:
            night_start = datetime.strptime("08:00", "%H:%M").time()
            night_end = datetime.strptime("16:00", "%H:%M").time()
            session_name = "夏令时"
        else:
            night_start = datetime.strptime("09:00", "%H:%M").time()
            night_end = datetime.strptime("17:00", "%H:%M").time()
            session_name = "冬令时"
        
        is_night = night_start <= current_time < night_end
        message = f"当前为美股{session_name}夜盘时段" if is_night else f"当前非美股夜盘时段"
        return is_night, message
    
    def get_ib_night_prices(self):
        is_night, message = self.is_us_night_session()

        if not is_night:
            return {"error": "当前非夜盘时段", "message": message, "prices": {}, "prev_closes": ib_reader_instance.prev_closes}

        if not ib_reader_instance.connected:
            return {"error": "IB未连接", "message": "IB API 未连接", "prices": {}, "prev_closes": ib_reader_instance.prev_closes}

        # 尝试获取昨收（如果还没有）
        if not ib_reader_instance.prev_closes:
            ib_reader_instance.fetch_prev_closes_once()

        if not ib_reader_instance.prices:
            return {"error": "IB数据未就绪", "message": "IB数据正在获取中...", "prices": {}, "prev_closes": ib_reader_instance.prev_closes}

        return {
            "status": "success",
            "prices": ib_reader_instance.prices,
            "prev_closes": ib_reader_instance.prev_closes,
            "message": "成功获取IB夜盘价格",
            "timestamp": ib_reader_instance.last_update_time.strftime('%Y-%m-%d %H:%M:%S') if ib_reader_instance.last_update_time else ""
        }
    
    def fetch_lof_data_sina(self, fund_code):
        try:
            exchange_prefix = 'sh' if fund_code.startswith('5') else 'sz'
            sina_code = f"{exchange_prefix}{fund_code}"
            price_url = f"https://hq.sinajs.cn/list={sina_code}"
            price_response = requests.get(price_url, headers=self.sina_headers, timeout=5)
            price = None
            if price_response.status_code == 200:
                match = re.search(r'"([^"]+)"', price_response.text)
                if match:
                    parts = match.group(1).split(',')
                    if len(parts) > 7: # 确保有卖一价
                        # 优先使用卖一价(parts[7])，如果为0则用最新成交价(parts[3])
                        ask_price = float(parts[7])
                        last_price = float(parts[3])
                        price = ask_price if ask_price > 0 else last_price
            
            nav_url = f"http://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=3"
            nav_headers = {'Referer': 'http://fundf10.eastmoney.com/'}
            nav = None
            try:
                nav_response = requests.get(nav_url, headers=nav_headers, timeout=5)
                nav_data = nav_response.json()
                if nav_data.get('Data') and nav_data['Data'].get('LSJZList'):
                    nav = float(nav_data['Data']['LSJZList'][0]['DWJZ'])
            except: pass
            
            result = {'price': price, 'nav': nav}
            if price and nav:
                result['premium'] = (price - nav) / nav * 100
            return result
        except Exception as e:
            return {"nav": None, "price": None, "premium": None}
    
    def get_lof_data(self, fund_code):
        return self.fetch_lof_data_sina(fund_code)

    def print_current_date_info(self):
        print(f"\n=== 系统就绪 ===")
        return {}

class SinaFuturesReader:
    def __init__(self):
        self.prices = {'GC': 0, 'CL': 0, 'AG': 0, 'NQ': 0, 'ES': 0}
        self.prev_prices = {'GC': 0, 'CL': 0, 'AG': 0, 'NQ': 0, 'ES': 0}
        self.settlement_prices = {'AG': 0, 'GC': 0, 'CL': 0, 'NQ': 0, 'ES': 0}
        self.sources = {'GC': '新浪API', 'CL': '新浪API', 'AG': '新浪API', 'NQ': '新浪API', 'ES': '新浪API'}
        self.headers = {'Referer': 'https://finance.sina.com.cn/'}
    
    def is_trading_time(self):
        now = time.localtime()
        h, m = now.tm_hour, now.tm_min
        wd = now.tm_wday
        if 0 <= wd <= 4:
            if (h == 9 and m >= 0) or (h == 10) or (h == 11 and m < 30): return True
            if (h == 13 and m >= 30) or (h == 14) or (h == 15 and m == 0): return True
            if (h >= 21) or (h < 3): return True
        elif wd == 5 and h < 3: return True
        return False
    
    def get_price(self, symbol): return self.prices.get(symbol, 0)
    def get_settlement_price(self, symbol): return self.settlement_prices.get(symbol, 0)
    def get_source(self, symbol): return self.sources.get(symbol, '未知')
    def get_change_percent(self, symbol):
        cp, pp = self.prices.get(symbol, 0), self.prev_prices.get(symbol, 0)
        return (cp - pp) / pp * 100 if pp > 0 else 0.0
    
    def update_prices(self):
        # 移除交易时间限制，确保美股期货数据始终更新
        trading_time = True
        url = "http://hq.sinajs.cn/list=hf_GC,hf_CL,nf_AG0,hf_NQ,hf_ES"
        # 存储所有期货的结算价数据
        futures_data = {'GC': 0, 'CL': 0, 'NQ': 0, 'ES': 0}
        try:
            time.sleep(random.uniform(1, 3))
            res = requests.get(url, headers=self.headers, timeout=10)
            res.encoding = 'gbk'
            if res.status_code == 200:
                for line in res.text.strip().split('\n'):
                    if 'hf_GC' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            current_price = float(v[0])
                            yesterday_settlement = float(v[7])
                            old_price = self.prices.get('GC', 0)
                            if old_price != current_price:
                                self.prices['GC'] = current_price
                                # WebSocket推送期货价格更新
                                socketio.emit('futures_price_update', {
                                    'symbol': 'GC',
                                    'price': current_price,
                                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                    'source': '新浪API'
                                })
                            self.prev_prices['GC'] = yesterday_settlement
                            self.settlement_prices['GC'] = yesterday_settlement
                            futures_data['GC'] = yesterday_settlement
                    elif 'hf_CL' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            current_price = float(v[0])
                            yesterday_settlement = float(v[7])
                            old_price = self.prices.get('CL', 0)
                            if old_price != current_price:
                                self.prices['CL'] = current_price
                                # WebSocket推送期货价格更新
                                socketio.emit('futures_price_update', {
                                    'symbol': 'CL',
                                    'price': current_price,
                                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                    'source': '新浪API'
                                })
                            self.prev_prices['CL'] = yesterday_settlement
                            self.settlement_prices['CL'] = yesterday_settlement
                            futures_data['CL'] = yesterday_settlement
                    elif 'hf_NQ' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            current_price = float(v[0])
                            yesterday_settlement = float(v[7])
                            old_price = self.prices.get('NQ', 0)
                            if old_price != current_price:
                                self.prices['NQ'] = current_price
                                # WebSocket推送期货价格更新
                                socketio.emit('futures_price_update', {
                                    'symbol': 'NQ',
                                    'price': current_price,
                                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                    'source': '新浪API'
                                })
                            self.prev_prices['NQ'] = yesterday_settlement
                            self.settlement_prices['NQ'] = yesterday_settlement
                            futures_data['NQ'] = yesterday_settlement
                    elif 'hf_ES' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            current_price = float(v[0])
                            yesterday_settlement = float(v[7])
                            old_price = self.prices.get('ES', 0)
                            if old_price != current_price:
                                self.prices['ES'] = current_price
                                # WebSocket推送期货价格更新
                                socketio.emit('futures_price_update', {
                                    'symbol': 'ES',
                                    'price': current_price,
                                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                    'source': '新浪API'
                                })
                            self.prev_prices['ES'] = yesterday_settlement
                            self.settlement_prices['ES'] = yesterday_settlement
                            futures_data['ES'] = yesterday_settlement
                    elif 'nf_AG0' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 15:
                            try:
                                buy_p, sell_p, close_p = float(v[6]), float(v[7]), float(v[8])
                                old_price = self.prices.get('AG', 0)
                                if buy_p > 0 and sell_p > 0:
                                    new_price = (buy_p + sell_p) / 2
                                else:
                                    new_price = close_p if close_p > 0 else float(v[3])
                                if old_price != new_price:
                                    self.prices['AG'] = new_price
                                    # WebSocket推送白银价格更新
                                    socketio.emit('futures_price_update', {
                                        'symbol': 'AG',
                                        'price': new_price,
                                        'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                        'source': '新浪API'
                                    })
                                self.prev_prices['AG'] = float(v[7]) if float(v[7])>0 else float(v[10])
                                self.settlement_prices['AG'] = float(v[9]) if float(v[9])>0 else float(v[11])
                            except: pass
                

        except Exception as e:
            print(f"更新期货价格时出错: {e}")
            pass

class SSEFuturesReader:
    def __init__(self):
        self.ag0_price, self.ag0_settlement, self.ag0_vwap = 0.0, 0.0, 0.0
        self.running = False
        self.connected = False
        self.retry_delay = 1.0
        self.sina_reader = SinaFuturesReader()
    
    def is_trading_time(self): return self.sina_reader.is_trading_time()
    def get_ag0_price(self): return self.ag0_price
    def get_ag0_settlement(self): return self.ag0_settlement
    def get_ag0_vwap(self): return self.ag0_vwap
    
    def start_sse_listener(self):
        if not self.running:
            self.running = True
            print("[SSEReader] 🚀 启动东财SSE白银(AGm)期货长连接监听线程...")
            threading.Thread(target=self._sse_listener, daemon=True).start()
    
    def stop_sse_listener(self): self.running = False
    
    def update_ag0_price(self):
        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        try:
            print("[SSEReader] 正在拉取东财SSE白银快照...")
            res = requests.get(url, headers={'Accept':'text/event-stream'}, stream=True, timeout=(5,10), verify=False)
            for i, line in enumerate(res.iter_lines()):
                if line and line.decode('utf-8').startswith('data:'):
                    try:
                        d = json.loads(line.decode('utf-8')[5:])['qt']
                        if 'p' in d:
                            old_price = self.ag0_price
                            new_price = float(d['p'])
                            if old_price != new_price:
                                self.ag0_price = new_price
                                # WebSocket推送白银价格更新
                                socketio.emit('futures_price_update', {
                                    'symbol': 'AG0',
                                    'price': new_price,
                                    'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                    'source': 'SSE'
                                })
                        if 'fzjsj' in d and d['fzjsj'] != '-': self.ag0_settlement = float(d['fzjsj'])
                        elif 'rzjsj' in d and d['rzjsj'] != '-': self.ag0_settlement = float(d['rzjsj'])
                        if 'cje' in d and 'vol' in d and d['vol'] > 0:
                            self.ag0_vwap = d['cje'] / (d['vol'] * 15)
                        elif 'av' in d and d['av'] != '-': # 有时会直接返回均价
                            self.ag0_vwap = float(d['av'])
                        break
                    except: pass
                if i > 5: break
            res.close()
        except: pass
        
    def _sse_listener(self):
        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        while self.running:
            if not self.is_trading_time():
                self.connected = False
                time.sleep(10)
                continue
            try:
                res = requests.get(url, stream=True, timeout=(5,30), verify=False)
                if res.status_code == 200:
                    if not self.connected:
                        print("[SSEReader] 🔗 东财SSE白银长连接建立成功，等待推送...")
                    self.connected = True
                    self.retry_delay = 1.0
                    last_log_time = 0
                    update_count = 0
                    for line in res.iter_lines():
                        if not self.running or not self.is_trading_time(): break
                        if line and line.decode('utf-8').startswith('data:'):
                            try:
                                d = json.loads(line.decode('utf-8')[5:])['qt']
                                updated = False
                                if 'p' in d:
                                    new_price = float(d['p'])
                                    if new_price != self.ag0_price:
                                        self.ag0_price = new_price
                                        db_manager.save_futures_data('AG0', self.ag0_price, 'SSE')
                                        # WebSocket推送白银价格更新
                                        socketio.emit('futures_price_update', {
                                            'symbol': 'AG0',
                                            'price': new_price,
                                            'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                            'source': 'SSE'
                                        })
                                        updated = True
                                if 'fzjsj' in d and d['fzjsj'] != '-': self.ag0_settlement = float(d['fzjsj'])
                                if 'cje' in d and 'vol' in d and d['vol'] > 0:
                                    # 绝对原汁原味计算，剔除任何兜底伪造逻辑
                                    self.ag0_vwap = d['cje'] / (d['vol'] * 15)
                                    
                                if updated:
                                    current_time = time.time()
                                    if current_time - last_log_time >= 30:
                                        print(f"[SSEReader] 📈 白银流数据已更新: 最新价={self.ag0_price}, 结算价={self.ag0_settlement}, VWAP={self.ag0_vwap:.2f}")
                                        last_log_time = current_time
                            except: pass
                else: raise Exception()
            except:
                self.connected = False
                self.sina_reader.update_prices()
                if self.sina_reader.prices['AG'] > 0:
                    self.ag0_price = self.sina_reader.prices['AG']
                time.sleep(self.retry_delay)
                self.retry_delay = min(self.retry_delay*2, 30.0)

class LOFPriceReader:
    """LOF实时盘口报价读取器：QMT Socket优先 > 通达信推送/快照 > 新浪API兜底"""
    def __init__(self):
        self.lof_prices = {}
        self.running = False
        self.use_tdx = False
        self.use_qmt = False
        
        # QMT Socket客户端
        self.qmt_client = None
        
        self.lof_codes = ['160719', '160723', '161116', '164701', '161129', '161226', '162411', '501018']
        try:
            with open('lof_config.yaml', 'r', encoding='utf-8') as f:
                self.lof_codes = [x['code'] for x in yaml.safe_load(f).get('funds', [])]
        except: pass
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/'
        }

    def _get_tdx_code(self, code):
        return f"{code}.SH" if code.startswith('5') else f"{code}.SZ"
    
    def _get_qmt_code(self, code):
        return f"{code}.SH" if code.startswith('5') else f"{code}.SZ"
        
    def get_source_name(self):
        if self.use_qmt: return "银河QMT (Socket极速)"
        if self.use_tdx: return "通达信 (内存直连)"
        return "新浪API (轮询兜底)"

    def reconnect(self):
        print("🔄 [手动触发] 尝试重新挂载 A股 LOF 极速行情通道...")
        self.stop_price_polling()
        time.sleep(1.0) # 给旧线程一点时间退出和释放资源
        self.start_price_polling()
        return self.get_source_name()
    
    def _on_tdx_update(self, data_str):
        """通达信价格跳动实时推送回调"""
        try:
            data = json.loads(data_str)
            stock_code = data.get('Code')
            if stock_code:
                # 价格跳动后，顺手拉取完整快照更新内存字典
                snap = tq.get_market_snapshot(stock_code=stock_code)
                if isinstance(snap, dict):
                    # 优先使用卖一价，如果卖一价为0（比如涨停），则使用最新成交价作为替代
                    price_to_use = float(snap.get('Sell1', 0))
                    if price_to_use == 0:
                        price_to_use = float(snap.get('Now', 0))

                    if price_to_use > 0:
                        code = stock_code.split('.')[0]
                        old_price = self.lof_prices.get(code, 0)
                        self.lof_prices[code] = price_to_use
                        # WebSocket推送LOF价格更新
                        if old_price != price_to_use:
                            socketio.emit('lof_price_update', {
                                'code': code,
                                'price': price_to_use,
                                'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            })
        except:
            pass
        
    def start_price_polling(self):
        if not self.running:
            self.running = True
            self.use_qmt = False
            self.use_tdx = False
            print("\n" + "="*55)
            print("📡 [行情引擎] 正在初始化 A股 LOF 实时行情流...")
            
            # 【优先级1】尝试挂载银河QMT Socket长连接
            try:
                def on_qmt_price_update(code, price):
                    old_price = self.lof_prices.get(code, 0)
                    self.lof_prices[code] = price
                    if not hasattr(self, '_qmt_success_logged') and price > 0:
                        print("  ✅ [行情状态] 银河QMT数据接收成功，行情链路畅通！")
                        self._qmt_success_logged = True
                    if old_price != price:
                        socketio.emit('lof_price_update', {
                            'code': code,
                            'price': price,
                            'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        })
                
                self.qmt_client = QmtSocketClient(on_price_update=on_qmt_price_update)
                if self.qmt_client.connect():
                    if self.qmt_client.ping():
                        self.qmt_client.start_long_connection()
                        qmt_codes = [self._get_qmt_code(c) for c in self.lof_codes]
                        self.qmt_client.subscribe(qmt_codes)
                        
                        self.use_qmt = True
                        print("  🚀 [引擎启动] 首选引擎【银河QMT Socket】已成功挂载！")
            except Exception as e:
                print(f"  ⚠️ [引擎降级] 银河QMT初始化失败({e})，尝试备用通道...")
                self.use_qmt = False
                if self.qmt_client:
                    self.qmt_client.stop()
                    self.qmt_client = None
            
            if not self.use_qmt and TDX_AVAILABLE:
                try:
                    tq.initialize(__file__)
                    self.use_tdx = True
                    print("  🚀 [引擎启动] 备用引擎【通达信内存直连】已成功挂载！")
                    print("  💡 [系统提示] 请确保您的通达信客户端已登录并保持运行。")
                except Exception as e:
                    self.use_tdx = False
                    print(f"  ⚠️ [引擎降级] 通达信初始化失败({e})，退回至新浪API模式")
            
            if not self.use_qmt and not self.use_tdx:
                print("  🐌 [引擎启动] 最终兜底引擎【新浪轮询爬虫】已启用 (间隔20秒)")
            print("="*55 + "\n")
                    
            threading.Thread(target=self._price_polling, daemon=True).start()
            
    def get_price(self, symbol):
        """获取LOF交易价格"""
        return self.lof_prices.get(symbol, 0)

    def stop_price_polling(self):
        self.running = False
        if self.use_qmt and self.qmt_client:
            try:
                self.qmt_client.stop()
            except:
                pass
        if self.use_tdx:
            try:
                tq.close()
            except:
                pass
    
    def _price_polling(self):
        last_codes = set()
        while self.running:
            try:
                # 动态加载最新基金列表，让后端无缝衔接新加的LOF，无需重启5000黑窗口
                try:
                    with open('lof_config.yaml', 'r', encoding='utf-8') as f:
                        self.lof_codes = [x['code'] for x in yaml.safe_load(f).get('funds', [])]
                        current_codes = [x['code'] for x in yaml.safe_load(f).get('funds', [])]
                        if current_codes: self.lof_codes = current_codes
                except: pass
                
                if self.use_qmt and self.qmt_client:
                    # ======== 模式一：银河QMT Socket（优先级最高，实时推送）========
                    # 价格更新已通过回调函数处理
                    # 如果订阅列表有变化，重新订阅
                    if set(self.lof_codes) != last_codes:
                        last_codes = set(self.lof_codes)
                        qmt_codes = [self._get_qmt_code(c) for c in self.lof_codes]
                        self.qmt_client.subscribe(qmt_codes)
                    # QMT模式下短休眠
                    time.sleep(1)
                    
                elif self.use_tdx:
                    # ======== 模式二：通达信纯本地读取 ========
                    # 1. 如果 YAML 监控池发生了增删，动态修改通达信的底层推送订阅
                    if set(self.lof_codes) != last_codes:
                        old_stocks = [self._get_tdx_code(c) for c in last_codes]
                        if old_stocks:
                            try: tq.unsubscribe_hq(stock_list=old_stocks)
                            except: pass
                        last_codes = set(self.lof_codes)
                        new_stocks = [self._get_tdx_code(c) for c in self.lof_codes]
                        if new_stocks:
                            try: tq.subscribe_hq(stock_list=new_stocks, callback=self._on_tdx_update)
                            except: pass
                    
                    # 2. 除了靠回调，每隔10秒主动拉一次最新快照（防止断流兜底），全走本地内存0延迟！
                    tdx_stocks = [self._get_tdx_code(c) for c in self.lof_codes]
                    for stock in tdx_stocks:
                        try:
                            # 严格匹配您的测试脚本: 显式传入 field_list=[] 以获取完整快照
                            snap = tq.get_market_snapshot(stock_code=stock, field_list=[])
                            if snap:
                                # 优先使用卖一价，如果卖一价为0（比如涨停），则使用最新成交价作为替代
                                price_to_use = float(snap.get('Sell1', 0))
                                if price_to_use == 0:
                                    price_to_use = float(snap.get('Now', 0))

                                if price_to_use > 0:
                                    code = stock.split('.')[0]
                                    self.lof_prices[code] = price_to_use
                                    if not hasattr(self, '_tdx_success_logged'):
                                        print(f"  ✅ [行情状态] 通达信接口首次获取 {code} 成功，链路畅通！")
                                        self._tdx_success_logged = True
                        except: pass
                    time.sleep(10) # 纯本地读取，10秒足够高频，也不会卡死
                    
                else:
                    # ======== 模式三：新浪外网爬虫兜底 ========
                    qs = [f"{'sh' if c.startswith('5') else 'sz'}{c}" for c in self.lof_codes]
                    for i in range(0, len(qs), 40):
                        res = requests.get(f"https://hq.sinajs.cn/list={','.join(qs[i:i+40])}", headers=self.headers, timeout=10)
                        res.encoding = 'gbk'
                        for line in res.text.strip().split('\n'):
                            match = re.search(r'hq_str_[a-z]{2}(\d{6})="([^"]+)"', line)
                            if match:
                                code = match.group(1)
                                parts = match.group(2).split(',')
                                if len(parts) > 7: # 确保有卖一价字段
                                    old_price = self.lof_prices.get(code, 0)
                                    # 优先使用卖一价(parts[7])，如果卖一价为0（比如涨停），则使用最新成交价(parts[3])
                                    ask_price = float(parts[7])
                                    last_price = float(parts[3])
                                    new_price = ask_price if ask_price > 0 else last_price
                                    self.lof_prices[code] = new_price
                                    # WebSocket推送LOF价格更新
                                    if old_price != new_price:
                                        socketio.emit('lof_price_update', {
                                            'code': code,
                                            'price': new_price,
                                            'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
                                        })
                    time.sleep(20) # 爬虫间隔必须长于20秒，防止封IP
            except: pass
            time.sleep(20)

class FuturePriceService:
    def __init__(self):
        self.sina_reader = SinaFuturesReader()
        self.sse_reader = SSEFuturesReader()
        self.running = False
        
    def start_polling(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._polling_loop, daemon=True).start()
            
    def stop_polling(self): self.running = False
    
    def _polling_loop(self):
        while self.running:
            self.update_prices()
            time.sleep(20)

    def get_price(self, symbol):
        if symbol == 'AG0': return self.sse_reader.ag0_price if self.sse_reader.ag0_price > 0 else self.sina_reader.prices['AG']
        return self.sina_reader.prices.get(symbol, 0)
        
    def get_settlement_price(self, symbol): 
        if symbol == 'AG0':
            return self.sse_reader.ag0_settlement if self.sse_reader.ag0_settlement > 0 else self.sina_reader.get_settlement_price('AG')
        # 对于其他期货，直接从sina_reader获取结算价
        return self.sina_reader.get_settlement_price(symbol)
        
    def get_vwap(self, symbol): 
        if symbol == 'AG0':
            return self.sse_reader.ag0_vwap  # 坚决不使用最新价兜底，暴露真实的0
        return 0

    def get_source(self, symbol):
        if symbol == 'AG0': return 'SSE' if self.sse_reader.ag0_price > 0 else '新浪API'
        return self.sina_reader.get_source(symbol)
    def get_change_percent(self, symbol): return self.sina_reader.get_change_percent('AG' if symbol=='AG0' else symbol)
    
    def update_prices(self):
        self.sina_reader.update_prices()
        if not self.sse_reader.running:
            self.sse_reader.update_ag0_price()

class DatabaseManager:
    def __init__(self):
        os.makedirs('data', exist_ok=True)
        self.db_path = 'data/lof_arb.db'
        self.init_db()
        
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute('PRAGMA journal_mode=WAL;')
        return conn
    
    def init_db(self):
        conn = self._get_conn()
        conn.execute('CREATE TABLE IF NOT EXISTS lof_data (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, fund_code TEXT, price REAL, nav REAL, premium REAL, created_at TEXT, UNIQUE(date, fund_code))')
        conn.execute('CREATE TABLE IF NOT EXISTS futures_data (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER, symbol TEXT, price REAL, source TEXT, created_at TEXT)')
        conn.commit()
        conn.close()
        
    def save_lof_data(self, date, fund_code, price, nav, premium):
        conn = self._get_conn()
        conn.execute('INSERT OR REPLACE INTO lof_data (date, fund_code, price, nav, premium, created_at) VALUES (?, ?, ?, ?, ?, ?)', (date, fund_code, price, nav, premium, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        
    def save_futures_data(self, symbol, price, source):
        conn = self._get_conn()
        conn.execute('INSERT INTO futures_data (timestamp, symbol, price, source, created_at) VALUES (?, ?, ?, ?, ?)', (int(time.time()), symbol, price, source, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()

db_manager = DatabaseManager()
future_service = FuturePriceService()
sse_reader = SSEFuturesReader()
lof_price_reader = LOFPriceReader()

# WebSocket事件处理
@socketio.on('connect')
def handle_connect():
    print('前端WebSocket连接成功')
    # 发送当前价格快照
    emit('ib_price_snapshot', {
        'prices': ib_reader_instance.prices,
        'prev_closes': ib_reader_instance.prev_closes,
        'timestamp': ib_reader_instance.last_update_time.strftime('%Y-%m-%d %H:%M:%S') if ib_reader_instance.last_update_time else ""
    })
    # 发送LOF价格快照
    emit('lof_price_snapshot', {
        'prices': lof_price_reader.lof_prices,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    # 发送期货价格快照
    emit('futures_price_snapshot', {
        'prices': future_service.sina_reader.prices,
        'settlement_prices': future_service.sina_reader.settlement_prices,
        'sources': future_service.sina_reader.sources,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@socketio.on('disconnect')
def handle_disconnect():
    print('前端WebSocket断开连接')

@app.route('/api/futures')
def get_futures_data():
    is_trading = future_service.sina_reader.is_trading_time()
    data = {
        'GC': {'price': future_service.get_price('GC'), 'change_percent': future_service.get_change_percent('GC'), 'source': future_service.get_source('GC')},
        'CL': {'price': future_service.get_price('CL'), 'change_percent': future_service.get_change_percent('CL'), 'source': future_service.get_source('CL')},
        'AG0': {'price': future_service.get_price('AG0'), 'change_percent': future_service.get_change_percent('AG0'), 'settlement': future_service.get_settlement_price('AG0'), 'vwap': future_service.get_vwap('AG0'), 'source': future_service.get_source('AG0')},
        'NQ': {'price': future_service.get_price('NQ'), 'change_percent': future_service.get_change_percent('NQ'), 'source': future_service.get_source('NQ')},
        'ES': {'price': future_service.get_price('ES'), 'change_percent': future_service.get_change_percent('ES'), 'source': future_service.get_source('ES')},
        'timestamp': int(time.time()),
        'is_trading_time': is_trading
    }
    return jsonify(data)

@app.route('/api/ib_prices')
def get_ib_prices():
    try:
        result = DataFetcher().get_ib_night_prices()
        if "error" in result:
            return jsonify({'status': 'error', 'message': result.get('message', '获取失败'), 'prices': result.get('prices', {}), 'prev_closes': result.get('prev_closes', {})}), 200
        return jsonify({'status': 'success', 'prices': result.get('prices', {}), 'prev_closes': result.get('prev_closes', {}), 'timestamp': result.get('timestamp')}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'prices': {}}), 500

@app.route('/api/exchange_rate')
def get_exchange_rate():
    """供前端实时拉取最新的汇率及对应日期"""
    try:
        filepath = os.path.join(BASE_DIR, 'data', 'GLD_USO_basic_data.csv')
        if os.path.exists(filepath):
            df = pd.read_csv(filepath)
            if '日期' in df.columns:
                df['日期'] = pd.to_datetime(df['日期'], errors='coerce')
                df = df.sort_values('日期', ascending=False)
                rate = df.iloc[0].get('人民币中间价')
                date_val = df.iloc[0].get('日期')
                if pd.notna(rate):
                    return jsonify({
                        "rate": float(rate),
                        "date": date_val.strftime('%Y-%m-%d') if pd.notna(date_val) else ""
                    })
    except Exception:
        pass
    return jsonify({"rate": None, "date": None})

@app.route('/api/lof')
def get_all_lof_data():
    return jsonify({code: {'price': lof_price_reader.get_price(code), 'time': datetime.now().strftime('%H:%M:%S')} for code in lof_price_reader.lof_codes})

@app.route('/api/lof/<fund_code>')
def get_lof_data(fund_code):
    data = DataFetcher().get_lof_data(fund_code)
    db_manager.save_lof_data(datetime.now().strftime('%Y-%m-%d'), fund_code, data.get('price',0), data.get('nav',0), data.get('premium',0))
    return jsonify(data)

@app.route('/api/lof_source')
def get_lof_source():
    return jsonify({'source': lof_price_reader.get_source_name()})

@app.route('/api/reconnect_lof', methods=['POST'])
def reconnect_lof():
    lof_price_reader.reconnect()
    return jsonify({'status': 'success', 'source': lof_price_reader.get_source_name()})

@app.route('/api/update-historical-data')
def update_historical_data():
    return jsonify({"success": False, "message": "此功能已移至011/012专用脚本"}), 200

@app.route('/admin/run/<task>', methods=['POST'])
def admin_run(task):
    if task == '011': _run_script_async("LOF011_generate_basic_data.py", "011")
    elif task == '012': _run_script_async("LOF012_generate_lof_data.py", "012")
    elif task == 'woody': _run_script_async("LOF011_generate_basic_data.py", "woody", force_woody=True)
    return jsonify({"status": "started", "task": task})

@app.route('/api/trade', methods=['POST'])
def api_trade():
    """接收前端的一键下单请求，并通过Socket转发给本地QMT或直接调用通达信"""
    data = request.get_json()
    action = data.get('action') # 'BUY' or 'SELL'
    symbol = data.get('symbol') # e.g. '162411.SZ'
    volume = data.get('volume', 100)
    price = data.get('price')
    broker = data.get('broker', 'yinhe_qmt')
    
    if trade_manager:
        success, msg = trade_manager.send_order(broker, action, symbol, volume, price)
        return jsonify({"status": "success" if success else "error", "message": msg})
    else:
        return jsonify({"status": "error", "message": "服务端 TradeManager 未启动，无法交易"}), 500

@app.route('/api/ib_trade', methods=['POST'])
def api_ib_trade():
    """接收前端发来的IB外盘下单指令"""
    data = request.get_json()
    action = data.get('action')
    symbol = data.get('symbol', '').strip().upper()
    volume = data.get('volume', 0)
    price = data.get('price', 0)
    
    if not symbol or float(volume) <= 0 or float(price) <= 0:
        return jsonify({"status": "error", "message": "参数非法: 代码, 数量或价格无效"}), 400
        
    success, msg = ib_reader_instance.place_us_order(symbol, action, volume, price)
    return jsonify({"status": "success" if success else "error", "message": msg})

@app.route('/sse/futures')
def sse_futures():
    """SSE端点，用于实时推送期货数据"""
    def generate():
        while True:
            is_trading = future_service.sina_reader.is_trading_time()
            data_dict = {
                'GC': {'price': future_service.get_price('GC'), 'change_percent': future_service.get_change_percent('GC'), 'source': future_service.get_source('GC')},
                'CL': {'price': future_service.get_price('CL'), 'change_percent': future_service.get_change_percent('CL'), 'source': future_service.get_source('CL')},
                'AG0': {'price': future_service.get_price('AG0'), 'change_percent': future_service.get_change_percent('AG0'), 'settlement': future_service.get_settlement_price('AG0'), 'vwap': future_service.get_vwap('AG0'), 'source': future_service.get_source('AG0')},
                'NQ': {'price': future_service.get_price('NQ'), 'change_percent': future_service.get_change_percent('NQ'), 'source': future_service.get_source('NQ')},
                'ES': {'price': future_service.get_price('ES'), 'change_percent': future_service.get_change_percent('ES'), 'source': future_service.get_source('ES')},
                'timestamp': int(time.time()),
                'is_trading_time': is_trading
            }
            data_json = json.dumps(data_dict)
            yield f'data: {data_json}\n\n'
            time.sleep(1) # 每秒推送一次
    return Response(generate(), mimetype='text/event-stream')

@app.route('/health')
def health_check():
    return jsonify({'status': 'ok'}), 200

@app.route('/')
def index():
    """动态渲染主页面 (SSR)"""
    try:
        import importlib
        import LOF03_generate_monitor_html
        importlib.reload(LOF03_generate_monitor_html) # 强制热重载03模块，修改03代码后刷新浏览器即可生效
        
        is_trading = future_service.sina_reader.is_trading_time()
        f_data = {
            'GC': {'price': future_service.get_price('GC'), 'change_percent': future_service.get_change_percent('GC'), 'source': future_service.get_source('GC')},
            'CL': {'price': future_service.get_price('CL'), 'change_percent': future_service.get_change_percent('CL'), 'source': future_service.get_source('CL')},
            'AG0': {'price': future_service.get_price('AG0'), 'change_percent': future_service.get_change_percent('AG0'), 'settlement': future_service.get_settlement_price('AG0'), 'vwap': future_service.get_vwap('AG0'), 'source': future_service.get_source('AG0')},
            'NQ': {'price': future_service.get_price('NQ'), 'change_percent': future_service.get_change_percent('NQ'), 'source': future_service.get_source('NQ')},
            'ES': {'price': future_service.get_price('ES'), 'change_percent': future_service.get_change_percent('ES'), 'source': future_service.get_source('ES')},
            'timestamp': int(time.time()),
            'is_trading_time': is_trading
        }
        
        ib_res = DataFetcher().get_ib_night_prices()
        if "error" in ib_res:
            ib_data = ({}, {}, ib_res.get("message", "IB未连接"))
        else:
            ib_data = (ib_res.get("prices", {}), ib_res.get("prev_closes", {}), ib_res.get("message", "IB夜盘价格已获取"))
            
        html_content = LOF03_generate_monitor_html.generate(futures_data=f_data, ib_data=ib_data)
        
        response = Response(html_content, mimetype='text/html')
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return response
    except Exception as e:
        import traceback
        return f"<h1>页面生成失败</h1><pre>{traceback.format_exc()}</pre>", 500

if __name__ == "__main__":
    print("🚀 启动LOF套利监控系统...")
    ib_reader_instance.start_polling()
    if sse_reader.is_trading_time():
        sse_reader.start_sse_listener()
    lof_price_reader.start_price_polling()
    future_service.start_polling()
    try:
        # 使用socketio.run()替代app.run()以支持WebSocket
        socketio.run(app, debug=False, host='0.0.0.0', port=5000)
    except OSError as e:
        if "10048" in str(e) or "Address already in use" in str(e):
            print("\n" + "❌"*20)
            print("【致命错误】Web服务器启动失败：端口 5000 被占用！")
            print("这通常是因为后台已经有一个 02 主程序正在运行，或者上次关闭不彻底。")
            print("👉 解决办法：")
            print("   1. 检查 VSCode 下方的终端面板，点击右侧的「垃圾桶」图标关闭所有旧终端。")
            print("   2. 或者打开 Windows 任务管理器，强制结束所有残留的 'python.exe' 进程。")
            print("   3. 清理完毕后，再次重新运行本脚本即可。")
            print("❌"*20 + "\n")
        else:
            print(f"启动服务器失败: {e}")
    except KeyboardInterrupt:
        ib_reader_instance.stop_polling()
#