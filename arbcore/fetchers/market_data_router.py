# -*- coding: utf-8 -*-
"""
market_data_router.py - 市场数据路由服务

根据标的类型自动选择数据源：
- 美股 ETF (GLD, SPY, QQQ...) → IB / 富途
- A 股 ETF (SZ159560, SH510050...) → 通达信/新浪
- 港股 (00700...) → 富途/通达信
- 期货 (CU2409...) → 通达信
- 指数 (.INX, .NDX...) → 新浪
"""

import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class MarketDataRouter:
    """市场数据路由：根据标的类型选择数据源"""
    
    # 美股 ETF 代码模式（纯字母，2-6个字符）
    US_SYMBOL_PATTERN = re.compile(r'^[A-Z]{2,6}$')
    
    # A 股代码模式（6位数字，或带 SH/SZ 前缀）
    CN_SYMBOL_PATTERN = re.compile(r'^(SH|SZ)?[0-9]{6}$')
    
    # 港股代码模式（5位数字）
    HK_SYMBOL_PATTERN = re.compile(r'^[0-9]{5}$')
    
    # 期货代码模式（2位字母 + 4位数字，如 CU2409）
    FUTURES_PATTERN = re.compile(r'^[A-Z]{2}[0-9]{4,6}$')
    
    # 指数模式（以 . 开头）
    INDEX_PATTERN = re.compile(r'^\.[A-Z]+$')
    
    def __init__(self):
        self.ib_reader = None
        self.tdx_fetcher = None
        self.futu_fetcher = None
    
    def classify_symbol(self, symbol: str) -> str:
        """
        根据标的代码分类，返回数据源类型
        
        Returns:
            'us_stock', 'cn_stock', 'hk_stock', 'futures', 'index'
        """
        s = symbol.upper().strip()
        
        # 移除前缀 (SH, SZ)
        if s.startswith(('SH', 'SZ')):
            s = s[2:]
        
        # 指数
        if self.INDEX_PATTERN.match(s):
            return 'index'
        
        # 美股 ETF/股票（纯字母 2-6 位）
        if self.US_SYMBOL_PATTERN.match(s):
            return 'us_stock'
        
        # 港股（5 位数字）
        if self.HK_SYMBOL_PATTERN.match(s):
            return 'hk_stock'
        
        # 期货（2 字母 + 数字）
        if self.FUTURES_PATTERN.match(s):
            return 'futures'
        
        # A 股（6 位数字，或带 SH/SZ 前缀）
        if self.CN_SYMBOL_PATTERN.match(s):
            return 'cn_stock'
        
        # 默认返回 A 股
        logger.warning(f"无法识别标的类型: {symbol}，默认使用 A 股数据源")
        return 'cn_stock'
    
    def get_us_symbols_from_db(self) -> List[str]:
        """从数据库获取所有美股 ETF 标的（去重）"""
        import sqlite3
        conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT underlying_symbol FROM fund_basket_weights')
        rows = cursor.fetchall()
        conn.close()
        
        us_symbols = set()
        for symbol, in rows:
            symbol = symbol.strip().upper().replace('^', '')
            if self.US_SYMBOL_PATTERN.match(symbol):
                us_symbols.add(symbol)
        
        return sorted(us_symbols)
    
    def get_cn_symbols_from_db(self) -> List[str]:
        """从数据库获取所有 A 股标的（去重）"""
        import sqlite3
        conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT underlying_symbol FROM fund_basket_weights')
        rows = cursor.fetchall()
        conn.close()
        
        cn_symbols = set()
        for symbol, in rows:
            symbol = symbol.strip().upper()
            if self.CN_SYMBOL_PATTERN.match(symbol):
                cn_symbols.add(symbol)
        
        return sorted(cn_symbols)
    
    def fetch_us_prices(self, symbols: List[str]) -> Dict[str, dict]:
        """
        从 IB/富途获取美股实时价格
        
        Args:
            symbols: 美股 ETF 代码列表，如 ['GLD', 'SPY', 'QQQ']
        
        Returns:
            价格字典: {'GLD': {'bid': 230.5, 'ask': 230.6, 'last': 230.55}, ...}
        """
        if not symbols:
            return {}
        
        # TODO: 实现 IB/富途数据获取
        # 目前返回空字典，等待后续实现
        logger.info(f"从 IB/富途获取美股价格: {', '.join(symbols)}")
        return {}
    
    def fetch_cn_prices(self, symbols: List[str]) -> Dict[str, dict]:
        """
        从通达信/新浪获取 A 股实时价格
        
        Args:
            symbols: A 股代码列表，如 ['159560', '510050']
        
        Returns:
            价格字典
        """
        if not symbols:
            return {}
        
        # TODO: 实现通达信/新浪数据获取
        logger.info(f"从通达信/新浪获取 A 股价格: {', '.join(symbols)}")
        return {}
    
    def fetch_all_realtime_prices(self) -> Dict[str, dict]:
        """
        获取所有标的的实时价格（自动分类路由）
        
        Returns:
            统一价格字典: {'GLD': {...}, '159560': {...}, ...}
        """
        all_prices = {}
        
        # 获取美股标的
        us_symbols = self.get_us_symbols_from_db()
        if us_symbols:
            logger.info(f"路由: {len(us_symbols)} 只美股标的 → IB/富途")
            # all_prices.update(self.fetch_us_prices(us_symbols))
        
        # 获取 A 股标的
        cn_symbols = self.get_cn_symbols_from_db()
        if cn_symbols:
            logger.info(f"路由: {len(cn_symbols)} 只 A 股标的 → 通达信/新浪")
            # all_prices.update(self.fetch_cn_prices(cn_symbols))
        
        return all_prices


# 全局单例
router = MarketDataRouter()
