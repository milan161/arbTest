# 02_fetch_trade_data.py - 生成LOF基金交易数据和分析报告
# 版本: 2.1.0
# 最后修改时间: 2026-03-17

import requests
import re
import os
# 强制全局禁用系统代理，防止所有爬虫和API请求报错 WinError 10061
os.environ['NO_PROXY'] = '*'
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

# 导入 ArbCore 公共基座中的数据库管理器
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arbcore.database.db_manager import DatabaseManager
from arbcore.fetchers.data_fetcher import data_fetcher as core_fetcher
from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
from arbcore.fetchers.ib_reader import IBReader

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

# 尝试导入富途API
try:
    from futu import OpenQuoteContext, SubType, Session
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

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

# ====== [架构重构] 延迟加载 A股下单引擎 (TradeManager) 解决端口冲突问题 ======
trade_manager = None
TDX_AVAILABLE = False
tq = None
_trade_manager_lock = threading.Lock()

def init_trade_manager():
    global trade_manager, TDX_AVAILABLE, tq
    with _trade_manager_lock:
        if trade_manager is not None: return
        try:
            from readers.trade_manager import TradeManager
            print("⚙️ [系统] 正在懒加载 TradeManager 交易引擎...")
            trade_manager = TradeManager()
            TDX_AVAILABLE = trade_manager.tdx_available
            tq = trade_manager.tq if TDX_AVAILABLE else None
            print("✅ [系统] TradeManager 交易引擎加载就绪。")
        except Exception as e:
            print(f"ERROR: TradeManager 加载异常 ({e})，交易功能可能不可用")
            trade_manager = None
            TDX_AVAILABLE = False
            tq = None

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

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

def on_ib_price_update(data):
    socketio.emit('ib_price_update', data)
    
# 创建唯一的实例，使用随机 Client ID 防止僵尸进程占用冲突
ib_reader_instance = IBReader(client_id=random.randint(5000, 9999), on_price_update=on_ib_price_update)
atexit.register(ib_reader_instance.disconnect_from_ib)

# ==========================================
# 数据获取模块 DataFetcher
# ==========================================
def is_us_night_session():
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

def get_ib_night_prices():
    is_night, message = is_us_night_session()
    if not is_night:
        return {"error": "当前非夜盘时段", "message": message, "prices": {}, "prev_closes": ib_reader_instance.prev_closes}
    if not ib_reader_instance.connected:
        return {"error": "IB未连接", "message": "IB API 未连接", "prices": {}, "prev_closes": ib_reader_instance.prev_closes}
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

def get_active_etf_symbols():
    """动态解析配置文件，提取所有活跃的美股 ETF 标的"""
    symbols = set()
    try:
        config_path = os.path.join(BASE_DIR, "lof_config.yaml")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
                for fund in cfg.get('funds', []):
                    for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                        sym = item.get('symbol', '').replace('^', '').split('-')[0].upper()
                        if sym and sym not in ['GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ']:
                            symbols.add(sym)
                    if fund.get('trade_etf'):
                        for s in str(fund.get('trade_etf')).replace('，', ',').split(','):
                            s = s.strip().upper()
                            if s and s not in ['GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ']:
                                symbols.add(s)
    except:
        pass
    # 兜底默认列表
    return list(symbols) if symbols else ['GLD', 'USO', 'XOP', 'XBI', 'XLY', 'SLV', 'SPY', 'QQQ', 'INDA', 'KWEB', 'RSPH']

class FutuReader:
    """富途行情长连接读取器"""
    def __init__(self):
        self.ctx = None
        self.prices = {}
        self.subscribed_codes = set()
        self.last_connect_time = 0
        self.last_log_time = 0
        
    def close(self):
        if self.ctx:
            try: self.ctx.close()
            except: pass
            self.ctx = None

    def get_prices(self, symbols):
        if not FUTU_AVAILABLE:
            return False, "未安装 futu-api 库 (pip install futu-api)", self.prices
            
        try:
            # 限制重连频率，避免富途OpenD未启动时狂刷错误
            if self.ctx is None:
                if time.time() - self.last_connect_time < 60:
                    return False, "富途OpenD未连接 (等待重连...)", self.prices
                self.last_connect_time = time.time()
                
                # 静音富途底层日志
                try:
                    import futu
                    futu.SysConfig.set_client_info('LOFarb')
                except: pass
                
                self.ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                self.subscribed_codes = set()
            
            futu_codes = [f"US.{sym}" for sym in symbols]
            new_codes = [c for c in futu_codes if c not in self.subscribed_codes]
            
            # 订阅新增加的股票，指定 Session.ALL 获取夜盘
            if new_codes:
                ret, data = self.ctx.subscribe(new_codes, [SubType.QUOTE], session=Session.ALL)
                if ret != 0:
                    self.close()  # 必须关闭失效的上下文，否则底层线程会无限重连导致控制台刷屏
                    return False, f"订阅失败: {data}", self.prices
                self.subscribed_codes.update(new_codes)
            
            ret, data = self.ctx.get_stock_quote(futu_codes)
            if ret == 0:
                for _, row in data.iterrows():
                    code = row['code'].replace('US.', '')
                    bid = 0.0
                    ask = 0.0
                    last = 0.0
                    
                    # 【修复】优先使用真正的买一价/卖一价，兼容夜盘数据
                    # bid_price_0 = 买一价, ask_price_0 = 卖一价, last_price = 最新价
                    if 'bid_price_0' in row and pd.notna(row['bid_price_0']) and float(row['bid_price_0']) > 0:
                        bid = float(row['bid_price_0'])
                    if 'ask_price_0' in row and pd.notna(row['ask_price_0']) and float(row['ask_price_0']) > 0:
                        ask = float(row['ask_price_0'])
                    if 'last_price' in row and pd.notna(row['last_price']) and float(row['last_price']) > 0:
                        last = float(row['last_price'])
                    
                    # 如果买一/卖一都缺失，尝试使用夜盘/盘前/盘后/最新价作为兜底
                    if bid <= 0 or ask <= 0:
                        # 优先级：夜盘 > 盘前 > 盘后 > 常规盘最新价
                        fallback_price = 0.0
                        if 'overnight_price' in row and pd.notna(row['overnight_price']) and float(row['overnight_price']) > 0:
                            fallback_price = float(row['overnight_price'])
                        elif 'pre_price' in row and pd.notna(row['pre_price']) and float(row['pre_price']) > 0:
                            fallback_price = float(row['pre_price'])
                        elif 'after_price' in row and pd.notna(row['after_price']) and float(row['after_price']) > 0:
                            fallback_price = float(row['after_price'])
                        elif 'last_price' in row and pd.notna(row['last_price']) and float(row['last_price']) > 0:
                            fallback_price = float(row['last_price'])
                        
                        if fallback_price > 0:
                            if bid <= 0: bid = fallback_price
                            if ask <= 0: ask = fallback_price
                    
                    # 如果仍有缺失，用last_price兜底bid/ask
                    if bid <= 0 and last > 0: bid = last
                    if ask <= 0 and last > 0: ask = last
                    if bid > 0 and ask <= 0: ask = bid  # 防止bid有值但ask为空
                    
                    if bid > 0:
                        self.prices[code] = {'bid': bid, 'ask': ask, 'last': last if last > 0 else bid}
                        
                # 增加控制台心跳回显 (每30秒打印一次)
                current_time = time.time()
                if current_time - self.last_log_time >= 30:
                    if self.prices:
                        price_strs = [f"{k}=${v['bid']:.2f}" for k, v in self.prices.items()]
                        print(f"🦉 [富途OpenD] 实时夜盘: {', '.join(price_strs)}")
                    self.last_log_time = current_time
                        
                return True, "成功获取富途夜盘价格", self.prices
            else:
                self.close()  # 接口返回错误时立即销毁上下文，切断底层的死亡重连循环
                return False, f"获取数据失败: {data}", self.prices
                
        except Exception as e:
            self.close()
            return False, f"富途接口异常: {str(e)}", self.prices

futu_reader = FutuReader()
atexit.register(futu_reader.close)

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
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
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
            res = requests.get(url, headers={'Accept':'text/event-stream'}, stream=True, timeout=(5,10), verify=False, proxies={"http": None, "https": None})
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
                res = requests.get(url, stream=True, timeout=(5,30), verify=False, proxies={"http": None, "https": None})
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
    """LOF实时盘口报价读取器：支持手动选择数据源（通达信新版 > 银河QMT > 新浪API）"""
    def __init__(self):
        self.lof_prices = {}
        self.running = False
        self.use_tdx = False
        self.use_qmt = False
        # self.use_guojin = False  # 国金QMT已注释，用户不使用
        self.preferred_source = "tongdaxin"  # 默认使用通达信新版
        self.start_time = time.time()
        
        # QMT Socket客户端
        self.qmt_client = None
        
        self.lof_codes = ['160719', '160723', '161116', '164701', '161129', '161226', '162411', '501018']
        try:
            import sys
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from arbcore.config.config_loader import get_fund_codes
            
            config_file = os.path.join(os.path.dirname(__file__), "lof_config.yaml")
            self.lof_codes = get_fund_codes(config_file)
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
        # 根据实际连接状态返回数据源名称
        if self.use_qmt: return "银河QMT (Socket极速)"
        if self.use_tdx: return "通达信 (内存直连)"
        # if self.use_guojin: return "国金QMT (原生直连)"
        return "新浪轮询兜底"

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
            # self.use_guojin = False  # 国金QMT已注释
            print("\n" + "="*55)
            print(f"📡 [行情引擎] 正在初始化 A股 LOF 实时行情流... (首选: {self.preferred_source})")
            
            # 【根据用户选择的数据源决定连接策略】
            source_priority = []
            if self.preferred_source == 'tongdaxin':
                source_priority = ['tongdaxin', 'sina']
            elif self.preferred_source == 'qmt':
                source_priority = ['qmt', 'tongdaxin', 'sina']
            else:  # sina
                source_priority = ['sina']
            
            # 【通达信新版】(优先级取决于用户选择)
            if 'tongdaxin' in source_priority:
                init_trade_manager()
                if TDX_AVAILABLE and tq:
                    try:
                        tq.initialize(__file__)
                        self.use_tdx = True
                        print("  🚀 [引擎启动] 【通达信新版】已成功挂载！")
                        print("  💡 [系统提示] 请确保您的通达信客户端已登录并保持运行。")
                    except Exception as e:
                        self.use_tdx = False
                        print(f"  ⚠️ [引擎降级] 通达信新版初始化失败({e})，尝试下一通道...")
            
            # 【银河QMT Socket】(仅当首选或通达信失败时)
            if not self.use_tdx and 'qmt' in source_priority:
                try:
                    def on_qmt_price_update(code, raw_price):
                        # 健壮性修复：检查 raw_price 是否为有效数字，过滤掉时间戳等异常数据
                        try:
                            # 尝试将 raw_price 转换为浮点数。如果失败，说明不是价格数据，直接忽略。
                            price_from_raw = float(raw_price)
                        except (ValueError, TypeError):
                            return # 静默忽略非价格数据

                        clean_code = code.split('.')[0] if '.' in code else code
                        
                        # 尝试从 qmt_client 提取完整五档盘口字典
                        order_book = None
                        if hasattr(self, 'qmt_client') and self.qmt_client:
                            order_book = self.qmt_client.get_order_book(clean_code)
                            
                        # 严格遵循"卖一价"原则，如果卖一价为0（如涨停封板），则兜底使用 raw_price (通常是最新成交价)
                        price = price_from_raw # 使用已经验证过的数字
                        if order_book:
                            ask1 = float(order_book.get('ask1_p', order_book.get('ask_p1', 0)))
                            if ask1 > 0:
                                price = ask1
                                
                        old_price = self.lof_prices.get(clean_code, 0)
                        self.lof_prices[clean_code] = price
                        
                        if not hasattr(self, '_qmt_success_logged') and price > 0:
                            print("  ✅ [行情状态] 银河QMT数据接收成功，行情链路畅通！")
                            self._qmt_success_logged = True
                            
                        # 1. 满足你在黑窗口看日志的需求 (为了防止刷屏太快，只在首次或价格变动时打印)
                        log_flag = f'_tick_logged_{clean_code}'
                        if order_book and (old_price != price or not hasattr(self, log_flag)):
                            ask1_print = order_book.get('ask1_p', order_book.get('ask_p1', price_from_raw))
                            last_p = order_book.get('last_price', price_from_raw)
                            print(f"⚡ [银河] {clean_code} 价格更新: {price:.3f} (卖一: {float(ask1_print):.3f}, 最新: {float(last_p):.3f})")
                            setattr(self, log_flag, True)

                        # 2. 将五档盘口打包，通过 WebSocket 穿透推送到前端自留地
                        payload = {
                            'code': clean_code,
                            'price': price,
                            'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        }
                        if order_book:
                            payload['order_book'] = order_book # 附加五档数据
                            # 额外发送沙盘专属深度数据事件
                            socketio.emit('lof_order_book_update', {'code': clean_code, 'data': order_book})

                        # 只要价格变动或者带有盘口数据，就推送给前端
                        if old_price != price or order_book:
                            socketio.emit('lof_price_update', payload)
                    
                    self.qmt_client = QmtSocketClient(on_price_update=on_qmt_price_update)
                    if self.qmt_client.connect():
                        self.qmt_client.start_long_connection()
                        qmt_codes = [self._get_qmt_code(c) for c in self.lof_codes]
                        self.qmt_client.subscribe(qmt_codes)
                        
                        self.use_qmt = True
                        print("  🚀 [引擎启动] 【银河QMT Socket】已成功挂载！")
                    else:
                        print("  ⚠️ [引擎降级] 银河QMT Socket(8888端口)连接被拒绝，请确认QMT内是否已运行Server端！")
                except Exception as e:
                    print(f"  ⚠️ [引擎降级] 银河QMT初始化失败({e})，尝试下一通道...")
                    self.use_qmt = False
                    if self.qmt_client:
                        self.qmt_client.stop()
                        self.qmt_client = None
            
            # 【国金QMT已注释】用户不使用
            # if not self.use_qmt and not self.use_tdx:
            #     try:
            #         from xtquant import xtdata
            #         _ = xtdata.get_full_tick(['510300.SH'])
            #         self.use_guojin = True
            #         print("  🚀 [引擎启动] 备用引擎【国金QMT (xtquant)】已成功挂载！")
            #         print("  💡 [系统提示] 请确保您的国金QMT/miniQMT已登录并保持运行。")
            #     except Exception as e:
            #         self.use_guojin = False
            #         print(f"  ⚠️ [引擎降级] 国金QMT初始化失败({e})，退回至新浪API模式")

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
                    
                # 【国金QMT已注释】用户不使用
                # elif self.use_guojin:
                #     # ======== 模式三：国金QMT (xtquant) ========
                #     try:
                #         from xtquant import xtdata
                #         if set(self.lof_codes) != last_codes:
                #             last_codes = set(self.lof_codes)
                #             new_stocks = [self._get_qmt_code(c) for c in self.lof_codes]
                #             if new_stocks:
                #                 for stock in new_stocks:
                #                     xtdata.subscribe_quote(stock, period='tick', count=1)
                #         
                #         guojin_stocks = [self._get_qmt_code(c) for c in self.lof_codes]
                #         ticks = xtdata.get_full_tick(guojin_stocks)
                #         
                #         # 掉线自动降级检测：如果连续15秒拿不到任何有效Tick数据
                #         if not ticks or all(not t for t in ticks.values()):
                #             self._guojin_empty_count = getattr(self, '_guojin_empty_count', 0) + 1
                #             if self._guojin_empty_count > 15:
                #                 print("  ⚠️ [行情告警] 国金QMT连续15秒未返回有效数据(可能已关闭)。自动降级至【新浪API兜底】！")
                #                 self.use_guojin = False
                #         else:
                #             self._guojin_empty_count = 0
                #         
                #         for stock, tick in ticks.items():
                #             if tick:
                #                 ask_prices = tick.get('askPrice', [0])
                #                 price_to_use = float(ask_prices[0]) if ask_prices else 0
                #                 if price_to_use == 0:
                #                     price_to_use = float(tick.get('lastPrice', 0))
                #                 
                #                 if price_to_use > 0:
                #                     code = stock.split('.')[0]
                #                     old_price = self.lof_prices.get(code, 0)
                #                     self.lof_prices[code] = price_to_use
                #                     if old_price != price_to_use:
                #                         socketio.emit('lof_price_update', {
                #                             'code': code,
                #                             'price': price_to_use,
                #                             'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]
                #                         })
                #                     if not getattr(self, '_guojin_success_logged', False):
                #                         print(f"  ✅ [行情状态] 国金QMT接口首次获取 {code} 成功，链路畅通！")
                #                         self._guojin_success_logged = True
                #     except Exception as e:
                #         self._guojin_err_count = getattr(self, '_guojin_err_count', 0) + 1
                #         if self._guojin_err_count > 3:
                #             print(f"  ⚠️ [行情告警] 国金QMT接口崩溃 ({e})。自动降级至【新浪API兜底】！")
                #             self.use_guojin = False
            
                # ======== 终极颗粒度兜底：新浪外网爬虫 ========
                # 无论什么引擎为主，只要有基金价格是 0（断流或懒加载拦截），新浪立刻补位！
                current_time = time.time()
                last_sina_time = getattr(self, '_last_sina_time', 0)
                
                # 优雅启动：系统启动前 15 秒绝对不触发新浪兜底，给 QMT 充足的建连和推流时间！
                if current_time - getattr(self, 'start_time', 0) > 15 and current_time - last_sina_time > 20:
                    # 如果新浪是主数据源（QMT和通达信均未启用），则必须持续轮询所有基金
                    if not self.use_qmt and not self.use_tdx:
                        missing_codes = self.lof_codes
                    else:
                        missing_codes = [c for c in self.lof_codes if self.get_price(c.split('.')[0] if '.' in c else c) == 0]
                    if missing_codes:
                        qs = [f"{'sh' if c.startswith('5') else 'sz'}{c.split('.')[0] if '.' in c else c}" for c in missing_codes]
                        for i in range(0, len(qs), 40):
                            try:
                                res = requests.get(f"http://hq.sinajs.cn/list={','.join(qs[i:i+40])}", headers=self.headers, timeout=10, proxies={"http": None, "https": None})
                                res.encoding = 'gbk'
                                for line in res.text.strip().split('\n'):
                                    match = re.search(r'hq_str_[a-z]{2}(\d{6})="([^"]+)"', line)
                                    if match:
                                        code = match.group(1)
                                        parts = match.group(2).split(',')
                                        if len(parts) > 7:
                                            ask_price = float(parts[7])
                                            last_price = float(parts[3])
                                            new_price = ask_price if ask_price > 0 else last_price
                                            if new_price > 0:
                                                self.lof_prices[code] = new_price
                                                socketio.emit('lof_price_update', {'code': code, 'price': new_price, 'timestamp': datetime.now().strftime('%H:%M:%S.%f')[:-3]})
                            except: pass
                    self._last_sina_time = current_time
                    
                # 引擎休眠控制（银河QMT和通达信不需要休眠，实时推送或本地读取）
                if self.use_qmt: time.sleep(1)
                elif self.use_tdx: time.sleep(10)
                else: time.sleep(20)

            except: pass

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

db_manager = DatabaseManager()
# 初始化大一统极速盘中估值引擎，驻留内存待命
dynamic_calculator = DynamicValuationCalculator(db_manager)
future_service = FuturePriceService()
sse_reader = SSEFuturesReader()
lof_price_reader = LOFPriceReader()

# 增加：在岸价独立高速缓存与轮询线程 (30秒一次)
cny_spot_cache = {'rate': None, 'time': None}
def _poll_spot_rate():
    while True:
        try:
            # 修复：直接调用 core_fetcher，解决之前找不到 fetch_cny_spot_rate 方法导致的假死
            res = core_fetcher.fetch_cny_spot_rate()
            if res and '人民币在岸价' in res:
                cny_spot_cache['rate'] = res['人民币在岸价']
                cny_spot_cache['time'] = res.get('时间', '')
        except: pass
        time.sleep(30)
threading.Thread(target=_poll_spot_rate, daemon=True).start()

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
        result = get_ib_night_prices()
        if "error" in result:
            return jsonify({'status': 'error', 'message': result.get('message', '获取失败'), 'prices': result.get('prices', {}), 'prev_closes': result.get('prev_closes', {})}), 200
        return jsonify({'status': 'success', 'prices': result.get('prices', {}), 'prev_closes': result.get('prev_closes', {}), 'timestamp': result.get('timestamp')}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'prices': {}}), 500

@app.route('/api/futu_prices')
def get_futu_prices():
    """
    富途API夜盘数据接口 (对接前端的轮询)
    """
    try:
        symbols = get_active_etf_symbols()
        success, msg, prices = futu_reader.get_prices(symbols)
        
        return jsonify({
            'status': 'success' if success else 'error',
            'message': msg,
            'prices': prices,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e), 'prices': {}}), 500

@app.route('/api/exchange_rate')
def get_exchange_rate():
    """供前端实时拉取最新的汇率及对应日期"""
    try:
        db_path = os.path.join(os.path.dirname(BASE_DIR), 'database', 'arb_master.db')
        conn = sqlite3.connect(db_path)
        df = pd.read_sql("SELECT date, usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
        conn.close()
        if not df.empty:
            rate = df.iloc[0]['usd_cny_mid']
            date_val = pd.to_datetime(df.iloc[0]['date'])
            if pd.notna(rate):
                return jsonify({
                    "rate": float(rate),
                    "date": date_val.strftime('%Y-%m-%d'),
                    "spot_rate": cny_spot_cache['rate'],
                    "spot_time": cny_spot_cache['time']
                })
    except Exception:
        pass
    return jsonify({"rate": None, "date": None})

@app.route('/api/lof')
def get_all_lof_data():
    return jsonify({code: {'price': lof_price_reader.get_price(code), 'time': datetime.now().strftime('%H:%M:%S')} for code in lof_price_reader.lof_codes})

@app.route('/api/lof_source')
def get_lof_source():
    return jsonify({'source': lof_price_reader.get_source_name()})

@app.route('/api/reconnect_lof', methods=['POST'])
def reconnect_lof():
    lof_price_reader.reconnect()
    return jsonify({'status': 'success', 'source': lof_price_reader.get_source_name()})

@app.route('/api/set_lof_source', methods=['POST'])
def set_lof_source():
    """设置LOF数据源（tongdaxin=通达信新版, qmt=银河QMT, sina=新浪API）"""
    data = request.get_json()
    source = data.get('source', 'sina') if data else 'sina'
    
    # 验证数据源有效性
    valid_sources = ['tongdaxin', 'qmt', 'sina']
    if source not in valid_sources:
        return jsonify({'success': False, 'error': f'无效的数据源: {source}'})
    
    lof_price_reader.preferred_source = source
    
    # 重新连接以应用新数据源
    lof_price_reader.reconnect()
    
    return jsonify({
        'success': True, 
        'source': source,
        'connected_source': lof_price_reader.get_source_name()
    })

@app.route('/api/order_book/<code>')
def get_order_book(code):
    """获取指定A股的五档深度盘口"""
    # 提取纯数字代码，兼容 '162411' 或 '162411.SZ'
    clean_code = code.split('.')[0] if '.' in code else code
    
    if lof_price_reader.use_qmt and lof_price_reader.qmt_client:
        book = lof_price_reader.qmt_client.get_order_book(clean_code)
        if book:
            return jsonify({'status': 'success', 'data': book})
            
    return jsonify({'status': 'error', 'message': '暂无盘口数据 (目前仅银河QMT Socket通道支持五档盘口)'})

@app.route('/admin/run/<task>', methods=['POST'])
def admin_run(task):
    if task == '011': _run_script_async("LOF011_daily_updater.py", "011")
    elif task == '012': _run_script_async("LOF012_calculate_static_valuation.py", "012")
    elif task == 'woody': _run_script_async("LOF011_daily_updater.py", "woody", force_woody=True)
    return jsonify({"status": "started", "task": task})

@app.route('/api/trade', methods=['POST'])
def api_trade():
    """接收前端的一键下单请求，并通过Socket转发给本地QMT或直接调用通达信"""
    init_trade_manager()
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

@app.route('/api/ib_cancel_all', methods=['POST'])
def api_ib_cancel_all():
    """一键撤销所有IB未成交订单"""
    try:
        if hasattr(ib_reader_instance, 'cancel_all_orders'):
            success, msg = ib_reader_instance.cancel_all_orders()
            if not success:
                return jsonify({"status": "error", "message": msg})
        else:
            return jsonify({"status": "error", "message": "精准撤单机制未就绪，请在 TWS 客户端手动操作"})
            
        return jsonify({"status": "success", "message": "指令已发送: 仅撤销沙盘产生的挂单"})
    except Exception as e:
        return jsonify({"status": "error", "message": f"撤单异常: {str(e)}"})

@app.route('/api/export_fund/<code>')
def export_fund_data(code):
    try:
        import sys
        if BASE_DIR not in sys.path:
            sys.path.append(BASE_DIR)
        import LOF005_output
        
        root_dir = os.path.dirname(BASE_DIR)
        success, msg, csv_content = LOF005_output.generate_fund_excel_csv(code, root_dir)
        
        if success:
            # utf-8-sig 的 BOM 编码完美解决直接双击 Excel 打开时中文乱码的问题
            return Response(
                csv_content.encode('utf-8-sig'),
                mimetype="text/csv",
                headers={"Content-disposition": f"attachment; filename=fund_{code}_export.csv"}
            )
        else:
            return jsonify({"status": "error", "message": msg}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
        
        ib_res = get_ib_night_prices()
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
    
    # 延时 10 秒在后台静默加载交易引擎，确保行情组件优先获得系统连接和资源
    def delayed_trade_init():
        time.sleep(10)
        init_trade_manager()
    threading.Thread(target=delayed_trade_init, daemon=True).start()
    try:
        # 使用socketio.run()替代app.run()以支持WebSocket
        try:
            # 兼容新版 Flask 强制要求确认安全参数，否则 threading 模式在开发服务器下会报错
            socketio.run(app, debug=False, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
        except TypeError:
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
        elif "10013" in str(e):
            print("\n" + "❌"*20)
            print("【致命错误】Web服务器启动失败：[WinError 10013] 访问权限被拒绝！")
            print("这说明你的 5000 端口被 Windows 系统服务强行锁死，或被管理员权限进程霸占。")
            print("👉 解决办法：")
            print("   1. 彻底重启一次电脑即可释放端口锁定。")
            print("   2. 或打开任务管理器强制结束所有 python.exe 进程。")
            print("❌"*20 + "\n")
        else:
            print(f"启动服务器失败: {e}")
    except KeyboardInterrupt:
        print("\n⏹️ [系统] 接收到 Ctrl+C 手动停止信号，正在强制销毁所有后台线程并退出...")
        ib_reader_instance.stop_polling()
        os._exit(0)
#