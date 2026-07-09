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

# [AI-2026-07-09] 新增：指数估值公式（用于 QDII日本、无 hedge 的指数基金）
def calculate_index_valuation(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float,
    base_fx: float
) -> Optional[float]:
    """
    指数估值公式（无 hedge、无 basket 的兜底逻辑）。
    
    适用场景：
    - QDII日本（513000、513520、159866）跟踪日经225
    - QDII亚洲（161725、161726）跟踪港股指数
    - 国内LOF（A股指数基金）
    
    公式：估值 = T-1净值 × (1 + 仓位 × (指数T/指数T-1 × 汇率T/汇率T-1 - 1))
    
    参数：
    - base_nav: T-1日净值
    - position: 仓位比例 (0-1)，如 0.95 表示 95%
    - current_idx: 指数当前值（T日）
    - base_idx: 指数基准值（T-1日）
    - current_fx: 当前汇率（T日）
    - base_fx: 基准汇率（T-1日）
    
    返回：估值（float）或 None（数据不足）
    """
    if not all([base_nav, position, current_idx, base_idx, current_fx, base_fx]):
        return None
    if base_nav <= 0 or base_idx <= 0 or base_fx <= 0:
        return None
    if current_idx <= 0 or current_fx <= 0:
        return None
        
    # 指数涨跌幅
    idx_change = current_idx / base_idx
    
    # 汇率涨跌幅
    fx_change = current_fx / base_fx
    
    # 净值变动 = 仓位 × (指数涨跌 × 汇率涨跌 - 1)
    net_ratio = position * (idx_change * fx_change - 1.0)
    
    return base_nav * (1.0 + net_ratio)


# [AI-2026-07-09] 新增：亚洲市场估值公式（港股指数，与指数公式相同但语义区分）
def calculate_asia_valuation(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float,
    base_fx: float
) -> Optional[float]:
    """
    亚洲市场估值公式（港股指数基金）。
    
    适用场景：
    - QDII亚洲（161725 嘉实恒生H股、161726 招商标普港股）
    - 跟踪港股指数（HSI、HSCEI 等）
    
    公式与 calculate_index_valuation 相同：
    估值 = T-1净值 × (1 + 仓位 × (指数T/指数T-1 × 汇率T/汇率T-1 - 1))
    
    区别在于汇率处理：
    - 港股使用港币汇率（HKD/CNY）
    - 日股使用日元汇率（JPY/CNY）
    """
    # 港股和日股的公式完全一致，汇率已在参数中区分
    return calculate_index_valuation(
        base_nav, position, current_idx, base_idx, current_fx, base_fx
    )


# [AI-2026-07-09] 新增：国内 LOF 估值公式（A股指数，无汇率）
def calculate_lof_premium(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float = 1.0,
    base_fx: float = 1.0
) -> Optional[float]:
    """
    国内 LOF 估值公式（A股指数基金，无汇率）。
    
    适用场景：
    - 国内 LOF（501018、501025 等）跟踪 A股指数
    - 汇率固定为 1.0（无跨境）
    
    公式：估值 = T-1净值 × (1 + 仓位 × (指数T/指数T-1 - 1))
    """
    return calculate_index_valuation(
        base_nav, position, current_idx, base_idx, current_fx, base_fx
    )
