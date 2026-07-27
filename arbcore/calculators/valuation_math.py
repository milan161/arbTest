# -*- coding: utf-8 -*-
# valuation_math.py - 估值公式兼容层（全部委托统一核心）
#
# 历史 5 个函数（magic / basket / index / asia / lof_premium）现已全部收敛到
# arbcore.calculators.unified_valuation.basket_valuation（单一篮子矩阵公式）。
# 魔法公式 = 单组件 + hedge 常量折叠；指数/亚洲/LOF = 单组件 weight=1.0 矩阵。
# 本文件仅作兼容外壳，避免破坏既有 import；新代码请直接用 unified_valuation。

import logging
from typing import Optional, List, Dict

from .unified_valuation import basket_valuation

logger = logging.getLogger(__name__)

def calculate_magic_valuation(
    base_nav: float, 
    position: float, 
    current_asset_price: float, 
    current_fx: float, 
    hedge_value: float
) -> Optional[float]:
    """魔法公式（hedge 常量折叠）。委托统一核心。"""
    if not all([base_nav, position, current_asset_price, current_fx, hedge_value]):
        return None
    return basket_valuation(
        base_nav, position,
        [{'symbol': '', 'current_price': current_asset_price, 'base_price': 1.0, 'weight': 1.0}],
        fx_base=1.0, fx_now=current_fx, hedge=hedge_value,
    )

def calculate_basket_valuation(
    base_nav: float,
    position: float,
    current_fx: float,
    base_fx: float,
    portfolio_items: List[Dict]
) -> Optional[float]:
    """一篮子资产矩阵推演公式。委托统一核心。"""
    return basket_valuation(base_nav, position, portfolio_items, fx_base=base_fx, fx_now=current_fx)

# [AI-2026-07-27] 指数估值公式（QDII日本 / QDII亚洲 / 国内LOF）：单组件 weight=1.0，hedge=None
def calculate_index_valuation(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float,
    base_fx: float
) -> Optional[float]:
    """指数估值公式（无 hedge）。委托统一核心（单组件矩阵）。"""
    return basket_valuation(
        base_nav, position,
        [{'symbol': '', 'current_price': current_idx, 'base_price': base_idx, 'weight': 1.0}],
        fx_base=base_fx, fx_now=current_fx, hedge=None,
    )


# [AI-2026-07-27] 亚洲市场估值公式：与指数公式一致，委托统一核心
def calculate_asia_valuation(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float,
    base_fx: float
) -> Optional[float]:
    """亚洲市场估值公式（港股指数）。委托统一核心。"""
    return calculate_index_valuation(base_nav, position, current_idx, base_idx, current_fx, base_fx)


# [AI-2026-07-27] 国内 LOF 估值公式（无汇率）。委托统一核心
def calculate_lof_premium(
    base_nav: float,
    position: float,
    current_idx: float,
    base_idx: float,
    current_fx: float = 1.0,
    base_fx: float = 1.0
) -> Optional[float]:
    """国内 LOF 估值公式（A股指数，无汇率）。委托统一核心。"""
    return calculate_index_valuation(base_nav, position, current_idx, base_idx, current_fx, base_fx)
