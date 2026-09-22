# -*- coding: utf-8 -*-
"""
futu_reader.py - 富途行情读取器模块

复用自 LOFarb 项目，已稳定运行
功能：通过富途 OpenD 获取美股/港股实时行情
"""

import time
import threading
import pandas as pd
import logging

logger = logging.getLogger(__name__)

# 尝试导入富途API
try:
    from futu import OpenQuoteContext, SubType, Session
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    logger.warning("[WARNING] 未安装 futu-api 库，富途读取器不可用 (pip install futu-api)")


# [AI-2026-08-06] 把 futu SDK 自带的文件日志从 DEBUG 降到 WARNING。
# 根因：futu/common/ft_logger.py 中 FTLog.__init__ 默认 _file_level=logging.DEBUG，
# 每次行情 tick 都往 ~/.com.futunn.FutuOpenD/Log/py_YYYY_MM_DD.log 写 DEBUG，
# 且其 TimedRotatingFileHandler(backupCount=20) 最坏可留 20 份 GB 级文件。
# ARM 上 5 天累积到 5.2G（单文件最大 2.4G），磁盘 7%→21%，故在此源头降级。
# 只降"写文件"级别，控制台 (FTConsoleLog) 保持原样，不影响任何行情功能与错误可见性。
def _silence_futu_sdk_file_log():
    if not FUTU_AVAILABLE:
        return
    try:
        # 标准 logging 层面拦截（即使 SDK 内部 gate 放行，这里也会过滤掉）
        logging.getLogger('FTFileLog').setLevel(logging.WARNING)
        # SDK 内部 gate + handler 层面同步降级，省掉字符串格式化开销
        from futu.common.ft_logger import logger as _ft_logger
        _ft_logger._file_level = logging.WARNING
        file_handler = getattr(_ft_logger, 'fileHandler', None)
        if file_handler is not None:
            file_handler.setLevel(logging.WARNING)
    except Exception as exc:
        # 仅日志降噪失败，不能影响主流程
        logger.warning(f"[FUTU] SDK 文件日志降级失败（不影响行情）: {exc}")


_silence_futu_sdk_file_log()


class FutuReader:
    """富途行情长连接读取器
    
    复用自 LOFarb 项目的稳定实现
    支持夜盘、盘前、盘后行情获取
    """

    # [AI-2026-09-22] 订阅标的硬上限（额度收口）。
    # 富途免费正股额度 100，但 QUOTE 与 ORDER_BOOK 分别计数、共享这 100：
    # QUOTE 快照不含买一卖一，_get_prices_impl 对每个标的都要再订一次 ORDER_BOOK 取盘口
    # ⇒ 实际 1 标的 = 2 额度，100 额度只装得下 ~50 个标的。
    # 白名单（DB 权威篮子 ∪ IB 核心池）本身已远小于此值，此上限只作越界告警与截断保护。
    FUTU_MAX_SUBSCRIBABLE = 50

    @staticmethod
    def to_futu_code(symbol):
        """标的符号 → 富途代码（US.XXX / HK.XXXXX）；不适用富途返回 None。

        [AI-2026-09-22] 从 _get_prices_impl 内联逻辑抽出。白名单构建与订阅走同一函数，
        保证"白名单里允许的代码"与"实际提交订阅的代码"逐字一致（两套归一化会错配）。
        规则沿用原实现：去 ^ 前缀 / 去 -EU|-JP|-HK 后缀；5 位纯数字 → HK；
        2-6 位纯字母 → US；其余（A股 6 位、LSE 的 BRNT.L/CRUD.L、东京 2644.T 等）→ None。
        """
        import re as _re
        if not symbol:
            return None
        clean = str(symbol).strip().lstrip('^')
        for suffix in ('-EU', '-JP', '-HK'):
            if clean.endswith(suffix):
                clean = clean[:-len(suffix)]
                break
        if _re.match(r'^[0-9]{5}$', clean):
            return f"HK.{clean}"
        if _re.match(r'^[A-Za-z]{2,6}$', clean):
            return f"US.{clean}"
        return None

    def set_subscription_allowlist(self, symbols) -> int:
        """注入订阅白名单（调用方应为 DB 权威篮子 ∪ IB 核心池）。

        [AI-2026-09-22] 额度收口的根因修复：非白名单标的在订阅入口(_get_prices_impl)
        与盘口入口(_fetch_order_book)直接被丢弃，不吃 QUOTE / ORDER_BOOK 额度，
        因此不会再出现"第 101 个标的把整批订阅拖垮 → 清 ctx → 重连 → 盘口订阅全丢"的连锁。

        空列表视为"不启用"（保持旧行为），避免上游 DB 查询失败时把订阅全禁掉。
        返回实际生效的标的数。
        """
        codes = set()
        for s in (symbols or []):
            c = self.to_futu_code(s)
            if c:
                codes.add(c)
        if not codes:
            logger.warning("[富途] 白名单为空，不启用订阅白名单（保持旧行为，不做额度限制）")
            self.subscription_allowlist = None
            return 0
        ordered = sorted(codes)
        if len(ordered) > self.FUTU_MAX_SUBSCRIBABLE:
            over = ordered[self.FUTU_MAX_SUBSCRIBABLE:]
            ordered = ordered[:self.FUTU_MAX_SUBSCRIBABLE]
            logger.error(
                f"[富途] 白名单 {len(codes)} 个标的超过硬上限 {self.FUTU_MAX_SUBSCRIBABLE}"
                f"（1 标的 = 2 额度，100 额度上限）→ 以下 {len(over)} 个不订阅: {', '.join(over)}")
        self.subscription_allowlist = set(ordered)
        logger.info(f"[富途] 订阅白名单已生效: {len(ordered)} 个标的"
                    f"（预计额度占用 ~{len(ordered) * 2}/100）")
        return len(ordered)

    def _is_allowed(self, futu_code) -> bool:
        """白名单校验；未注入白名单(None)时一律放行"""
        if self.subscription_allowlist is None:
            return True
        return futu_code in self.subscription_allowlist

    def __init__(self, host='127.0.0.1', port=11111, max_retries=3, connect_timeout=5):
        """
        Args:
            host: 富途 OpenD 地址
            port: 富途 OpenD 端口
            max_retries: 最大连接尝试次数（默认3次）
            connect_timeout: 每次连接的超时秒数（默认5秒）
        """
        self.ctx = None
        self.host = host
        self.port = port
        self.max_retries = max_retries
        self.connect_timeout = connect_timeout
        self.prices = {}  # {symbol: {'bid': ..., 'ask': ..., 'last': ...}}
        self.subscribed_codes = set()
        self._order_book_subscribed = set()  # [AI-2026-08-03] ORDER_BOOK 订阅跟踪（get_order_book 取真实盘口用）
        self._order_book_needed = set()  # [AI-2026-09-21] 持久记录"需盘口订阅的标的"，重连后据此批量补订 ORDER_BOOK（重连不清空，区别于 _order_book_subscribed）
        # [AI-2026-09-22] 订阅白名单（额度收口）：见 set_subscription_allowlist()。
        # None = 不启用（保持旧行为）；非 None = 只允许订阅集合内标的，白名单外直接丢弃。
        self.subscription_allowlist = None
        self._blocked_logged = set()  # 白名单拦截日志去重（每进程每标的一次，防盘中刷屏）
        self.last_connect_time = 0
        self.last_log_time = 0
        self.connected = False  # [AI-2026-07-15] 实时连接标志（与 IB 一致），reconnect 成功=True，断开=False
        self.disabled = True  # [V10.0] 启动时不自动连接，用户点击页面"富途"按钮才重连
        self.session_closed = False  # [AI-2026-08-04] A股非交易时段门禁标志，上游据此跳过熔断计数
        self._lock = threading.Lock()  # [V10.13] 多线程并发保护
        
        # [V10.0] 不再启动后台连接线程，用户手动触发 reconnect() 即可
    
    @staticmethod
    def _connect_with_timeout(host, port, timeout=5):
        """
        用线程包装 OpenQuoteContext 连接，超时则放弃。
        解决 futu-api 底层 C 层无超时参数的问题。
        """
        result = [None]
        error = [None]
        timed_out = [False]  # [AI-2026-09-21] 超时兜底：后台线程若建好 ctx 但外层已超时，由后台自行 close，避免泄漏无引用的连接

        def _do_connect():
            try:
                import futu
                futu.SysConfig.set_all_thread_daemon(True)
                futu.SysConfig.set_client_info('ArbDashboard', 1)
                ctx = futu.OpenQuoteContext(host=host, port=port)
                if timed_out[0]:
                    # 外层已超时，这个连接没被采用，立刻关闭回收，杜绝后台泄漏
                    try:
                        ctx.close()
                    except:
                        pass
                    return
                result[0] = ctx
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_do_connect, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            # 连接还在进行中，说明超时了
            timed_out[0] = True  # 通知后台线程：你建好的连接请自行 close
            raise Exception(f"富途 OpenD 连接超时 ({timeout}秒)，请检查富途 OpenD 是否运行在 {host}:{port}")

        if error[0]:
            raise error[0]

        if result[0] is None:
            raise Exception("富途连接返回 None")

        return result[0]
        
    @staticmethod
    def _call_with_timeout(fn, timeout=10):
        """
        [AI-2026-08-26] 给富途请求调用加超时，防半开连接挂死。
        复用 _connect_with_timeout 的线程包装模式：OpenD 半开连接（TCP 挂着但不响应）时，
        SDK 的 subscribe/get_stock_quote/get_order_book 会无限阻塞且不报错，
        一旦发生会把整个 get_prices（含估值线程）拖死。这里统一包一层，
        超时抛 TimeoutError，由调用方清 ctx 走懒重连。
        """
        result = {}

        def _do():
            try:
                result['value'] = fn()
            except Exception as e:
                result['error'] = e

        t = threading.Thread(target=_do, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            raise TimeoutError(f"富途请求超时 ({timeout}s)")
        if 'error' in result:
            raise result['error']
        return result.get('value')

    def _try_connect_silent(self):
        """
        静默尝试连接富途 OpenD（不输出 INFO 日志，只在失败时 WARNING）
        最多尝试 max_retries 次，每次失败后 sleep 1 秒再试
        成功后 ctx 不为 None，disabled = False
        全部失败后 disabled = True，ctx = None
        """
        if self.disabled:
            return
        
        for attempt in range(1, self.max_retries + 1):
            try:
                import futu
                futu.SysConfig.set_all_thread_daemon(True)
                futu.SysConfig.set_client_info('ArbDashboard', 1)
            except:
                pass
            
            try:
                # [AI-2026-09-21] 重连前先关闭旧 ctx，否则旧 socket 泄漏 → OpenD 侧 CLOSE-WAIT 堆积
                # → 撑满连接槽后被 OpenD 踢(RemoteClose) → 又重连又泄漏，恶性循环（断连根因）。
                old_ctx = self.ctx
                self.ctx = None  # 先解绑，避免重连异常时旧引用丢失导致 socket 泄漏
                if old_ctx is not None:
                    try:
                        old_ctx.close()
                        logger.debug("[富途] 重连前已关闭旧 ctx（释放旧连接）")
                    except:
                        pass
                self.ctx = FutuReader._connect_with_timeout(self.host, self.port, timeout=5)
                self.subscribed_codes = set()
                self._order_book_subscribed = set()  # [AI-2026-08-06] 重建 ctx 必须同步清空 ORDER_BOOK 订阅集合，否则新连接无盘口订阅、_fetch_order_book 跳过订阅直取空盘口→bid/ask 永久为 None
                logger.info(f"{'='*50}\n[富途] 连接成功 (第 {attempt} 次尝试)\n{'='*50}")
                self.disabled = False
                self.connected = True  # [AI-2026-07-15] 跟踪实时连接状态（与 IB 一致）
                self._rebuild_order_book_subscriptions()  # [AI-2026-09-21] 新 ctx 建好后立即批量补订 ORDER_BOOK
                return
            except Exception as e:
                if attempt < self.max_retries:
                    logger.debug(f"[富途] 连接尝试 {attempt}/{self.max_retries} 失败: {e}")
                    time.sleep(1)
                else:
                    logger.warning(f"[富途] 连接失败（已尝试 {self.max_retries} 次），OpenD 可能未起/重启中，将自动重试。")
                    self.disabled = False  # [AI-2026-08-04] 不自永禁，改由懒重连(30s节流)自动恢复
                    self.ctx = None
                    self.connected = False  # [AI-2026-07-15] 与 IB 一致
                    # [AI-2026-08-26] 断连保留最后价格缓存供估值降级（旧实现清空 prices 会导致
                    # 断连期间估值拿不到任何数据）；"是否有新数据"由上游判断，前端状态以 connected 为准
    
    def reconnect(self):
        """
        手动重连（供用户点击"富途"按钮时调用）
        重置 disabled 标志，重新尝试连接
        返回 (success: bool, message: str)
        """
        with self._lock:  # [AI-2026-07-15] 加锁防止与 _get_prices_impl 并发冲突
            # [AI-2026-07-15] 总是先关闭旧连接再重连，避免 ctx 残留导致"已经连接"跳过
            if self.ctx is not None:
                try:
                    self.ctx.close()
                except:
                    pass
                self.ctx = None
            logger.info("[富途] 用户手动触发重连...")
            self.disabled = False
            self.last_connect_time = 0  # 清除冷却时间
        
        for attempt in range(1, self.max_retries + 1):
            try:
                import futu
                futu.SysConfig.set_all_thread_daemon(True)
                futu.SysConfig.set_client_info('ArbDashboard', 1)
            except:
                pass
            
            try:
                self.ctx = FutuReader._connect_with_timeout(self.host, self.port, timeout=5)
                self.subscribed_codes = set()
                self._order_book_subscribed = set()  # [AI-2026-08-06] 重建 ctx 必须同步清空 ORDER_BOOK 订阅集合（同 _try_connect_silent），否则新连接盘口订阅丢失、bid/ask 永久 None
                self.disabled = False
                self.connected = True  # [AI-2026-07-15] 与 IB 一致
                self._rebuild_order_book_subscriptions()  # [AI-2026-09-21] 新 ctx 建好后立即批量补订 ORDER_BOOK
                # [AI-2026-08-17] reconnect 只建连接不拉价，会导致后端状态为"富途(无数据)"、前端按钮不变绿。
                # 连接成功后立即拉一次常见标的，把 prices 填充上，状态立刻变成 Ready。
                try:
                    self.get_prices(['GLD', 'XOP', 'QQQ', 'SPY', 'USO'])
                except Exception as fetch_err:
                    logger.debug(f"[富途] 重连后首次拉价失败: {fetch_err}")
                logger.info(f"[富途] 手动重连成功 (第 {attempt} 次)")
                return True, f"富途连接成功 (第 {attempt} 次尝试)"
            except Exception as e:
                logger.warning(f"[富途] 重连失败 (第 {attempt}/{self.max_retries} 次): {e}")
                self.ctx = None
                if attempt < self.max_retries:
                    time.sleep(1)
        
        self.disabled = False  # [AI-2026-08-04] 不自永禁，OpenD 恢复后懒重连自动恢复
        self.connected = False  # [AI-2026-07-15] 与 IB 一致
        # [AI-2026-08-26] 断连保留最后价格缓存供估值降级（不清空 prices）
        logger.warning("[富途] 手动重连失败（已尝试 {} 次），将自动重试，请确认富途 OpenD 已启动".format(self.max_retries))
        return False, f"富途重连失败（已尝试 {self.max_retries} 次），请确认富途 OpenD 已启动"
    
    def close(self):
        """关闭连接"""
        if self.ctx:
            try:
                self.ctx.close()
            except:
                pass
            self.ctx = None
        self.connected = False  # [AI-2026-07-15] 与 IB 一致
        logger.info("[富途] 已关闭连接")
    
    def get_prices(self, symbols):
        if not FUTU_AVAILABLE:
            return False, "未安装 futu-api 库", self.prices

        if self.disabled:
            return False, "富途API已被禁用（启动时连接失败，请点击页面'富途'标签重试）", self.prices

        # [AI-2026-08-04] 原美股/港股盘口展示窗口门禁（8:30-16:00）仅服务 IB（未购买行情）。
        # [AI-2026-08-19] 东哥确认：富途促销期全时段免费实时行情（含盘前/夜盘/现在），
        # 故富途不再受 is_quote_window 限制，全时段可取。IB 路径未动（仍走 is_quote_window）。
        # 窗口外不建连/不订阅/不请求 OpenD 的逻辑对富途不适用——OpenD 全时段有真实行情。
        self.session_closed = False

        with self._lock:  # [V10.13] 多线程并发保护
            return self._get_prices_impl(symbols)
    
    def _get_prices_impl(self, symbols):
        """get_prices 的实际实现，由 _lock 保护"""
        try:
            # ctx 为 None 说明还没连接或已断开，尝试连接
            if self.ctx is None:
                # 限制连接频率，避免频繁重连
                if time.time() - self.last_connect_time < 30:
                    return False, "富途API未运行 (等待重连...)", self.prices
                self.last_connect_time = time.time()
                
                # 最多尝试 max_retries 次连接
                connected = False
                for attempt in range(1, self.max_retries + 1):
                    try:
                        # [AI-2026-09-21] 懒重连前先关闭旧 ctx（同 _try_connect_silent），断 socket 泄漏
                        old_ctx = self.ctx
                        self.ctx = None
                        if old_ctx is not None:
                            try:
                                old_ctx.close()
                                logger.debug("[富途] 懒重连前已关闭旧 ctx（释放旧连接）")
                            except:
                                pass
                        self.ctx = FutuReader._connect_with_timeout(self.host, self.port, timeout=5)
                        self.subscribed_codes = set()
                        self._order_book_subscribed = set()  # [AI-2026-08-06] 懒重连建新 ctx 必须同步清空 ORDER_BOOK 订阅集合（同前），否则新连接盘口订阅丢失、bid/ask 永久 None
                        connected = True
                        logger.info(f"[富途] 连接成功 (第 {attempt} 次)")
                        self.disabled = False
                        self.connected = True  # [AI-2026-07-15] 与 IB 一致
                        self._rebuild_order_book_subscriptions()  # [AI-2026-09-21] 新 ctx 建好后立即批量补订 ORDER_BOOK
                        break
                    except Exception as connect_err:
                        logger.warning(f"[富途] 连接失败 (第 {attempt}/{self.max_retries} 次): {connect_err}")
                        self.ctx = None
                        if attempt < self.max_retries:
                            time.sleep(1)
                
                if not connected:
                    # [AI-2026-08-04] 连接多次失败（OpenD 未起/重启中）：标记断开而非永久禁用，
                    # 下次 get_prices 经 30s 节流懒重连自动恢复，免去 H5 手动点"富途"按钮。
                    self.disabled = False
                    self.connected = False  # [AI-2026-07-15] 与 IB 一致
                    # [AI-2026-08-26] 断连保留最后价格缓存供估值降级（不清空 prices）
                    return False, f"富途OpenD连接失败（已尝试 {self.max_retries} 次），自动重试中", self.prices
            
            # 区分美股和港股，并正确添加前缀（归一化规则统一走 to_futu_code，与白名单同源）
            futu_codes = []

            for sym in symbols:
                code = self.to_futu_code(sym)
                if code is None:
                    logger.debug(f"[富途] 自动过滤非适用代码: {sym}")
                    continue
                futu_codes.append(code)

            # [AI-2026-09-22] 白名单收口：非权威标的在提交订阅前丢弃，不吃额度。
            # 记录日志去重，避免盘中同一标的每轮刷屏。
            if self.subscription_allowlist is not None:
                blocked = [c for c in futu_codes if c not in self.subscription_allowlist]
                if blocked:
                    new_blocked = [c for c in blocked if c not in self._blocked_logged]
                    if new_blocked:
                        self._blocked_logged.update(new_blocked)
                        logger.info(f"[富途] 白名单外不订阅: {', '.join(new_blocked)}"
                                    f"（非 DB 权威篮子 / IB 核心池，避免占用正股额度）")
                    futu_codes = [c for c in futu_codes if c in self.subscription_allowlist]

            if not futu_codes:
                return True, "无适用富途的数据标的", self.prices

            new_codes = [c for c in futu_codes if c not in self.subscribed_codes]
            
            # 订阅新增加的股票，指定 Session.ALL 获取盘前盘后夜盘全时段数据
            if new_codes:
                # [AI-2026-08-26] 批量订阅优先：OpenD 正常时一次往返，大幅减少重连后的订阅风暴
                # （34 标的原本 34 次往返 → 1 次）。批量失败再逐个回退，保留 [AI-2026-07-15] 容错：
                # 单个符号失败（如 HSSI 非交易标的）不销毁整条连接。所有订阅调用走
                # _call_with_timeout，防半开连接挂死。
                valid_codes = []
                if len(new_codes) > 1:
                    try:
                        ret, data = self._call_with_timeout(
                            lambda: self.ctx.subscribe(new_codes, [SubType.QUOTE], session=Session.ALL),
                            timeout=15)
                        if ret == 0:
                            valid_codes = list(new_codes)
                        else:
                            logger.warning(f"[富途] 批量订阅失败: {data}，逐个回退")
                    except Exception as e:
                        # 批量订阅超时/连接异常：连接多半已挂，直接清 ctx 重连，不做逐个回退（避免连环超时）
                        logger.warning(f"[富途] 批量订阅异常: {e}，清空 ctx 重连")
                        old = self.ctx
                        self.ctx = None
                        if old is not None:
                            try:
                                old.close()
                            except:
                                pass
                        self.connected = False
                        return False, f"富途订阅异常: {e}", self.prices
                if not valid_codes:
                    for code in new_codes:
                        try:
                            ret, data = self._call_with_timeout(
                                lambda c=code: self.ctx.subscribe([c], [SubType.QUOTE], session=Session.ALL),
                                timeout=10)
                            if ret == 0:
                                valid_codes.append(code)
                            else:
                                logger.warning(f"[富途] 订阅失败 {code}: {data}，跳过该标的")
                        except Exception:
                            # 单个订阅超时说明连接已挂，停止回退直接走重连
                            logger.warning(f"[富途] 订阅超时 {code}，停止回退并清空 ctx")
                            break
                if valid_codes:
                    self.subscribed_codes.update(valid_codes)
                    logger.info(f"[富途] 已订阅: {', '.join(valid_codes)}")
                # [AI-2026-09-21] Option C：不过度清 ctx，保留已成功的 ORDER_BOOK 盘口补订。
                # 原逻辑：QUOTE 批量订阅本轮全失败时，若 subscribed_codes 也空就清空 ctx 重连。
                # 问题：富途免费正股额度 100/100，盘中 get_prices 无上限累积订阅，第 101 个标的
                # （XBI 等，不在 fund_basket_weights 内、由某次实时取价带入）触发整个批量订阅失败
                # → 看似"全失败" → 清 ctx → 下次重连清空 _order_book_subscribed → 已成功的 ORDER_BOOK
                # 盘口补订丢失 → etf_bid1/etf_ask1 反复写 0（09-18 分时断档根因之一）。
                # 修复：只要已成功补订 ORDER_BOOK 盘口（_order_book_subscribed 非空），即证明 ctx 连接
                # 仍存活、OpenD 可达，不应清 ctx；仅当 QUOTE 与 ORDER_BOOK 全未成功、历史上也无订阅时
                # 才判连接断开、清 ctx 走重连。
                if not valid_codes and not self.subscribed_codes and not self._order_book_subscribed:
                    # 没有一个订阅成功且未订阅过任何标的 → 连接可能已断
                    logger.warning("[富途] 所有标的订阅均失败，清空 ctx")
                    old = self.ctx
                    self.ctx = None
                    if old is not None:
                        try:
                            old.close()
                        except:
                            pass
                    self.connected = False
                    return False, "富途所有标的订阅均失败", self.prices
            
            # 获取实时报价
            # [AI-2026-08-26] 请求级超时：OpenD 半开连接时 SDK 会无限阻塞，这里 15s 内不返回即
            # 抛 TimeoutError，由外层 except 清 ctx 走懒重连，避免拖死估值线程。
            ret, data = self._call_with_timeout(
                lambda: self.ctx.get_stock_quote(futu_codes), timeout=15)
            if ret == 0:
                got_any = False  # [AI-2026-08-26] 本轮是否取到真实盘口（区别于 self.prices 旧缓存）
                for _, row in data.iterrows():
                    futu_code = row['code']
                    code = futu_code.replace('US.', '').replace('HK.', '')
                    bid = 0.0
                    ask = 0.0
                    last = 0.0
                    
                    def safe_float(val):
                        if pd.isna(val) or val == 'N/A' or val == '': return 0.0
                        try:
                            return float(val)
                        except:
                            return 0.0

                    # [AI-2026-08-03] 富途 QUOTE 快照不含 bid/ask 列，必须 ORDER_BOOK + get_order_book 取真实买一卖一。
                    # _fetch_order_book 返回 (bid, ask, bid_size, ask_size)；取不到则全 0（前端走"等待数据"）。
                    last_0 = safe_float(row.get('last_price'))
                    ob_bid, ob_ask, ob_bid_sz, ob_ask_sz, ob_bids, ob_asks = self._fetch_order_book(futu_code)

                    bid = ob_bid if ob_bid and ob_bid > 0 else 0.0
                    ask = ob_ask if ob_ask and ob_ask > 0 else 0.0
                    bid_size = ob_bid_sz if ob_bid_sz and ob_bid_sz > 0 else 0.0
                    ask_size = ob_ask_sz if ob_ask_sz and ob_ask_sz > 0 else 0.0
                    last = last_0

                    # [AI-2026-08-04] INFO→DEBUG：此行每标的每轮各打一次，盘中每秒数十行，
                    # 是 ARM syslog 膨胀主因（单机 314M / 磁盘 +5pp 每天）。逐笔盘口属排障细节，
                    # 非运行必需；需要时用 LOG_LEVEL=DEBUG 打开。30 秒一次的价格心跳仍保留 INFO。
                    logger.debug(f"【富途盘口】 {code}: bid={bid}(×{bid_size}) ask={ask}(×{ask_size}) last={last} levels={len(ob_bids)}/{len(ob_asks)}")

                    # 只要有真实盘口或 last 就存，上游决定显示/估值（全 0 视为无数据由门禁处理）
                    if last > 0 or bid > 0 or ask > 0:
                        got_any = True  # [AI-2026-08-26] 本轮取到数据（与旧缓存区分）
                        self.prices[code] = {
                            'bid': bid,
                            'ask': ask,
                            'last': last,
                            'bid_size': bid_size,
                            'ask_size': ask_size,
                            # [AI-2026-08-17] 富途多档盘口（最多10档），供前端展示对比用，不参与估值计算
                            'bid_levels': ob_bids,
                            'ask_levels': ob_asks,
                        }
                        self.last_data_time = time.time()  # [AI-2026-07-15] 记录成功获取数据的时间戳
                
                # 控制台心跳回显 (每30秒打印一次)
                current_time = time.time()
                if current_time - self.last_log_time >= 30:
                    if self.prices:
                        price_strs = [f"{k}=${v.get('last', 0):.2f}" for k, v in self.prices.items()]
                        logger.info(f"[富途] 实时价格: {', '.join(price_strs)}")
                    self.last_log_time = current_time
                
                # [V10.13] 如果没有任何标的获取到真实盘口（如非交易时段），返回失败而非成功
                # [AI-2026-08-26] 判定基于本轮 got_any 而非 self.prices：断连后缓存保留旧价，
                # 不能把旧缓存当成"本轮成功"，否则上游会误判行情新鲜。
                if not got_any:
                    return False, "本轮未获取到真实盘口数据", self.prices
                return True, "成功获取富途价格", self.prices
            else:
                logger.warning(f"[富途] 获取数据失败: {data}，清空 ctx 下次可重连")
                old = self.ctx
                self.ctx = None
                if old is not None:
                    try:
                        old.close()
                    except:
                        pass
                self.connected = False
                return False, f"富途API未运行: {data}", self.prices
                
        except Exception as e:
            logger.warning(f"[富途] get_prices 异常: {e}")
            err_msg = str(e)
            if "refused" in err_msg.lower() or "10061" in err_msg:
                # [AI-2026-08-04] OpenD 暂不可达（如重启中）：不自永禁，标记断开后由懒重连(30s节流)自动恢复，
                # 免去 H5 手动点"富途"按钮。严守：不抛异常、不影响其他源估值。
                logger.warning("[富途] OpenD 暂不可达(refused)，将自动重试（每30s），无需手动重连")
                self.disabled = False
                self.connected = False  # [AI-2026-07-15] 与 IB 一致
                # [AI-2026-08-26] 断连保留最后价格缓存供估值降级（不清空 prices）
                return False, "富途OpenD暂不可达，自动重试中", self.prices
            # [AI-2026-07-15] 非"refused"异常（如连接断开）→ 标记断开，让 reconnect 可以重试
            logger.error(f"[富途] 异常: {err_msg} → 标记为断开，下次点击可重连")
            self.connected = False
            old = self.ctx
            self.ctx = None
            if old is not None:
                try:
                    old.close()
                except:
                    pass
            return False, f"富途接口异常: {err_msg}", self.prices
    
    def _rebuild_order_book_subscriptions(self):
        """
        [AI-2026-09-21] 重连后主动批量补订 ORDER_BOOK，修复「重连清空盘口订阅→需等下一轮才恢复」弱点。

        背景：09-18 富途 OpenD 链路剧烈抖动（RemoteClose 风暴），每次 ctx 重建都会清空
        _order_book_subscribed，原实现只能靠下一轮采样在 _fetch_order_book 里逐标的懒订阅重建，
        重连后的首轮采样要 N 次单标的往返，极易在半开连接上失败 → etf_bid1/etf_ask1 全天写 0。

        做法：用持久集合 _order_book_needed（重连不清空）记录"需要盘口订阅的标的"，ctx 建好后
        立即批量补订 ORDER_BOOK（沿用 QUOTE 批量订阅同款容错：批量优先、失败逐个回退），
        把重连后的空盘口窗口压到最短。无任何"需补订"标的时为 no-op（不订阅、不报错）。

        注意：本方法不获取 self._lock（调用方 reconnect/_get_prices_impl 已在锁内，
        _try_connect_silent 本就不加锁），与现有 self.ctx 访问风格一致。
        """
        if self.ctx is None:
            return False
        pending = [c for c in self._order_book_needed if c not in self._order_book_subscribed]
        if not pending:
            return True
        try:
            if len(pending) > 1:
                try:
                    ret, data = self._call_with_timeout(
                        lambda: self.ctx.subscribe(pending, [SubType.ORDER_BOOK], session=Session.ALL),
                        timeout=15)
                    if ret == 0:
                        self._order_book_subscribed.update(pending)
                        logger.info(f"[富途] 重连后批量补订 ORDER_BOOK: {', '.join(pending)}")
                        return True
                    else:
                        logger.warning(f"[富途] 批量补订 ORDER_BOOK 失败: {data}，逐个回退")
                except Exception as e:
                    logger.warning(f"[富途] 批量补订 ORDER_BOOK 异常: {e}，逐个回退")
            # 单标的或批量失败回退：逐个补订（同市场单标的订阅必然合法）
            ok = False
            for code in pending:
                try:
                    ret, data = self._call_with_timeout(
                        lambda c=code: self.ctx.subscribe([c], [SubType.ORDER_BOOK], session=Session.ALL),
                        timeout=10)
                    if ret == 0:
                        self._order_book_subscribed.add(code)
                        ok = True
                    else:
                        logger.debug(f"[富途] 补订 ORDER_BOOK 失败 {code}: {data}")
                except Exception:
                    # 单个订阅超时=连接已挂，停止回退，交由上层清 ctx 重连
                    break
            if ok:
                logger.info(f"[富途] 重连后补订 ORDER_BOOK 完成（部分/全部）")
            return ok
        except Exception as e:
            logger.warning(f"[富途] _rebuild_order_book_subscriptions 异常: {e}")
            return False

    # [AI-2026-08-03] 富途 QUOTE 快照不含买一卖一，必须 ORDER_BOOK 订阅 + get_order_book 取真实盘口。
    # [AI-2026-08-17] 扩展为多档：返回 (bid, ask, bid_size, ask_size, bid_levels, ask_levels)。
    #   - 前四项 = 第一档（兼容旧调用 _get_prices_impl 取买一卖一）；
    #   - bid_levels / ask_levels = [[price, vol], ...] 最多 max_levels 档（富途免费 LV3 给 10 档）。
    #   取不到返回 (None, None, 0, 0, [], [])。
    def _fetch_order_book(self, futu_code, max_levels: int = 10):
        if self.ctx is None:
            return (None, None, 0, 0, [], [])
        # [AI-2026-09-22] 白名单外的标的不订盘口（ORDER_BOOK 同样吃正股额度）
        if not self._is_allowed(futu_code):
            return (None, None, 0, 0, [], [])
        try:
            if futu_code not in self._order_book_subscribed:
                # [AI-2026-08-26] 请求级超时，防半开连接挂死
                ret, _ = self._call_with_timeout(
                    lambda: self.ctx.subscribe([futu_code], [SubType.ORDER_BOOK], session=Session.ALL),
                    timeout=10)
                if ret == 0:
                    self._order_book_subscribed.add(futu_code)
                    self._order_book_needed.add(futu_code)  # [AI-2026-09-21] 持久记录，重连后据此批量补订
                else:
                    return (None, None, 0, 0, [], [])
            ret, ob = self._call_with_timeout(
                lambda: self.ctx.get_order_book(futu_code), timeout=10)
            if ret != 0 or not isinstance(ob, dict):
                return (None, None, 0, 0, [], [])
            bid_list = ob.get('Bid') or []
            ask_list = ob.get('Ask') or []
            if not bid_list or not ask_list:
                return (None, None, 0, 0, [], [])
            # [AI-2026-08-17] 多档解析：每档 [price, vol]，过滤无效价，截断到 max_levels
            bid_levels = []
            for row in bid_list[:max_levels]:
                if not row:
                    continue
                p = float(row[0]) if len(row) > 0 else 0.0
                v = float(row[1]) if len(row) > 1 else 0.0
                if p > 0:
                    bid_levels.append([p, v])
            ask_levels = []
            for row in ask_list[:max_levels]:
                if not row:
                    continue
                p = float(row[0]) if len(row) > 0 else 0.0
                v = float(row[1]) if len(row) > 1 else 0.0
                if p > 0:
                    ask_levels.append([p, v])
            if not bid_levels or not ask_levels:
                return (None, None, 0, 0, [], [])
            b0 = bid_levels[0]
            a0 = ask_levels[0]
            return (b0[0], a0[0], b0[1], a0[1], bid_levels, ask_levels)
        except TimeoutError:
            # [AI-2026-08-26] 请求超时=连接半开，上抛给 get_prices 统一清 ctx 重连，
            # 避免 34 标的逐个连环超时（10s×34=340s）拖死估值线程。
            raise
        except Exception as e:
            logger.debug(f"[富途] get_order_book {futu_code} 失败: {e}")
            return (None, None, 0, 0, [], [])

    def get_price(self, symbol):
        """
        获取单个股票的最新买一价
        
        Args:
            symbol: 股票代码，如 'GLD'
            
        Returns:
            float: 买一价，获取失败返回 0.0
        """
        if symbol in self.prices:
            return self.prices[symbol].get('bid', 0.0)
        return 0.0
    
    def get_realtime_quote(self, symbol):
        """
        获取单个股票的完整报价
        
        Args:
            symbol: 股票代码
            
        Returns:
            dict: {'bid': ..., 'ask': ..., 'last': ...} 或 None
        """
        if symbol in self.prices:
            return self.prices[symbol]
        return None
