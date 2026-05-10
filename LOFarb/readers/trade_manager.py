import os
import sys
import time
import socket

# 导入本地敏感配置
try:
    from config_local import GJS_ACCOUNT
except ImportError:
    print("WARNING: config_local.py 不存在，请复制 config_local.example.py 并填入真实账号")
    GJS_ACCOUNT = None

class TradeManager:
    """A股/LOF统一交易接口管理器"""
    def __init__(self):
        self.tdx_available = False
        self.tq = None
        self.tqconst = None
        self.tdx_account_id = None
        
        self.xtquant_available = False
        self.xt_trader = None
        self.xt_account = None
        self.xtconstant = None

        # 启动时自动初始化可用通道
        self._init_tdx()
        self._init_guojin_qmt()

    def _init_tdx(self):
        try:
            # 新版 tqcenter 路径（请根据实际路径修改）
            tdx_api_paths = [
                r'D:\new_tdx_test\PYPlugins\user',  # 新版路径
                r'D:\new_tdx64\PYPlugins\user',      # 旧版路径备选
            ]
            
            for tdx_api_path in tdx_api_paths:
                if os.path.exists(tdx_api_path) and tdx_api_path not in sys.path:
                    sys.path.insert(0, tdx_api_path)
            
            from tqcenter import tq, tqconst
            self.tq = tq
            self.tqconst = tqconst
            
            # 初始化并获取账户句柄
            tq.initialize(__file__)
            self.tdx_account_id = tq.stock_account()
            
            if self.tdx_account_id and self.tdx_account_id > 0:
                self.tdx_available = True
                print(f"SUCCESS: [TradeManager] 已挂载【通达信】交易通道 (账户句柄: {self.tdx_account_id})")
            else:
                print("WARNING: [TradeManager] 通达信账户句柄获取失败")
                
        except ImportError as e:
            print(f"INFO: [TradeManager] 未检测到新版通达信环境(tqcenter): {e}")
        except Exception as e:
            print(f"INFO: [TradeManager] 通达信模块跳过加载: {e}")

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
                self.xt_account = StockAccount(GJS_ACCOUNT)
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
                # 转换买卖方向: BUY=0(买入), SELL=1(卖出)
                order_type = self.tqconst.STOCK_BUY if action == 'BUY' else self.tqconst.STOCK_SELL
                
                # 调用通达信下单接口
                result = self.tq.order_stock(
                    account_id=self.tdx_account_id,
                    stock_code=symbol,        # 动态基金代码，如 "162411.SZ"
                    order_type=order_type,
                    order_volume=int(volume),
                    price_type=self.tqconst.PRICE_MY,  # 限价单
                    price=float(price)
                )
                
                # 解析返回结果
                error_id = result.get('ErrorId', -1)
                msg = result.get('Msg', '未知')
                
                if result.get('Value') in [1, 2] or error_id == 0:
                    wtbh = result.get('Wtbh', '')
                    return True, f"通达信下单成功，委托编号: {wtbh}"
                else:
                    return False, f"通达信下单失败: {msg}"
                    
            except Exception as e:
                return False, f"通达信下单异常: {str(e)}"
                
        return False, f"未知的通道标识: {broker}"