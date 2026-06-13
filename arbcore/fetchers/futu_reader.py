# -*- coding: utf-8 -*-
"""
futu_reader.py - 富途行情读取器模块

复用自 LOFarb 项目，已稳定运行
功能：通过富途 OpenD 获取美股/港股实时行情
"""

import time
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
    
    def __init__(self, host='127.0.0.1', port=11111):
        """
        Args:
            host: 富途 OpenD 地址
            port: 富途 OpenD 端口
        """
        self.ctx = None
        self.host = host
        self.port = port
        self.prices = {}  # {symbol: {'bid': ..., 'ask': ..., 'last': ...}}
        self.subscribed_codes = set()
        self.last_connect_time = 0
        self.last_log_time = 0
        self.disabled = False  # 如果连接失败，标记为禁用，防止无限重试
        
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
            return False, "富途API已被禁用 (连接曾被拒绝)", self.prices
            
        try:
            # 限制重连频率，避免富途OpenD未启动时狂刷错误
            if self.ctx is None:
                if time.time() - self.last_connect_time < 60:
                    return False, "富途API未运行 (等待重连...)", self.prices
                self.last_connect_time = time.time()
                
                # 静音富途底层日志
                try:
                    import futu
                    futu.SysConfig.set_all_thread_daemon(True)
                    futu.SysConfig.set_client_info('ArbDashboard')
                except:
                    pass
                
                logger.info(f"[富途] 尝试连接 OpenD ({self.host}:{self.port})...")
                self.ctx = OpenQuoteContext(host=self.host, port=self.port)
                self.subscribed_codes = set()
            
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
            
            # 订阅新增加的股票，指定 Session.ALL 获取夜盘
            if new_codes:
                ret, data = self.ctx.subscribe(new_codes, [SubType.QUOTE], session=Session.ALL)
                if ret != 0:
                    self.close()
                    logger.warning(f"[富途] 订阅失败: {data}")
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
                    
                    if bid_0 > 0: bid = bid_0
                    if ask_0 > 0: ask = ask_0
                    if last_0 > 0: last = last_0
                    
                    # 如果买一/卖一都缺失，使用夜盘/盘前/盘后/最新价作为兜底
                    if bid <= 0 or ask <= 0:
                        fallback_price = 0.0
                        overnight = safe_float(row.get('overnight_price'))
                        pre = safe_float(row.get('pre_price'))
                        after = safe_float(row.get('after_price'))
                        
                        if overnight > 0: fallback_price = overnight
                        elif pre > 0: fallback_price = pre
                        elif after > 0: fallback_price = after
                        elif last_0 > 0: fallback_price = last_0
                        
                        if fallback_price > 0:
                            if bid <= 0:
                                bid = fallback_price
                            if ask <= 0:
                                ask = fallback_price
                    
                    # 如果仍有缺失，用last_price兜底bid/ask
                    if bid <= 0 and last > 0:
                        bid = last
                    if ask <= 0 and last > 0:
                        ask = last
                    if bid > 0 and ask <= 0:
                        ask = bid
                    
                    if bid > 0:
                        self.prices[code] = {
                            'bid': bid,
                            'ask': ask,
                            'last': last if last > 0 else bid
                        }
                
                # 控制台心跳回显 (每30秒打印一次)
                current_time = time.time()
                if current_time - self.last_log_time >= 30:
                    if self.prices:
                        price_strs = [f"{k}=${v['bid']:.2f}" for k, v in self.prices.items()]
                        logger.info(f"[富途] 实时价格: {', '.join(price_strs)}")
                    self.last_log_time = current_time
                
                return True, "成功获取富途价格", self.prices
            else:
                self.close()
                logger.warning(f"[富途] 获取数据失败: {data}")
                return False, f"富途API未运行: {data}", self.prices
                
        except Exception as e:
            self.close()
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
