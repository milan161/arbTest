# -*- coding: utf-8 -*-
# valuation_data_engine.py — 数据引擎（采集与计算分离）
#
# 本模块不连接任何数据源、不爬网、不读库。
# 它只定义「估值核心需要哪些输入」，并提供一个纯函数把调用方已取到的
# 价格 / 汇率 / 权重 整形为 unified_valuation.basket_valuation 需要的 components。
#
# 调用方（static_valuation / dynamic_valuation / fund_service 实时入口）负责：
#   - 从数据库历史表取静态基准价
#   - 从 IB / 富途 / 新浪 取实时 ETF 价
#   - 从新浪 hf_NK 取日经期货实时价（QDII日本）
#   - 从 exchange_rate 取汇率
# 然后把取到的价格以 {symbol: price} 形式注入，本引擎只做整形与归一。
#
# 这就是 woody EstNetValue 的 arSrc 注入模式：估值函数只认 {symbol: 现价}。

from typing import Optional, List, Dict, Any

# 区域后缀：^USO-EU / ^GLD-JP / ^HSI-HK 去掉后缀得到基础代码
_REGION_SUFFIXES = ('-EU', '-JP', '-HK')


def resolve_base_symbol(full_symbol: str) -> str:
    """去掉 ^ 前缀与 -EU/-JP/-HK 后缀，得到基础代码（USO / GLD / NKY）。"""
    s = (full_symbol or '').lstrip('^')
    for suffix in _REGION_SUFFIXES:
        if s.endswith(suffix):
            s = s[:-len(suffix)]
            break
    return s


def assemble_dynamic_components(
    fund_cfg: Dict[str, Any],
    base_data: Dict[str, Any],
    current_prices: Dict[str, float],
) -> Dict[str, Any]:
    """
    装配实时估值的输入。

    参数：
      fund_cfg      : 基金配置（含 valuation_portfolio / hedging_portfolio / code）
      base_data     : get_base_data() 返回的 T-1 基准（nav/exchange_rate/position/hedge/各ETF基准价）
      current_prices: 调用方已取到的实时价 {基础代码: 现价}，如 {'XOP': 110.2, 'NKY': 38000.0}
                      —— QDII日本 由调用方把 NK 期货价注入到 'NKY'（或对应 portfolio symbol）。

    返回：
      { 'components': [...], 'fx_base': float, 'fx_now': float, 'hedge': float|None, 'ok': bool }
    """
    portfolio = fund_cfg.get('valuation_portfolio', []) or fund_cfg.get('hedging_portfolio', [])
    position = base_data.get('position')
    if position is None or (hasattr(position, 'isna') and position.isna()):
        position = fund_cfg.get('holdings', {}).get('equity_ratio', 100.0) / 100.0
    fx_base = base_data.get('exchange_rate')
    fx_now = None  # 由调用方在 calculate 时单独传入
    hedge = base_data.get('hedge')

    components = []
    for p in portfolio:
        full_sym = p.get('symbol', '')
        base_sym = resolve_base_symbol(full_sym)
        b_price = base_data.get(full_sym) or base_data.get(base_sym) or 0
        c_price = current_prices.get(base_sym) or 0
        if not c_price or c_price <= 0:
            c_price = b_price  # 实时缺失则退化用基准价（与旧逻辑一致）
        if b_price and c_price > 0:
            components.append({
                'symbol': full_sym,
                'current_price': float(c_price),
                'base_price': float(b_price),
                'weight': float(p.get('weight', 0)) / 100.0,
            })

    return {
        'components': components,
        'fx_base': fx_base,
        'fx_now': fx_now,
        'hedge': hedge,
        'position': position,
        'base_nav': base_data.get('nav'),
        'ok': bool(components),
    }


def assemble_static_components(
    row: Dict[str, Any],
    base_row: Dict[str, Any],
    portfolio: List[Dict],
    related_index: str = '',
    valuation_method: str = '',
) -> Dict[str, Any]:
    """
    装配静态估值（单点）的输入。

    参数：
      row / base_row : 当日 / T-1 基准行的字典（含各 portfolio symbol 价、related_index 价、exchange_rate、nav、hedge）
      portfolio      : 基金持仓列表
      related_index : 跟踪指数代码（QDII日本=N225、QDII亚洲=HSI 等）；空表示无
      valuation_method : 来自 lof_config.yaml，决定 hedge 是否可用

    hedge 路由规则（与旧 _deduce_valuation 完全一致，防止指数类基金误走魔法）：
      - 'index' / 'equity_asia' / 'lof_domestic'：hedge 强制 None（走指数/单组件矩阵公式）
      - '' / 'etf' / 'basket'：hedge 取自 base_row（etf 命中魔法，缺失则矩阵兜底；basket 永远矩阵）

    返回：
      { 'components': [...], 'fx_base', 'fx_now', 'hedge', 'position', 'base_nav', 'ok' }
    """
    nav_base = base_row.get('nav')
    fx_base = base_row.get('exchange_rate')
    fx_now = row.get('exchange_rate')
    position = base_row.get('position')
    if position is None or (hasattr(position, 'isna') and position.isna()):
        position = 0.95

    components = []
    # 1) 优先用 portfolio 组件（多篮子 / 单 ETF）
    for p in portfolio:
        sym = p.get('symbol', '').replace('^', '')
        if any(suffix in sym for suffix in _REGION_SUFFIXES):
            sym = f"^{sym}"
        if sym in row and sym in base_row:
            components.append({
                'symbol': sym,
                'current_price': float(row[sym]),
                'base_price': float(base_row[sym]),
                'weight': float(row.get(f"{sym}_weight", p.get('weight', 0))) / 100.0,
            })
    # 2) 若无 portfolio 组件（指数/亚洲/国内LOF），用 related_index 作为单组件
    if not components and related_index and related_index in row and related_index in base_row:
        c_idx = row[related_index]
        b_idx = base_row[related_index]
        if c_idx and b_idx and c_idx > 0 and b_idx > 0:
            components.append({
                'symbol': related_index,
                'current_price': float(c_idx),
                'base_price': float(b_idx),
                'weight': 1.0,
            })

    # hedge 路由（关键安全点）：index/亚洲/国内LOF 绝不消费 hedge
    hedge = None
    if valuation_method in ('', 'etf', 'basket'):
        h = base_row.get('hedge')
        if h is not None and not (hasattr(h, 'isna') and h.isna()) and h > 0:
            hedge = float(h)

    return {
        'components': components,
        'fx_base': fx_base,
        'fx_now': fx_now,
        'hedge': hedge,
        'position': position,
        'base_nav': nav_base,
        'ok': bool(components),
    }
