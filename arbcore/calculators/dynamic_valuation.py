# -*- coding: utf-8 -*-
# dynamic_valuation.py - 盘中实时动态估值引擎 (工业级 V2.2)

import pandas as pd
import logging
import time
from typing import Dict, Any, Optional
from .valuation_math import calculate_magic_valuation, calculate_basket_valuation

logger = logging.getLogger(__name__)

class DynamicValuationCalculator:
    def __init__(self, db_manager):
        self.db = db_manager
        # 缓存 T-1 基准数据，避免盘中高频调用时反复查库卡死 IO
        self._base_data_cache = {}
        self._cache_timestamp = {}
    
    def refresh_cache(self):
        """刷新基准数据缓存"""
        self._base_data_cache.clear()
        self._cache_timestamp.clear()

    def get_base_data(self, fund_code: str) -> Optional[Dict[str, Any]]:
        """获取 T-1 完美基准数据 (自带 10 分钟自动过期机制)"""
        current_time = time.time()
        if fund_code in self._base_data_cache:
            # 10分钟 (600秒) 过期机制
            if current_time - self._cache_timestamp.get(fund_code, 0) < 600:
                return self._base_data_cache[fund_code]
            else:
                # 缓存过期，安全剔除
                del self._base_data_cache[fund_code]


        conn = self.db._get_conn()
        try:
            # 联表查询：净值 + 因子 + 汇率
            query = """
                SELECT 
                    a.date, a.nav, a.price as close, 
                    c.usd_cny_mid as exchange_rate,
                    b.position, b.hedge, b.calibration
                FROM fund_data a
                JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
                JOIN exchange_rate c ON a.date = c.date
                WHERE a.fund_code = ? AND a.nav IS NOT NULL AND a.nav > 0
                ORDER BY a.date DESC LIMIT 1
            """
            df = pd.read_sql(query, conn, params=(fund_code,))
            if df.empty: return None
            
            base_row = df.iloc[0].to_dict()
            base_date = base_row['date']
            
            # 补充底层 ETF 基准价格
            etf_df = pd.read_sql(
                "SELECT symbol, COALESCE(NULLIF(netvalue, 0), price) as price FROM usa_etf_daily_prices WHERE date = ?", 
                conn, params=(base_date,)
            )
            for _, r in etf_df.iterrows():
                # 保留完整符号（如 ^USO-EU），不要去掉 ^ 前缀
                sym = r['symbol']
                base_row[sym] = r['price']
                # 同时存一份不带 ^ 的以防匹配失败
                if sym.startswith('^'):
                    base_row[sym[1:]] = r['price']
                else:
                    base_row['^' + sym] = r['price']

            self._base_data_cache[fund_code] = base_row
            self._cache_timestamp[fund_code] = time.time()
            return base_row
        except Exception as e:
            logger.error(f"获取 {fund_code} 基准数据失败: {e}")
            return None
        finally:
            conn.close()

    def calculate(self, fund_config: Dict, current_fx: float, current_etfs: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """
        实时估值矩阵推演
        """
        code = str(fund_config.get('code', ''))
        base_data = self.get_base_data(code)
        if not base_data: return None
        
        b_nav = base_data['nav']
        b_fx = base_data['exchange_rate']
        position = base_data['position']
        if pd.isna(position):
            position = fund_config.get('holdings', {}).get('equity_ratio', 100.0) / 100.0
            
        # 1. 尝试魔法公式 (Hedge)
        b_hedge = base_data['hedge']
        portfolio = fund_config.get('valuation_portfolio', []) or fund_config.get('hedging_portfolio', [])
        
        rt_val = None
        if pd.notna(b_hedge) and b_hedge > 0 and len(portfolio) == 1:
            # 分子：实时价格，去掉 ^ 前缀和 -EU/-JP/-HK 后缀，得到基础代码 USO/GLD
            full_symbol = portfolio[0].get('symbol', '')
            primary_sym = full_symbol.lstrip('^')  # ^USO-EU → USO-EU
            for suffix in ['-EU', '-JP', '-HK']:
                if primary_sym.endswith(suffix):
                    primary_sym = primary_sym[:-len(suffix)]  # USO-EU → USO
                    break
            c_price = current_etfs.get(primary_sym, 0)
            if not c_price or c_price <= 0:
                c_price = base_data.get(full_symbol, 0)
            if c_price > 0:
                rt_val = calculate_magic_valuation(b_nav, position, c_price, current_fx, b_hedge)
        
        # 2. 尝试矩阵公式
        if rt_val is None:
            items = []
            for p in portfolio:
                # 分母：基准价格，用完整符号查数据库
                full_symbol = p.get('symbol', '')
                b_price = base_data.get(full_symbol)
                # 分子：实时价格，去掉 ^ 前缀和 -EU/-JP/-HK 后缀，得到基础代码
                c_sym = full_symbol.lstrip('^')  # ^USO-EU → USO-EU
                for suffix in ['-EU', '-JP', '-HK']:
                    if c_sym.endswith(suffix):
                        c_sym = c_sym[:-len(suffix)]  # USO-EU → USO
                        break
                c_price = current_etfs.get(c_sym, 0)
                if not c_price or c_price <= 0:
                    c_price = b_price
                if b_price and c_price > 0:
                    items.append({
                        'current_price': c_price,
                        'base_price': b_price,
                        'weight': p.get('weight', 0) / 100.0
                    })
            rt_val = calculate_basket_valuation(b_nav, position, current_fx, b_fx, items)
            
        if rt_val:
            return {
                'rt_val': round(rt_val, 4),
                'base_date': base_data['date'],
                'premium': (fund_config.get('current_price', 0) / rt_val - 1) if fund_config.get('current_price', 0) > 0 else None
            }
        return None
