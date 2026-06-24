# -*- coding: utf-8 -*-
"""
IB REL 订单测试程序
==================
测试 IB REL (Relative) 订单类型，用于做空时自动设置在卖一价下方1分钱。

警告：这是实盘账户测试！
- 请确认你的 IB 账户已开启交易权限
- 请确认你有足够的融券额度
- 请确认当前时间是美盘夜盘时段（22:00-02:00 ET）

使用方法：
  python test_ib_rel_order.py

预期行为：
  - 获取 GLD 当前卖一价（ask）
  - 用 REL 订单做空 2 股 GLD
  - REL 价格 = ask - 0.01（即比卖一低1分钱）
  - 观察订单是否成功提交
"""

import sys
import os
import time
import random
import threading
from datetime import datetime

# 屏蔽 IBAPI 底层的 INFO 级别刷屏日志
import logging
logging.getLogger('ibapi.client').setLevel(logging.WARNING)
logging.getLogger('ibapi.wrapper').setLevel(logging.WARNING)

import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from ibapi.client import EClient
    from ibapi.wrapper import EWrapper
    from ibapi.contract import Contract
    from ibapi.order import Order
except ImportError:
    print("ibapi not installed. Run: pip install ibapi")
    sys.exit(1)


class RELTestWrapper(EWrapper):
    """订单结果回调"""
    
    def __init__(self):
        super().__init__()
        self.order_status = None
        self.order_id = None
        self.error_msg = None
        self.ask_price = None
        self.bid_price = None
        self.next_valid_id = None
        self.open_order_done = False
        self.tick_received = False
        self.id_event = threading.Event()
    
    def error(self, reqId, *args):
        """错误回调"""
        msg = ' '.join(str(a) for a in args)
        if reqId > 0:
            print(f"\n[IB] ReqId: {reqId} | {msg}")
        # 关键：399 是委托单警告(非错误)，2104/2106/2107/2157 是数据农场状态
        code = args[0] if args else 0
        if isinstance(code, int) and code not in (2104, 2106, 2107, 2157, 399):
            self.error_msg = msg
    
    def tickPrice(self, reqId, tickType, price, attrib):
        """捕获实时行情价格"""
        # IB API tickType 映射:
        #   1 = BID (实时买一), 2 = ASK (实时卖一), 4 = Last (实时最新)
        #   66 = BID (延迟买一), 67 = ASK (延迟卖一), 68 = Last (延迟最新)
        if tickType in [2, 67]:  # ASK
            self.ask_price = price
            self.tick_received = True
            print(f"   📈 收到实时报价: ASK = {price}")
        elif tickType in [1, 66]:  # BID
            self.bid_price = price
            print(f"   📉 收到实时报价: BID = {price}")
    
    def tickSize(self, reqId, tickType, size):
        """捕获实时行情数量"""
        pass
    
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, 
                    permId, parentId, lastFillPrice, clientId, whyHeld, 
                    mktCapPrice):
        """订单状态更新"""
        self.order_id = orderId
        self.order_status = {
            'orderId': orderId,
            'status': status,
            'filled': filled,
            'remaining': remaining,
            'avgFillPrice': avgFillPrice,
            'lastFillPrice': lastFillPrice,
        }
        print(f"\n📊 订单状态: {status}")
        print(f"   已成交: {filled}, 剩余: {remaining}")
        if avgFillPrice:
            print(f"   平均成交价: {avgFillPrice}")
    
    def nextValidId(self, orderId):
        """获取下一个有效订单ID"""
        self.next_valid_id = orderId
        print(f"✅ 下一个有效订单ID: {orderId}")
        self.id_event.set()
    
    def openOrder(self, orderId, contract, order, orderState):
        """订单已提交"""
        print(f"\n📋 订单已提交:")
        print(f"   订单ID: {orderId}")
        print(f"   合约: {contract.symbol} {contract.secType} {contract.exchange}")
        print(f"   动作: {order.action} {order.totalQuantity}股")
        print(f"   类型: {order.orderType}")
        if hasattr(order, 'relativeDelay'):
            print(f"   相对延迟: {order.relativeDelay}")
        print(f"   状态: {orderState.status}")
        self.open_order_done = True
    
    def execDetails(self, reqId, contract, execution):
        """成交详情"""
        print(f"\n💰 成交详情:")
        print(f"   执行价格: {execution.price}")
        print(f"   执行数量: {execution.shares}")
        print(f"   执行时间: {execution.time}")
        print(f"   交易所: {execution.exchange}")


class RELTester(EClient):
    """IB REL 订单测试器"""
    
    def __init__(self):
        wrapper = RELTestWrapper()
        EClient.__init__(self, wrapper)
        self.wrapper = wrapper
        self.next_valid_id = None
        self.open_order_done = False
        self.ask_price = None
        self.done = False
    
    def connect_to_ib(self, host='127.0.0.1', port=4001, client_id=None):
        """连接到 IB Gateway"""
        if client_id is None:
            client_id = random.randint(10000, 99999)
        print(f"\n[CONNECT] {host}:{port} (ClientId: {client_id})")
        EClient.connect(self, host, port, client_id)
        # 必须启动消息处理线程，否则收不到任何回调
        t = threading.Thread(target=self.run, daemon=True)
        t.start()
        return True
    
    def _is_us_night_session(self):
        """判断当前是否为美盘夜盘时段 (20:00 - 03:50 ET)"""
        now = datetime.now()
        # 北京时间转美东时间 (UTC-5)，夏令时 UTC-4
        # 简单估算：北京 20:00 = ET 07:00 (冬) 或 08:00 (夏)
        # 实际上美盘夜盘是 ET 20:00 - 03:50，对应北京时间 08:00 - 15:50 (冬) 或 09:00 - 16:50 (夏)
        # 这里用北京时间判断：08:00-15:50 为夜盘时段
        hour = now.hour
        minute = now.minute
        total_minutes = hour * 60 + minute
        start_minutes = 8 * 60  # 08:00
        end_minutes = 15 * 60 + 50  # 15:50
        return start_minutes <= total_minutes <= end_minutes
    
    def get_ask_price(self, symbol='XOP', timeout=5):
        """获取当前卖一价"""
        print(f"\n📈 获取 {symbol} 卖一价...")
        
        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.exchange = 'OVERNIGHT'  # 与程序3一致，夜盘免费行情
        contract.currency = 'USD'
        
        # 请求实时行情
        self.reqMktData(1001, contract, '', False, False, [])
        
        # 等待数据（夜盘行情可能需要更长时间建立连接）
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(0.5)
            if self.wrapper.ask_price:
                print(f"   卖一价: {self.wrapper.ask_price}")
                break
        
        if not self.wrapper.ask_price:
            print(f"   [WARN] 未能获取到 {symbol} 的卖一价，使用默认测试值 152.85")
            self.wrapper.ask_price = 152.85
        
        return self.wrapper.ask_price
    
    def place_rel_order(self, symbol='XOP', action='SELL', quantity=10, 
                        offset=0.01, timeout=10):
        """
        提交 REL 订单
        
        REL (Relative) 订单类型：
        - 对于卖出订单：价格 = 卖一价 - offset
        - 对于买入订单：价格 = 买一价 + offset
        
        参数：
        - symbol: 股票代码
        - action: 'BUY' 或 'SELL'
        - quantity: 数量
        - offset: 偏移量（美元）
        - timeout: 等待响应超时
        """
        ask_price = self.get_ask_price(symbol, timeout=10)
        
        if action == 'SELL':
            # 卖空：价格 = 卖一价 - offset
            lmt_price = ask_price - offset
            print(f"\n📤 提交 REL 订单:")
            print(f"   股票代码: {symbol}")
            print(f"   动作: {action} {quantity}股")
            print(f"   卖一价: {ask_price}")
            print(f"   偏移量: {offset}")
            print(f"   限价: {lmt_price}")
        else:
            lmt_price = ask_price + offset
            print(f"\n📤 提交 REL 订单:")
            print(f"   股票代码: {symbol}")
            print(f"   动作: {action} {quantity}股")
            print(f"   买一价: {ask_price}")
            print(f"   偏移量: {offset}")
            print(f"   限价: {lmt_price}")
        
        # 构建合约
        contract = Contract()
        contract.symbol = symbol
        contract.secType = 'STK'
        contract.currency = 'USD'
        
        # 智能判断交易所：夜盘用 OVERNIGHT，盘前/盘后用 SMART
        # 测试：尝试 OVERNIGHT 交易所
        contract.exchange = "OVERNIGHT"
        print(f"   交易所: OVERNIGHT")
        
        # 构建订单
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = 'REL'  # 关键：使用 REL 订单类型
        order.lmtPriceOffset = offset  # REL 订单的偏移量
        order.tif = "DAY"
        order.outsideRth = True  # 允许盘外交易（盘前/盘后/夜盘）
        
        # 如果是卖空，需要指定融券来源
        if action == 'SELL':
            order.shortSaleSlot = 1
        
        # 提交订单
        self.placeOrder(self.wrapper.next_valid_id, contract, order)
        print(f"   订单已提交，等待响应...")
        
        # 等待响应
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(0.1)
            if self.wrapper.open_order_done:
                break
        
        # 打印结果
        if self.wrapper.order_status:
            print(f"\n📊 订单状态: {self.wrapper.order_status}")
        
        if self.wrapper.error_msg:
            print(f"\n❌ 订单提交失败: {self.wrapper.error_msg}")
            return False
        
        return True
    
    def do_disconnect(self):
        """断开连接"""
        print("\n[DISCONNECT]")
        EClient.disconnect(self)


def main():
    """主函数"""
    print("=" * 60)
    print("IB REL 订单测试程序")
    print("=" * 60)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # 创建测试器
    tester = RELTester()
    
    # 连接 IB
    if not tester.connect_to_ib(host='127.0.0.1', port=4001, client_id=8888):
        print("❌ 连接失败，退出")
        return
    
    # 等待 nextValidId
    print("\n[WAIT] Waiting for nextValidId...")
    if not tester.wrapper.id_event.wait(timeout=10):
        print("[FAIL] Did not receive nextValidId")
        print(f"[DEBUG] Wrapper state: ask={tester.wrapper.ask_price}, bid={tester.wrapper.bid_price}, error={tester.wrapper.error_msg}")
        tester.do_disconnect()
        return
    print(f"[OK] nextValidId = {tester.wrapper.next_valid_id}")
    
    # 等待 serverVersion 初始化
    time.sleep(2)
    sv = tester.serverVersion()
    print(f"[INFO] Server version: {sv}")
    
    # 提交 REL 订单
    print("\n" + "=" * 60)
    print("提交 REL 订单")
    print("=" * 60)
    
    success = tester.place_rel_order(
        symbol='GLD',
        action='SELL',
        quantity=2,
        offset=0.01
    )
    
    if success:
        print("\n✅ 订单提交成功！")
    else:
        print("\n❌ 订单提交失败！")
    
    # 等待订单执行，然后取消
    print("\n[WAIT] 等待 30 秒后取消订单...")
    time.sleep(30)
    from ibapi.order_cancel import OrderCancel
    tester.cancelOrder(2, OrderCancel())
    print("[CANCEL] 已发送取消请求")
    
    # 断开连接
    tester.do_disconnect()
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
