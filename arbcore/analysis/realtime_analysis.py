# -*- coding: utf-8 -*-
# arbcore/analysis/realtime_analysis.py - 实时估值聚合层（薄封装）
#
# [AI-2026-08-05] 新增：喂基金代码 → 一步出「实时估值 + 溢价 + 对冲数量」三件套。
# 生产级单基金聚合入口：供 H5 详情页(get_realtime_valuation_detail 的 quantity 字段)与 Debug 复用；
# 直接复用生产引擎 DynamicValuationCalculator.calculate() 与 CalcQuantity，绝不手写公式。
#
# 用法:
#   from arbcore.analysis import analyze_realtime
#   r = analyze_realtime('162411', lof_qty=4100)                 # 快照(基准价/基准汇率)
#   r = analyze_realtime('161116', current_price=1.567,
#                        current_etfs={'GLD':381.44,'^GLD-EU':381.40},
#                        current_fx=6.79, lof_qty=195300)        # 传实时值
import logging
from typing import Dict, Any, Optional

from arbcore.database.db_manager import DatabaseManager
from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
from arbcore.calculators.calc_quantity import CalcQuantity
from .common import load_fund_config, load_basket_weights

logger = logging.getLogger(__name__)

import numpy as np  # [AI-2026-08-05] 用于把 CalcQuantity 返回的 numpy 类型转为原生类型，避免下游 JSON 序列化失败


def _nativize(v):
    """递归把 numpy 标量(numpy.floating/integer/bool_)转为 Python 原生，供 JSON 序列化安全使用。"""
    if isinstance(v, dict):
        return {k: _nativize(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_nativize(x) for x in v]
    if isinstance(v, np.floating):
        return float(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v

# base_data 中的非价格字段，提取快照 etfs 时排除
_FIELD_KEYS = {'position', 'hedge', 'calibration', 'nav', 'exchange_rate', 'close', 'date'}


def _snapshot_etfs(base: Dict[str, Any]) -> Dict[str, float]:
    """从基准数据中提取所有 ETF 价格键（GLD / ^GLD-EU / XOP ...），作为离线快照输入。"""
    etfs = {}
    for k, v in base.items():
        if k in _FIELD_KEYS:
            continue
        if isinstance(v, (int, float)) and not str(k).endswith('_mkt'):
            etfs[k] = float(v)
    return etfs


def analyze_realtime(
    code: str,
    current_price: Optional[float] = None,
    current_etfs: Optional[Dict[str, float]] = None,
    current_fx: Optional[float] = None,
    lof_qty: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """喂基金代码 → 实时估值 + 溢价 + 对冲数量 三件套（生产级单基金聚合入口，供 H5 详情页与 Debug 复用）。

    Args:
        code:          基金代码（如 162411 / 161116）
        current_price: LOF 现价；缺省用基准日 close（快照）
        current_etfs:  {基础代码: 实时价}；缺省用基准日参考价（快照，fx_change=1, price_change=1）
        current_fx:    实时汇率；缺省用基准日汇率（快照）
        lof_qty:       LOF 股数（用于算对冲数量）；缺省不返回 quantity

    Returns:
        {
          'code','name','category','base_date',
          'current_price','rt_val','premium'(小数),
          'fx_base','fx_current','position','hedge','nav',
          'quantity': {                  # 仅当 lof_qty 给定
             'mode':'etf'|'basket', 'lof_qty','etf_qty'(单ETF), 'breakdown':[{symbol,shares,weight_pct,is_short}]
          } 或 None
        } 或 None（数据缺失）
    """
    code = str(code)
    fund = load_fund_config(code)
    db = DatabaseManager()
    calc = DynamicValuationCalculator(db)
    base = calc.get_base_data(code)
    if not base:
        logger.error(f"[{code}] get_base_data 返回 None（数据缺失）")
        return None

    # 默认快照：基准日收盘 + 基准汇率
    price = current_price if (current_price and current_price > 0) else (base.get('close') or 0)
    fx = current_fx if (current_fx and current_fx > 0) else base.get('exchange_rate')
    fund['current_price'] = price
    etfs = dict(current_etfs) if current_etfs else _snapshot_etfs(base)

    res = calc.calculate(fund, fx, etfs)
    if not res:
        logger.debug(f"[{code}] calculate 返回 None（组件价/position 缺失）→ rt_val 由主面板独立计算")
        return None

    out: Dict[str, Any] = {
        'code': code,
        'name': fund.get('name', ''),
        'category': fund.get('category', ''),
        'base_date': base.get('date'),
        'current_price': price,
        'rt_val': res['rt_val'],
        'premium': res['premium'],
        'fx_base': base.get('exchange_rate'),
        'fx_current': fx,
        'position': base.get('position'),
        'hedge': base.get('hedge'),
        'nav': base.get('nav'),
    }

    # 对冲数量（喂 lof_qty 才算）
    if lof_qty and lof_qty > 0:
        nav = base.get('nav')
        position = base.get('position')
        basket = load_basket_weights(db, code)
        basis = price if (price and price > 0) else (nav or 0)

        if not basket:
            # 单 ETF 路线：etf_qty = floor(LOF / hedge)
            out['quantity'] = _nativize(CalcQuantity.etf_hedge(
                target_capital=lof_qty * basis,
                lof_price=basis,
                hedge=base.get('hedge') or 0,
                position=position if position is not None else 1.0,
                exchange_rate=fx if fx else 0,
                nav=nav,
            ))
        else:
            # 篮子路线：NAV 基准权重拆解（与 calc_woody.calc_quantity 篮子分支一致）
            _exp_basis = nav if (nav is not None and nav > 0) else basis
            exposure_rmb = lof_qty * _exp_basis * (position if position is not None else 1.0)
            exposure_usd = exposure_rmb / fx if fx else 0.0
            portfolio = [{
                'symbol': b['symbol'],
                'weight': b['weight'],
                'price': (base.get(b['symbol']) or base.get(b['symbol'].lstrip('^')) or 0),
            } for b in basket]
            breakdown = CalcQuantity._basket_breakdown(exposure_usd, portfolio)
            out['quantity'] = _nativize({
                'mode': 'basket',
                'lof_qty': lof_qty,
                'etf_qty': None,
                'breakdown': breakdown,
            })
    else:
        out['quantity'] = None

    return out
