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
                    a.date, COALESCE(a.nav, b.nav) as nav, a.price as close, 
                    c.usd_cny_mid as exchange_rate,
                    b.position, b.hedge, b.calibration
                FROM unified_fund_history a
                LEFT JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
                LEFT JOIN exchange_rate c ON a.date = c.date
                WHERE a.fund_code = ? AND COALESCE(a.nav, b.nav) IS NOT NULL AND COALESCE(a.nav, b.nav) > 0
                ORDER BY a.date DESC LIMIT 1
            """
            df = pd.read_sql(query, conn, params=(fund_code,))
            if df.empty: return None
            
            base_row = df.iloc[0].to_dict()
            base_date = base_row['date']
            
            # [AI-2026-07-07] 校验基准日是否有美股ETF数据；若为空（美国假期），向前回溯到有数据的最近日期
            # 先尝试从 fund_basket_weights 获取 ETF 代码，兜底用 related_index（单一ETF基金如162411）
            etf_syms = pd.read_sql(
                "SELECT DISTINCT underlying_symbol FROM fund_basket_weights WHERE fund_code = ?",
                conn, params=(fund_code,)
            )
            sym_list = []
            if not etf_syms.empty:
                sym_list = [s.replace('^', '') for s in etf_syms['underlying_symbol'].tolist() if s]
            if not sym_list:
                # 无 basket_weights → 用 related_index 作为单一ETF代码
                ri_df = pd.read_sql(
                    "SELECT related_index FROM unified_fund_list WHERE fund_code = ?",
                    conn, params=(fund_code,)
                )
                if not ri_df.empty:
                    ri = str(ri_df.iloc[0]['related_index'] or '').strip()
                    if ri and ri != '-' and ri != '0' and ri != 'nan':
                        sym_list = [ri]
            if sym_list:
                placeholders = ','.join('?' for _ in sym_list)
                etf_count = conn.execute(
                    f"SELECT COUNT(*) FROM usa_etf_daily_prices "
                    f"WHERE symbol IN ({placeholders}) AND date = ? AND price > 0",
                    (*sym_list, base_date)
                ).fetchone()[0]
                if etf_count == 0:
                    # 基准日无ETF数据 → 找最近一个有净值+ETF数据的日期
                    logger.info(f"  ⏭️ [{fund_code}] 基准日 {base_date} 无ETF数据（美国假期），向前回溯...")
                    corrected_df = pd.read_sql(f"""
                        SELECT a.date, COALESCE(a.nav, b.nav) as nav, a.price as close,
                               c.usd_cny_mid as exchange_rate,
                               b.position, b.hedge, b.calibration
                        FROM unified_fund_history a
                        LEFT JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
                        LEFT JOIN exchange_rate c ON a.date = c.date
                        WHERE a.fund_code = ? AND COALESCE(a.nav, b.nav) > 0
                          AND EXISTS (
                              SELECT 1 FROM usa_etf_daily_prices e
                              WHERE e.symbol IN ({placeholders}) AND e.date = a.date AND e.price > 0
                          )
                        ORDER BY a.date DESC LIMIT 1
                    """, conn, params=(fund_code, *sym_list))
                    if not corrected_df.empty:
                        base_row = corrected_df.iloc[0].to_dict()
                        base_date = base_row['date']
                        logger.info(f"  ✅ [{fund_code}] 回溯后基准日调整为 {base_date}")

            # [FIX] 当最新日期缺少 hedge/position 时，向前查找最近的有效数据
            if pd.isna(base_row.get('hedge')) or float(base_row.get('hedge', 0)) <= 0:
                try:
                    hedge_query = """
                        SELECT hedge, position 
                        FROM fund_daily_factors 
                        WHERE fund_code = ? AND hedge IS NOT NULL AND hedge > 0
                        ORDER BY date DESC LIMIT 1
                    """
                    hedge_df = pd.read_sql(hedge_query, conn, params=(fund_code,))
                    if not hedge_df.empty:
                        base_row['hedge'] = hedge_df.iloc[0]['hedge']
                        base_row['position'] = hedge_df.iloc[0]['position']
                except Exception as e:
                    logger.warning(f"获取 hedge 兜底数据失败 ({fund_code}): {e}")
            
            # 补充底层 ETF 基准价格（精确日期优先，取不到则往前找最近一日）
            etf_df = pd.read_sql(
                "SELECT symbol, COALESCE(NULLIF(netvalue, 0), price) as price, date "
                "FROM usa_etf_daily_prices WHERE date = ?", 
                conn, params=(base_date,)
            )
            if not etf_df.empty:
                for _, r in etf_df.iterrows():
                    sym = r['symbol']
                    base_row[sym] = r['price']
                    if sym.startswith('^'):
                        base_row[sym[1:]] = r['price']
                    else:
                        base_row['^' + sym] = r['price']
            # 兜底：对仍然缺失的 known ETF 取最近一条记录
            try:
                known_etfs = [s.strip() for s in (
                    'XLE,USO,GLD,XOP,SPY,QQQ,INDA,XBI,XLK,SLV,AGG,BOTZ,ARKK,ARKG,'
                    'SMH,SOXX,TLT,IWM,EEM,EWJ,HYG,LQD,GDX,GDXJ,^XLE-EU,^XLE-JP,'
                    '^XLE-HK,^USO-EU,^USO-JP,^USO-HK,^GLD-EU,^GLD-JP,^GLD-HK,'
                    '^INDA-EU,^INDA-JP,^INDA-HK'
                ).split(',') if s and s not in base_row]
                if known_etfs:
                    placeholders = ','.join('?' for _ in known_etfs)
                    fallback_df = pd.read_sql(
                        f"SELECT symbol, COALESCE(NULLIF(netvalue, 0), price) as price, MAX(date) as md "
                        f"FROM usa_etf_daily_prices "
                        f"WHERE symbol IN ({placeholders}) AND price > 0 AND date <= ? "
                        f"GROUP BY symbol",
                        conn, params=(*known_etfs, base_date)
                    )
                    for _, r in fallback_df.iterrows():
                        sym = r['symbol']
                        if sym not in base_row or not base_row.get(sym):
                            base_row[sym] = r['price']
                            if sym.startswith('^'):
                                base_row[sym[1:]] = r['price']
                            else:
                                base_row['^' + sym] = r['price']
            except Exception:
                pass

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
