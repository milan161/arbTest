# -*- coding: utf-8 -*-
# dynamic_valuation.py - 盘中实时动态估值引擎 (为后台轮动套利与监控提供极速计算)

import pandas as pd
import logging
from .valuation_math import calculate_magic_valuation

logger = logging.getLogger(__name__)

class DynamicValuationCalculator:
    def __init__(self, db_manager):
        self.db = db_manager
        # 缓存 T-1 基准数据，避免盘中高频调用时反复查库卡死 IO
        self._base_data_cache = {}
        
    def _get_base_data(self, fund_code):
        """获取 T-1 完美基准数据 (带内存缓存)"""
        if fund_code in self._base_data_cache:
            return self._base_data_cache[fund_code]
            
        conn = self.db._get_conn()
        try:
            # 寻找最新有净值和汇率的一天作为推演基石
            query = f"""
                SELECT * FROM fund_history_{fund_code} 
                WHERE nav IS NOT NULL AND nav > 0 AND exchange_rate IS NOT NULL AND exchange_rate > 0
                ORDER BY date DESC LIMIT 1
            """
            df = pd.read_sql(query, conn)
            if not df.empty:
                base_row = df.iloc[0].to_dict()
                self._base_data_cache[fund_code] = base_row
                return base_row
            return None
        except Exception as e:
            logger.error(f"获取 {fund_code} 基准数据失败: {e}")
            return None
        finally:
            conn.close()

    def refresh_cache(self):
        """每日 012 静态计算完毕后调用此方法，释放并刷新 T-1 缓存"""
        self._base_data_cache.clear()

    def calculate(self, fund_config, current_fx, current_etfs, current_futures, gold_calib=10.9067, oil_calib=0.8227):
        """
        推演实时估值矩阵 (O(1) 时间复杂度)
        :param fund_config: 基金配置字典 (从 YAML 加载)
        :param current_fx: 实时汇率 (float)
        :param current_etfs: 实时 ETF 价格字典 {'GLD': 230.5, 'USO': 75.2, ...}
        :param current_futures: 实时期货价格字典 {'GC': 2350.5, 'CL': 80.2, ...}
        :return: dict 包含各维度估值及 T-1 基准日期
        """
        code = str(fund_config.get('code', ''))
        base_data = self._get_base_data(code)
        if not base_data:
            return None
            
        b_nav = base_data.get('nav')
        b_fx = base_data.get('exchange_rate')
        if not b_nav or not b_fx or b_nav <= 0 or b_fx <= 0:
            return None
            
        # 核心修正1：优先使用基准日(T-1)真实的仓位，严禁直接使用 YAML 配置里的最新(T)仓位
        db_pos = base_data.get('仓位', base_data.get('position'))
        if pd.notna(db_pos) and db_pos != '无' and db_pos != '':
            try:
                pf = float(db_pos)
                position = pf if pf <= 1 else pf / 100.0
            except:
                pos_val = fund_config.get('holdings', {}).get('equity_ratio', 100.0)
                position = (pos_val / 100.0) if pos_val > 1 else pos_val
        else:
            pos_val = fund_config.get('holdings', {}).get('equity_ratio', 100.0)
            position = (pos_val / 100.0) if pos_val > 1 else pos_val
            
        fx_change = current_fx / b_fx if current_fx > 0 else 1.0
        
        # 核心修正2：严格从基准日(T-1)提取魔法因子，严禁使用 get_latest_fund_factor 造成时间穿透
        hedge = base_data.get('hedge')
        if pd.isna(hedge) or hedge == '无' or hedge == '': hedge = None
        else: hedge = float(hedge)
        
        calibration = base_data.get('calibration')
        if pd.isna(calibration) or calibration == '无' or calibration == '': calibration = None
        else: calibration = float(calibration)

        result = {
            'etf_val': None,
            'fut_calib_val': None,
            'pure_fut_val': None,
            'base_date': base_data.get('date')
        }
        
        # --- 1. 纯 ETF 实时估值 (优先走魔法捷径) ---
        portfolio = fund_config.get('valuation_portfolio', []) or fund_config.get('hedging_portfolio', [])
        
        # 仅限单一ETF使用魔法捷径，多区域组合强制退回矩阵
        if hedge and portfolio and len(portfolio) == 1:
            primary_sym = portfolio[0].get('symbol', '').replace('^', '')
            base_sym = 'GLD' if 'GLD' in primary_sym else ('USO' if 'USO' in primary_sym else ('XOP' if 'XOP' in primary_sym else ('XBI' if 'XBI' in primary_sym else ('SLV' if 'SLV' in primary_sym else ('SPY' if 'SPY' in primary_sym else ('QQQ' if 'QQQ' in primary_sym else primary_sym))))))
            c_price = current_etfs.get(base_sym, 0.0)
            
            result['etf_val'] = calculate_magic_valuation(b_nav, position, c_price, current_fx, hedge)
                
        # 如果捷径失败 (如多区域复杂持仓且未获取到Hedge)，回退传统的基准价推演
        if not result['etf_val'] and b_fx > 0:
            w_change, valid_w, has_etf_data = 0.0, 0.0, True
            for item in portfolio:
                sym = item.get('symbol', '').replace('^', '')
                weight = item.get('weight', 0.0) / 100.0
                if weight <= 0: continue
                
                base_sym = 'GLD' if 'GLD' in sym else ('USO' if 'USO' in sym else ('XOP' if 'XOP' in sym else ('XBI' if 'XBI' in sym else ('SLV' if 'SLV' in sym else ('SPY' if 'SPY' in sym else ('QQQ' if 'QQQ' in sym else sym))))))
                c_price = current_etfs.get(base_sym, 0.0)
                b_price = base_data.get(sym) or base_data.get(f"^{sym}", 0.0)
                
                if c_price > 0 and b_price > 0:
                    w_change += (c_price / b_price) * weight
                    valid_w += weight
                else:
                    has_etf_data = False
                    
            if has_etf_data and valid_w > 0:
                if valid_w < 0.98 or valid_w > 1.02: w_change = w_change / valid_w
                result['etf_val'] = b_nav * (1 + position * (w_change * fx_change - 1))
            
        # --- 2. 计算 期货校准 与 纯期货 实时估值 ---
        category = fund_config.get('category', '')
        fut_sym = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ'}.get(fund_config.get('trade_future', '').upper(), fund_config.get('trade_future', '').upper())
        if not fut_sym:
            fut_sym = 'GC' if category == '黄金' else ('CL' if category == '原油' and code != '162411' else ('NQ' if code in ['161130', '161128'] else ('ES' if code in ['161125', '161127'] else None)))
                
        if fut_sym and fut_sym in current_futures:
            c_fut = current_futures.get(fut_sym, 0.0)
            if c_fut > 0:
                # [魔法] 期货校准实时估值 (利用 calibration 将期货等效为 ETF)
                eff_calib = calibration if calibration and calibration > 0 else (gold_calib if fut_sym == 'GC' else (oil_calib if fut_sym == 'CL' else None))
                if eff_calib and hedge and len(portfolio) == 1:
                    c_future_etf = c_fut / eff_calib
                    result['fut_calib_val'] = calculate_magic_valuation(b_nav, position, c_future_etf, current_fx, hedge)

                # [魔法] 纯期货映射估值 (物理反推 Futures_Hedge 分母)
                b_fut = base_data.get('期货结算价', 0.0)
                if b_fut > 0:
                    derived_future_hedge = (b_fut * b_fx) / (b_nav * position)
                    result['pure_fut_val'] = calculate_magic_valuation(b_nav, position, c_fut, current_fx, derived_future_hedge)
                            
        return result
