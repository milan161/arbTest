import logging




import threading




import time




import os



import sys
import io
import contextlib
from typing import List, Dict, Optional, Any

from .base import BaseRealtimeFetcher


@contextlib.contextmanager
def _suppress_console_output():
    """抑制 tqcenter C++ 插件的控制台刷屏。

    Windows 上 C++ 插件可能直接调用 WriteConsole 绕过 CRT 文件描述符，
    所以除了 Python 层和 CRT fd 层外，还通过 kernel32.SetStdHandle
    重定向 Windows 标准句柄到 NUL。
    """
    old_out, old_err = sys.stdout, sys.stderr
    null_out = io.StringIO()
    # 1) Python 层
    sys.stdout, sys.stderr = null_out, null_out
    # 2) CRT 文件描述符层（捕获 C printf/fprintf）
    nul_fd = None
    try:
        nul_fd = os.open(os.devnull, os.O_WRONLY)
        old_out_fd = os.dup(1)
        old_err_fd = os.dup(2)
        os.dup2(nul_fd, 1)
        os.dup2(nul_fd, 2)
    except OSError:
        nul_fd = old_out_fd = old_err_fd = None
    # 3) Windows 标准句柄层（捕获 WriteConsole 等 Win32 API 输出）
    _win_handles = None
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        STD_OUTPUT_HANDLE = -11
        STD_ERROR_HANDLE = -12
        old_hout = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        old_herr = k32.GetStdHandle(STD_ERROR_HANDLE)
        nul_handle = k32.CreateFileW(
            'NUL', 0x40000000, 2, None, 3, 0, None
        )
        if nul_handle and nul_handle != -1:
            k32.SetStdHandle(STD_OUTPUT_HANDLE, nul_handle)
            k32.SetStdHandle(STD_ERROR_HANDLE, nul_handle)
            _win_handles = (k32, nul_handle, old_hout, old_herr)
    except Exception:
        pass
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        if nul_fd is not None:
            os.dup2(old_out_fd, 1)
            os.dup2(old_err_fd, 2)
            os.close(nul_fd)
            os.close(old_out_fd)
            os.close(old_err_fd)
        if _win_handles:
            k32, nul_handle, old_hout, old_herr = _win_handles
            try:
                k32.SetStdHandle(-11, old_hout)
                k32.SetStdHandle(-12, old_herr)
                k32.CloseHandle(nul_handle)
            except Exception:
                pass


def _permanently_silence_tq_console():
    """永久抑制 tqcenter C++ 后台线程的 printf/WriteConsole 输出。

    tqcenter 初始化后，其 C++ 后台线程会持续推送行情数据并直接 printf，
    _suppress_console_output() 只在调用期间生效，无法覆盖后台线程。
    本函数仅重定向 CRT/Win32 标准句柄（C 级输出），保留 Python sys.stdout 不变。
    """
    try:
        # CRT 文件描述符层
        nul_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nul_fd, 1)
        os.dup2(nul_fd, 2)
        os.close(nul_fd)
    except OSError:
        pass
    try:
        # Windows 标准句柄层
        import ctypes
        k32 = ctypes.windll.kernel32
        nul_handle = k32.CreateFileW('NUL', 0x40000000, 2, None, 3, 0, None)
        if nul_handle and nul_handle != -1:
            k32.SetStdHandle(-11, nul_handle)
            k32.SetStdHandle(-12, nul_handle)
    except Exception:
        pass












logger = logging.getLogger(__name__)









class TdxRealtimeFetcher(BaseRealtimeFetcher):




    """




    通达信 (tqcenter) 实时行情抓取器。




    要求本地运行通达信客户端并配置 tqcenter 插件。




    """




    




    def __init__(self):




        super().__init__("Tongdaxin")




        self.tq = None




        self.quotes = {}




        self._lock = threading.Lock()









    def connect(self) -> bool:




        try:




            # 尝试从常见路径导入 tqcenter




            tdx_api_path = r'D:\new_tdx_test\PYPlugins\user'




            if os.path.exists(tdx_api_path) and tdx_api_path not in sys.path:




                sys.path.insert(0, tdx_api_path)




            




            from tqcenter import tq




            self.tq = tq




            # 使用通达信插件目录的绝对路径，而非当前模块的 __file__
            tdx_plugin_path = os.path.join(tdx_api_path, 'tqcenter.py')
            with _suppress_console_output():
                tq.initialize(tdx_plugin_path)

            # [永久抑制] tqcenter 后台 C++ 线程的 printf 刷屏
            _permanently_silence_tq_console()

            # [防御] 拦截 _data_callback_transfer 中的 RuntimeError，防止刷屏
            _orig_cb = getattr(tq, '_data_callback_transfer', None)
            if _orig_cb and not getattr(tq, '_cb_patched_by_tdx_fetcher', False):
                _cb_error_count = 0
                def _safe_cb(*args, **kwargs):
                    nonlocal _cb_error_count
                    try:
                        return _orig_cb(*args, **kwargs)
                    except RuntimeError:
                        _cb_error_count += 1
                        if _cb_error_count <= 1:
                            logger.warning("[TDX] _data_callback_transfer RuntimeError 已拦截")
                        return None
                    except Exception:
                        return None
                try:
                    tq._data_callback_transfer = _safe_cb
                    type(tq)._data_callback_transfer = _safe_cb
                    tq._cb_patched_by_tdx_fetcher = True
                except:
                    pass


            self.is_connected = True




            logger.info("通达信 (tqcenter) 适配器加载成功")




            return True




        except ImportError:




            logger.warning("未找到 tqcenter 模块，通达信适配器停用")




            return False




        except RuntimeError as e:
            logger.warning(f"通达信初始化 RuntimeError (已捕获): {e}")
            return False


        except Exception as e:




            logger.error(f"通达信连接失败: {e}")




            return False









    def disconnect(self):




        if self.tq:




            try: self.tq.close()




            except: pass




        self.is_connected = False









    def subscribe(self, symbols: List[str]):




        if not self.is_connected: return




        # 过滤：仅订阅符合股票代码规则的品种，防止 USDCNY 等汇率引发插件报错
        # 同时过滤纯字母代码（如 CL, CU 等期货代码）
        valid_symbols = []
        for s in symbols:
            clean_s = s.split('.')[0]
            if clean_s.replace('-', '').isalpha() and len(clean_s) >= 2:
                continue  # 纯字母期货代码跳过 TDX
            if clean_s.isdigit() and len(clean_s) in [5, 6]:
                valid_symbols.append(s)

        

        if not valid_symbols: return

        tdx_codes = [self.normalize_symbol(s) for s in valid_symbols]




        try:
            with _suppress_console_output():
                self.tq.subscribe_hq(stock_list=tdx_codes, callback=self._internal_callback)
            logger.info(f"通达信已订阅: {tdx_codes}")
        except Exception as e:
            logger.error(f"通达信订阅失败: {e}")

    def unsubscribe(self, symbols: List[str]):




        if not self.is_connected: return




        tdx_codes = [self.normalize_symbol(s) for s in symbols]




        try:




            self.tq.unsubscribe_hq(stock_list=tdx_codes)




        except: pass









    def _internal_callback(self, data_str):




        """通达信价格跳动回调"""




        try:




            import json




            data = json.loads(data_str)




            stock_code = data.get('Code')




            if stock_code:




                # 获取完整快照



                with _suppress_console_output():
                    snap = self.tq.get_market_snapshot(stock_code=stock_code)

                if snap:




                    quote = self._format_snap(stock_code, snap)




                    if quote:




                        symbol = stock_code.split('.')[0]




                        with self._lock:




                            self.quotes[symbol] = quote




                        self._notify_update(symbol, quote)




        except:




            pass









    def _format_snap(self, symbol_full: str, snap: Dict) -> Optional[Dict[str, Any]]:




        try:




            # 提取 5 档盘口




            # snap.get('Sellp') 和 snap.get('Sellv') 是列表，包含 5 个元素




            asks = [float(p) for p in snap.get('Sellp', [0,0,0,0,0])]




            ask_vols = [int(v) for v in snap.get('Sellv', [0,0,0,0,0])]




            bids = [float(p) for p in snap.get('Buyp', [0,0,0,0,0])]




            bid_vols = [int(v) for v in snap.get('Buyv', [0,0,0,0,0])]









            ask1 = asks[0]




            last_price = float(snap.get('Now', 0))




            symbol = symbol_full.split('.')[0]









            # 提取成交额（通达信 snapshot 中的 Amount 通常已经是万元单位）




            amount = float(snap.get('Amount', 0))




            # 提取成交量（通常是手）




            volume = float(snap.get('Volume', 0))









            return {




                "symbol": symbol,




                "price": ask1 if ask1 > 0 else last_price,




                "last_price": last_price,




                "amount": amount,




                "volume": volume,




                "ask": asks,




                "ask_vol": ask_vols,




                "bid": bids,




                "bid_vol": bid_vols,




                "time": snap.get('Time', time.time()),




                "source": self.name




            }




        except:




            return None









    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """每次都从通达信拉取最新快照（本地内存直连，延迟极低），确保盘口实时"""
        clean_symbol = symbol.split('.')[0]

        # 过滤非A/港股标的（期货代码如 CL 等会触发 tqcenter 的 "代码格式错误" 刷屏）
        base = symbol.upper().split('.')[0]
        if base.replace('-', '').isalpha() and len(base) >= 2:
            return None  # 纯字母代码（如 CL, USO, GLD）不走TDX

        # 始终尝试主动拉取最新快照，不依赖可能过期的缓存
        if self.is_connected:
            tdx_code = self.normalize_symbol(symbol)
            try:
                with _suppress_console_output():
                    snap = self.tq.get_market_snapshot(stock_code=tdx_code)
                if snap:
                    quote = self._format_snap(tdx_code, snap)
                    if quote:
                        # 同步更新缓存，供回调和其他模块使用
                        with self._lock:
                            self.quotes[clean_symbol] = quote
                        return quote
            except Exception:
                pass

        # 通达信拉取失败时，降级使用缓存
        with self._lock:
            if clean_symbol in self.quotes:
                return self.quotes[clean_symbol]

        return None









    def normalize_symbol(self, symbol: str) -> str:
        """
        标准化标的代码为通达信格式
        
        规则：
        - 美股 ETF（纯字母）：不加后缀，直接返回
        - A 股（6 位数字）：根据代码段添加 .SH/.SZ
        - 港股（5 位数字）：添加 .HK
        - 期货：添加 .SHF/.DCE/.CZC 等后缀
        - 指数（以 ^ 开头）：保留 ^ 前缀
        """
        s = symbol.upper()
        
        # 已经包含交易所后缀，直接返回
        if '.' in s:
            return s
        
        # 移除 ^ 前缀（指数）
        is_index = s.startswith('^')
        if is_index:
            s = s[1:]
        
        # 美股 ETF（纯字母 2-6 位）：直接返回，不加后缀
        if s.replace('-', '').isalpha() and 2 <= len(s.replace('-', '')) <= 6:
            return symbol  # 保留原始格式（包括 ^ 前缀）
        
        # 港股（5 位数字）
        if len(s) == 5 and s.isdigit():
            return f"{s}.HK"
        
        # A 股（6 位数字）
        if len(s) == 6 and s.isdigit():
            if s.startswith('5') or s.startswith('6'):
                return f"{s}.SH"
            return f"{s}.SZ"
        
        # 期货合约（如 CU2409）
        if len(s) >= 5 and s[:2].isalpha() and s[2:].isdigit():
            return f"{s}.SHF"  # 默认上期所
        
        # 指数（如 USO-EU, INDA-EU）
        if is_index:
            return f"^{s}"
        
        # 默认返回原始格式
        return symbol

