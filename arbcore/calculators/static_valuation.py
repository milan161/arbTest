# -*- coding: utf-8 -*-
# static_valuation.py - 静态估值核心计算引擎 (工业级 V2.2)

import pandas as pd
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
# [AI-2026-07-09] 导入新增的指数/亚洲/LOF估值函数
from .valuation_math import (
    calculate_magic_valuation, 
    calculate_basket_valuation,
    calculate_index_valuation,
    calculate_asia_valuation,
    calculate_lof_premium
)

logger = logging.getLogger(__name__)

class StaticValuationCalculator:
    def __init__(self, db_manager):
        self.db = db_manager
        
    def process_fund(self, fund_config: Dict[str, Any]):
        """
        计算单只基金的静态估值历史并存入数据库
        """
        code = str(fund_config.get('code', ''))
        name = fund_config.get('name', '')
        if not code: return False
        
        logger.info(f"📊 [静态估值] 开始计算: {name} ({code})")
        
        # 1. 获取基础数据 (A股收盘价、净值、汇率、因子)
        # 暂时保留部分 SQL 以保证联表查询效率，但未来应封装进 Manager
        conn = self.db._get_conn()
        try:
            # [AI-2026-06-28] 改用 unified_fund_history（废弃 fund_data）
            query = """
                SELECT 
                    a.date, a.price as close, a.nav, 
                    c.usd_cny_mid as exchange_rate,
                    b.position, b.hedge, b.calibration
                FROM unified_fund_history a
                LEFT JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
                LEFT JOIN exchange_rate c ON a.date = c.date
                WHERE a.fund_code = ?
                ORDER BY a.date DESC LIMIT 40
            """
            df = pd.read_sql(query, conn, params=(code,))
            if df.empty:
                logger.warning(f"  ⚠️ [{name}] 基础行情数据为空，跳过")
                return False

            # 获取底层资产价格
            portfolio = fund_config.get('valuation_portfolio', []) or fund_config.get('hedging_portfolio', [])
            primary_sym = self._identify_primary_symbol(fund_config)
            
            # 批量获取持仓价格
            for item in portfolio:
                sym = item.get('symbol', '').replace('^', '')
                # 处理区域后缀
                if any(suffix in sym for suffix in ['-JP', '-EU', '-HK']):
                    sym = f"^{sym}"
                
                etf_df = pd.read_sql(f'SELECT date, COALESCE(NULLIF(netvalue, 0), price) as "{sym}" FROM usa_etf_daily_prices WHERE symbol = ?', conn, params=(sym,))
                df = pd.merge(df, etf_df, on='date', how='left')
                
                # 获取权重
                weight_df = pd.read_sql('SELECT date, weight FROM fund_basket_weights WHERE fund_code = ? AND underlying_symbol = ?', conn, params=(code, sym))
                weight_df.rename(columns={'weight': f'{sym}_weight'}, inplace=True)
                df = pd.merge(df, weight_df, on='date', how='left')

            # 2. 执行计算
            df = self._calculate_history(df, portfolio, primary_sym, fund_config)
            
            # 3. 保存结果
            self._save_results(code, df)
            return True
            
        except Exception as e:
            logger.error(f"  ❌ [{name}] 计算异常: {e}")
            return False
        finally:
            conn.close()

    def _identify_primary_symbol(self, fund_config: Dict) -> Optional[str]:
        """识别主对冲锚点"""
        portfolio = fund_config.get('valuation_portfolio', []) or fund_config.get('hedging_portfolio', [])
        if not portfolio: return None
        
        first_sym = portfolio[0].get('symbol', '').replace('^', '').split('-')[0]
        # 优先匹配已知的大宗锚点
        base_syms = ['GLD', 'USO', 'XOP', 'XBI', 'SLV', 'SPY', 'QQQ']
        for bs in base_syms:
            if bs in first_sym: return bs
        return first_sym

    def _calculate_history(self, df: pd.DataFrame, portfolio: List[Dict], primary_sym: str, fund_config: Dict) -> pd.DataFrame:
        """核心历史推演循环"""
        df = df.sort_values('date', ascending=False).reset_index(drop=True)
        df['static_val'] = None
        df['val_error'] = None
        
        # 继承因子权重（bfill 向前填充，处理节假日权重缺失）
        for item in portfolio:
            sym = item.get('symbol', '').replace('^', '')
            # 处理区域后缀 — 和 merge 时保持一致
            if any(suffix in sym for suffix in ['-JP', '-EU', '-HK']):
                sym = f"^{sym}"
            w_col = f"{sym}_weight"
            if w_col in df.columns:
                df[w_col] = df[w_col].bfill().fillna(item.get('weight', 0))
        
        # 遍历日期进行推演
        for i in range(len(df)):
            row = df.iloc[i]
            # 寻找 T-1 基准日 (最多回溯 15 个自然行以跨过周末/假期)
            base_row = None
            for j in range(i + 1, min(i + 15, len(df))):
                candidate = df.iloc[j]
                if pd.notna(candidate['nav']) and candidate['nav'] > 0 and pd.notna(candidate['exchange_rate']):
                    base_row = candidate
                    break
            
            if base_row is None: continue
            
            # [AI-2026-06-28] 检查基准日跨度，超过 5 个自然日说明中间有长假（端午/春节），跳过计算
            from datetime import datetime as _dt
            try:
                base_dt = _dt.strptime(str(base_row['date']), '%Y-%m-%d')
                curr_dt = _dt.strptime(str(row['date']), '%Y-%m-%d')
                gap_days = (curr_dt - base_dt).days
                if gap_days > 5:
                    logger.info(f"  ⏭️ [{code}] {row['date']} 距基准日 {base_row['date']} 跨越 {gap_days} 天（长假），跳过静态估值")
                    continue
            except:
                pass
            
            # 计算逻辑
            val = self._deduce_valuation(row, base_row, portfolio, primary_sym, fund_config)
            if val:
                df.at[i, 'static_val'] = round(val, 4)
                if pd.notna(row['nav']) and row['nav'] > 0:
                    df.at[i, 'val_error'] = (val - row['nav']) / row['nav']
                    
        return df

    def _deduce_valuation(self, row, base_row, portfolio, primary_sym, fund_config) -> Optional[float]:
        """单点估值推演"""
        b_nav = base_row['nav']
        b_fx = base_row['exchange_rate']
        c_fx = row['exchange_rate']
        position = base_row['position']
        if pd.isna(position):
            # 降级从配置读取
            position = fund_config.get('holdings', {}).get('equity_ratio', 100.0) / 100.0
        
        valuation_method = fund_config.get('valuation_method', '')
        
        # 0. 明确指定走纯指数估值（跳过魔法/矩阵）
        if valuation_method == 'index' or valuation_method == 'equity_asia' or valuation_method == 'lof_domestic':
            related_index = fund_config.get('related_index', '')
            if related_index and related_index in row and related_index in base_row:
                c_idx = row[related_index]
                b_idx = base_row[related_index]
                if pd.notna(c_idx) and pd.notna(b_idx) and c_idx > 0 and b_idx > 0:
                    if valuation_method == 'equity_asia':
                        return calculate_asia_valuation(b_nav, position, c_idx, b_idx, c_fx, b_fx)
                    elif valuation_method == 'lof_domestic':
                        return calculate_lof_premium(b_nav, position, c_idx, b_idx, c_fx, b_fx)
                    else:
                        return calculate_index_valuation(b_nav, position, c_idx, b_idx, c_fx, b_fx)
                        
        # 1. 尝试魔法公式 (O(1))
        if valuation_method == '' or valuation_method == 'etf':
            b_hedge = base_row['hedge']
            if pd.notna(b_hedge) and b_hedge > 0 and primary_sym in row:
                c_price = row[primary_sym]
                val = calculate_magic_valuation(b_nav, position, c_price, c_fx, b_hedge)
                if val: return val
            
        # 2. 尝试矩阵公式 (一篮子权重) - ETF 模式下若无 hedge 也应 fallback 到此处 (Level 2)
        if valuation_method == '' or valuation_method == 'basket' or valuation_method == 'etf':
            items = []
            for p in portfolio:
                sym = p.get('symbol', '').replace('^', '')
                if any(suffix in sym for suffix in ['-JP', '-EU', '-HK']): sym = f"^{sym}"
                
                if sym in row and sym in base_row:
                    items.append({
                        'current_price': row[sym],
                        'base_price': base_row[sym],
                        'weight': row.get(f"{sym}_weight", p.get('weight', 0)) / 100.0
                    })
            
            basket_val = calculate_basket_valuation(b_nav, position, c_fx, b_fx, items)
            if basket_val:
                return basket_val
        
        # [AI-2026-07-09] 3. 指数估值公式（无 hedge、无 basket 的兜底）
        # 适用：QDII日本（513000/513520/159866）、QDII亚洲、国内LOF
        related_index = fund_config.get('related_index', '')
        if related_index and related_index in row and related_index in base_row:
            c_idx = row[related_index]
            b_idx = base_row[related_index]
            if pd.notna(c_idx) and pd.notna(b_idx) and c_idx > 0 and b_idx > 0:
                # 根据 valuation_method 选择对应函数
                valuation_method = fund_config.get('valuation_method', '')
                if valuation_method == 'equity_asia':
                    return calculate_asia_valuation(b_nav, position, c_idx, b_idx, c_fx, b_fx)
                elif valuation_method == 'lof_domestic':
                    return calculate_lof_premium(b_nav, position, c_idx, b_idx, c_fx, b_fx)
                else:
                    return calculate_index_valuation(b_nav, position, c_idx, b_idx, c_fx, b_fx)
        
        return None

    def _save_results(self, fund_code: str, df: pd.DataFrame):
        """保存结果到数据库"""
        conn = self.db._get_conn()
        cursor = conn.cursor()
        try:
            for _, row in df.iterrows():
                if pd.notna(row['static_val']):
                    # [AI-2026-06-28] 直接写入 unified_fund_history（废弃 fund_data）
                    cursor.execute("""
                        INSERT INTO unified_fund_history (date, fund_code, static_val, valuation_error, calibration)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(date, fund_code) DO UPDATE SET 
                            static_val = excluded.static_val,
                            valuation_error = excluded.valuation_error
                    """, (row['date'], fund_code, row['static_val'], row['val_error'], row.get('calibration')))
            conn.commit()
        finally:
            conn.close()
