# -*- coding: utf-8 -*-
# valuation_math.py - 估值核心数学引擎 (工业级 V2.0)

import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

def calculate_magic_valuation(
    base_nav: float, 
    position: float, 
    current_asset_price: float, 
    current_fx: float, 
    hedge_value: float
) -> Optional[float]:
    """
    利用常量折叠（Hedge对冲值）进行 O(1) 极速推演的大一统函数。
    
    公式: 估值 = T-1净值 * (1 - 仓位) + (T日价格 * T日汇率) / Hedge
    """
    if not all([base_nav, position, current_asset_price, current_fx, hedge_value]):
        return None
    if hedge_value <= 0 or current_asset_price <= 0 or current_fx <= 0:
        return None
        
    return base_nav * (1.0 - position) + (current_asset_price * current_fx) / hedge_value

def calculate_basket_valuation(
    base_nav: float,
    position: float,
    current_fx: float,
    base_fx: float,
    portfolio_items: List[Dict]
) -> Optional[float]:
    """
    一篮子资产矩阵推演公式（当缺失对冲因子时的兜底逻辑）。
    
    portfolio_items 格式: [{'current_price': 10, 'base_price': 9, 'weight': 0.5}, ...]
    """
    if not all([base_nav, base_fx, current_fx]) or base_fx <= 0 or current_fx <= 0:
        return None
        
    fx_change = current_fx / base_fx
    w_change = 0.0
    
    for item in portfolio_items:
        c_p = item.get('current_price', 0)
        b_p = item.get('base_price', 0)
        weight = item.get('weight', 0) # 可能为负（空头/对冲头寸）
        
        if c_p > 0 and b_p > 0 and weight != 0:
            w_change += (c_p / b_p) * weight
            
    if w_change == 0:
        return None
        
    net_ratio = position * (w_change * fx_change - 1.0)
    return base_nav * (1.0 + net_ratio)
