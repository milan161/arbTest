# -*- coding: utf-8 -*-
# ib_reader.py - IB 盈透实时行情与交易基座模块

import threading
import time
from datetime import datetime
import yaml
import random
import os

from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.order import Order

class IBReader(EWrapper, EClient):
    def __init__(self, client_id=None, on_price_update=None):
        EClient.__init__(self, self)
        self.client_id = client_id if client_id is not None else random.randint(1000, 9999)
        self.on_price_update = on_price_update  # 注入回调函数解耦 SocketIO
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
        
        # 内存长连接订阅池
        self.mkt_req_ids = {}
        self.symbol_req_ids = {}
        self.last_tick_time = {}
        self.running = False
        self.polling_thread = None

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
            c_prev.symbol, c_prev.secType, c_prev.exchange, c_prev.currency = sym, "STK", "SMART", "USD"
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
            print(f"[IBReader] 📊 已获取昨日收盘价: " + ", ".join([f"{k}=${v:.2f}" for k, v in self.prev_closes.items()]))
        else:
            # 🛡️ 核心修复：如果获取失败，直接填入占位符，
            # 让 self.prev_closes 不再为空，从而彻底掐断无限重试的死循环，还控制台清净！
            print("[IBReader] ⚠️ 未能获取到昨日收盘价(可能是并发超限、超时或非交易日无数据)。已终止重试。")
            self.prev_closes = {sym: 0.0 for sym in self.symbols}

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
            # 兼容原有的 YAML 动态读取，遇到异常直接跳过(依赖外部传入 symbols)
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
                            for s in str(trade_etf).replace('，', ',').split(','):
                                if s.strip(): syms.add(s.strip().upper())
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
                            self.prices[sym] = {'bid': 0.0, 'ask': 0.0, 'bid_size': 0, 'ask_size': 0}
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
        if errorCode in [2104, 2106, 2107, 2108, 2157, 2158, 10091, 10197, 10089, 10346]:
            return
            
        if errorCode in [2103, 2105]:
            print(f"[IBReader] ⚠️ IB数据农场连接断开 (代码 {errorCode}): {errorString} - 这将导致长连接无数据！")
            return
            
        # 智能诊断：拦截典型的“无行情订阅权限”错误码
        if errorCode in [354, 10090, 10167, 10168]:
            print(f"[IBReader] 💡 提示 (代码 {errorCode}): 您的账号无美股实时行情订阅权限，系统已自动转入【安全快照】兜底模式，不影响套利运行。")
            return
            
        print(f"[IBReader] ⚠️ Error {errorCode} (ReqId: {reqId}): {errorString}")
        
        # 🛡️ 核心修复：如果一个同步请求(如历史数据)发生错误，必须设置其Event，否则主线程会卡死
        if reqId in self.req_events:
            print(f"[IBReader] 💡 提示: 请求 {reqId} 发生错误，已解除其等待锁。")
            self.req_events[reqId].set()

        if errorCode in [502, 504, 1100, 1101, 1102]:
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
                    self.prices[sym] = {'bid': 0.0, 'ask': 0.0, 'bid_size': 0, 'ask_size': 0}
                
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
                self.prices[sym] = {'bid': 0.0, 'ask': 0.0, 'bid_size': 0, 'ask_size': 0}
                
            # 💡 只要长连接有任何跳动，都喂一口看门狗，防止被断线判定
            if tickType in [0, 3, 5, 69, 70, 71]:
                self.last_tick_time[sym] = time.time()
                
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
        
        order_id = self.next_order_id
        self.placeOrder(order_id, contract, order)
        self.placed_order_ids.add(order_id)
        self.next_order_id += 1 # 内部自增以便连续下单
        
        return True, f"指令已发送: {action} {quantity}股 {symbol} @ {price} (路由: {contract.exchange})"

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
                        from ibapi.order import OrderCancel
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
