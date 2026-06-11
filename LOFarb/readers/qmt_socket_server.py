# encoding: gbk
# =================================================================
# v4.3 沙盘推演版 - 银河QMT Socket Server端策略 2026-06-05
# 优化：1. 修复 __file__ 变量在 QMT 环境下不存在导致崩溃的 Bug。
#      2. 吸收 BigQMT 理念，引入基于 builtins 的世代机制，自动清理旧残留线程，解决 8888 端口被占用问题。
# =================================================================
import socket
import threading
import time
import builtins

# 尝试导入本地敏感配置
try:
    import sys, os
    # 获取 QMT 安装目录或其他路径
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(''))))
    # 如果上面的方式在纯内存执行下失效，使用更宽松的加载机制
    try:
        from account_private import YH_ACCOUNT as QMT_ACCOUNT
    except ImportError:
        # 如果当前路径找不到，尝试硬编码绝对路径(请根据您的实际工程路径修改)
        sys.path.insert(0, r"D:\Study\arbTest\LOFarb")
        from account_private import YH_ACCOUNT as QMT_ACCOUNT
except ImportError:
    print("[警告] 无法导入 account_private.py，请检查路径。")
    QMT_ACCOUNT = "您的银河QMT账号"

g_context = None
g_api_lock = threading.Lock()
g_account_id = "" 
g_active_clients = []
g_clients_lock = threading.Lock()
g_subscribed_stocks = set()

# ==================== 防僵尸线程机制 ====================
if not hasattr(builtins, '_qmt_socket_gen'):
    builtins._qmt_socket_gen = 0

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

def socket_server_thread(my_gen):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 8888))
        server.listen(5)
        server.settimeout(1.0) # 设置超时，让 while 循环能定期往下走，检查世代
        print(f"✅ 银河QMT Socket Server Started. Listening on 8888... (世代: {my_gen})")
    except Exception as e:
        print(f"❌ 致命错误：端口 8888 被占用！详细报错: {e}")
        return
        
    while True:
        current_gen = getattr(builtins, '_qmt_socket_gen', 0)
        if current_gen != my_gen:
            print(f"🔄 检测到策略重载，主动退出旧版 Socket 线程 (旧世代: {my_gen}, 新世代: {current_gen})")
            break
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=client_handler, args=(conn, addr))
            t.setDaemon(True)
            t.start()
        except socket.timeout:
            continue
        except Exception: 
            time.sleep(1)
            
    server.close()

def broadcast_message(msg):
    with g_clients_lock:
        dead_clients = []
        for client_conn in g_active_clients:
            try: client_conn.sendall(msg.encode('utf-8'))
            except Exception: dead_clients.append(client_conn)
        for dead in dead_clients: g_active_clients.remove(dead)

def init(ContextInfo):
    global g_account_id, g_context
    print("\n[策略日志] 加载 v4.3 沙盘推演版 Socket 策略 (防残影线程版)...")
    
    # 优先尝试从 QMT 界面上的"资金账号"列读取，若无则使用硬编码
    try:
        g_account_id = account
    except NameError:
        g_account_id = QMT_ACCOUNT
        
    g_context = ContextInfo
    ContextInfo.set_account(g_account_id)
    
    builtins._qmt_socket_gen += 1
    my_gen = builtins._qmt_socket_gen
    
    t = threading.Thread(target=socket_server_thread, args=(my_gen,))
    t.setDaemon(True)
    t.start()
    
    ContextInfo.run_time("check_tasks", "200ms", "2020-01-01 09:30:00")

def push_ticks():
    global g_context, g_subscribed_stocks
    if not g_context or not g_subscribed_stocks or len(g_active_clients) == 0: return
    with g_api_lock:
        try:
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

                last_close = tick.get('lastClose', 0)
                amount = tick.get('amount', 0)

                # 扩充为 5 档盘口发送
                msg = f"TICK,{code},{tick.get('lastPrice', 0)},{tick.get('volume', 0)}," \
                      f"{ap[0]},{av[0]},{ap[1]},{av[1]},{ap[2]},{av[2]},{ap[3]},{av[3]},{ap[4]},{av[4]}," \
                      f"{bp[0]},{bv[0]},{bp[1]},{bv[1]},{bp[2]},{bv[2]},{bp[3]},{bv[3]},{bp[4]},{bv[4]}," \
                      f"{tick.get('timetag', '')},{last_close},{amount}\n"
                broadcast_message(msg)

        except Exception as e:
            broadcast_message(f"ERROR, push_ticks 发生致命错误: {e}\n")
            print(f"❌ [推流异常] push_ticks 发生错误: {e}")

def check_tasks(ContextInfo): push_ticks()
def handlebar(ContextInfo): push_ticks()
def orderError_callback(ContextInfo, passOrderInfo, msg): pass
def deal_callback(ContextInfo, dealInfo): pass
def order_callback(ContextInfo, orderInfo): pass

