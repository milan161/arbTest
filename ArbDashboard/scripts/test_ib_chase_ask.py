# -*- coding: utf-8 -*-
"""
IB Chase-Ask LMT 订单测试程序
=============================
测试 IB LMT 订单追价机制：
1. 获取当前 ASK 价格
2. 以 ASK - offset 挂 SELL 限价单
3. 等待 RETRY_INTERVAL 秒，检查是否成交
4. 未成交则取消，获取新 ASK，重新挂单
5. 重复最多 MAX_RETRIES 次

警告：这是实盘账户测试！
- 请确认你的 IB 账户已开启交易权限
- 请确认你有足够的融券额度
- 请确认当前时间是美盘夜盘时段

使用方法：
  python test_ib_chase_ask.py

预期行为：
  - 连接 IB Gateway (端口 4001)
  - 订阅 GLD OVERNIGHT 实时行情 (BID + ASK)
  - 每次以 ASK - 0.01 挂 SELL 限价单
  - 追价最多 5 次，直到成交或达到上限
"""

import sys
import os
import time
import random
import threading
import logging
from datetime import datetime
from pathlib import Path

# 屏蔽 IBAPI 底层的 INFO 级别刷屏日志
logging.getLogger('ibapi.client').setLevel(logging.WARNING)
logging.getLogger('ibapi.wrapper').setLevel(logging.WARNING)

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
    from ibapi.order_cancel import OrderCancel
except ImportError:
    print("ibapi not installed. Run: pip install ibapi")
    sys.exit(1)


# ============================================================================
# 测试参数（顶部可配置）
# ============================================================================
SYMBOL = "GLD"
QUANTITY = 2
OFFSET = 0.01
MAX_RETRIES = 5
RETRY_INTERVAL = 3        # 每次挂单后等待检查的时间（秒）
MIN_ORDER_INTERVAL = 3    # IB 速率限制安全间隔（秒）
IB_PORT = 4001
IB_CLIENT_ID = 8888
ASK_TIMEOUT = 10          # 获取 ASK 价格的超时时间（秒）


# ============================================================================
# 日志工具
# ============================================================================
def setup_logger():
    """设置控制台 + 文件双重日志"""
    logger = logging.getLogger('chase_ask')
    logger.setLevel(logging.DEBUG)

    # 控制台 handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))
    logger.addHandler(ch)

    # 文件 handler
    log_dir = Path(__file__).parent / 'logs'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"chase_ask_{datetime.now().strftime('%Y-%m-%d')}.log"
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    logger.addHandler(fh)

    return logger


logger = setup_logger()


# ============================================================================
# IB Wrapper — 处理所有回调
# ============================================================================
class ChaseWrapper(EWrapper):
    """Chase-Ask 测试专用 Wrapper"""

    def __init__(self):
        super().__init__()
        self.ask_price = None
        self.bid_price = None
        self.next_valid_id = None
        self.order_status = None
        self.error_msg = None
        self.tick_received = False
        self.id_event = threading.Event()
        self._ask_event = threading.Event()
        self._order_submitted = threading.Event()

    def error(self, reqId, *args):
        """错误回调"""
        msg = ' '.join(str(a) for a in args)
        if reqId > 0:
            logger.info(f"ReqId: {reqId} | {msg}")
        # 忽略市场数据农场连接等 informational 错误
        code = args[0] if args else 0
        if isinstance(code, int) and code not in (2104, 2106, 2107, 2157, 399):
            self.error_msg = msg

    def tickPrice(self, reqId, tickType, price, attrib):
        """捕获实时行情价格"""
        # tickType: 1/66 = BID, 2/67 = ASK, 4/68 = Last
        try:
            price = float(price)
        except (TypeError, ValueError):
            return

        if tickType in (2, 67):  # ASK
            self.ask_price = price
            self.tick_received = True
            self._ask_event.set()
            logger.info(f"ASK = {price}")
        elif tickType in (1, 66):  # BID
            self.bid_price = price
            logger.debug(f"BID = {price}")

    def tickSize(self, reqId, tickType, size):
        """捕获实时行情数量 — 无 attrib 参数！"""
        pass

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld,
                    mktCapPrice):
        """订单状态更新"""
        self.order_status = {
            'orderId': orderId,
            'status': status,
            'filled': float(filled),
            'remaining': float(remaining),
            'avgFillPrice': avgFillPrice,
            'lastFillPrice': lastFillPrice,
        }
        if status == 'Filled':
            logger.info(f"FILLED! orderId={orderId}, price={avgFillPrice}, qty={filled}")
        elif status in ('Cancelled', 'Inactive'):
            logger.info(f"Order {status}: orderId={orderId}")

    def openOrder(self, orderId, contract, order, orderState):
        """订单已提交回调"""
        logger.info(f"Order submitted: {contract.symbol} {contract.secType} @ {contract.exchange}")
        self._order_submitted.set()

    def nextValidId(self, orderId):
        """获取下一个有效订单ID"""
        self.next_valid_id = orderId
        logger.info(f"nextValidId = {orderId}")
        self.id_event.set()

    def execDetails(self, reqId, contract, execution):
        """成交详情"""
        logger.info(f"execDetails: {contract.symbol} fill@{execution.price} qty={execution.shares} time={execution.time}")


# ============================================================================
# IB Chase Tester
# ============================================================================
class ChaseTester(EClient):
    """IB Chase-Ask LMT 订单测试器"""

    def __init__(self):
        wrapper = ChaseWrapper()
        EClient.__init__(self, wrapper)
        self.wrapper = wrapper
        self.connected = False
        self._subscriptions = {}  # reqId -> symbol

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def connect_to_ib(self, host='127.0.0.1', port=None, client_id=None):
        """连接到 IB Gateway"""
        port = port or IB_PORT
        client_id = client_id or IB_CLIENT_ID
        logger.info(f"Connecting to IB Gateway {host}:{port} (ClientId: {client_id})...")

        EClient.connect(self, host, port, client_id)
        t = threading.Thread(target=self.run, daemon=True)
        t.start()

        # 等待 nextValidId
        if not self.wrapper.id_event.wait(timeout=15):
            logger.info("ERROR: Did not receive nextValidId within 15s")
            self.do_disconnect()
            return False

        self.connected = True
        logger.info(f"Connected to IB Gateway [nextValidId={self.wrapper.next_valid_id}]")
        return True

    def do_disconnect(self):
        """断开连接"""
        logger.info("Disconnecting from IB...")
        # 取消所有行情订阅
        for reqId in list(self._subscriptions.keys()):
            try:
                self.cancelMktData(reqId)
            except Exception:
                pass
        self._subscriptions.clear()
        time.sleep(0.5)
        EClient.disconnect(self)
        self.connected = False

    # ------------------------------------------------------------------
    # 行情订阅
    # ------------------------------------------------------------------
    def subscribe_gld(self):
        """订阅 GLD OVERNIGHT 实时行情（BID + ASK）"""
        if not self.connected:
            logger.info("ERROR: Not connected to IB")
            return False

        contract = Contract()
        contract.symbol = SYMBOL
        contract.secType = 'STK'
        contract.exchange = 'OVERNIGHT'
        contract.currency = 'USD'

        reqId = 1001
        self._subscriptions[reqId] = SYMBOL
        self.reqMktData(reqId, contract, '', False, False, [])
        logger.info(f"Subscribed to {SYMBOL} OVERNIGHT (reqId={reqId})")
        return True

    def get_current_ask(self, timeout=None):
        """
        获取当前 ASK 价格。
        如果已有缓存则直接返回，否则等待新 tick。
        """
        timeout = timeout or ASK_TIMEOUT
        ask = self.wrapper.ask_price
        if ask and ask > 0:
            return ask

        # 等待新的 ASK tick
        self.wrapper._ask_event.clear()
        if self.wrapper._ask_event.wait(timeout=timeout):
            return self.wrapper.ask_price

        logger.info(f"WARNING: No ASK price received within {timeout}s, using cached value")
        return self.wrapper.ask_price

    # ------------------------------------------------------------------
    # 订单操作
    # ------------------------------------------------------------------
    def place_lmt_sell(self, symbol, quantity, limit_price):
        """
        提交 LMT SELL 订单。
        返回订单 ID。
        """
        if not self.connected:
            logger.info("ERROR: Not connected to IB")
            return None

        # 确保有有效的 orderId
        if self.wrapper.next_valid_id is None:
            logger.info("ERROR: No valid order ID available")
            return None

        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.exchange = 'OVERNIGHT'
        contract.currency = 'USD'

        order = Order()
        order.action = 'SELL'
        order.totalQuantity = quantity
        order.orderType = 'LMT'
        order.lmtPrice = round(limit_price, 2)
        order.tif = 'DAY'
        order.outsideRth = True

        # 卖空需要指定融券来源
        order.shortSaleSlot = 1
        # 填写券商内部仓库（IB 要求）
        order.destinationParams = None

        orderId = self.wrapper.next_valid_id
        self.wrapper.next_valid_id += 1  # 递增，下次用新 ID
        self.wrapper._order_submitted.clear()

        logger.info(f"Placing LMT SELL: {quantity} {symbol} @ {order.lmtPrice}")
        self.placeOrder(orderId, contract, order)

        # 等待 openOrder 回调确认
        if not self.wrapper._order_submitted.wait(timeout=5):
            logger.info("WARNING: openOrder callback not received within 5s")

        return orderId

    def cancel_order(self, orderId):
        """取消指定订单"""
        if orderId is None:
            return
        try:
            self.cancelOrder(orderId, OrderCancel())
            logger.info(f"Cancelled order {orderId}")
        except Exception as e:
            logger.info(f"ERROR cancelling order {orderId}: {e}")

    def is_order_filled(self, orderId):
        """检查订单是否已成交"""
        if self.wrapper.order_status is None:
            return False
        if self.wrapper.order_status.get('orderId') != orderId:
            return False
        return self.wrapper.order_status.get('status') == 'Filled'

    def get_latest_order_status(self, orderId):
        """获取订单最新状态"""
        if self.wrapper.order_status and self.wrapper.order_status.get('orderId') == orderId:
            return self.wrapper.order_status
        return None

    # ------------------------------------------------------------------
    # 主循环：Chase-Ask 追价
    # ------------------------------------------------------------------
    def run_chase(self):
        """
        Chase-Ask 主循环：
        1. 获取 ASK
        2. 挂 LMT SELL @ ASK - OFFSET
        3. 等待 RETRY_INTERVAL 秒检查是否成交
        4. 未成交则取消，重复
        """
        logger.info("=" * 60)
        logger.info(f"START Chase-Ask Test: {SYMBOL} SELL {QUANTITY} @ ASK-{OFFSET}")
        logger.info("=" * 60)

        # 订阅行情
        if not self.subscribe_gld():
            logger.info("FATAL: Failed to subscribe market data")
            return

        # 等待初始 ASK
        initial_ask = self.get_current_ask(timeout=15)
        if not initial_ask or initial_ask <= 0:
            logger.info(f"FATAL: Could not get initial ASK price for {SYMBOL}")
            logger.info("Make sure IB Gateway is running and you have market data subscriptions")
            return

        last_order_id = None
        prev_ask = None

        for attempt in range(1, MAX_RETRIES + 1):
            logger.info("")
            logger.info("-" * 40)
            logger.info(f"Attempt {attempt}/{MAX_RETRIES}")

            # 1. 获取当前 ASK
            ask = self.get_current_ask(timeout=5)
            if not ask or ask <= 0:
                logger.info(f"No ASK price, aborting chase")
                if last_order_id:
                    self.cancel_order(last_order_id)
                break

            # 如果 ASK 没变，稍等再试
            if ask == prev_ask and attempt > 1:
                logger.info(f"ASK unchanged at {ask}, waiting 2s...")
                time.sleep(2)
                ask = self.get_current_ask(timeout=3)
                if not ask or ask <= 0:
                    break

            prev_ask = ask

            # 2. 计算限价
            limit_price = round(ask - OFFSET, 2)
            logger.info(f"ASK = {ask}, Limit Price = {limit_price}")

            # 3. 取消上一笔订单（如果有）
            if last_order_id:
                self.cancel_order(last_order_id)
                time.sleep(0.5)

            # 4. 挂新订单
            order_id = self.place_lmt_sell(SYMBOL, QUANTITY, limit_price)
            if order_id is None:
                logger.info("ERROR: Failed to place order")
                break

            last_order_id = order_id
            logger.info(f"Placed SELL {QUANTITY} {SYMBOL} @ {limit_price} (ASK was {ask})")

            # 5. 等待检查是否成交
            filled = False
            fill_price = None
            for _ in range(int(RETRY_INTERVAL * 10)):  # 每 100ms 检查一次
                time.sleep(0.1)
                if self.is_order_filled(order_id):
                    filled = True
                    fill_price = self.wrapper.order_status.get('avgFillPrice')
                    break

            if filled:
                logger.info("")
                logger.info(f"✅ FILLED at attempt {attempt}! Fill price: {fill_price}")
                logger.info("")
                break
            else:
                status = self.get_latest_order_status(order_id)
                status_str = status['status'] if status else 'unknown'
                logger.info(f"Not filled ({status_str}), cancelled order {order_id}")
                self.cancel_order(order_id)
                last_order_id = None

                # IB 速率限制安全间隔
                if attempt < MAX_RETRIES:
                    logger.info(f"Waiting {MIN_ORDER_INTERVAL}s before next retry...")
                    time.sleep(MIN_ORDER_INTERVAL)

        else:
            # 循环正常结束（未 break）
            logger.info("")
            logger.info(f"Max retries ({MAX_RETRIES}) reached, giving up")
            if last_order_id:
                self.cancel_order(last_order_id)

        logger.info("")
        logger.info("=" * 60)
        logger.info("Chase-Ask test complete")
        logger.info("=" * 60)


# ============================================================================
# 入口
# ============================================================================
def main():
    """主入口"""
    print("=" * 60)
    print("IB Chase-Ask LMT 订单测试程序")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"标的: {SYMBOL} | 数量: {QUANTITY} | 偏移: {OFFSET}")
    print(f"最大追价次数: {MAX_RETRIES} | 检查间隔: {RETRY_INTERVAL}s")
    print(f"IB 端口: {IB_PORT} | ClientId: {IB_CLIENT_ID}")
    print()

    tester = ChaseTester()

    try:
        # 1. 连接
        if not tester.connect_to_ib(port=IB_PORT, client_id=IB_CLIENT_ID):
            logger.info("FATAL: Connection to IB Gateway failed")
            return

        # 2. 运行 Chase-Ask
        tester.run_chase()

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    except Exception as e:
        logger.info(f"FATAL: Unexpected error: {e}", exc_info=True)
    finally:
        # 3. 清理
        tester.do_disconnect()
        logger.info("Disconnected from IB Gateway")


if __name__ == '__main__':
    main()
