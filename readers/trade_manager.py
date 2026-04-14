import os
import sys
import time
import socket

class TradeManager:
    """A股/LOF统一交易接口管理器"""
    def __init__(self):
        self.tdx_available = False
        self.tq = None
        
        self.xtquant_available = False
        self.xt_trader = None
        self.xt_account = None
        self.xtconstant = None

        # 启动时自动初始化可用通道
        self._init_tdx()
        self._init_guojin_qmt()

    def _init_tdx(self):
        try:
            tdx_api_path = r'D:\new_tdx64\PYPlugins\user'
            if os.path.exists(tdx_api_path) and tdx_api_path not in sys.path:
                sys.path.append(tdx_api_path)
            from tqcenter import tq
            self.tq = tq
            self.tdx_available = True
            print("SUCCESS: [TradeManager] 已挂载【通达信】交易与极速行情模块")
        except Exception as e:
            print("INFO: [TradeManager] 未检测到通达信环境，已跳过")

    def _init_guojin_qmt(self):
        try:
            # ====================== 国金 QMT 路径与环境配置 ======================
            QMT_INSTALL_PATH = r"D:\GJQMT"
            if os.path.exists(QMT_INSTALL_PATH):
                if QMT_INSTALL_PATH not in sys.path:
                    sys.path.append(QMT_INSTALL_PATH)
                    sys.path.append(os.path.join(QMT_INSTALL_PATH, "lib"))
                    sys.path.append(os.path.join(QMT_INSTALL_PATH, "bin.x64"))
                    sys.path.append(os.path.join(QMT_INSTALL_PATH, "bin.x64", "Lib", "site-packages"))
                
                from xtquant import xttrader, xtconstant
                from xtquant.xttype import StockAccount
                
                qmt_path = os.path.join(QMT_INSTALL_PATH, 'userdata_mini')
                session_id = int(time.time())
                self.xt_trader = xttrader.XtQuantTrader(qmt_path, session_id)
                self.xt_account = StockAccount('66655836')
                self.xtconstant = xtconstant
                
                self.xt_trader.start()
                connect_result = self.xt_trader.connect()
                if connect_result == 0:
                    self.xt_trader.subscribe(self.xt_account)
                    self.xtquant_available = True
                    print(f"SUCCESS: [TradeManager] 已挂载【国金MiniQMT】原生直连通道 (账号:{self.xt_account.account_id})")
                else:
                    print(f"WARNING: [TradeManager] 国金QMT客户端连接失败 (错误码: {connect_result})")
        except Exception as e:
            print(f"INFO: [TradeManager] 国金QMT模块跳过加载: {e}")

    def send_order(self, broker, action, symbol, volume, price):
        """暴露给外部的统一路由函数"""
        if broker == 'yinhe_qmt':
            try:
                cmd_str = f"{action},{symbol},{volume},{price}\n"
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(2.0)
                client.connect(('127.0.0.1', 8888))
                client.sendall(cmd_str.encode('utf-8'))
                response = client.recv(1024).decode('utf-8')
                client.close()
                return True, f"银河QMT(Socket)返回: {response}"
            except ConnectionRefusedError:
                return False, "银河QMT未开启或 8888 桥接策略未运行"
            except Exception as e:
                return False, f"银河QMT下单异常: {str(e)}"
                
        elif broker == 'guojin_qmt':
            if not self.xtquant_available: return False, "国金 QMT 底层环境未就绪"
            try:
                order_type = self.xtconstant.STOCK_BUY if action == 'BUY' else self.xtconstant.STOCK_SELL
                seq = self.xt_trader.order_stock(self.xt_account, symbol, order_type, volume, self.xtconstant.FIX_PRICE, price, 'LOF_Arb', 'Strategy')
                return True, f"国金QMT(原生)委托成功, 编号: {seq}"
            except Exception as e:
                return False, f"国金QMT下单异常: {str(e)}"
                
        elif broker == 'tdx':
            if not self.tdx_available: return False, "通达信接口未就绪"
            try:
                direction = 0 if action == 'BUY' else 1
                res = self.tq.send_order(stock_code=symbol, price=price, volume=volume, direction=direction)
                return True, f"通达信返回: {res}"
            except Exception as e:
                return False, f"通达信下单异常: {str(e)}"
                
        return False, f"未知的通道标识: {broker}"