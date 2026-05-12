# encoding: gbk
# =================================================================
# v4.2 沙盘推演版 - 银河QMT Socket Server端策略 2026-4-27
# =================================================================
import socket
import threading
import time

# 尝试导入本地敏感配置
try:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from account_private import YH_ACCOUNT as QMT_ACCOUNT
except ImportError:
    print("[警告] account_private.py 不存在，使用默认账号")
    QMT_ACCOUNT = "您的银河QMT账号"

g_context = None
g_api_lock = threading.Lock()
g_account_id = "" 
g_active_clients = []
g_clients_lock = threading.Lock()
g_subscribed_stocks = set()

def client_handler(conn, addr):
    with g_clients_lock: g_active_clients.append(conn)
    buffer = ""
    try:
        while True:
            data = conn.recv(1024).decode('utf-8')
            if not data: break
            buffer += data
            while '\n' in buffer:
                cmd_str, buffer = buffer.split('\n', 1)
                if cmd_str: process_command_sync(conn, cmd_str.strip())
    except Exception: pass
    finally:
        with g_clients_lock:
            if conn in g_active_clients: g_active_clients.remove(conn)
        conn.close()

def process_command_sync(conn, cmd_str):
    global g_context, g_account_id, g_subscribed_stocks
    parts = cmd_str.split(',')
    action = parts[0].upper()

    if action == 'PING':
        try: conn.sendall(b'PONG\n')
        except: pass
    elif action == 'QUERY_TICK' and len(parts) >= 2:
        code = parts[1].strip()
        response = f"TICK_RESULT,{code} | 暂无数据"
        if g_context:
            with g_api_lock:
                try:
                    ticks = g_context.get_full_tick([code])
                    if code in ticks:
                        tick = ticks[code]
                        response = f"TICK_RESULT,{code} | 最新/收盘价:{tick.get('lastPrice', 0)} | 昨收:{tick.get('lastClose', 0)}"
                except Exception as e: response = f"TICK_RESULT,{code} | 查询异常: {e}"
        try: conn.sendall((response + '\n').encode('utf-8'))
        except: pass
    elif action in ['BUY', 'SELL'] and len(parts) >= 4:
        code, volume, price = parts[1], int(parts[2]), float(parts[3])
        opType = 23 if action == 'BUY' else 24
        if g_context:
            with g_api_lock:
                try:
                    msg = f"Socket_{action}_{code}"
                    passorder(opType, 1101, g_account_id, code, 11, price, volume, 'SocketTrade', 1, msg, g_context)
                except Exception as e: print(f"Passorder Error: {e}")
        try: conn.sendall(b'OK\n')
        except: pass
    elif action == 'SUBSCRIBE' and len(parts) > 1:
        new_stocks = [p.strip() for p in parts[1:] if p.strip()]
        g_subscribed_stocks.update(new_stocks)
        
        try: conn.sendall(b'SUBSCRIBE_OK\n')
        except: pass
        try: conn.sendall(f"DEBUG, 开始为您提取 {new_stocks} 的盘口数据...\n".encode('utf-8'))
        except: pass
        push_ticks()  # 核心：破除周末休眠

def socket_server_thread():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 8888))
        server.listen(5)
        print("? 银河QMT Socket Server Started. Listening on 8888...")
    except Exception as e:
        print(f"❌ 致命错误：端口 8888 被占用！请彻底重启QMT软件！详细报错: {e}")
        return
        
    while True:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=client_handler, args=(conn, addr))
            t.setDaemon(True)
            t.start()
        except Exception: time.sleep(1)

def broadcast_message(msg):
    with g_clients_lock:
        dead_clients = []
        for client_conn in g_active_clients:
            try: client_conn.sendall(msg.encode('utf-8'))
            except Exception: dead_clients.append(client_conn)
        for dead in dead_clients: g_active_clients.remove(dead)

def init(ContextInfo):
    global g_account_id, g_context
    print("\n[策略日志] 加载 v4.2 沙盘推演版 Socket 策略 (防崩溃版)...")
    g_account_id = QMT_ACCOUNT
    g_context = ContextInfo
    ContextInfo.set_account(g_account_id)
    
    t = threading.Thread(target=socket_server_thread)
    t.setDaemon(True)
    t.start()
    
    ContextInfo.run_time("check_tasks", "1nSecond", "2020-01-01 09:30:00")

def push_ticks():
    global g_context, g_subscribed_stocks
    if not g_context or not g_subscribed_stocks or len(g_active_clients) == 0: return
    with g_api_lock:
        try:
            # 听从架构师的指引：回归极致性能！直接传入全量列表让C++引擎一次性并发处理！
            ticks = g_context.get_full_tick(list(g_subscribed_stocks))    
            
            for code, tick in ticks.items():
                if not tick or not isinstance(tick, dict): continue
                
                # 终极防御：处理 QMT 返回 Tuple 或 None 导致的拼接崩溃问题
                def safe_list(val):
                    if isinstance(val, (list, tuple)): return list(val) + [0]*5
                    return [0]*5
                    
                ap = safe_list(tick.get('askPrice'))
                av = safe_list(tick.get('askVol'))
                bp = safe_list(tick.get('bidPrice'))
                bv = safe_list(tick.get('bidVol'))
                
                msg = f"TICK,{code},{tick.get('lastPrice', 0)},{tick.get('volume', 0)},{ap[0]},{av[0]},{ap[1]},{av[1]},{bp[0]},{bv[0]},{bp[1]},{bv[1]},{tick.get('timetag', '')}\n"
                broadcast_message(msg)
        except Exception as e:
            broadcast_message(f"ERROR, push_ticks 发生致命错误: {e}\n")
            print(f"❌ [推流异常] push_ticks 发生错误: {e}")

def check_tasks(ContextInfo): push_ticks()
def handlebar(ContextInfo): push_ticks()
def orderError_callback(ContextInfo, passOrderInfo, msg): pass
def deal_callback(ContextInfo, dealInfo): pass
def order_callback(ContextInfo, orderInfo): pass
