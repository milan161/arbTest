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


class FutuReader:
    """富途行情长连接读取器
    
    复用自 LOFarb 项目的稳定实现
    支持夜盘、盘前、盘后行情获取
    """
    
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
        self.last_connect_time = 0
        self.last_log_time = 0
        self.disabled = True  # [V10.0] 启动时不自动连接，用户点击页面"富途"按钮才重连
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
        
        def _do_connect():
            try:
                import futu
                futu.SysConfig.set_all_thread_daemon(True)
                futu.SysConfig.set_client_info('ArbDashboard', 1)
                ctx = futu.OpenQuoteContext(host=host, port=port)
                result[0] = ctx
            except Exception as e:
                error[0] = e
        
        t = threading.Thread(target=_do_connect, daemon=True)
        t.start()
        t.join(timeout=timeout)
        
        if t.is_alive():
            # 连接还在进行中，说明超时了
            raise Exception(f"富途 OpenD 连接超时 ({timeout}秒)，请检查富途 OpenD 是否运行在 {host}:{port}")
        
        if error[0]:
            raise error[0]
        
        if result[0] is None:
            raise Exception("富途连接返回 None")
        
        return result[0]
        
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
                self.ctx = FutuReader._connect_with_timeout(self.host, self.port, timeout=5)
                self.subscribed_codes = set()
                logger.info(f"{'='*50}\n[富途] 连接成功 (第 {attempt} 次尝试)\n{'='*50}")
                self.disabled = False
                return
            except Exception as e:
                if attempt < self.max_retries:
                    logger.debug(f"[富途] 连接尝试 {attempt}/{self.max_retries} 失败: {e}")
                    time.sleep(1)
                else:
                    logger.warning(f"[富途] 连接失败（已尝试 {self.max_retries} 次），已禁用富途读取器。如需启用，请点击页面顶部的'富途'标签重试。")
                    self.disabled = True
                    self.ctx = None
    
    def reconnect(self):
        """
        手动重连（供用户点击"富途"按钮时调用）
        重置 disabled 标志，重新尝试连接
        返回 (success: bool, message: str)
        """
        if self.ctx is not None:
            logger.info("[富途] 已经连接，跳过重复重连")
            return True, "富途已经连接"
        logger.info("[富途] 用户手动触发重连...")
        self.disabled = False
        self.ctx = None
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
                self.disabled = False
                logger.info(f"[富途] 手动重连成功 (第 {attempt} 次)")
                return True, f"富途连接成功 (第 {attempt} 次尝试)"
            except Exception as e:
                logger.warning(f"[富途] 重连失败 (第 {attempt}/{self.max_retries} 次): {e}")
                self.ctx = None
                if attempt < self.max_retries:
                    time.sleep(1)
        
        self.disabled = True
        logger.warning("[富途] 手动重连失败（已尝试 {} 次），请检查富途 OpenD 是否运行".format(self.max_retries))
        return False, f"富途重连失败（已尝试 {self.max_retries} 次），请确认富途 OpenD 已启动"
    
    def close(self):
        """关闭连接"""
        if self.ctx:
            try:
                self.ctx.close()
            except:
                pass
            self.ctx = None
            logger.info("[富途] 已关闭连接")
    
    def get_prices(self, symbols):
        if not FUTU_AVAILABLE:
            return False, "未安装 futu-api 库", self.prices
            
        if self.disabled:
            return False, "富途API已被禁用（启动时连接失败，请点击页面'富途'标签重试）", self.prices
            
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
                        self.ctx = FutuReader._connect_with_timeout(self.host, self.port, timeout=5)
                        self.subscribed_codes = set()
                        connected = True
                        logger.info(f"[富途] 连接成功 (第 {attempt} 次)")
                        self.disabled = False
                        break
                    except Exception as connect_err:
                        logger.warning(f"[富途] 连接失败 (第 {attempt}/{self.max_retries} 次): {connect_err}")
                        self.ctx = None
                        if attempt < self.max_retries:
                            time.sleep(1)
                
                if not connected:
                    self.disabled = True
                    return False, f"富途OpenD连接失败（已尝试 {self.max_retries} 次）", self.prices
            
            # 区分美股和港股，并正确添加前缀
            import re
            futu_codes = []
            valid_symbols = []
            
            for sym in symbols:
                clean_sym = sym.lstrip('^')
                for suffix in ['-EU', '-JP', '-HK']:
                    if clean_sym.endswith(suffix):
                        clean_sym = clean_sym[:-len(suffix)]
                        break
                
                # 港股通常是5位纯数字
                if re.match(r'^[0-9]{5}$', clean_sym):
                    futu_codes.append(f"HK.{clean_sym}")
                    valid_symbols.append(clean_sym)
                # 美股代码通常为纯字母 (2-6位)
                elif re.match(r'^[A-Za-z]{2,6}$', clean_sym):
                    futu_codes.append(f"US.{clean_sym}")
                    valid_symbols.append(clean_sym)
                else:
                    logger.debug(f"[富途] 自动过滤非适用代码: {sym}")
            
            if not futu_codes:
                return True, "无适用富途的数据标的", self.prices

            new_codes = [c for c in futu_codes if c not in self.subscribed_codes]
            
            # 订阅新增加的股票，指定 Session.ALL 获取盘前盘后夜盘全时段数据
            if new_codes:
                ret, data = self.ctx.subscribe(new_codes, [SubType.QUOTE], session=Session.ALL)
                if ret != 0:
                    logger.warning(f"[富途] 订阅失败: {data}（连接保留，下次重试）")
                    return False, f"富途API未运行 (订阅失败): {data}", self.prices
                self.subscribed_codes.update(new_codes)
                logger.info(f"[富途] 已订阅: {', '.join(new_codes)}")
            
            # 获取实时报价
            ret, data = self.ctx.get_stock_quote(futu_codes)
            if ret == 0:
                for _, row in data.iterrows():
                    code = row['code'].replace('US.', '').replace('HK.', '')
                    bid = 0.0
                    ask = 0.0
                    last = 0.0
                    
                    def safe_float(val):
                        if pd.isna(val) or val == 'N/A' or val == '': return 0.0
                        try:
                            return float(val)
                        except:
                            return 0.0

                    # 【核心逻辑】优先使用真正的买一价/卖一价
                    bid_0 = safe_float(row.get('bid_price_0'))
                    ask_0 = safe_float(row.get('ask_price_0'))
                    last_0 = safe_float(row.get('last_price'))
                    overnight_0 = safe_float(row.get('overnight_price'))
                    pre_0 = safe_float(row.get('pre_price'))
                    after_0 = safe_float(row.get('after_price'))
                    
                    # [V10.13] 打印富途裸数据排查盘口问题
                    logger.info(f"【富途裸数据】 {code}: bid={bid_0} ask={ask_0} last={last_0} overnight={overnight_0} pre={pre_0} after={after_0}")
                    
                    if bid_0 > 0: bid = bid_0
                    if ask_0 > 0: ask = ask_0
                    if last_0 > 0: last = last_0
                    
                    # [V10.13] 真实盘口修补逻辑
                    # 规则：有真实 bid/ask 时用真实数据；没有时存 last_price（上游显示价格,"等待数据"）
                    if bid > 0 or ask > 0:
                        # 一边有真实盘口，另一边缺失 → 用 last 补齐
                        if bid > 0 and ask <= 0:
                            ask = last if last > 0 else bid
                        elif ask > 0 and bid <= 0:
                            bid = last if last > 0 else ask
                        # 两边都有 → 真实价差
                    # 两边都缺失（bid=0, ask=0）：保留 last 作为价格，bid/ask 为 0
                    
                    # 只要有 last 就存，上游决定 bid/ask 的显示
                    if last > 0:
                        self.prices[code] = {
                            'bid': bid,
                            'ask': ask,
                            'last': last
                        }
                
                # 控制台心跳回显 (每30秒打印一次)
                current_time = time.time()
                if current_time - self.last_log_time >= 30:
                    if self.prices:
                        price_strs = [f"{k}=${v.get('last', 0):.2f}" for k, v in self.prices.items()]
                        logger.info(f"[富途] 实时价格: {', '.join(price_strs)}")
                    self.last_log_time = current_time
                
                # [V10.13] 如果没有任何标的获取到真实盘口（如非交易时段），返回失败而非成功
                if not self.prices:
                    return False, "非交易时段，无真实盘口数据", self.prices
                return True, "成功获取富途价格", self.prices
            else:
                logger.warning(f"[富途] 获取数据失败: {data}（连接保留，下次重试）")
                return False, f"富途API未运行: {data}", self.prices
                
        except Exception as e:
            logger.warning(f"[富途] get_prices 异常: {e}")
            err_msg = str(e)
            if "refused" in err_msg.lower() or "10061" in err_msg:
                logger.warning("[富途] 无法连接到OpenD，已永久禁用后续自动重试。如需使用请重启系统。")
                self.disabled = True
                return False, "富途API未运行 (连接被拒绝)", self.prices
            logger.error(f"[富途] 异常: {err_msg}")
            return False, f"富途接口异常: {err_msg}", self.prices
    
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
