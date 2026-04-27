# encoding: gbk
# =================================================================
# v4.1 沙盘推演版 - 银河QMT Socket Server端策略
# 【重要】此文件是运行在银河QMT客户端内部的策略代码
# 不是Python主程序调用的，请在QMT策略编辑器中加载此代码
# =================================================================
# 功能：
# - 监听 127.0.0.1:8888 端口
# - 支持 PING 心跳检测
# - 支持 SUBSCRIBE 订阅股票代码
# - 实时推送 TICK 行情数据
# - 使用互斥锁保护 QMT 底层 API，防止死锁
# =================================================================

import socket
import threading
import time

g_context = None
g_api_lock = threading.Lock()  # 保护 银河QMT 底层 API 的并发锁

g_account_id = ""
g_active_clients = []
g_clients_lock = threading.Lock()
g_subscribed_stocks = set()


def client_handler(conn, addr):
    print(f"? 新客户端接入: {addr}")
    with g_clients_lock:
        g_active_clients.append(conn)

    buffer = ""
    try:
        while True:
            data = conn.recv(1024).decode('utf-8')
            if not data: break

            buffer += data
            while '\n' in buffer:
                cmd_str, buffer = buffer.split('\n', 1)
                if cmd_str:
                    process_command_sync(conn, cmd_str.strip())
    except Exception:
        pass
    finally:
        print(f"?? 客户端断开: {addr}")
        with g_clients_lock:
            if conn in g_active_clients:
                g_active_clients.remove(conn)
        conn.close()


def process_command_sync(conn, cmd_str):
    """同步处理指令：直接在当前线程响应，告别排队和休眠超时"""
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
            with g_api_lock:  # 加锁保护 C++ 引擎
                try:
                    ticks = g_context.get_full_tick([code])
                    if code in ticks:
                        tick = ticks[code]
                        response = f"TICK_RESULT,{code} | 最新/收盘价:{tick.get('lastPrice', 0)} | 昨收:{tick.get('lastClose', 0)}"
                except Exception as e:
                    response = f"TICK_RESULT,{code} | 查询异常: {e}"
        try: conn.sendall((response + '\n').encode('utf-8'))
        except: pass

    elif action in ['BUY', 'SELL'] and len(parts) >= 4:
        code, volume, price = parts[1], int(parts[2]), float(parts[3])
        opType = 23 if action == 'BUY' else 24
        if g_context:
            with g_api_lock:  # 加锁保护 C++ 引擎
                try:
                    msg = f"Socket_{action}_{code}"
                    passorder(opType, 1101, g_account_id, code, 11, price, volume, 'SocketTrade', 1, msg, g_context)
                    print(f"Order Sent: {action} {code} {volume} @ {price}")
                except Exception as e:
                    print(f"Passorder Error: {e}")
        try: conn.sendall(b'OK\n')
        except: pass

    elif action == 'SUBSCRIBE' and len(parts) > 1:
        new_stocks = [p.strip() for p in parts[1:] if p.strip()]
        g_subscribed_stocks.update(new_stocks)
        print(f"? 订阅成功，已加入轮询列表: {new_stocks}")
        try: conn.sendall(b'SUBSCRIBE_OK\n')
        except: pass


def socket_server_thread():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 8888))
        server.listen(5)
        print("? 银河QMT Socket Server Started. Listening on 8888...")
    except Exception as e:
        print(f"? 无法绑定端口 8888: {e}")
        return

    while True:
        try:
            conn, addr = server.accept()
            t = threading.Thread(target=client_handler, args=(conn, addr))
            t.setDaemon(True)
            t.start()
        except Exception:
            time.sleep(1)


def broadcast_message(msg):
    with g_clients_lock:
        dead_clients = []
        for client_conn in g_active_clients:
            try: client_conn.sendall(msg.encode('utf-8'))
            except Exception: dead_clients.append(client_conn)
        for dead in dead_clients:
            g_active_clients.remove(dead)


def init(ContextInfo):
    global g_account_id, g_context
    print("\n[策略日志] 加载 v4.1 沙盘推演版 Socket 策略 (五档盘口与并发锁)...")
    g_account_id = '230500059288'
    g_context = ContextInfo
    ContextInfo.set_account(g_account_id)

    t = threading.Thread(target=socket_server_thread)
    t.setDaemon(True)
    t.start()

    ContextInfo.run_time("check_tasks", "1nSecond", "2020-01-01 09:30:00")
    print("银河QMT Engine Initialized (v4.1 Sandbox Mode).")


def push_ticks():
    global g_context, g_subscribed_stocks
    if not g_context or not g_subscribed_stocks or len(g_active_clients) == 0:
        return
    with g_api_lock:
        try:
            ticks = g_context.get_full_tick(list(g_subscribed_stocks))
            for code, tick in ticks.items():
                ap = tick.get('askPrice', [0, 0, 0, 0, 0])
                av = tick.get('askVol', [0, 0, 0, 0, 0])
                bp = tick.get('bidPrice', [0, 0, 0, 0, 0])
                bv = tick.get('bidVol', [0, 0, 0, 0, 0])
                
                # 防御性截取，防止数组长度不够
                ap = ap + [0]*5 if len(ap) < 5 else ap
                av = av + [0]*5 if len(av) < 5 else av
                bp = bp + [0]*5 if len(bp) < 5 else bp
                bv = bv + [0]*5 if len(bv) < 5 else bv
                
                # 格式: TICK, code, lastPrice, volume, ask_p1, ask_v1, ask_p2, ask_v2, bid_p1, bid_v1, bid_p2, bid_v2, timetag
                msg = f"TICK,{code},{tick.get('lastPrice', 0)},{tick.get('volume', 0)},{ap[0]},{av[0]},{ap[1]},{av[1]},{bp[0]},{bv[0]},{bp[1]},{bv[1]},{tick.get('timetag', '')}\n"
                broadcast_message(msg)
        except Exception:
            pass


def check_tasks(ContextInfo):
    push_ticks()


def handlebar(ContextInfo):
    push_ticks()


def orderError_callback(ContextInfo, passOrderInfo, msg):
    error_msg = f"[API Error] Code: {passOrderInfo.orderCode}, Reason: {msg}"
    print(error_msg)
    broadcast_message(f"ORDER_ERROR,{passOrderInfo.orderCode},{msg}\n")


def deal_callback(ContextInfo, dealInfo):
    deal_msg = f"[Deal] Code: {dealInfo.m_strInstrumentID}, Price: {dealInfo.m_dPrice}"
    print(deal_msg)
    broadcast_message(f"DEAL,{dealInfo.m_strInstrumentID},{dealInfo.m_dPrice},{dealInfo.m_nVolume}\n")


def order_callback(ContextInfo, orderInfo): pass
