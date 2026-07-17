# encoding: gbk
# =================================================================
# Test_Yinhe_qmt_ServerV5.py (QMT策略) v5.2.0
# 日期: 2026-07-17
# 变更日志:
#   v5.2.0 (2026-07-17) - DEAL成交广播 + ORDER状态广播 + QUERY_POSITION命令 + position cache
#   v5.1.3 (2026-06-16) - position/account回调静默, 日志只显示下单/成交/错误
#   v5.1.2 (2026-06-16) - position_callback: 60s时间去重(解决同代码多行仓位互相覆盖刷屏)
#   v5.0   (2026-06-15) - rewrite from v4.3, main-thread queue mode, QMT thread compliant
# IMPORTANT: This file runs INSIDE the QMT client strategy editor, not standalone.
# =================================================================
# Architecture:
#   Socket thread -> pending_actions queue -> tick_push timer(200ms)
#   Main thread drain -> passorder (safe, no message bus blocking)
#   quote_push timer(1s) -> main thread get_full_tick -> broadcast TICK
#
# External protocol (v5.2 — [AI-2026-07-17] added QUERY_POSITION + DEAL/ORDER broadcast):
#   BUY,code,volume,price          -> OK\n                        (下单)
#   SELL,code,volume,price         -> OK\n                        (卖券)
#   QUERY_TICK,code                -> TICK_RESULT,code,lastPrice,preClose\n
#   QUERY_POSITION,code            -> POSITION_RESULT,code,vol,price\n
#   SUBSCRIBE,code1,code2,...      -> SUBSCRIBE_OK\n
#   PING                           -> PONG\n
# Server broadcast (all connected clients receive):
#   DEAL,code,vol,price\n           (deal_callback 成交广播)
#   ORDER,code,sysid,status\n       (order_callback 状态广播)
#   TICK,code,...\n                 (quote_push 行情广播)
#
# Ref: Jiang_big_qmt_trader_server.py v3.6.0
# - builtins for cross-namespace shared state
# - socket_thread_gen to kill zombie threads
# - pending_actions queue ensures C++ API called only by main thread
# =================================================================

import builtins
import socket
import threading
import time

# ==================== 版本 ====================
SERVER_VERSION = '5.2.0 (2026-07-17)'

# ==================== 共享状态（builtins）====================
# QMT对每个回调赋予独立命名空间，模块级全局变量在各空间中不同
# 只有 builtins 是真正跨命名空间共享的
_V5_KEY = '_qmt_v5_state'

def _S():
    """get shared state dict, init on first access"""
    s = getattr(builtins, _V5_KEY, None)
    if s is None:
        s = {}
        setattr(builtins, _V5_KEY, s)
    defaults = {
        'context': None,
        'account_id': None,
        'account_type': None,
        'active_clients': [],
        'clients_lock': threading.Lock(),
        'api_lock': threading.Lock(),
        'pending_actions': [],
        'pending_lock': threading.Lock(),
        'subscribed_stocks': set(),
        'latest_ticks': {},           # QUERY_TICK reads from here, no C++ call
        'ticks_lock': threading.Lock(),
        'latest_positions': {},       # [AI-2026-07-17] position_callback 缓存，供 QUERY_POSITION 读取
        'positions_lock': threading.Lock(),
        'socket_gen': [0],            # bumped by init(); old threads check gen mismatch and exit
        'push_count': [0],
    }
    for k, v in defaults.items():
        if k not in s:
            s[k] = v
    return s

_S()  # ensure state dict exists at module load

# ==================== QUEUE MECHANISM ====================
def _enqueue(action):
    """safe enqueue, callable from any thread (pure Python, no C++ API)"""
    s = _S()
    with s['pending_lock']:
        s['pending_actions'].append(action)

def _drain(ContextInfo):
    """main thread timer callback: dequeue and call C++ API"""
    s = _S()
    with s['pending_lock']:
        if not s['pending_actions']:
            return
        actions = s['pending_actions'][:]
        s['pending_actions'][:] = []

    for act in actions:
        kind = act.get('kind')
        try:
            if kind == 'place':
                _do_place(ContextInfo, act)
            elif kind == 'cancel':
                _do_cancel(ContextInfo, act)
        except Exception as e:
            print(f"[QMTv5][drain] EXC: {e}")

def _do_place(ContextInfo, act):
    """main thread executes passorder"""
    s = _S()
    acc_id = s['account_id']
    if not acc_id:
        print("[QMTv5][place] account not ready, skip")
        return
    side = act['side']  # 'BUY' or 'SELL'
    op_type = 23 if side == 'BUY' else 24
    try:
        passorder(op_type, 1101, acc_id, act['code'], 11,
                  act['price'], act['volume'],
                  'QMTv5', 1, '', ContextInfo)
        print(f"[QMTv5][place] OK: {side} {act['code']} {act['volume']}@{act['price']}")
    except Exception as e:
        print(f"[QMTv5][place] FAIL: {e}")

def _do_cancel(ContextInfo, act):
    """main thread executes cancel order"""
    s = _S()
    acc_id = s['account_id']
    if not acc_id:
        return
    try:
        ok = cancel(act['sysid'], acc_id, s['account_type'], ContextInfo)
        print(f"[QMTv5][cancel] sysid={act['sysid']} ok={ok}")
    except Exception as e:
        print(f"[QMTv5][cancel] FAIL: {e}")

# ==================== SOCKET LAYER ====================
def _safe_send(conn, data):
    try:
        conn.sendall(data)
    except Exception:
        pass

def _broadcast(msg):
    """broadcast message to all active clients"""
    encoded = msg.encode('utf-8')
    s = _S()
    with s['clients_lock']:
        dead = []
        for c in s['active_clients']:
            try:
                c.sendall(encoded)
            except Exception:
                dead.append(c)
        for c in dead:
            s['active_clients'].remove(c)

def client_handler(conn, addr):
    """Socket child thread: network IO only, no C++ API calls"""
    s = _S()
    with s['clients_lock']:
        s['active_clients'].append(conn)

    buffer = ''
    try:
        while True:
            data = conn.recv(1024).decode('utf-8')
            if not data:
                break
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                line = line.strip()
                if not line:
                    continue

                parts = line.split(',')
                action = parts[0].upper()

                if action == 'PING':
                    _safe_send(conn, b'PONG\n')

                elif action in ('BUY', 'SELL') and len(parts) >= 4:
                    # BUY,code,volume,price -> enqueue, main thread executes passorder
                    _enqueue({
                        'kind': 'place',
                        'side': action,
                        'code': parts[1].strip(),
                        'volume': int(parts[2]),
                        'price': float(parts[3]),
                    })
                    _safe_send(conn, b'OK\n')

                elif action == 'QUERY_TICK' and len(parts) >= 2:
                    # read from cache, no C++ call
                    code = parts[1].strip()
                    with s['ticks_lock']:
                        tick = s['latest_ticks'].get(code, {})
                    last_price = tick.get('lastPrice', 0)
                    pre_close = tick.get('lastClose', 0)
                    resp = f"TICK_RESULT,{code},{last_price},{pre_close}\n"
                    _safe_send(conn, resp.encode('utf-8'))

                elif action == 'QUERY_POSITION' and len(parts) >= 2:
                    # [AI-2026-07-17] 从 position_callback 缓存读取，不调用 C++ API
                    code = parts[1].strip()
                    with s['positions_lock']:
                        pos = s['latest_positions'].get(code, {})
                    vol = pos.get('volume', 0)
                    price = pos.get('price', 0.0)
                    resp = f"POSITION_RESULT,{code},{vol},{price}\n"
                    _safe_send(conn, resp.encode('utf-8'))

                elif action == 'SHUTDOWN':
                    print(f"[QMTv5] SHUTDOWN received, signaling old server to exit")
                    _broadcast("SHUTDOWN\n")
                    # bump socket_gen to make old threads exit
                    s['socket_gen'][0] += 1

                elif action == 'SUBSCRIBE' and len(parts) > 1:
                    new_codes = [p.strip() for p in parts[1:] if p.strip()]
                    s['subscribed_stocks'].update(new_codes)
                    print(f"[QMTv5] SUBSCRIBE: {new_codes}")
                    _safe_send(conn, b'SUBSCRIBE_OK\n')

                else:
                    _safe_send(conn, b'UNKNOWN\n')

    except Exception:
        pass
    finally:
        with s['clients_lock']:
            if conn in s['active_clients']:
                s['active_clients'].remove(conn)
        try:
            conn.close()
        except Exception:
            pass

def socket_server_thread():
    """Socket server thread: supports generation self-exit + zombie port preemption"""
    s = _S()
    my_gen = s['socket_gen'][0]

    # ---- zombie port preemption: send SHUTDOWN to old v5.0 thread ----
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.settimeout(0.5)
        probe.connect(('127.0.0.1', 8888))
        probe.sendall(b'SHUTDOWN\n')
        probe.close()
        time.sleep(0.5)
        print(f"[QMTv5] sent SHUTDOWN to old server on 8888")
    except Exception:
        pass  # no old server running, normal startup

    # ---- bind port (SO_REUSEADDR allows coexistence with zombie, but we are the last binder) ----
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 8888))
        server.listen(5)
        server.settimeout(1.0)
        print(f"[QMTv5] Server listening on 8888 (gen={my_gen})")
    except Exception as e:
        print(f"[QMTv5] bind 8888 failed: {e}")
        return

    try:
        while True:
            current_gen = s['socket_gen'][0]
            if current_gen != my_gen:
                print(f"[QMTv5] old server thread exits (gen {my_gen} != {current_gen})")
                break
            try:
                conn, addr = server.accept()
            except socket.timeout:
                continue
            except Exception:
                time.sleep(1)
                continue
            t = threading.Thread(target=client_handler, args=(conn, addr))
            t.daemon = True
            t.start()
    finally:
        try:
            server.close()
        except Exception:
            pass

# ==================== QMT CALLBACKS ====================
def init(ContextInfo):
    print("=" * 50)
    print(f"[QMTv5] v{SERVER_VERSION} 主线程队列模式启动")
    print("=" * 50)

    s = _S()
    s['context'] = ContextInfo

    # read account from QMT global variables
    try:
        s['account_id'] = account
        s['account_type'] = accountType
        print(f"[QMTv5] account: id={account!r} type={accountType!r}")
    except NameError:
        print("[QMTv5][WARN] account globals not found, place/cancel will fail")
        s['account_id'] = None
        s['account_type'] = None

    if s['account_id']:
        try:
            ContextInfo.set_account(s['account_id'])
        except Exception as e:
            print(f"[QMTv5][WARN] set_account failed: {e}")

    # bump generation, old socket thread will auto-exit
    s['socket_gen'][0] += 1
    t = threading.Thread(target=socket_server_thread)
    t.daemon = True
    t.start()

    # 200ms timer: consume order queue (main thread executes passorder)
    ContextInfo.run_time("tick_push", "200nMilliSecond", "2020-01-01 09:30:00")
    # 1s timer: push TICK quotes (main thread executes get_full_tick)
    ContextInfo.run_time("quote_push", "1nSecond", "2020-01-01 09:30:00")

    print(f"[QMTv5] v{SERVER_VERSION} initialized, account={s['account_id']}")

def tick_push(ContextInfo):
    """200ms timer: consume pending_actions queue"""
    _drain(ContextInfo)
    s = _S()
    s['push_count'][0] += 1

def quote_push(ContextInfo):
    """1s timer: push TICK quotes"""
    s = _S()
    if not s['subscribed_stocks'] or not s['account_id']:
        return
    codes = list(s['subscribed_stocks'])
    if not codes:
        return
    with s['api_lock']:  # protect C++ calls from multi-timer competition
        try:
            ticks = ContextInfo.get_full_tick(codes)
        except Exception:
            return
    if not ticks:
        return

    # update cache (for QUERY_TICK)
    with s['ticks_lock']:
        s['latest_ticks'].update(ticks)

    # broadcast TICK to all clients
    for code, tick in ticks.items():
        ask_prices = tick.get('askPrice', [0]*5)
        ask_vols   = tick.get('askVol',   [0]*5)
        bid_prices = tick.get('bidPrice', [0]*5)
        bid_vols   = tick.get('bidVol',   [0]*5)
        pre_close  = tick.get('lastClose', 0)
        amount     = tick.get('amount', 0)
        msg = (f"TICK,{code},{tick.get('lastPrice', 0)},{tick.get('volume', 0)},"
               f"{ask_prices[0]},{ask_vols[0]},{ask_prices[1]},{ask_vols[1]},"
               f"{ask_prices[2]},{ask_vols[2]},{ask_prices[3]},{ask_vols[3]},"
               f"{ask_prices[4]},{ask_vols[4]},"
               f"{bid_prices[0]},{bid_vols[0]},{bid_prices[1]},{bid_vols[1]},"
               f"{bid_prices[2]},{bid_vols[2]},{bid_prices[3]},{bid_vols[3]},"
               f"{bid_prices[4]},{bid_vols[4]},"
               f"{pre_close},{amount}\n")
        _broadcast(msg)

def handlebar(ContextInfo):
    """QMT framework requires this, only used for GIL yield"""
    time.sleep(0.001)

def order_callback(ContextInfo, orderInfo):
    """order status update — broadcasts ORDER to socket clients"""
    try:
        status = getattr(orderInfo, 'm_nOrderStatus', None)
        sysid = getattr(orderInfo, 'm_strOrderSysID', '') or ''
        code = getattr(orderInfo, 'm_strInstrumentID', '') or ''
        print(f"[QMTv5][order] code={code} sysid={sysid} status={status}")
        # [AI-2026-07-17] 广播订单状态到所有 socket 客户端
        _broadcast(f"ORDER,{code},{sysid},{status}\n")
    except Exception:
        pass

def deal_callback(ContextInfo, dealInfo):
    """deal/trade callback — broadcasts DEAL to socket clients"""
    try:
        code = getattr(dealInfo, 'm_strInstrumentID', '')
        price = getattr(dealInfo, 'm_dPrice', 0.0)
        vol = getattr(dealInfo, 'm_nVolume', 0)
        print(f"[QMTv5][deal] {code} {vol}@{price}")
        # [AI-2026-07-17] 广播成交到所有 socket 客户端，SmartOpenMonitor 据此实时检测
        _broadcast(f"DEAL,{code},{vol},{price}\n")
    except Exception:
        pass

def orderError_callback(ContextInfo, passOrderInfo, msg):
    """order error callback"""
    try:
        code = getattr(passOrderInfo, 'm_strInstrumentID', '') or ''
        print(f"[QMTv5][error] code={code} msg={msg}")
    except Exception:
        pass

def position_callback(ContextInfo, positionInfo):
    """position update — caches to 'latest_positions' for QUERY_POSITION; console silent"""
    # [AI-2026-07-17] 重写：不再静默无视，改为更新缓存供 QUERY_POSITION 读取。
    # 不打印日志保持控制台清爽。
    try:
        code = getattr(positionInfo, 'm_strInstrumentID', '') or ''
        vol = getattr(positionInfo, 'm_nVolume', 0) or 0
        price = getattr(positionInfo, 'm_dOpenPrice', 0.0) or 0.0
        if not code:
            return
        s = _S()
        with s['positions_lock']:
            if vol > 0:
                s['latest_positions'][code] = {'volume': vol, 'price': price}
            else:
                s['latest_positions'].pop(code, None)
    except Exception:
        pass

_last_cash_key = '_qmt_v5_last_cash'

def account_callback(ContextInfo, accountInfo):
    """cash update (silent by default)"""
    # User requested silence for cash logs. Uncomment to re-enable.
    pass
