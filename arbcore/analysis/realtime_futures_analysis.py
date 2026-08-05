# -*- coding: utf-8 -*-
# arbcore/analysis/realtime_futures_analysis.py - 期货估值聚合层（薄封装）
#
# [AI-2026-08-05] 新增：把前端实时沙盘「期货校准 futCalibVal」与「纯期货 pureFutVal」的算法
# 搬进生产引擎，消除前端手算分叉，单一算法源（与 analyze_realtime 同层）。
#
# 两个入口：
#   analyze_realtime_futures      期货校准模式（等价现货 = futPrice/calib，再走 篮子/指数 口径）
#   analyze_realtime_pure_futures 纯期货模式（单成分篮子公式，成分 = 期货合约本身；QDII日本 NK 与 黄金原油 MGC/MCL 通用）
#
# 基准价来源（权威，缺失即返回 None，绝不兜底）：
#   - 纯期货 base_future = futures_daily.settle_price(最新 >0, symbol = trade_future)
#   - 指数类 index_close  = index_history(related_index 最新)（base_data.index_close 缺失时回退到此）
#   - ETF 基准价          = base_data
#
# 关键结论（东哥 2026-08-05 拍板）：纯期货 = 单成分篮子公式，成分换成期货合约即可。
#   因此 QDII日本(NK) 与 黄金原油(MGC/MCL/CL) 是「同一算法、不同期货合约」，
#   analyze_realtime_pure_futures 对两者通用，无需分支。
import logging
from typing import Dict, Any, Optional

import numpy as np

from arbcore.database.db_manager import DatabaseManager
from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
from .common import load_fund_config
from .realtime_analysis import _nativize

logger = logging.getLogger(__name__)

# 期货合约乘数（与前端 lofQtyFuture/lofQtyPureFuture 一致；NK 无专属项 → 1）
_FUT_MULTIPLIER = {
    'MGC': 10, 'GC': 100, 'MCL': 100, 'CL': 1000,
    'MNQ': 2, 'NQ': 20, 'MES': 5, 'ES': 50, 'AG': 15,
}

# [AI-2026-08-05] 微期货 → 大期货 重映射：新浪只提供大期货数据(GC/CL/ES/NQ/AG0)，
# 取不到微期货(MGC/MCL/MES/MNQ)。估值只需 fut_now/fut_base 比值，二者用同一大期货符号即等价。
# 仅影响基准价查询（与合约手数乘数无关，乘数仍按原始 trade_future 取）。
_FUTURE_REMAP = {
    'MGC': 'GC', 'MCL': 'CL', 'MES': 'ES', 'MNQ': 'NQ',
}


def _remap_futures_symbol(sym: str) -> str:
    if not sym:
        return sym
    s = str(sym).upper()
    return _FUTURE_REMAP.get(s, s)


# ---------------------------------------------------------------------------
# 基础数据 / 连接 辅助
# ---------------------------------------------------------------------------
def _get_conn(db: DatabaseManager):
    """复用 MarketManager 的连接（与 fund_service 直查 futures_daily 同一来源）。"""
    return db.market._get_conn()


def _latest_futures_settle(db: DatabaseManager, symbol: str) -> Optional[float]:
    """期货基准结算价：futures_daily 最新 >0 的 settle_price。缺失返回 None（不兜底）。

    [AI-2026-08-05] 微期货(MGC/MCL/MES/MNQ) 重映射到大期货(GC/CL/ES/NQ)——新浪只给大期货数据。
    """
    if not symbol:
        return None
    sym = _remap_futures_symbol(symbol)
    conn = _get_conn(db)
    try:
        row = conn.execute(
            "SELECT settle_price FROM futures_daily WHERE symbol=? AND settle_price>0 "
            "ORDER BY date DESC LIMIT 1",
            (sym,),
        ).fetchone()
        return float(row[0]) if row else None
    finally:
        conn.close()


def _latest_index_close(db: DatabaseManager, related_index: str) -> Optional[float]:
    """指数基准收盘：index_history 最新 close。缺失返回 None（不兜底）。"""
    if not related_index:
        return None
    conn = _get_conn(db)
    try:
        row = conn.execute(
            "SELECT close FROM index_history WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (related_index,),
        ).fetchone()
        return float(row[0]) if row else None
    finally:
        conn.close()


def _futures_multiplier(symbol: str) -> int:
    if not symbol:
        return 1
    s = symbol.upper()
    for k, v in _FUT_MULTIPLIER.items():
        if k in s:
            return v
    return 1


def _futures_contracts(bd: Dict[str, Any], trade_future: str, calib: float,
                        lof_qty: float) -> Optional[int]:
    """对冲期货合约手数（移植前端 lofQtyFuture/lofQtyPureFuture 的反算：给定 LOF 股数 → 合约手数）。

    前端正向：finalLofQty = round(targetLots * etfHedge * round(calib*multiplier) / 100) * 100
    反算：lots ≈ lof_qty / (etfHedge * round(calib*multiplier))。calib 缺失 / hedge 缺失 → None（不兜底）。
    """
    etf_hedge = float(bd.get('hedge') or 0)
    if etf_hedge <= 0 or not calib or calib <= 0:
        return None
    multiplier = _futures_multiplier(trade_future)
    shares_per_contract = round(calib * multiplier)
    if shares_per_contract <= 0:
        return None
    display_hedge = etf_hedge * shares_per_contract
    if display_hedge <= 0:
        return None
    return int(round(lof_qty / display_hedge))


# ---------------------------------------------------------------------------
# 期货校准模式（移植 futCalibVal）
# ---------------------------------------------------------------------------
def analyze_realtime_futures(
    code: str,
    futures_price: float,
    calibration: float = 1.0,
    current_price: Optional[float] = None,
    current_fx: Optional[float] = None,
    lof_qty: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """期货校准实时估值 + 溢价 + 对冲手数（生产级单基金聚合入口，移植前端 futCalibVal）。

    Args:
        code:           基金代码
        futures_price:  期货合约实时价（必填；缺失则无法估值）
        calibration:    期现校准系数（futPrice/calib = 等价现货）；默认 1.0
        current_price:  LOF 现价（用于算溢价）；缺省用基准日 close
        current_fx:     实时汇率；缺省用基准日汇率（快照）
        lof_qty:       LOF 股数（用于算对冲手数）；缺省不返回 quantity

    Returns: {code,name,category,current_price,rt_val,premium,fx_base,fx_current,
              position,hedge,nav,quantity:{mode,contracts}} 或 None（数据缺失）
    """
    code = str(code)
    fund = load_fund_config(code)
    db = DatabaseManager()
    calc = DynamicValuationCalculator(db)
    base = calc.get_base_data(code)
    if not base:
        logger.error(f"[{code}] get_base_data 返回 None（数据缺失）")
        return None

    base_nav = float(base.get('nav') or 0)
    pos = base.get('position')
    if pos is None:
        cfg_pos = fund.get('position')
        pos = (float(cfg_pos) / 100.0) if cfg_pos is not None else None
    if pos is None or pos <= 0:
        logger.error(f"[{code}] position 缺失或非法")
        return None
    base_fx = float(base.get('exchange_rate') or 0)
    today_fx = current_fx if (current_fx and current_fx > 0) else base_fx

    if base_nav <= 0 or today_fx <= 0 or base_fx <= 0:
        logger.error(f"[{code}] nav/fx 缺失（base_nav={base_nav}, today_fx={today_fx}, base_fx={base_fx}）")
        return None
    if not futures_price or futures_price <= 0:
        logger.error(f"[{code}] futures_price 缺失或非法")
        return None
    if not calibration or calibration <= 0:
        logger.error(f"[{code}] calibration 缺失或非法")
        return None

    equiv_spot = futures_price / calibration
    category = fund.get('category', '')
    portfolio = fund.get('valuation_portfolio') or fund.get('hedging_portfolio') or []

    rt_val: Optional[float] = None

    if category == '指数':
        main_anchor = (portfolio[0] or {}).get('symbol', '') if portfolio else ''
        clean_main = main_anchor.replace('^', '')
        caret_main = '^' + clean_main
        base_etf_price = (
            base.get(caret_main) if base.get(caret_main) is not None
            else base.get(clean_main) if base.get(clean_main) is not None
            else base.get(main_anchor) or 0
        )
        base_index_price = base.get('index_close')
        if not base_index_price or base_index_price <= 0:
            base_index_price = _latest_index_close(db, fund.get('related_index'))
        if not base_index_price or base_index_price <= 0:
            base_index_price = 0

        equiv_etf = 0.0
        if base_index_price > 0 and base_etf_price and base_etf_price > 0:
            equiv_etf = equiv_spot * (base_etf_price / base_index_price)
        elif float(base.get('calibration') or 0) > 0 and base_etf_price and base_etf_price > 0:
            derived_base_index = float(base.get('calibration')) / calibration
            if derived_base_index > 0:
                equiv_etf = equiv_spot * (base_etf_price / derived_base_index)

        hedge_value = float(base.get('hedge') or 0)
        etf_calibration = hedge_value * pos if (hedge_value > 0 and pos > 0) else 0

        if etf_calibration > 0 and equiv_etf > 0:
            rt_val = base_nav * (1.0 - pos) + (pos / etf_calibration) * (equiv_etf * today_fx)
        elif base_index_price > 0:
            spot_change = equiv_spot / base_index_price
            fx_change = today_fx / base_fx
            rt_val = base_nav * (1 + pos * (spot_change * fx_change - 1))
        else:
            # 指数基准价与 ETF 基准价双双缺失 → 无法估值，不兜底
            logger.error(f"[{code}] 指数类期货校准：index_close/ETF基准价均缺失")
            return None
    else:
        # 非指数（黄金原油等）：加权期货变化率（equiv_spot 作为整篮等价现货）
        weighted_fut_change = 0.0
        total_valid_weight = 0.0
        for item in portfolio:
            w = float(item.get('weight') or 0)
            if w <= 0 or w < 0.02 or 'SLV' in str(item.get('symbol', '')):
                continue
            total_valid_weight += w
        if total_valid_weight > 0:
            for item in portfolio:
                w = float(item.get('weight') or 0)
                if w <= 0 or w < 0.02 or 'SLV' in str(item.get('symbol', '')):
                    continue
                sym = str(item.get('symbol', ''))
                clean_sym = sym.replace('^', '')
                caret_sym = '^' + clean_sym
                base_etf_price = (
                    base.get(caret_sym) if base.get(caret_sym) is not None
                    else base.get(clean_sym) if base.get(clean_sym) is not None
                    else base.get(sym) or 0
                )
                if base_etf_price and base_etf_price > 0:
                    etf_change = equiv_spot / base_etf_price
                    weighted_fut_change += etf_change * (w / total_valid_weight)
            fx_change = today_fx / base_fx
            rt_val = base_nav * (1 + pos * (weighted_fut_change * fx_change - 1))
        else:
            logger.error(f"[{code}] 非指数期货校准：有效篮子权重为 0")
            return None

    if rt_val is None or rt_val <= 0:
        logger.error(f"[{code}] 期货校准估值异常 rt_val={rt_val}")
        return None

    price = current_price if (current_price and current_price > 0) else (base.get('close') or 0)
    premium = (price / rt_val - 1) if (price and price > 0) else None

    out: Dict[str, Any] = {
        'code': code,
        'name': fund.get('name', ''),
        'category': category,
        'mode': 'futures_calib',
        'current_price': price,
        'rt_val': rt_val,
        'premium': premium,
        'fx_base': base_fx,
        'fx_current': today_fx,
        'position': pos,
        'hedge': base.get('hedge'),
        'nav': base_nav,
    }

    if lof_qty and lof_qty > 0:
        contracts = _futures_contracts(base, fund.get('trade_future', ''), calibration, lof_qty)
        out['quantity'] = _nativize({
            'mode': 'futures',
            'contracts': contracts,
        })
    else:
        out['quantity'] = None

    return out


# ---------------------------------------------------------------------------
# 纯期货模式（移植 pureFutVal）— QDII日本 NK 与 黄金原油 MGC/MCL 通用
# ---------------------------------------------------------------------------
def analyze_realtime_pure_futures(
    code: str,
    futures_price: float,
    current_price: Optional[float] = None,
    current_fx: Optional[float] = None,
    lof_qty: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """纯期货实时估值 + 溢价 + 对冲手数（生产级单基金聚合入口，移植前端 pureFutVal）。

    纯期货 = 单成分篮子公式，成分即期货合约本身：
        rt_val = base_nav * (1 + pos * (fut_now / fut_base * fx_change - 1))
    QDII日本(NK) 与 黄金原油(MGC/MCL/CL) 共用此式，仅期货合约符号不同。

    Args:
        code:           基金代码
        futures_price:  期货合约实时价（必填）
        current_price:  LOF 现价（用于溢价）；缺省用基准日 close
        current_fx:     实时汇率；缺省用基准日汇率
        lof_qty:       LOF 股数（用于算对冲手数）；缺省不返回 quantity

    Returns: {..., mode:'pure_futures', quantity:{mode,contracts}} 或 None（数据缺失）
    """
    code = str(code)
    fund = load_fund_config(code)
    db = DatabaseManager()
    calc = DynamicValuationCalculator(db)
    base = calc.get_base_data(code)
    if not base:
        logger.error(f"[{code}] get_base_data 返回 None（数据缺失）")
        return None

    base_nav = float(base.get('nav') or 0)
    pos = base.get('position')
    if pos is None:
        cfg_pos = fund.get('position')
        pos = (float(cfg_pos) / 100.0) if cfg_pos is not None else None
    if pos is None or pos <= 0:
        logger.error(f"[{code}] position 缺失或非法")
        return None
    base_fx = float(base.get('exchange_rate') or 0)
    today_fx = current_fx if (current_fx and current_fx > 0) else base_fx

    # 期货基准结算价：futures_daily.settle_price（QDII日本=NK；黄金原油=MGC/MCL → 重映射 GC/CL/ES）
    trade_future = fund.get('trade_future', '')
    base_future = _latest_futures_settle(db, trade_future)

    if base_nav <= 0 or today_fx <= 0 or base_fx <= 0:
        logger.error(f"[{code}] nav/fx 缺失")
        return None
    if not futures_price or futures_price <= 0:
        logger.error(f"[{code}] futures_price 缺失或非法")
        return None
    if not base_future or base_future <= 0:
        logger.error(f"[{code}] 期货基准价缺失（trade_future={trade_future}→{_remap_futures_symbol(trade_future)} 在 futures_daily 无 settle）")
        return None

    fut_change = futures_price / base_future
    fx_change = today_fx / base_fx
    rt_val = base_nav * (1 + pos * (fut_change * fx_change - 1))
    if rt_val <= 0:
        logger.error(f"[{code}] 纯期货估值异常 rt_val={rt_val}")
        return None

    price = current_price if (current_price and current_price > 0) else (base.get('close') or 0)
    premium = (price / rt_val - 1) if (price and price > 0) else None

    out: Dict[str, Any] = {
        'code': code,
        'name': fund.get('name', ''),
        'category': fund.get('category', ''),
        'mode': 'pure_futures',
        'current_price': price,
        'rt_val': rt_val,
        'premium': premium,
        'fx_base': base_fx,
        'fx_current': today_fx,
        'position': pos,
        'hedge': base.get('hedge'),
        'nav': base_nav,
        'base_future': base_future,
        'future_symbol': _remap_futures_symbol(trade_future),
    }

    if lof_qty and lof_qty > 0:
        # 纯期货手数反算用 base.calibration（与前端 lofQtyPureFuture 一致）
        calib = float(base.get('calibration') or 0)
        contracts = _futures_contracts(base, fund.get('trade_future', ''), calib, lof_qty)
        out['quantity'] = _nativize({
            'mode': 'pure_futures',
            'contracts': contracts,
        })
    else:
        out['quantity'] = None

    return out
