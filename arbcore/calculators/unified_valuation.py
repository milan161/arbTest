# -*- coding: utf-8 -*-
# unified_valuation.py — 统一估值核心（公式层 / 估值引擎）
#
# 设计原则（与 woody EstNetValue 一致）：
#   1. 所有估值 = 篮子矩阵公式；魔法公式 = 单组件 + hedge 常量折叠（数学等价）。
#   2. 本模块只做计算，不碰任何数据源（不读库、不爬网）。
#      所有价格 / 汇率 / 权重由「数据引擎」从外部注入（arSrc 模式）。
#   3. hedge 数学恒等式不可改写：魔法公式 = base_nav*(1-pos) + (price*fx)/hedge。
#
# 这样就绪：静态 / 实时 / ETF / 指数 / 期货 共用同一个核心，
# 区别仅在「数据引擎喂进来的 components 是什么」。

from typing import Optional, List, Dict


def basket_valuation(
    base_nav: float,
    position: float,
    components: List[Dict],
    fx_base: float,
    fx_now: float,
    hedge: Optional[float] = None,
) -> Optional[float]:
    """
    统一篮子矩阵估值核心。

    components: [{ 'symbol': str, 'current_price': float, 'base_price': float, 'weight': float }, ...]
      - weight 为小数（0.95 表示 95%）；多篮子来自 yaml / fund_basket_weights。
      - 单组件（如 162411 的 XOP、161125 的 SPY、QDII日本 的 NKY）→ weight 取 1.0。

    魔法公式（hedge 常量折叠）路径：
      - 当 hedge 给定且 > 0 且 components 恰为 1 个时，等价于单组件篮子公式，
        用 O(1) 直接计算：base_nav*(1-pos) + (current_price*fx_now)/hedge。
      - 这是 woody 每日算好 hedge 这个常数的原因：实时高频算得更快。

    矩阵公式（备用源）路径：
      - 多组件，或 hedge 缺失时的单组件，均走：
        base_nav * (1 + pos * (Σ wᵢ*(Pᵢ/Pᵢ₀) * (fx_now/fx_base) - 1))

    涵盖的历史别名：
      - calculate_magic_valuation  → hedge 路径
      - calculate_basket_valuation → 矩阵路径
      - calculate_index_valuation / asia / lof → 单组件(weight=1.0)矩阵路径（国内LOF 令 fx=1）
    """
    if not base_nav or base_nav <= 0:
        return None
    if position is None:
        return None  # [AI-2026-08-04 SUPREME] position 缺失不兜底，返回 None 让上游显"--"
    if components is None or len(components) == 0:
        return None

    # ── 魔法公式（hedge 常量折叠）──
    if hedge is not None and hedge > 0 and len(components) == 1:
        c = components[0]
        cp = c.get('current_price', 0) or 0
        if cp > 0 and fx_now > 0:
            return base_nav * (1.0 - position) + (cp * fx_now) / hedge

    # ── 矩阵公式（标准篮子）──
    if not (fx_base and fx_now) or fx_base <= 0 or fx_now <= 0:
        return None

    fx_change = fx_now / fx_base
    w_change = 0.0
    for c in components:
        cp = c.get('current_price', 0) or 0
        bp = c.get('base_price', 0) or 0
        w = c.get('weight', 0) or 0
        if cp > 0 and bp > 0 and w != 0:
            w_change += (cp / bp) * w

    if w_change == 0:
        return None

    net_ratio = position * (w_change * fx_change - 1.0)
    return base_nav * (1.0 + net_ratio)


def build_single_component(current_price: float, base_price: float, weight: float = 1.0,
                           symbol: str = '') -> Dict:
    """构造单组件（指数 / 单 ETF / 单期货通用）。"""
    return {
        'symbol': symbol,
        'current_price': current_price,
        'base_price': base_price,
        'weight': weight,
    }
