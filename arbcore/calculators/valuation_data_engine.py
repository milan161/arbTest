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
import os

# 区域后缀：^USO-EU / ^GLD-JP / ^HSI-HK 去掉后缀得到基础代码
_REGION_SUFFIXES = ('-EU', '-JP', '-HK')

# ─────────────────────────────────────────────────────────────
# [AI-2026-07-27] 估值类型路由：由 lof_config.yaml `valuation_routing` 节驱动
# yaml 缺失该节时用 _DEFAULT_ROUTING 备用（与 yaml 中内容保持一致）。
# hedge 语义（2026-07-27 用 woody API JSON 数值核对）：
#   hedge = calibration / position（含仓位）；calibration = 基准价×基准汇率/净值（不含仓位）；
#   hedge 计价标的因基金而异（162411=XOP、161125=SPY、161130=QQQ、513000=NKY期货），
#   故是否可用取决于「当前估值路径取的价格标的」是否与 hedge 计价标的一致——由本路由表决策。
# ─────────────────────────────────────────────────────────────
_DEFAULT_ROUTING = {
    'methods': {
        '':             {'static_hedge': True,  'dynamic_hedge': True},
        'etf':          {'static_hedge': True,  'dynamic_hedge': True},
        'basket':       {'static_hedge': False, 'dynamic_hedge': False},
        'index':        {'static_hedge': False, 'dynamic_hedge': True},
        'equity_asia':  {'static_hedge': False, 'dynamic_hedge': False},
        'lof_domestic': {'static_hedge': False, 'dynamic_hedge': False},
    },
    'category_fallback': {
        'QDII日本': 'index',
        'QDII亚洲': 'equity_asia',
        '国内LOF': 'lof_domestic',
        '现金管理': 'lof_domestic',
    },
}

_routing_cache = None


def load_valuation_routing() -> Dict[str, Any]:
    """从 lof_config.yaml 读取 valuation_routing 节（模块级缓存；失败则用内置默认）。"""
    global _routing_cache
    if _routing_cache is not None:
        return _routing_cache
    routing = _DEFAULT_ROUTING
    try:
        import yaml as _yaml
        cfg_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'lof_config.yaml')
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = _yaml.safe_load(f)
        r = cfg.get('valuation_routing') if isinstance(cfg, dict) else None
        if isinstance(r, dict) and isinstance(r.get('methods'), dict):
            routing = {
                'methods': {str(k): dict(v) for k, v in r['methods'].items() if isinstance(v, dict)},
                'category_fallback': dict(r.get('category_fallback') or {}),
            }
    except Exception:
        pass  # yaml 不可读时静默用默认表（默认表与 yaml 内容一致）
    _routing_cache = routing
    return routing


def resolve_method(valuation_method: str, category: str = '') -> str:
    """基金未显式配置 valuation_method（空串）时，按 category 备用路由。"""
    m = (valuation_method or '').strip()
    if m:
        return m
    routing = load_valuation_routing()
    return routing.get('category_fallback', {}).get((category or '').strip(), '')


def hedge_allowed(valuation_method: str, category: str = '', mode: str = 'static') -> bool:
    """查询该基金在 static/dynamic 路径下是否允许消费 hedge 因子（魔法公式）。"""
    routing = load_valuation_routing()
    m = resolve_method(valuation_method, category)
    rule = routing.get('methods', {}).get(m)
    if rule is None:
        rule = routing.get('methods', {}).get('', {})
    key = 'static_hedge' if mode == 'static' else 'dynamic_hedge'
    return bool(rule.get(key, False))


def _clean_float(value, fallback=None):
    """[AI-2026-07-27] 健壮的数值清洗：None / NaN(float或numpy) / 非法值 → fallback。
    修复原 `hasattr(x, 'isna')` 判断对 float('nan') / numpy.nan 无效导致 NaN 毒化公式的隐患。"""
    try:
        f = float(value)
        if f == f:  # NaN != NaN
            return f
    except (TypeError, ValueError):
        pass
    return fallback


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
      fund_cfg      : 基金配置（含 valuation_portfolio / hedging_portfolio / code / category / valuation_method）
      base_data     : get_base_data() 返回的 T-1 基准（nav/exchange_rate/position/hedge/各ETF基准价）
      current_prices: 调用方已取到的实时价 {基础代码: 现价}，如 {'XOP': 110.2, 'NKY': 38000.0}
                      —— QDII日本 由调用方把 NK 期货价注入到 'NKY'（或对应 portfolio symbol）。

    [AI-2026-07-27] hedge 路由改为 yaml valuation_routing 驱动（dynamic_hedge 列）：
      - 实时路径取的是 portfolio 交易标的价（SPY/QQQ/XOP…），与 woody hedge 计价标的一致，
        故 index 类（161125/161130）实时允许魔法公式（与旧 valuation_method != 'basket' 行为一致）。
      - 仅当 portfolio 恰为 1 个组件时才携带 hedge（魔法公式仅对单组件成立）。
      - 组件基准价缺失但实时价可得时仍保留组件（魔法公式不需要基准价，矩阵路径会自然跳过）。

    返回：
      { 'components': [...], 'fx_base': float, 'fx_now': float, 'hedge': float|None, 'ok': bool }
    """
    portfolio = fund_cfg.get('valuation_portfolio', []) or fund_cfg.get('hedging_portfolio', [])
    # [AI-2026-08-04 SUPREME 铁律] 禁止用 equity_ratio 填补 position。
    # position 缺失时为 None，由 basket_valuation 自然返回 None（H5 显示"--"）。
    # 根因：get_base_data 的 LEFT JOIN 在 factors 滞后时取不到当日 position → 被误填成 1.0 → H 失真。
    # 修复在 get_base_data 侧（回溯最近 factors 行），此处仅删除该填补逻辑。
    position = _clean_float(base_data.get('position'))
    fx_base = _clean_float(base_data.get('exchange_rate'))
    fx_now = None  # 由调用方在 calculate 时单独传入

    # hedge 路由（yaml 驱动）：dynamic 列 + 单组件守卫
    hedge = None
    if len(portfolio) == 1 and hedge_allowed(
        fund_cfg.get('valuation_method', ''), fund_cfg.get('category', ''), mode='dynamic'
    ):
        h = _clean_float(base_data.get('hedge'))
        if h is not None and h > 0:
            hedge = h

    components = []
    for p in portfolio:
        full_sym = p.get('symbol', '')
        base_sym = resolve_base_symbol(full_sym)
        b_price = base_data.get(full_sym) or base_data.get(base_sym) or 0
        c_price = current_prices.get(base_sym) or 0
        if not c_price or c_price <= 0:
            # [AI-2026-08-04] 实时缺失退化时取市场价(price)，不用 b_price（可能取了 netvalue）。
            # b_price 按 basket_count 分流（矩阵用 price、魔法展示用 netvalue）是计算层设计，
            # 但 current_price 是"当前市场价"语义，退化时应统一取 price 列，不能因 basket_count 不同而异。
            c_price = base_data.get(full_sym + '_mkt') or base_data.get(base_sym + '_mkt') or b_price
        if c_price and c_price > 0:
            components.append({
                'symbol': full_sym,
                'current_price': float(c_price),
                'base_price': float(b_price or 0),
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
    category: str = '',
) -> Dict[str, Any]:
    """
    装配静态估值（单点）的输入。

    参数：
      row / base_row : 当日 / T-1 基准行的字典（含各 portfolio symbol 价、related_index 价、exchange_rate、nav、hedge）
      portfolio      : 基金持仓列表
      related_index : 跟踪指数代码（QDII日本=N225、QDII亚洲=HSI 等）；空表示无
      valuation_method : 来自 lof_config.yaml，决定 hedge 是否可用
      category       : 基金类别；valuation_method 为空串时按 yaml category_fallback 备用路由

    [AI-2026-07-27] hedge 路由改为 yaml valuation_routing 驱动（static_hedge 列）：
      - 'index' / 'equity_asia' / 'lof_domestic'：hedge 强制 None（走指数/单组件矩阵公式）。
        原因：静态路径取的是指数价（.INX/.NDX/N225），而 woody hedge 以 SPY/QQQ/NKY期货 计价，
        标的不一致，误用会差 10 倍/41 倍（161125/161130）或引入期现基差（513000）。
      - '' / 'etf'：hedge 取自 base_row（etf 命中魔法，缺失则矩阵备用源）；'basket' 永远矩阵。
      - 513000/513880 的 valuation_method 为空串，靠 category_fallback（QDII日本→index）守卫。

    返回：
      { 'components': [...], 'fx_base', 'fx_now', 'hedge', 'position', 'base_nav', 'ok' }
    """
    nav_base = _clean_float(base_row.get('nav'))
    fx_base = _clean_float(base_row.get('exchange_rate'))
    fx_now = _clean_float(row.get('exchange_rate'))
    # [AI-2026-08-04 SUPREME 铁律] 禁止用 0.95 填补 position。缺失则为 None。
    position = _clean_float(base_row.get('position'))

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

    # hedge 路由（关键安全点，yaml valuation_routing 驱动）：index/亚洲/国内LOF 绝不消费 hedge
    hedge = None
    if hedge_allowed(valuation_method, category, mode='static'):
        h = _clean_float(base_row.get('hedge'))
        if h is not None and h > 0:
            hedge = h

    return {
        'components': components,
        'fx_base': fx_base,
        'fx_now': fx_now,
        'hedge': hedge,
        'position': position,
        'base_nav': nav_base,
        'ok': bool(components),
    }
