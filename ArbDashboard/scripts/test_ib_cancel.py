from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import threading, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class CancelApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.done = False
    def nextValidId(self, orderId):
        print(f'nextValidId: {orderId}')
        self.done = True
    def error(self, reqId, *args):
        msg = ' '.join(str(a) for a in args)
        print(f'[IB] ReqId:{reqId} {msg}')
    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice,
                    permId, parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):
        print(f'Order {orderId}: {status} filled={filled} remaining={remaining}')

app = CancelApp()
app.connect('127.0.0.1', 4001, 8888)
t = threading.Thread(target=app.run, daemon=True)
t.start()

for i in range(5):
    time.sleep(1)
    if app.done:
        break

print('Cancelling order 2...')
app.cancelOrder(2, '')
time.sleep(3)
app.disconnect()
print('Done')
