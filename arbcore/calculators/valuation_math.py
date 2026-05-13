# -*- coding: utf-8 -*-
# valuation_math.py - 估值核心数学引擎 (大一统魔法公式)

def calculate_magic_valuation(base_nav: float, position: float, current_asset_price: float, current_fx: float, hedge_value: float) -> float:
    """
    利用常量折叠（Hedge对冲值）进行 O(1) 极速推演的大一统函数。
    
    数学推导：
    传统公式: 估值 = T-1净值 * (1 + 仓位 * ((T日价格 * T日汇率) / (T-1价格 * T-1汇率) - 1))
    由于 Hedge = (T-1价格 * T-1汇率) / T-1净值
    代入化简后: 估值 = T-1净值 * (1 - 仓位) + (T日价格 * T日汇率) * 仓位 / Hedge
    
    适用场景：
    1. 纯ETF实时估值:     current_asset_price = T日ETF现价,        hedge_value = API_Hedge
    2. 期货校准实时估值:  current_asset_price = T日期货现价 / 校准值, hedge_value = API_Hedge
    3. 纯期货映射估值:    current_asset_price = T日期货现价,        hedge_value = 物理反推的Futures_Hedge
    """
    if not hedge_value or hedge_value <= 0:
        return None
    if not current_asset_price or current_asset_price <= 0:
        return None
    if not current_fx or current_fx <= 0:
        return None
        
    # 大一统魔法公式（修正版：第二项需乘以仓位）
    return base_nav * (1.0 - position) + (current_asset_price * current_fx) * position / hedge_value

def calculate_base_denominator(base_nav: float, position: float, hedge_value: float) -> float:
    """
    [辅助函数] 逆向还原分母
    如果你在某些旧版逻辑中，非要用到 "T-1日基准价格 * T-1日基准汇率" 这个绝对分母，
    无需去查数据库的 T-1 行情表，直接用本函数还原即可。
    
    公式：分母 = Hedge * Base_NAV * Position
    """
    if not hedge_value or hedge_value <= 0:
        return None
    if not base_nav or base_nav <= 0:
        return None
        
    return hedge_value * base_nav * position
