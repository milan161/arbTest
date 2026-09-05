import os
import sys
import time
import socket
import struct
import threading
import json

# Ensure LOFarb directory is in sys.path so we can find account_private.py when imported from elsewhere
_tm_dir = os.path.dirname(os.path.abspath(__file__))
_lof_dir = os.path.normpath(os.path.join(_tm_dir, "..", "..", "LOFarb"))
if os.path.exists(_lof_dir) and _lof_dir not in sys.path:
    sys.path.append(_lof_dir)

import logging
logger = logging.getLogger(__name__)

# 优先尝试从 arbcore.config 导入
try:
    from arbcore.config.account_private import GJS_ACCOUNT
except ImportError:
    try:
        # 兼容旧路径
        from account_private import GJS_ACCOUNT
    except ImportError:
        print("WARNING: account_private.py 不存在，请复制 account_example.py 并填入真实账号")
        GJS_ACCOUNT = None

def _enable_tcp_keepalive(sock, idle: int = 5, interval: int = 2) -> None:
    """[2026-09-03] 启用 TCP keepalive，使半开连接（如对端 QMT/ServerV5 进程重启）能在数秒内
    被探测并断开，从而触发 _deal_listener_loop 自动重连，避免 listener 永久僵死导致 Monitor 失明
    （本次 164701 成交后未对冲的根因：QMT 重启 → 旧连接半开卡死 → ORDER/DEAL 广播全丢）。

    - Windows: SO_KEEPALIVE + SIO_KEEPALIVE_VALS(idle/interval 毫秒)
    - Linux:   SO_KEEPALIVE + TCP_KEEPIDLE/TCP_KEEPINTVL/TCP_KEEPCNT
    任何一步失败都静默跳过（至少保留系统默认 keepalive），绝不抛异常影响连接建立。
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError:
        return
    if os.name == 'nt':
        # SIO_KEEPALIVE_VALS = _WSAIOW(IOC_VENDOR, 4) = 0x98000004
        # ⚠️ Windows socket.ioctl 要的是 3 元组 (onoff, keepalivetime_ms, keepaliveinterval_ms)，
        #    不是 struct.pack 出来的 bytes（旧写法传 bytes 抛 TypeError，且下面 except 没接住 → 打死 listener）。
        SIO_KEEPALIVE_VALS = 0x98000004
        try:
            sock.ioctl(SIO_KEEPALIVE_VALS, (1, idle * 1000, interval * 1000))
        except Exception:
            pass   # keepalive 失败绝不致命：兜底用系统默认，异常不外冒
    else:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, interval)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except (OSError, AttributeError):
            pass


class TradeManager:
    """A股/LOF统一交易接口管理器"""
    def __init__(self):
        self.tdx_available = False
        self.tq = None
        self.tqconst = None
        self.tdx_account_id = None
        self.last_tdx_order_id = ''   # [2026-09-02] 最近一次 tdx 下单返回的委托编号(wtbh)，供 monitor 撤单/成交追踪
        
        self.xtquant_available = False
        self.xt_trader = None
        self.xt_account = None
        self.xtconstant = None

        # [AI-2026-07-17] 银河 QMT 成交监听（方案 A：实时广播 + 方案 B：轮询保底）
        self._deal_listeners = []      # list[callable(code, vol, price)]
        # [AI-2026-07-21] 订单状态回调（ORDER 广播），供 SmartMonitor 捕获 QMT sysid 用于撤单
        self._order_listeners = []     # list[callable(code, sysid, status)]
        self._listener_running = False
        self._listener_thread = None
        self._listener_sock = None
        # [H1 2026-09-03] 回传通道健康自检：PING 心跳 + 最近回包时间戳，供 Monitor 区分"没成交 vs 收不到成交"
        self._listener_alive = False
        self._listener_last_rx = 0.0
        self.LISTENER_PING_INTERVAL = 5.0      # 静默 5s 主动发一次 PING（活服务端会回 PONG）
        self.LISTENER_STALE_SECONDS = 20.0    # 连续 20s 无任何回包 → 判定半开/僵尸连接 → 强制重连

        # [2026-09-02 tdx] 通达信交易回调
        self._tdx_trade_listeners = []   # list[callable(code, status, vol, price)] — WTSTATUS_ALLCJ/PARTCJ
        self._tdx_order_listeners = []   # list[callable(code, order_id, status)] — ORDER 广播
        self._tdx_order_id_map = {}      # order_id -> fund_code (用于回调时反向查基金代码)

        # [2026-09-02] 通达信交易通道改为按需连接：启动时不再硬连，
        # 避免后端启动时通达信交易软件未开导致 tdx_available 被永久写死为 False。
        # 由前端「通达信」按键触发 /api/system/reconnect_tdx 调用 _init_tdx() 才连。
        # 【重要】_init_tdx() 只允许调用一次：tqcenter 使用 ctypes 加载 C++ DLL，
        # 多次调用会导致 DLL 内部状态损坏，引发 [WinError 1] 函数不正确。
        self._tdx_initialized = False
        # [2026-09-03 方案A] 仅护并发重入的临时标志；失败不再置 _tdx_initialized，可点「通达信」重连重试
        self._tdx_inflight = False
        # 国金QMT旧逻辑保留后台初始化。
        threading.Thread(target=self._init_guojin_qmt, daemon=True).start()

    def _on_tdx_trade_notify(self, data_str):
        """[2026-09-02] 通达信成交/撤单回调处理。
        data_str 是 JSON 字符串，包含委托状态变化。
        解析后触发 _tdx_trade_listeners (code, status, vol, price)。"""
        try:
            import json
            data = json.loads(data_str)
            # 常见字段: StockCode, OrderId, OrderStatus, DealVol, DealPrice 等
            code = data.get('StockCode', '')
            order_id = data.get('OrderSysno', '') or data.get('OrderId', '')
            status = data.get('OrderStatus', 0)  # 1=未成交 2=部分成交 3=全部成交 5=已撤单
            deal_vol = int(data.get('DealVolume', 0) or 0)
            deal_price = float(data.get('DealPrice', 0) or 0)

            # 反向查基金代码
            fund_code = self._tdx_order_id_map.get(order_id, code.split('.')[0])

            logger.info(f"[TradeManager] tdx 回调: code={fund_code} order_id={order_id} status={status} deal_vol={deal_vol} price={deal_price}")

            # 触发订单状态监听
            for cb in self._tdx_order_listeners[:]:
                try:
                    cb(fund_code, order_id, status)
                except Exception as e:
                    logger.warning(f"[TradeManager] tdx order listener 异常: {e}")

            # 触发成交监听 (部分成交或全部成交)
            if status in (2, 3) and deal_vol > 0:
                for cb in self._tdx_trade_listeners[:]:
                    try:
                        cb(fund_code, deal_vol, deal_price)
                    except Exception as e:
                        logger.warning(f"[TradeManager] tdx deal listener 异常: {e}")

            # 更新订单 ID 映射 (用于后续撤单)
            if order_id and code:
                self._tdx_order_id_map[order_id] = fund_code

        except Exception as e:
            logger.warning(f"[TradeManager] tdx 回调解析异常: {e}")

    def _init_tdx(self):
        """[2026-09-03 方案A 修复] 按需初始化通达信交易通道。

        幂等口径修正：旧实现"一进门就把 _tdx_initialized=True 写死"，在 tq.initialize/
        stock_account 尚未真正成功时就永久锁定，之后点「通达信」重连被早退挡回、永不重试 →
        tq 对象在但内部连接路径为空 → 下单/查持仓全抛"连接路径为空"。
        现改为【双确认成功后】(tq.initialize 成功 + stock_account()>0) 才置 _tdx_initialized=True；
        任一失败则 tdx_available=False 且不锁死，用户可点「通达信」按键重连重试。
        并发保护：_tdx_inflight 只挡同时重入（规避 ctypes 重复加载 DLL 引发 [WinError 1]），
        不再充当"永久只准一次"的标志。"""
        if getattr(self, '_tdx_initialized', False):
            logger.info("[TradeManager] 通达信已成功初始化，跳过重复初始化")
            return
        if getattr(self, '_tdx_inflight', False):
            logger.info("[TradeManager] 通达信初始化进行中，跳过并发重入")
            return
        self._tdx_inflight = True
        try:
            # 仅使用新版 tqcenter 路径
            tdx_api_path = r'D:\new_tdx_test\PYPlugins\user'

            # [2026-09-03 方案A] tqcenter(C++ DLL) 只在手上还没有模块时加载一次：
            # 重连重试时复用已 import 的 tq，只重跑 initialize/stock_account，
            # 避免反复 del sys.modules + 重新 ctypes 加载 DLL 引发 [WinError 1]。
            if self.tq is None:
                # 清除旧版缓存
                if r'D:\new_tdx64\PYPlugins\user' in sys.path:
                    sys.path.remove(r'D:\new_tdx64\PYPlugins\user')
                sys.path_importer_cache.clear()
                if 'tqcenter' in sys.modules:
                    del sys.modules['tqcenter']

                if os.path.exists(tdx_api_path):
                    sys.path.insert(0, tdx_api_path)

                from tqcenter import tq, tqconst
                self.tq = tq
                self.tqconst = tqconst
            else:
                tq = self.tq
                tqconst = self.tqconst

            # 初始化并获取账户句柄
            tdx_plugin_path = os.path.join(tdx_api_path, 'tqcenter.py')
            tq.initialize(tdx_plugin_path)
            self.tdx_account_id = tq.stock_account()

            if self.tdx_account_id and self.tdx_account_id > 0:
                self.tdx_available = True
                # [2026-09-03 修正] 本版 tqcenter 无 set_trade_notify_callback(2026-09-02 误用了不存在的 API,
                # 抛 AttributeError 反把整个交易通道初始化拖垮 → tdx_available 被置 False)。order_stock/
                # cancel_order_stock/query_stock_orders/query_stock_positions 均可用；成交/委托无推送回调，
                # 改由轮询兜底。故仅当该版本确实提供此方法时才注册，缺失则跳过、不影响 tdx 下单能力。
                if callable(getattr(tq, 'set_trade_notify_callback', None)):
                    try:
                        tq.set_trade_notify_callback(self._on_tdx_trade_notify)
                    except Exception as e:
                        logger.warning(f"[TradeManager] tdx 成交回调注册失败(忽略，改轮询兜底): {e}")
                else:
                    logger.info("[TradeManager] tqcenter 无成交推送回调 API，tdx 成交/委托判定走轮询兜底")
                # ★ 全部成功后才永久锁定（放在块尾）：避免后续任何一步抛错却已锁死、连重连都救不回
                self._tdx_initialized = True
                logger.info(f"{'='*50}\n[TradeManager] 已挂载【通达信】交易通道 (账户句柄: {self.tdx_account_id})\n{'='*50}")
            else:
                self.tdx_available = False
                logger.warning("[TradeManager] 通达信账户句柄获取失败（可点「通达信」按键重连重试）")

        except ImportError as e:
            self.tdx_available = False
            logger.warning(f"[TradeManager] 未检测到新版通达信环境(tqcenter): {e}")
        except Exception as e:
            self.tdx_available = False
            logger.warning(f"[TradeManager] 通达信初始化失败（可点「通达信」按键重连重试）: {e}")
        finally:
            self._tdx_inflight = False

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
                    logger.info(f"[TradeManager] 已挂载【国金MiniQMT】原生直连通道 (账号:{self.xt_account.account_id})")
                else:
                    logger.warning(f"[TradeManager] 国金QMT客户端连接失败 (错误码: {connect_result})")
        except Exception as e:
            logger.info(f"[TradeManager] 国金QMT模块跳过加载: {e}")

    def _tdx_symbol(self, code) -> str:
        """[2026-09-03 修正] tdx(tqcenter) 下单/撤单要求 '代码.市场' 格式(如 162411.SZ)，
        裸 6 位码会被 check_stock_code_format 拒绝 → order_stock 返回 -1。此处仅在缺后缀时补：
        5/6/9 开头 .SH、4/8 开头 .BJ、其余(含 16xxxx/0/3) .SZ。已带后缀则原样返回。"""
        c = str(code).strip()
        if not c or '.' in c:
            return c
        head = c[:1]
        if head in ('5', '6', '9'):
            return c + '.SH'
        if head in ('4', '8'):
            return c + '.BJ'
        return c + '.SZ'

    def send_order(self, broker, action, symbol, volume, price, account_id=None):
        """暴露给外部的统一路由函数"""
        if broker == 'yinhe_qmt':
            # Try-read-OK 模式（v2 - 2026-06-15）
            # 连接 Test_Yinhe_qmt_ServerV5.py (8888)，主线程队列架构。
            # 服务端秒回 OK（入队后立即返回），所以发送后尝试读取回执。
            # 超时或失败时降级为 fire-and-forget（前端不卡死），兼顾可靠性与健壮性。
            try:
                if account_id:
                    cmd_str = f"{action},{symbol},{volume},{price},{account_id}\n"
                else:
                    cmd_str = f"{action},{symbol},{volume},{price}\n"
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(3.0)  # 3 秒内连不上就放弃
                client.connect(('127.0.0.1', 8888))
                client.sendall(cmd_str.encode('utf-8'))

                # 尝试读回执（1.5s 超时），读到 OK 可确认识别已送达引擎
                try:
                    client.settimeout(1.5)
                    resp = client.recv(1024).decode('utf-8').strip()
                    if resp == 'OK':
                        client.close()
                        logger.info(f"[TradeManager] 银河QMT下单 {action} {symbol} {volume}@{price} → 回执OK")
                        return True, "银河QMT下单成功 (回执确认)"
                    client.close()
                    logger.info(f"[TradeManager] 银河QMT下单 {action} {symbol} {volume}@{price} → 已发送(回执:{resp})")
                    return True, f"银河QMT下单指令已发送 (回执: {resp})"
                except socket.timeout:
                    client.close()
                    logger.info(f"[TradeManager] 银河QMT下单 {action} {symbol} {volume}@{price} → 已发送(fire-and-forget)")
                    return True, "银河QMT下单指令已发送 (fire-and-forget)"
                except Exception:
                    client.close()
                    logger.info(f"[TradeManager] 银河QMT下单 {action} {symbol} {volume}@{price} → 已发送(读回执异常)")
                    return True, "银河QMT下单指令已发送"

            except ConnectionRefusedError:
                # 端口被占但连接被拒 → 可能全是僵尸线程，建议重启 QMT
                return False, "银河QMT未开启或 8888 桥接策略未运行（如多次重载策略后出现此错误，请重启QMT）"
            except Exception as e:
                return False, f"银河QMT下单异常: {str(e)}"
                
        elif broker == 'guojin_qmt':
            if not self.xtquant_available: return False, "国金QMT接口未就绪"
            try:
                # 转换买卖方向
                order_type = self.xtconstant.STOCK_BUY if action == 'BUY' else self.xtconstant.STOCK_SELL
                
                # 调用国金下单接口
                order_id = self.xt_trader.order_stock(
                    self.xt_account, 
                    symbol, 
                    order_type, 
                    int(volume), 
                    self.xtconstant.FIX_PRICE, 
                    float(price), 
                    "LOF_Arb", 
                    "API下单"
                )
                if order_id != -1:
                    return True, f"国金QMT下单成功，委托编号: {order_id}"
                else:
                    return False, "国金QMT下单失败（返回编号 -1）"
            except Exception as e:
                return False, f"国金QMT下单异常: {e}"
                
        elif broker == 'tdx':
            if not self.tdx_available: return False, "通达信接口未就绪"
            symbol = self._tdx_symbol(symbol)   # [2026-09-03] tdx 要求 '代码.市场'，裸码会被拒(-1)
            try:
                # 转换买卖方向: BUY=0(买入), SELL=1(卖出)
                order_type = self.tqconst.STOCK_BUY if action == 'BUY' else self.tqconst.STOCK_SELL

                # [2026-09-02] 诊断：打印调用参数，便于排查 -1 原因
                logger.info(f"[TradeManager] tq.order_stock 调用: acc={self.tdx_account_id} code={symbol} type={order_type} vol={int(volume)} price={float(price)}")
                result = self.tq.order_stock(
                    account_id=self.tdx_account_id,
                    stock_code=symbol,        # 规范化后如 "162411.SZ"
                    order_type=order_type,
                    order_volume=int(volume),
                    price_type=self.tqconst.PRICE_MY,  # 限价单
                    price=float(price)
                )
                # [2026-09-02] tq.order_stock 失败时返回 int(-1) 而非 dict，先判再 .get()
                if result is None or (isinstance(result, int) and result <= 0):
                    logger.warning(f"[TradeManager] tq.order_stock 返回 {result!r}（参数: acc={self.tdx_account_id} code={symbol} type={order_type} vol={int(volume)} price={float(price)}）")
                    return False, f"通达信下单返回异常({result})，请检查账户/价格/数量"
                if not isinstance(result, dict):
                    return False, f"通达信下单返回非dict({type(result).__name__}): {result!r}"

                # 解析返回结果
                error_id = result.get('ErrorId', -1)
                msg = result.get('Msg', '未知')

                if result.get('Value') in [1, 2] or error_id == 0:
                    wtbh = result.get('Wtbh', '')
                    self.last_tdx_order_id = wtbh   # [2026-09-02] 缓存委托编号，供 monitor 撤单/追踪
                    return True, f"通达信下单成功，委托编号: {wtbh}"
                else:
                    logger.warning(f"[TradeManager] tq.order_stock 失败: ErrorId={error_id} Value={result.get('Value')} Msg={msg} result={result}")
                    return False, f"通达信下单失败: ErrorId={error_id}, Msg={msg}"

            except Exception as e:
                import traceback
                logger.error(f"[TradeManager] tq.order_stock 异常: {e}\n{traceback.format_exc()}")
                # [2026-09-03 方案A] 连接类异常(如"连接路径为空")→ 降级 tdx_available=False，
                # 后续调用干净返回"接口未就绪"并提示点「通达信」重连，不再假装可用反复抛底层错
                if 'initialize' in str(e) or '连接路径' in str(e):
                    self.tdx_available = False
                return False, f"通达信下单异常: {str(e)}"
                
        return False, f"未知的通道标识: {broker}"

    # ==================== [AI-2026-07-17] 银河 QMT 成交监听与持仓查询 ====================

    def on_deal(self, callback):
        """注册成交回调。callback(code, vol, price) — 方案 A：实时 DEAL 广播"""
        self._deal_listeners.append(callback)

    def on_order(self, callback):
        """注册订单状态回调。callback(code, sysid, status) — ORDER 广播，用于捕获 QMT sysid 供撤单使用"""
        self._order_listeners.append(callback)

    def on_tdx_deal(self, callback):
        """[2026-09-02] 注册通达信成交回调。callback(code, vol, price) — tqcenter 通知回调触发"""
        self._tdx_trade_listeners.append(callback)

    def on_tdx_order(self, callback):
        """[2026-09-02] 注册通达信订单状态回调。callback(code, order_id, status) — 1=未成交 2=部分成交 3=全成 5=撤单"""
        self._tdx_order_listeners.append(callback)

    def query_tdx_orders(self, fund_code: str = '') -> list:
        """[2026-09-03 方案H3a] 通达信当日委托轮询兜底（本 tqcenter 无成交推送回调）。
        返回该基金委托记录列表，每条含真实字段(诊断确认): Code/Wtbh(委托号)/WtPrice(价)/WtVol(委托量)/
        Status(0无效 1未成交 2部分成交 3全部成交 4部分撤单 5全部撤单)/CjVol·CjPrice(成交量价)/Time。未就绪或异常一律返回 []。"""
        if not (self.tdx_available and self.tq):
            return []
        try:
            raw = self.tq.query_stock_orders(account_id=self.tdx_account_id) or []
            logger.debug(f"[TradeManager] query_tdx_orders({fund_code}) 原始返回 type={type(raw).__name__} len={len(raw) if isinstance(raw, list) else 'NA'}")
            if not isinstance(raw, list):
                return []
            orders = raw
            if fund_code:
                fc = str(fund_code)
                orders = [o for o in orders
                          if isinstance(o, dict) and str(o.get('Code', '')).split('.')[0] == fc]
            if orders:
                logger.debug(f"[TradeManager] query_tdx_orders({fund_code}) 过滤后 {len(orders)} 条，首条字段: {sorted(orders[0].keys())}")
            else:
                logger.debug(f"[TradeManager] query_tdx_orders({fund_code}) 过滤后 0 条（Code 前缀未命中或当日无委托）")
            return orders
        except Exception as e:
            logger.warning(f"[TradeManager] query_tdx_orders 异常: {e}")
            return []

    def cancel_order(self, broker: str, sysid: str, stock_code: str = '') -> tuple[bool, str]:
        """按通道撤单。
        - yinhe_qmt: 经 8888 桥接按 sysid 撤
        - tdx: 经 tqcenter.cancel_order_stock 按委托编号(order_id=sysid)撤，stock_code 可选(如 '162411.SZ')
        返回 (success, message)"""
        if broker == 'tdx':
            if not self.tdx_available:
                return False, "通达信接口未就绪"
            try:
                sc = self._tdx_symbol(stock_code) if stock_code else ''   # [2026-09-03] 撤单也补 '代码.市场'
                ok = self.tq.cancel_order_stock(
                    account_id=self.tdx_account_id,
                    stock_code=sc,
                    order_id=str(sysid),
                )
                if ok not in (-1, None):
                    logger.info(f"[TradeManager] 通达信撤单 委托编号={sysid} → 成功")
                    return True, f"通达信撤单成功(委托编号:{sysid})"
                logger.warning(f"[TradeManager] 通达信撤单 委托编号={sysid} → 失败(返回{ok})")
                return False, f"通达信撤单失败(委托编号:{sysid})"
            except Exception as e:
                return False, f"通达信撤单异常: {e}"
        if broker != 'yinhe_qmt':
            return False, f"cancel_order 暂不支持 {broker}"
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(('127.0.0.1', 8888))
            client.sendall(f"CANCEL,{sysid}\n".encode('utf-8'))
            try:
                client.settimeout(1.5)
                resp = client.recv(1024).decode('utf-8').strip()
                client.close()
                if resp == 'OK':
                    logger.info(f"[TradeManager] 银河QMT撤单 sysid={sysid} → 回执OK")
                    return True, "撤单指令已发送 (回执OK)"
                client.close()
                logger.warning(f"[TradeManager] 银河QMT撤单 sysid={sysid} → 回执:{resp}，撤单可能未生效")
                return False, f"撤单可能未生效 (回执:{resp})"
            except socket.timeout:
                client.close()
                logger.info(f"[TradeManager] 银河QMT撤单 sysid={sysid} → 已发送(fire-and-forget)")
                return True, "撤单指令已发送 (fire-and-forget)"
        except ConnectionRefusedError:
            return False, "银河QMT 8888 未连接，无法撤单"
        except Exception as e:
            return False, f"银河QMT撤单异常: {e}"

    def query_position(self, code):
        """方案 B：查询单只持仓（短连接，超时 3s）。
        返回 dict {code, volume, price} 或 None"""
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(('127.0.0.1', 8888))
            client.sendall(f"QUERY_POSITION,{code}\n".encode('utf-8'))
            client.settimeout(1.5)
            resp = client.recv(1024).decode('utf-8').strip()
            client.close()
            # POSITION_RESULT,code,vol,price
            if resp.startswith('POSITION_RESULT'):
                parts = resp.split(',')
                if len(parts) >= 4:
                    return {
                        'code': parts[1],
                        'volume': int(parts[2]),
                        'price': float(parts[3]),
                    }
            return None
        except socket.timeout:
            return None
        except ConnectionRefusedError:
            return None
        except Exception as e:
            logger.warning(f"[TradeManager] query_position 异常: {e}")
            return None

    def query_deals(self, start_date: str, end_date: str = None, timeout: float = 20.0) -> dict:
        """[AI-2026-08-15] 查询银河QMT历史成交（经 8888 桥接策略的 QUERY_DEALS 指令）。
        连接保持到收到 DEALS_END；逐笔 DEAL_JSON 解析为 dict，首行 DEAL_ATTRS 为方法探测结果（avail/all_get，首轮字段对齐用）。
        返回 {ok, deals:[dict], attrs:dict, error}。"""
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(('127.0.0.1', 8888))
            cmd = f"QUERY_DEALS,{start_date}"
            if end_date:
                cmd += f",{end_date}"
            cmd += "\n"
            client.sendall(cmd.encode('utf-8'))

            buffer = ''
            deals = []
            attrs = []
            error = None
            while True:
                data = client.recv(65536).decode('utf-8')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('DEALS_END'):
                        client.close()
                        return {"ok": True, "deals": deals, "attrs": attrs, "error": error}
                    elif line.startswith('DEALS_ERR'):
                        error = line.split(',', 1)[1] if ',' in line else 'unknown'
                    elif line.startswith('DEALS_EMPTY'):
                        pass
                    elif line.startswith('DEAL_ATTRS,'):
                        try:
                            attrs = json.loads(line[len('DEAL_ATTRS,'):])
                        except Exception:
                            pass
                    elif line.startswith('DEAL_JSON,'):
                        try:
                            deals.append(json.loads(line[len('DEAL_JSON,'):]))
                        except Exception:
                            pass
            client.close()
            return {"ok": True, "deals": deals, "attrs": attrs, "error": error}
        except ConnectionRefusedError:
            return {"ok": False, "error": "银河QMT 8888 未连接（请确认QMT已登录且 ServerV5 策略已加载）"}
        except socket.timeout:
            return {"ok": False, "error": f"银河QMT查询超时({timeout}s)"}
        except Exception as e:
            return {"ok": False, "error": f"银河QMT查询异常: {e}"}

    def query_orders(self, code: str = '', timeout: float = 8.0) -> dict:
        """[2026-09-03 方案A] 短连接主动查银河QMT当日委托状态（替代长连接 ORDER 广播）。
        连 8888 发 QUERY_ORDERS，读到 ORDERS_END 为止；逐笔 ORDER_JSON 解析为 dict。
        每条含 m_strOrderSysID/m_nOrderStatus/m_strInstrumentID/m_nVolume/m_dPrice。
        返回 {ok, orders:[dict], error}。code 非空时仅保留匹配代码(去后缀)的委托。"""
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(timeout)
            client.connect(('127.0.0.1', 8888))
            client.sendall(b"QUERY_ORDERS\n")
            buffer = ''
            orders = []
            error = None
            while True:
                data = client.recv(65536).decode('utf-8')
                if not data:
                    break
                buffer += data
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('ORDERS_END'):
                        client.close()
                        if code:
                            fc = str(code).split('.')[0]
                            orders = [o for o in orders
                                      if str(o.get('m_strInstrumentID', '')).split('.')[0] == fc]
                        return {"ok": True, "orders": orders, "error": error}
                    elif line.startswith('ORDERS_ERR'):
                        error = line.split(',', 1)[1] if ',' in line else 'unknown'
                    elif line.startswith('ORDERS_EMPTY'):
                        pass
                    elif line.startswith('ORDER_JSON,'):
                        try:
                            orders.append(json.loads(line[len('ORDER_JSON,'):]))
                        except Exception:
                            pass
            client.close()
            return {"ok": True, "orders": orders, "error": error}
        except ConnectionRefusedError:
            return {"ok": False, "error": "银河QMT 8888 未连接（请确认QMT已登录且 ServerV5 策略已加载）"}
        except socket.timeout:
            return {"ok": False, "error": f"银河QMT查询超时({timeout}s)"}
        except Exception as e:
            return {"ok": False, "error": f"银河QMT查询异常: {e}"}

    def start_deal_listener(self):
        """启动持久连接监听 DEAL 广播（方案 A：实时推送）"""
        if self._listener_running:
            return
        self._listener_running = True
        self._listener_thread = threading.Thread(target=self._deal_listener_loop, daemon=True)
        self._listener_thread.start()
        logger.info("[TradeManager] 已启动银河QMT成交监听线程")

    def stop_deal_listener(self):
        """停止成交监听"""
        self._listener_running = False
        if self._listener_sock:
            try:
                self._listener_sock.close()
            except Exception:
                pass
            self._listener_sock = None

    def is_listener_alive(self, max_age_seconds: float = 25.0) -> bool:
        """[H1 2026-09-03] 回传通道是否在线：监听线程在跑、已连上、且最近 max_age 秒内有回包(含 PING→PONG)。
        供 SmartMonitor 区分『没有成交』与『收不到成交回传』，避免把"失明"误判成"未成交"去撤单/halt。"""
        return bool(self._listener_running and self._listener_alive
                    and (time.time() - self._listener_last_rx) <= max_age_seconds)

    def _deal_listener_loop(self):
        """[H1 2026-09-03] 持久连接接收 QMTv5 的 ORDER/DEAL 广播，带 PING 心跳自检 + 失明自愈重连。

        旧实现用 client.settimeout(None) 永久阻塞读：QMT 重启换 socket_gen 后，老连接变半开、
        recv 永远挂着不报错 → 监听静默失明、成交/委托回传一条收不到，Monitor 无从察觉（今天 164701 即此）。
        现改为：有界读 + 每 LISTENER_PING_INTERVAL 静默发一次 PING(活服务端回 PONG) → 收到任意字节即刷新
        _listener_last_rx/置活；连续 LISTENER_STALE_SECONDS 无任何回包 → 判定僵死 → break 到外层重连 8888
        （新连接被当前活服务端 active_clients 收录，恢复 DEAL/ORDER 广播）。"""
        while self._listener_running:
            client = None
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(5.0)
                client.connect(('127.0.0.1', 8888))
                self._listener_sock = client
                _enable_tcp_keepalive(client)
                self._listener_last_rx = time.time()   # 刚连上先给一个新鲜窗口，避免首个 ping 前误判
                buffer = ''
                client.settimeout(self.LISTENER_PING_INTERVAL)   # 有界读：静默即醒来探活
                while self._listener_running:
                    try:
                        data = client.recv(4096).decode('utf-8')
                        if not data:
                            logger.info("[TradeManager] 成交监听：服务端关闭连接，触发重连")
                            break
                        self._listener_last_rx = time.time()
                        if not self._listener_alive:
                            self._listener_alive = True
                            logger.info("[TradeManager] ✅ 银河QMT回传通道在线（收到广播/PONG）")
                        buffer += data
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if line and line != 'PONG':
                                self._dispatch_deal_line(line)
                    except socket.timeout:
                        # 静默一个 ping 周期 → 主动探活：活服务端回 PONG 会刷新 last_rx
                        try:
                            client.sendall(b'PING\n')
                        except Exception:
                            logger.warning("[TradeManager] 成交监听：PING 发送失败，连接已断，触发重连")
                            break
                        if time.time() - self._listener_last_rx > self.LISTENER_STALE_SECONDS:
                            logger.warning(f"[TradeManager] ⚠️ 银河QMT回传通道 {self.LISTENER_STALE_SECONDS:.0f}s 无任何回包(PING 无应答)，判定失明/半开连接 → 强制重连")
                            self._listener_alive = False
                            break
            except ConnectionRefusedError:
                self._listener_alive = False
                logger.debug("[TradeManager] 银河QMT 8888 未就绪，5s后重试")
                time.sleep(5)
            except Exception as e:
                self._listener_alive = False
                logger.warning(f"[TradeManager] 监听线程异常: {e}")
                time.sleep(5)
            finally:
                self._listener_alive = False
                self._listener_sock = None
                try:
                    if client:
                        client.close()
                except Exception:
                    pass

    def _dispatch_deal_line(self, line):
        """解析收到的消息行，分发 DEAL/ORDER 给已注册回调"""
        if line.startswith('DEAL,'):
            parts = line.split(',')
            if len(parts) >= 4:
                code = parts[1]
                try:
                    vol = int(parts[2])
                    price = float(parts[3])
                    for cb in self._deal_listeners:
                        try:
                            cb(code, vol, price)
                        except Exception as e:
                            logger.warning(f"[TradeManager] deal回调异常: {e}")
                except (ValueError, IndexError):
                    pass
        # [AI-2026-07-21] 分发 ORDER 广播给已注册回调（SmartMonitor 捕获 QMT sysid 用）
        elif line.startswith('ORDER,'):
            parts = line.split(',')
            if len(parts) >= 4:
                code = parts[1]
                sysid = parts[2]
                status = parts[3]
                for cb in self._order_listeners:
                    try:
                        cb(code, sysid, status)
                    except Exception as e:
                        logger.warning(f"[TradeManager] order回调异常: {e}")
