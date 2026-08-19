# -*- coding: utf-8 -*-
# ib_reader.py - IB 盈透实时行情与交易基座模块

import threading
import time
import re
from datetime import datetime, timedelta
import yaml
import random
import os
import sys
import builtins
import logging

# 屏蔽 IBAPI 底层的 INFO 级别刷屏日志
logging.getLogger('ibapi.client').setLevel(logging.WARNING)
logging.getLogger('ibapi.wrapper').setLevel(logging.WARNING)
logging.getLogger('ibapi.utils').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Windows GBK encoding safe print helper
def print(*args, **kwargs):
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'gbk'
            safe_args = [str(arg).encode(encoding, errors='replace').decode(encoding) for arg in args]
            builtins.print(*safe_args, **kwargs)
        except:
            pass

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
    from ibapi.execution import ExecutionFilter, Execution
except ImportError:
    class EClient:
        def __init__(self, *args, **kwargs): pass
        def connect(self, *args, **kwargs): pass
        def disconnect(self, *args, **kwargs): pass
        def isConnected(self, *args, **kwargs): return False
    class EWrapper:
        def __init__(self, *args, **kwargs): pass
    class Contract: pass
    class Order: pass
    print("Warning: ibapi not installed. IBReader will not function.")

# [AI-2026-08-04] 协议层容错钩子：IB Gateway 重启瞬间可能发来含非 UTF-8 字节(如中文账户名/路径)的脏包，
# ibapi 内部 EReader 线程(_readerthread) 用 utf-8 解码失败抛 UnicodeDecodeError，该异常未捕获会导致
# 后端进程崩溃(后台 task 判定 failed)。此处注册全局线程异常钩子，仅拦截该已知协议杂音，触发 IBReader
# 自愈重连(断开并置 connected=False，由 _polling_loop 重连)，且不向 stderr 抛 traceback，避免进程被判失败。
# 严守 AGENTS.md TOP1 红线：绝不动 exchange="OVERNIGHT"、绝不加快史快照备用源。
_IB_READER_INSTANCE = None
_ORIG_THREAD_EXCEPTHOOK = None

def _ib_thread_excepthook(args):
    exc_type, exc_value, exc_tb, thread = (
        args.exc_type, args.exc_value, args.exc_traceback, args.thread
    )
    # 仅捕获 ibapi EReader 线程的协议层解码异常（已知的 Gateway 重启杂音）
    if exc_type is UnicodeDecodeError and thread is not None and '_readerthread' in thread.name:
        logger.warning(
            f"[IB] EReader线程解码异常(协议层杂音,非致命),触发自愈重连: {exc_value}"
        )
        inst = globals().get('_IB_READER_INSTANCE')
        if inst is not None:
            try:
                inst.disconnect_from_ib()
            except Exception:
                pass
            inst.connected = False  # 让 _polling_loop 的未连接分支发起重连
        return
    # 其他线程异常按原样上报，不掩盖未知问题
    if _ORIG_THREAD_EXCEPTHOOK:
        _ORIG_THREAD_EXCEPTHOOK(args)

class IBReader(EWrapper, EClient):
    def __init__(self, client_id=None, on_price_update=None, db_manager=None):
        EClient.__init__(self, self)
        self.client_id = client_id if client_id is not None else random.randint(1000, 9999)
        self.on_price_update = on_price_update  # 注入回调函数解耦 SocketIO
        self.db_manager = db_manager # 注入数据库管理器
        # [端口优先级] 东哥只用 IB Gateway 实盘：4001=IB Gateway 实盘(唯一使用) > 4002=IB Gateway 模拟
        #   > 7496=TWS 实盘 > 7497=TWS 模拟。⚠️ 7497 是 TWS 模拟端口、非 IB Gateway 实盘；
        #   IB Gateway 实盘标准端口即 4001（历史日志亦证实 4001 连上实盘并订阅 12 只标的）。
        self.target_ports = [4001, 4002, 7496, 7497] 
        self.current_port_index = 0
        self.connected = False
        self.retry_delay = 1.0 
        self.max_retry_delay = 60.0 
        self.polling_interval = 15

        self.prices = {} 
        self.prev_closes = {} 
        self.sources = {} 
        self.last_update_time = None
        self.symbols = ["GLD", "USO", "XOP", "SLV"]
        self.req_id_counter = 1000 

        self.next_order_id = None
        self.req_events = {} 
        self.req_data = {} 
        self.placed_order_ids = set() # 记录本实例下发的所有订单 ID，用于精准撤单
        self.on_ib_fill = None        # [AI-2026-08-15] 成交回执回调槽(精确每笔部分成交)：on_ib_fill(orderId, symbol, side, shares, price)
        self.on_ib_order_done = None   # [AI-2026-08-15] 订单终态回调(全成/已撤)：on_ib_order_done(orderId, status)
        self.order_status = {}         # orderId -> {status, filled, remaining, avgFillPrice}

        # [AI-2026-08-15] 历史成交查询（reqExecutions）隔离区：与实时成交回执(reqId=-1)严格区分，
        # 历史回执只进 buffer 收集，绝不喂 on_ib_fill（避免错误触发 monitor 对冲）。
        self._history_req_ids = set()      # 历史查询使用的 reqId 集合
        self._history_buffer = []          # 收集的历史成交 dict 列表
        self._history_event = None         # threading.Event，execDetailsEnd 置位结束等待
        self._history_commissions = {}     # execId -> commission，commissionReport 回填

        # 内存长连接订阅池
        self.mkt_req_ids = {}
        self.symbol_req_ids = {}
        self.last_tick_time = {}
        self.running = False
        self.polling_thread = None

        # [V10.0] 连接控制：启动时不自动连接，用户点击页面"IB"按钮才重连
        self.disabled = True
        self.max_retries = 3
        self.last_connect_time = 0
        # [V10.0] 不再启动后台连接线程，用户手动触发 reconnect() 即可

        # [AI-2026-08-02] 陈旧数据强制重连看门狗参数（详见 014 文档第九节）
        self.stale_reconnect_threshold = 600   # [AI-2026-08-03] 已连接但长连接零 tick 超过此秒数(夜盘)则强制重连自愈；无备用源机制，纯靠长连接真实 tick 时间判定
        self.stale_reconnect_cooldown = 600    # 两次强制重连最小间隔(秒)，防抖动
        self._last_forced_reconnect = 0
        # [AI-2026-08-05] 断连自动重连（自愈断连）：连接彻底断了(非"连着无tick")时，夜盘时段自动重连，
        # 避免每天隔夜数据农场掉线后需手动点IB按钮。auto_reconnect_cooldown 控制重试节奏(避免日志刷屏)。
        self.auto_reconnect_cooldown = 300     # 断连后自动重连最小间隔(秒)，默认5分钟试一次
        self._last_auto_reconnect = 0
        self._stale_watchdog_running = False
        self._stale_watchdog_thread = None

        # [AI-2026-08-06] 连接就绪门禁：仅当行情农场(2104/2106)就绪后才订阅，避免 IB 静默丢弃
        # 连接握手期过早发出的 reqMktData(竞态根因，近期回归)。connection_ready 由 error() 收
        # 2104/2106 置 True，并由 connect_time + 保护超时强制置 True，防信号丢失永久不订阅。
        self.connection_ready = False
        self.connect_time = 0.0
        self.subscribe_time = {}            # sym -> 订阅发起时间戳(死订阅检测用)
        # [AI-2026-08-06] 死订阅自愈参数：阈值 60→300(美东深夜/流动性差时 60s 零 tick 完全正常，
        # 原 60s 阈值实测导致 cancel+重订无限循环：13:13-13:22 触发 109 次，打断正常订阅并刷爆日志)；
        # 连续重订 sub_dead_max_retries 次仍零 tick → 停止重订并打 ERROR 提示重启 Gateway。
        self.sub_dead_threshold = 300       # 订阅后超过此秒数仍零 tick 视为死订阅，触发轻量重订
        self.sub_dead_max_retries = 3       # 每 symbol 连续重订上限，超限判定 Gateway 侧推流僵死
        self._dead_resub_count = {}         # sym -> 连续重订次数(收到首 tick 清零)
        self._last_dead_alarm = 0.0         # Gateway 僵死告警限频时间戳
        self.connection_ready_fallback = 30  # [AI-2026-08-06] 连上 Gateway 后最多 30s 兜底置 connection_ready；[AI-2026-08-19] 回退：当日误把门禁改严(只认usfarm+180s硬超时)致行情"启动不来/很久才来"，恢复 30s 宽松兜底(东哥"先启IB立刻程序秒到"实测可行)

        # [AI-2026-08-04] 注册协议层容错钩子（进程内只注册一次）
        global _IB_READER_INSTANCE, _ORIG_THREAD_EXCEPTHOOK
        _IB_READER_INSTANCE = self
        if threading.excepthook is not _ib_thread_excepthook:
            _ORIG_THREAD_EXCEPTHOOK = threading.excepthook
            threading.excepthook = _ib_thread_excepthook

    def is_us_night_session(self):
        """判断当前是否为IBKR美股夜盘交易时段 (北京时间)"""
        now = datetime.now()
        current_time = now.time()
        # 夏令时：3月第二个周日到11月第一个周日。简单处理为3-11月。
        is_summer_time = 3 <= now.month <= 11
        if is_summer_time:
            # 美东时间 20:00 - 03:50 -> 北京时间 08:00 - 15:50
            night_start = datetime.strptime("08:00", "%H:%M").time()
            night_end = datetime.strptime("15:50", "%H:%M").time()
        else:
            # 美东时间 20:00 - 03:50 -> 北京时间 09:00 - 16:50
            night_start = datetime.strptime("09:00", "%H:%M").time()
            night_end = datetime.strptime("16:50", "%H:%M").time()
        
        # 周一到周五
        is_weekday = 0 <= now.weekday() <= 4
        return is_weekday and (night_start <= current_time < night_end)

    def _get_next_req_id(self):
        self.req_id_counter += 1
        return self.req_id_counter

    def connect_to_ib(self):
        if self.disabled:
            logger.debug("[IB] 已禁用，跳过连接")
            return False
        target_port = self.target_ports[self.current_port_index]
        print(f"[IBReader] 尝试连接 IB Gateway/TWS (端口: {target_port}, ClientId: {self.client_id})...")
        self.next_order_id = None  # [AI-2026-07-02] 每次新连接重置订单ID
        try:
            self.connect("127.0.0.1", target_port, clientId=self.client_id)
            api_thread = threading.Thread(target=self.run, daemon=True)
            api_thread.start()
            time.sleep(2)
            if self.isConnected():
                self.connected = True
                self.retry_delay = 1.0
                self.connection_ready = False   # [AI-2026-08-06] 重置，等 2104/2106 或保护超时
                self.connect_time = time.time()
                print(f"[IBReader] [OK] 连接成功 (端口: {target_port})")
                return True
            else:
                print(f"[IBReader] [ERROR] 连接失败 (端口: {target_port})")
                self.disconnect()
                self.connected = False
                self.current_port_index = (self.current_port_index + 1) % len(self.target_ports)
                return False
        except Exception as e:
            print(f"[IBReader] [ERROR] 连接异常 (端口: {target_port}): {e}")
            self.disconnect()
            self.connected = False
            self.current_port_index = (self.current_port_index + 1) % len(self.target_ports)
            return False

    def disconnect_from_ib(self):
        # [AI-2026-08-05] 修复僵尸socket：无条件调用 disconnect()，不再依赖 isConnected() 判断。
        # isConnected()可能返回False但TCP socket仍alive（EReader线程崩溃后的僵尸状态），
        # 此时不断开旧socket则reconnect()时IB Gateway因重复ClientId拒绝新连接(Error 326)，
        # 导致3次重连全部失败。ibapi disconnect()内部检查socket非None才关闭，安全调用。
        try:
            self.disconnect()
            self.connected = False
            self.prices = {}  # [AI-2026-07-15] 断连时清除缓存价格，避免前端误判为 Ready
            self.last_update_time = None
            time.sleep(1)  # 给 TCP FIN 包传播到 TWS/Gateway 的时间，防止进程立即退出导致连接残留
            logger.info("[IB] 已断开与 Gateway 的连接")
        except Exception as e:
            logger.warning(f"[IB] 断开连接异常(自愈不影响重连): {e}")
        finally:
            # [AI-2026-08-03] 断连清空心跳时间戳，重连后看门狗从零计时，避免误判"已连接无数据"
            self.last_tick_time = {}
            # [AI-2026-08-04] 断连清空订阅池(mkt/symbol req_ids)，放 finally 确保 self.disconnect() 抛异常(EReader崩溃后常见)时也清空，
            # 任何重连路径(含 excepthook 自愈)都会重新 reqMktData，避免旧 ReqId 残留导致重连后不重新订阅、收不到 tick。
            self.mkt_req_ids.clear()
            self.symbol_req_ids.clear()
            self.connection_ready = False   # [AI-2026-08-06] 断连后需重新等行情农场就绪
            self.subscribe_time.clear()

    def fetch_prev_closes_once(self):
        """如果昨收数据为空，则尝试获取一次。"""
        if not self.connected or self.prev_closes:
            return

        # 🛡️ 核心修复：防止刚连上Socket但握手未完成时请求数据导致的 NoneType 比较崩溃
        if not self.serverVersion():
            return

        # 🛡️ 核心修复：增加 60 秒的冷却时间，防止因为取不到历史数据而频繁卡顿 API 5 秒
        current_time = time.time()
        if current_time - getattr(self, '_last_prev_close_attempt', 0) < 60:
            return
        self._last_prev_close_attempt = current_time

        print("[IBReader] 昨收数据为空，尝试获取一次...")
        current_prev_closes = {}
        req_ids = []
        for sym in self.symbols:
            req_id_prev = self._get_next_req_id()
            req_ids.append(req_id_prev)
            c_prev = Contract()
            c_prev.symbol = sym
            c_prev.secType = "IND" if sym == "VIX" else "STK"
            # [AI-2026-08-03] 铁律 TOP1：夜盘任何情况禁止 SMART/ISLAND/ARCA。前收盘备用源抓取改走 OVERNIGHT。
            c_prev.exchange = "CBOE" if sym == "VIX" else "OVERNIGHT"
            c_prev.currency = "USD"
            self.req_events[req_id_prev] = threading.Event()
            self.reqHistoricalData(req_id_prev, c_prev, "", "1 D", "1 day", "TRADES", 1, 1, False, [])
            # 🛡️ 增加微小延时，防止瞬间并发多个历史请求触发 IB 的 Pacing Violation (防刷限制)
            time.sleep(0.05)

        # 等待所有请求完成，最多15秒 (IB历史数据服务器排队响应时可能较慢)
        start_time = time.time()
        while not all(self.req_events.get(req_id, threading.Event()).is_set() for req_id in req_ids) and (time.time() - start_time < 15):
            time.sleep(0.1)

        for req_id, sym in zip(req_ids, self.symbols):
             prev_close_bar = self.req_data.get(req_id)
             if prev_close_bar: current_prev_closes[sym] = prev_close_bar
             
        if current_prev_closes:
            self.prev_closes = current_prev_closes
            print(f"[IBReader] [INFO] 已获取昨日收盘价: " + ", ".join([f"{k}=${v:.2f}" for k, v in self.prev_closes.items()]))
        else:
            # 🛡️ 核心修复：如果获取失败，直接填入占位符，
            # 让 self.prev_closes 不再为空，从而彻底掐断无限重试的死循环，还控制台清净！
            print("[IBReader] [WARNING] 未能获取到昨日收盘价(可能是并发超限、超时或非交易日无数据)。已终止重试。")
            self.prev_closes = {sym: 0.0 for sym in self.symbols}

    def start_polling(self):
        # [AI-2026-08-02] 防重入：若轮询线程已在运行则跳过，避免强制重连时新旧线程叠加
        if self.running and self.polling_thread and self.polling_thread.is_alive():
            logger.debug("[IB] 轮询线程已在运行，跳过重复启动")
            return
        if not self.running:
            self.running = True
            self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
            self.polling_thread.start()
            print("[IBReader] 启动 IB 后台轮询线程")
        # [AI-2026-08-02] 陈旧数据看门狗随轮询一同启动（独立线程，避免自 join 死锁）
        if not self._stale_watchdog_running:
            self._stale_watchdog_running = True
            self._stale_watchdog_thread = threading.Thread(target=self._stale_watchdog_loop, daemon=True)
            self._stale_watchdog_thread.start()

    def stop_polling(self):
        self.running = False
        if self.polling_thread:
            self.polling_thread.join(timeout=5)
        # [AI-2026-08-02] 停止看门狗；若在看门狗线程内调用则不自 join（防死锁）
        self._stale_watchdog_running = False
        if self._stale_watchdog_thread and threading.current_thread() is not self._stale_watchdog_thread:
            self._stale_watchdog_thread.join(timeout=5)
            self._stale_watchdog_thread = None

    def _stale_watchdog_loop(self):
        """[AI-2026-08-02] 陈旧数据强制重连看门狗（独立线程，避免与轮询线程相互 join 死锁）

        唯一触发条件（满足才动作）：
          - self.connected / EClient.isConnected() 为假（连接确实断了）
            且当前为美股夜盘时段 is_us_night_session()
          → 自动重连（自愈隔夜/盘中掉线）。

        [AI-2026-08-07] 移除原"情况A：已连接但停滞600s强制断开重连"分支。
          理由：① "连着但零tick"多为农场切换/低流动性/订阅待激活，IB会自行恢复，
                不等于连接死了；② 强制拆连接引发 client_id 互踢(Error326)与订阅竞态，
                且 stop_polling() 把看门狗自己关掉、reconnect() 失败分支不重启看门狗→
                看门狗永久自杀（2026-08-07 实测 10:22 后静默死）。
          连接存活但无 tick 已由订阅级"死订阅重订"负责，无需拆连接。
          红线约束（disconnect_from_ib/reconnect）在 Job1 自动重连时同样严守：
          - 即时停用开关：环境变量 ARB_IB_STALE_GUARD=0 可不经改代码关闭本看门狗。
        """
        # 即时停用开关：无需改代码即可关闭看门狗
        if os.environ.get('ARB_IB_STALE_GUARD', '1') == '0':
            self._stale_watchdog_running = False
            logger.info("[IB] 陈旧数据看门狗已被环境变量 ARB_IB_STALE_GUARD=0 禁用")
            return
        while self._stale_watchdog_running:
            time.sleep(30)
            try:
                # [AI-2026-08-05] 情况B：连接彻底断了(非"连着无tick")。隔夜数据农场掉线后，
                # self.connected 变 False，原逻辑直接 continue 跳过 → 需手动点IB按钮。
                # 改为：夜盘时段 + 未连接 + 冷却已过 → 自动重连，实现"隔夜断连早上自愈"。
                if (not self.connected or not self.isConnected()) and self.is_us_night_session():
                    now_ts = time.time()
                    if now_ts - self._last_auto_reconnect < self.auto_reconnect_cooldown:
                        continue
                    self._last_auto_reconnect = now_ts
                    logger.info("[IB] 看门狗：检测到未连接且处于夜盘时段，尝试自动重连(自愈断连)")
                    try:
                        # reconnect() 内含 disconnect_from_ib()(已修僵尸socket) + 重订阅；
                        # 若 IB Gateway 已恢复则成功，否则失败(下个冷却周期再试)。
                        ok, msg = self.reconnect()
                        if ok:
                            logger.info(f"[IB] 看门狗自动重连成功: {msg}")
                        else:
                            logger.warning(f"[IB] 看门狗自动重连暂未成功(IB Gateway可能未启动): {msg}")
                    except Exception as e:
                        logger.warning(f"[IB] 看门狗自动重连异常: {e}")
                    continue
                # [AI-2026-08-07] 情况A（连着但停滞→强制断开重连）已移除：见函数 docstring。
                # 连接存活但无 tick 交给订阅级"死订阅重订"处理，看门狗只负责真断自愈。
                # 此处 fall-through 到循环顶部 30s 后再次判定，不执行任何拆连接动作。
            except Exception as e:
                logger.warning(f"[IB] 看门狗循环异常: {e}")

    def _polling_loop(self):
        # [AI-2026-08-03] 外层 try/except 防线程意外退出后 self.running 卡在 True 导致 start_polling 防重入误判
        try:
            self._polling_loop_inner()
        except Exception as e:
            logger.error(f"[IB] 轮询线程异常退出: {e}", exc_info=True)
            self.running = False

    def _polling_loop_inner(self):
        while self.running:
            # 兼容原有的 YAML 动态读取，并且优先支持从数据库加载白名单
            try:
                # [V7.3] IB 只订阅核心套利标的，不拉取全量 SYMBOL_SOURCE_MAP
                # 核心标的列表从配置读取，支持用户自定义
                from arbcore.config.source_routing import IB_CORE_ARBITRAGE_SYMBOLS
                new_symbols = list(IB_CORE_ARBITRAGE_SYMBOLS)
                # [AI-2026-08-06] 仅当标的列表变化时才打印，避免每 5s 轮询循环反复刷屏
                if new_symbols != getattr(self, '_last_printed_symbols', None):
                    self._last_printed_symbols = new_symbols
                    print(f"[IBReader] 核心套利标的: {new_symbols} ({len(new_symbols)} 只)")
                self.symbols = new_symbols
            except Exception as e:
                print(f"[IBReader] 加载核心套利标的异常: {e}，使用默认列表")
                self.symbols = ["GLD", "USO", "XOP", "SLV", "SPY", "QQQ", "INDA"]
            
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

            is_night = self.is_us_night_session()
            
            if not is_night:
                self.prices, self.sources, self.last_update_time = {}, {}, datetime.now()
                # 非夜盘期间，取消所有订阅以释放资源
                for req_id in list(self.mkt_req_ids.keys()):
                    self.cancelMktData(req_id)
                self.mkt_req_ids.clear()
                self.symbol_req_ids.clear()
                time.sleep(self.polling_interval * 2) # 非夜盘时段降低轮询频率
                continue

            # [AI-2026-08-06] 订阅门禁：未连接握手完成(行情农场 2104/2106 就绪)前不订阅，
            # 避免 IB 静默丢弃连接握手期过早发出的 reqMktData(竞态根因，近期回归)。
            # [AI-2026-08-19] 回退：恢复 30s 宽松兜底，不筛 usfarm/不拉 180s 硬超时(旧行为"先启IB立刻程序秒到"验证可行)
            if not self.connection_ready:
                if (time.time() - self.connect_time) > self.connection_ready_fallback:
                    self.connection_ready = True
                    logger.info(f"[IB] 订阅门禁兜底解除(连上 {self.connection_ready_fallback}s 未收到2104/2106则强制订阅)")
                else:
                    time.sleep(2)
                    continue

            for sym in self.symbols:
                # 1. 建立并维持内存长连接订阅 (零违规风险)
                if sym not in self.symbol_req_ids:
                    req_id = self._get_next_req_id()
                    self.symbol_req_ids[sym] = req_id
                    self.mkt_req_ids[req_id] = sym
                    
                    c = Contract()
                    c.symbol = sym
                    c.secType = "IND" if sym == "VIX" else "STK"
                    c.exchange = "CBOE" if sym == "VIX" else "OVERNIGHT"
                    c.currency = "USD"
                    # snapshot=False 开启持续长连接推送
                    self.reqMktData(req_id, c, "", False, False, [])
                    self.sources[sym] = "订阅请求中..."
                    self.subscribe_time[sym] = time.time()  # [AI-2026-08-06] 记录订阅时刻(死订阅检测用)
                    # [AI-2026-08-03] 提升为 print 级别：用户需要看到订阅是否成功发出，debug 级别在控制台不可见
                    print(f"[IBReader] 已发起 {sym} 夜盘长连接订阅 (ReqId: {req_id})")

            # [AI-2026-08-06] 死订阅自愈：已订阅但超过 sub_dead_threshold 仍零 tick(连接健康)，
            # 取消并移除，让下一轮循环用新 ReqId 重订，无需整连。(last_tick_time 现仅在首 tick 打点)
            # ⚠️ 重订上限：连续 sub_dead_max_retries 次仍零 tick → 停止重订并告警"疑似 Gateway 侧推流僵死"，
            # 避免 cancel+重订无限循环(今日 13:13-13:22 实测 60s 阈值误伤触发 109 次，打断正常订阅并刷爆日志)。
            for sym in list(self.symbol_req_ids.keys()):
                st = self.subscribe_time.get(sym)
                if st is None:
                    continue
                if self.last_tick_time.get(sym) is None and (time.time() - st) > self.sub_dead_threshold:
                    cnt = self._dead_resub_count.get(sym, 0) + 1
                    if cnt > self.sub_dead_max_retries:
                        # 保留订阅挂着等真实 tick，不再 cancel 重订；仅限频告警，定位根因
                        if time.time() - self._last_dead_alarm > 300:
                            self._last_dead_alarm = time.time()
                            logger.error(
                                f"[IB] {sym} 连续重订 {cnt} 次仍零 tick(订阅 {int(time.time()-st)}s)："
                                f"疑似 IB Gateway 侧实时行情推流僵死(非 app 订阅问题)，请重启 IB Gateway(托盘退出重进+重登录)")
                        continue
                    self._dead_resub_count[sym] = cnt
                    rid = self.symbol_req_ids.pop(sym)
                    self.mkt_req_ids.pop(rid, None)
                    self.subscribe_time.pop(sym, None)
                    try:
                        self.cancelMktData(rid)
                    except Exception:
                        pass
                    logger.warning(f"[IB] 死订阅自愈: {sym} 订阅 {int(time.time()-st)}s 零 tick，已取消待重订(第{cnt}次)")

            # [AI-2026-08-03] 已彻底移除"历史 BID/TRADES 快照备用源"：东哥红线——任何时候都不写
            # 历史快照冒充实时盘口（bid=ask=last 单一值）。没有真实盘口时前端显示"等待数据"，
            # 由 stale 看门狗负责长连接零 tick 自愈重连。底层的 tickPrice/tickSize 会毫秒级更新字典，
            # 此处仅做短暂停留。
            time.sleep(5)

    def _try_connect_silent(self):
        """静默尝试连接 IB，最多 max_retries 次"""
        if self.disabled:
            return
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.connect_to_ib():
                    logger.info(f"{'='*50}\n[IB] 连接成功 (第 {attempt} 次尝试)\n{'='*50}")
                    self.disabled = False
                    return
            except Exception as e:
                logger.debug(f"[IB] 连接尝试 {attempt}/{self.max_retries} 失败: {e}")
                time.sleep(1)
        logger.warning("[IB] 连接失败（已尝试 {} 次），已禁用 IB 读取器。如需启用，请点击页面顶部的'IB'标签重试。".format(self.max_retries))
        self.disabled = True
        self.connected = False
    
    def reconnect(self):
        """手动重连（供用户点击"IB"按钮时调用）"""
        # [V10.4] 已连接时原本直接 return(避免 Error 326)，但会丢失"连着无数据"的自愈机会。
        # [AI-2026-08-06] 改为清空订阅池触发 polling 循环立即重订(不重连 socket)，自愈死订阅/竞态：
        # 连着但零 tick 时点按钮也能救，不必重启 Gateway。
        if self.isConnected():
            logger.info("[IB] 已连接，清空订阅池以触发重订阅(自愈死订阅/竞态，不清 socket)")
            self.mkt_req_ids.clear()
            self.symbol_req_ids.clear()
            self.subscribe_time.clear()
            if not self.running:
                self.start_polling()
            return True, "IB 已连接，已触发重订阅"
        # [AI-2026-08-05] 修复：重连前先彻底断开旧连接（含僵尸TCP socket）。
        # isConnected()返回False时旧socket可能仍alive，不先断开则IB Gateway因重复
        # ClientId拒绝新连接(Error 326)，3次重连全失败。disconnect_from_ib()已改为
        # 无条件disconnect()，能关闭僵尸socket。
        self.disconnect_from_ib()
        logger.info("[IB] 用户手动触发重连...")
        self.disabled = False
        self.connected = False
        self.last_connect_time = 0
        self.current_port_index = 0
        self.next_order_id = None  # [AI-2026-07-02] 重连后重置订单ID，确保 reqIds 重新获取
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.connect_to_ib():
                    logger.info(f"[IB] 手动重连成功 (第 {attempt} 次)")
                    self.disabled = False
                    # [AI-2026-08-04] 重连成功后清空订阅池，确保 polling_loop 重新 reqMktData 收到 tick；
                    # 否则旧 ReqId 残留会导致重连后跳过订阅、主看板实时估值仍空白（自愈重连假连接）。
                    self.mkt_req_ids.clear()
                    self.symbol_req_ids.clear()
                    # [AI-2026-07-02] 连接成功后立即启动轮询线程，不等前端请求懒加载
                    self.start_polling()
                    return True, f"IB 连接成功 (第 {attempt} 次尝试)"
            except Exception as e:
                logger.warning(f"[IB] 重连失败 (第 {attempt}/{self.max_retries} 次): {e}")
                time.sleep(1)
        self.disabled = True
        logger.warning("[IB] 手动重连失败（已尝试 {} 次），请检查 TWS/Gateway 是否运行".format(self.max_retries))
        return False, f"IB 重连失败（已尝试 {self.max_retries} 次），请确认 TWS/Gateway 已启动"
    
    def nextValidId(self, orderId: int):
        super().nextValidId(orderId)
        self.next_order_id = orderId
        print(f"[IBReader] [OK] 获取到下一个可用订单 ID: {orderId}")

    def error(self, reqId, *args):
        if len(args) >= 2:
            if isinstance(args[0], int) and args[0] > 1000000000:
                errorCode, errorString = args[1], (args[2] if len(args) > 2 else "")
            else:
                errorCode, errorString = args[0], args[1]
        else:
            return
        # 🤫 彻底屏蔽 10089(延时警告) 和 10346(持仓通道被TWS强制抢占警告)
        # [V10.11] 新增 502（连接被拒/端口不对）— 端口重试过程中的 502 是预期行为，不应触发断连
        # [AI-2026-08-06] 2104/2106=行情农场连接正常，是"可订阅"的就绪信号；收到即置 connection_ready
        # 解除订阅门禁(配合 connect_time 保护超时，防信号丢失永久不订阅)。
        # [AI-2026-08-19] 回退：任何 2104/2106 即就绪(不再解析农场名/筛 usfarm)——旧行为实测"先启IB立刻程序秒到"；
        # 严格等 usfarm 是把空窗拉到 180s 的退化，已废弃。
        if errorCode in [2104, 2106]:
            if not self.connection_ready:
                self.connection_ready = True
                logger.info("[IB] 行情农场就绪信号(2104/2106)，解除订阅门禁")
            return
        if errorCode in [200, 502, 2107, 2108, 2157, 2158, 10091, 10197, 10089, 10346]:
            return
            
        if errorCode in [2103, 2105]:
            print(f"[IBReader] [WARNING] IB数据农场连接断开 (代码 {errorCode}): {errorString} - 这将导致长连接无数据！")
            return
            
        # 智能诊断：拦截典型的“无行情订阅权限”错误码
        if errorCode in [354, 10090, 10167, 10168]:
            print(f"[IBReader] [INFO] 提示 (代码 {errorCode}): 您的账号无美股实时行情订阅权限，将无法显示实时盘口（前端显示等待数据），需检查 IB 行情订阅。")
            return
            
        print(f"[IBReader] [WARNING] Error {errorCode} (ReqId: {reqId}): {errorString}")
        
        # 🛡️ 核心修复：如果一个同步请求(如历史数据)发生错误，必须设置其Event，否则主线程会卡死
        if reqId in self.req_events:
            print(f"[IBReader] [INFO] 提示: 请求 {reqId} 发生错误，已解除其等待锁。")
            self.req_events[reqId].set()

        if errorCode in [504, 1100, 1101, 1102]:
            self.connected = False
            self.disconnect_from_ib()
            self.mkt_req_ids.clear()
            self.symbol_req_ids.clear()

    def tickPrice(self, reqId, tickType, price, attrib):
        # 🛡️ 核心修复：兼容新版 IBAPI，将 Decimal 强转为 float，防止后续 JSON 序列化崩溃
        try:
            price = float(price)
        except Exception:
            pass
        if price > 0:
            sym = self.mkt_req_ids.get(reqId)
            if sym:
                if sym not in self.prices or not isinstance(self.prices[sym], dict):
                    self.prices[sym] = {'bid': 0.0, 'ask': 0.0, 'last': 0.0, 'bid_size': 0, 'ask_size': 0}
                
                # 💡 只要长连接有任何跳动，都喂一口看门狗，重置30秒倒计时
                if tickType in [1, 2, 4, 66, 67, 68]:
                    self.last_tick_time[sym] = time.time()
                    # [AI-2026-08-06] 收到真实 tick → 清零该 symbol 的连续重订计数(死订阅自愈恢复正常)
                    self._dead_resub_count.pop(sym, None)
                
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
                elif tickType in [4, 68]: # [AI-2026-08-03] Last 仅写入 last，绝不回填 bid/ask。
                    # 长连接未推盘口(bid==0)时只保留 last，不把成交价伪装成买一卖一（违反 014 红线11）
                    self.prices[sym]['last'] = price
                
                self.last_update_time = datetime.now()
                
                # 触发外部传入的回调函数，将实时数据传给外层环境(如 Flask/Socket)
                if tickType in tick_names and self.on_price_update:
                    now_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    self.on_price_update({
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

    def tickSize(self, reqId, tickType, size):
        """接收 IB 推送的盘口挂单数量"""
        # 🛡️ 核心修复：兼容新版 IBAPI，将 Decimal 强转为 float/int，防止 JSON 序列化报错
        try:
            size = float(size)
        except Exception:
            pass
        sym = self.mkt_req_ids.get(reqId)
        if sym:
            if sym not in self.prices or not isinstance(self.prices[sym], dict):
                self.prices[sym] = {'bid': 0.0, 'ask': 0.0, 'last': 0.0, 'bid_size': 0, 'ask_size': 0}
                
            # 💡 只要长连接有任何跳动，都喂一口看门狗，防止被断线判定
            if tickType in [0, 3, 5, 69, 70, 71]:
                self.last_tick_time[sym] = time.time()
                # [AI-2026-08-06] 收到真实 tick → 清零该 symbol 的连续重订计数(死订阅自愈恢复正常)
                self._dead_resub_count.pop(sym, None)
                
            tick_names = {
                0: "BidSize(买一量)", 3: "AskSize(卖一量)", 5: "LastSize(最新量)",
                69: "BidSize(延迟买一量)", 70: "AskSize(延迟卖一量)", 71: "LastSize(延迟最新量)"
            }
            
            if tickType in [0, 69]: # 买盘数量
                self.prices[sym]['bid_size'] = size
            elif tickType in [3, 70]: # 卖盘数量
                self.prices[sym]['ask_size'] = size
                
            self.last_update_time = datetime.now()
            
            # 同样推送给后端的 Socket 回调，保持 Web 端的极速更新
            if tickType in tick_names and self.on_price_update:
                now_str = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                self.on_price_update({
                    'symbol': sym,
                    'size': size,
                    'tickType': tickType,
                    'tickName': tick_names[tickType],
                    'timestamp': now_str,
                    'prices': self.prices
                })

    def historicalData(self, reqId, bar):
        # 🛡️ 核心修复：兼容新版 IBAPI，将昨收盘价强转为 float，防止 JSON 序列化报 500 错误
        try:
            self.req_data[reqId] = float(bar.close)
        except Exception:
            self.req_data[reqId] = bar.close

    def historicalDataEnd(self, reqId, start, end):
        if reqId in self.req_events: self.req_events[reqId].set()

    def place_us_order(self, symbol, action, quantity, price):
        """核心恢复：IB 盈透盘前夜盘下单指令发送"""
        if not self.isConnected():
            return False, "IB 未连接", None
            
        if self.next_order_id is None:
            self.reqIds(-1)
            for _ in range(10):
                if self.next_order_id is not None: break
                time.sleep(0.1)
                
        if self.next_order_id is None:
            return False, "无法获取有效订单 ID，请检查 TWS 是否开启了 '只读API' 限制", None
            
        contract = Contract()
        contract.symbol = symbol
        contract.secType = "STK"
        
        # 🛡️ 智能追加 Primary Exchange (主交易所)
        # 直接路由时，如果没有 primaryExchange，极易被系统当作歧义合约而瞬间拒单 (Error 201)
        primary_map = {"QQQ": "NASDAQ", "SPY": "ARCA", "GLD": "ARCA", "USO": "ARCA", "XOP": "ARCA", "XBI": "ARCA", "SLV": "ARCA"}
        # 🛡️ 核心修复：夜盘直连 OVERNIGHT 必须移除 primaryExchange，否则 Gateway 的 Sec-def 断连时极易导致 201 废单
        if symbol in primary_map and not self.is_us_night_session():
            contract.primaryExchange = primary_map[symbol]
            
        # 智能判断交易所 (根据测试脚本的成功经验，统一使用 OVERNIGHT)
        if self.is_us_night_session():
            contract.exchange = "OVERNIGHT"
            print("[IBReader] 智能路由: 检测到夜盘时段，订单交易所切换为 OVERNIGHT")
        else:
            contract.exchange = "SMART"
            print("[IBReader] 智能路由: 非夜盘时段，订单交易所使用 SMART")
        contract.currency = "USD"
        
        order = Order()
        order.action = action # 'BUY' 或 'SELL'
        
        # 🛡️ 核心修复：API卖空指令的正确姿势。Gateway 不会像 TWS 界面那样自动转换，必须显式声明融券来源
        if action == "SELL":
            order.shortSaleSlot = 1
            
        order.orderType = "LMT"
        order.totalQuantity = float(quantity)
        order.lmtPrice = float(price)
        order.tif = "DAY"
        order.outsideRth = True # 与测试脚本保持100%一致，允许盘外交易
        # [AI-2026-07-02] 显式清零 EtradeOnly，防部分 TWS/Gateway 版本拒单 (Error 10268)
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        order_id = self.next_order_id
        self.placeOrder(order_id, contract, order)
        self.placed_order_ids.add(order_id)
        self.next_order_id += 1 # 内部自增以便连续下单
        
        return True, f"指令已发送: {action} {quantity}股 {symbol} @ {price} (路由: {contract.exchange})", order_id

    def cancel_all_orders(self):
        """精准撤单：只撤销本程序沙盘发出的订单，绝不误伤手机APP挂的单"""
        if not self.isConnected():
            return False, "IB 未连接"
        try:
            import inspect
            sig = inspect.signature(self.cancelOrder)
            
            # 仅精准撤销本程序下发的活动订单，对手机APP手动单秋毫无犯
            for oid in list(self.placed_order_ids):
                if 'orderCancel' in sig.parameters:
                    try:
                        from ibapi.order_cancel import OrderCancel
                        self.cancelOrder(oid, OrderCancel())
                    except ImportError:
                        self.cancelOrder(oid, None)
                elif 'manualOrderCancelTime' in sig.parameters:
                    self.cancelOrder(oid, "")
                else:
                    self.cancelOrder(oid)
                    
            self.placed_order_ids.clear()
            return True, "沙盘挂单已精准撤销 (您的手机手动MOC单不受影响)"
        except Exception as e:
            return False, f"撤单异常: {str(e)}"

    # ── [AI-2026-08-15] 成交回执回调：精确每笔部分成交，取代持仓 delta 推断 ──
    def execDetails(self, reqId, contract, execution):
        """每笔成交回执(symbol/side/shares/price/orderId)。
        [AI-2026-08-15] 按 reqId 隔离：历史查询(reqId 在 _history_req_ids)只收集进 buffer，
        绝不喂 on_ib_fill；实时成交(IB 广播 reqId=-1)走原逻辑喂 monitor 对冲。"""
        try:
            symbol = getattr(contract, 'symbol', None)
            order_id = getattr(execution, 'orderId', None)
            side = getattr(execution, 'side', None)      # 'BOT' / 'SLD'
            shares = float(getattr(execution, 'shares', 0) or 0)
            price = float(getattr(execution, 'price', 0) or 0)
            # [AI-2026-08-15] 历史查询回执：仅收集进流水 buffer，绝不触发 monitor 对冲
            if reqId in getattr(self, '_history_req_ids', set()):
                self._history_buffer.append({
                    'exec_id': getattr(execution, 'execId', None),
                    'order_id': order_id,
                    'symbol': symbol,
                    'side': side,
                    'shares': shares,
                    'price': price,
                    'trade_time': getattr(execution, 'time', None),
                    'account': getattr(execution, 'acctNumber', None) or getattr(execution, 'acctId', None),
                    'commission': None,
                    'currency': None,
                })
                logger.info(f"[IBReader] 📜 历史成交收集: {side} {shares} {symbol} @ {price} execId={getattr(execution, 'execId', None)}")
                return
            logger.info(f"[IBReader] ⚡ execDetails: {side} {shares} {symbol} @ {price} orderId={order_id}")
            cb = getattr(self, 'on_ib_fill', None)
            if callable(cb):
                cb(order_id, symbol, side, shares, price)
        except Exception as e:
            logger.warning(f"[IBReader] execDetails 解析异常: {e}")

    # ── [AI-2026-08-15] 历史成交查询（reqExecutions）：手动触发拉取过去 N 天真实成交 ──
    def execDetailsEnd(self, reqId):
        """历史查询结束标记：置位 Event 唤醒 fetch_executions 的等待。"""
        if reqId in getattr(self, '_history_req_ids', set()):
            if self._history_event:
                self._history_event.set()
            logger.info(f"[IBReader] ✅ 历史成交查询结束 reqId={reqId} (共 {len(self._history_buffer)} 笔)")

    def commissionReport(self, commissionReport):
        """手续费回执：按 execId 关联回填到历史成交 buffer。"""
        try:
            eid = getattr(commissionReport, 'execId', None)
            comm = float(getattr(commissionReport, 'commission', 0) or 0)
            if not eid:
                return
            for rec in getattr(self, '_history_buffer', []):
                if rec.get('exec_id') == eid:
                    rec['commission'] = comm
                    rec['currency'] = getattr(commissionReport, 'currency', None)
                    break
            else:
                # 回执晚于 execDetailsEnd 到达：暂存，fetch_executions 收尾时合并
                self._history_commissions[eid] = comm
            logger.info(f"[IBReader] 💰 commissionReport: execId={eid} commission={comm} {getattr(commissionReport, 'currency', '')}")
        except Exception as e:
            logger.warning(f"[IBReader] commissionReport 解析异常: {e}")

    def fetch_executions(self, days: int = 30, account: str = None) -> dict:
        """拉取过去 days 天的真实成交（需已连接 IB Gateway/TWS）。
        返回 {ok, count, since, data:[{exec_id,order_id,symbol,side,shares,price,trade_time,account,commission,currency}], error?}
        注意：本方法走独立 reqId，回执由 execDetails(reqId 在 _history_req_ids)收集，绝不触发 monitor 对冲。"""
        if not self.isConnected():
            return {"ok": False, "error": "IB 未连接（请先点页面 IB 按钮连接 Gateway）", "data": []}
        try:
            from ibapi.execution import ExecutionFilter
        except ImportError:
            return {"ok": False, "error": "ibapi.execution 不可用", "data": []}
        req_id = self._get_next_req_id()
        self._history_req_ids.add(req_id)
        self._history_buffer = []
        self._history_commissions = {}
        self._history_event = threading.Event()
        f = ExecutionFilter()
        since = datetime.utcnow() - timedelta(days=days)
        f.time = since.strftime("%Y%m%d-%H:%M:%S")   # IB 时间窗格式(UTC；IB 2174 警告要求 yyyymmdd-hh:mm:ss UTC，减号非空格)
        if account:
            f.acctCode = account
        try:
            self.reqExecutions(req_id, f)
        except Exception as e:
            self._history_req_ids.discard(req_id)
            return {"ok": False, "error": f"reqExecutions 调用失败: {e}", "data": []}
        finished = self._history_event.wait(timeout=60)
        if finished:
            time.sleep(3)   # 等手续费回执(可能晚于 execDetailsEnd 到达)
        # 合并晚到的手续费
        for rec in self._history_buffer:
            eid = rec.get('exec_id')
            if eid and eid in self._history_commissions:
                rec['commission'] = self._history_commissions[eid]
        self._history_req_ids.discard(req_id)
        return {
            "ok": True,
            "count": len(self._history_buffer),
            "since": since.strftime("%Y-%m-%d"),
            "data": self._history_buffer,
        }

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, *args):
        """订单终态/进度回执。记录到 order_status；全成/已撤时回调 on_ib_order_done。"""
        try:
            self.order_status[orderId] = {
                'status': status, 'filled': filled,
                'remaining': remaining, 'avgFillPrice': avgFillPrice
            }
            logger.info(f"[IBReader] orderStatus: orderId={orderId} status={status} filled={filled} remaining={remaining}")
            if status in ('Filled', 'Cancelled', 'ApiCancelled'):
                cb = getattr(self, 'on_ib_order_done', None)
                if callable(cb):
                    cb(orderId, status)
        except Exception as e:
            logger.warning(f"[IBReader] orderStatus 解析异常: {e}")
