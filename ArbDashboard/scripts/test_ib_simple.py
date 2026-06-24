from ibapi.client import EClient
from ibapi.wrapper import EWrapper
import threading, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class TestApp(EWrapper, EClient):
    def __init__(self):
        EClient.__init__(self, self)
        self.done = False
    def nextValidId(self, orderId):
        print(f'OK: nextValidId = {orderId}')
        self.done = True
    def error(self, reqId, *args):
        if len(args) >= 2:
            print(f'Error: code={args[0]} msg={args[1]}')

app = TestApp()
app.connect('127.0.0.1', 4001, 7777)
t = threading.Thread(target=app.run, daemon=True)
t.start()
for i in range(10):
    time.sleep(1)
    if app.done:
        print('Connection OK!')
        app.disconnect()
        sys.exit(0)
print('TIMEOUT: no nextValidId received')
app.disconnect()
