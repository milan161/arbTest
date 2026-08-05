# -*- coding: utf-8 -*-
# arbcore/analysis/common.py - 聚合层共享工具
# [AI-2026-08-05] 新增：从 lof_config.yaml 载入单只基金配置、按代码前缀解析汇率、取篮子权重。
import re
from typing import Dict, Any, List, Optional

from arbcore.config.config_loader import load_config, get_config_path


def load_fund_config(code: str) -> Dict[str, Any]:
    """从 lof_config.yaml 载入单只基金的完整配置 dict。私有配置优先（与 config_loader 一致）。"""
    cfg = load_config()
    for fd in cfg.get('funds', []):
        if str(fd.get('code')) == str(code):
            return dict(fd)
    raise KeyError(f'基金 {code} 不在 lof_config.yaml')


def is_lof(code: str) -> bool:
    """学 woody PalmmicroStock.IsLOF: 代码 16*/50* 开头=LOF, 其余=ETF。"""
    c = re.sub(r'^(SH|SZ|BJ)', '', str(code).upper())
    return c[:2] in ('16', '50')


def resolve_fx(db, code: str, choice: str = 'auto', fund_config: Optional[Dict[str, Any]] = None) -> Optional[float]:
    """返回当前(最新)汇率值。choice: auto / mid / spot / base。

    auto 口径（与 calc_woody.py 一致）：LOF(16*/50*)→中间价，非 LOF(15*/51* ETF)→在岸价；
    QDII日本用 jpy_cny 系列。base 由调用方从 base_data 取基准汇率（本函数返回 None）。
    """
    if choice == 'base':
        return None
    cat = (fund_config or {}).get('category', '')
    base_col = 'jpy_cny_mid' if cat == 'QDII日本' else 'usd_cny_mid'
    if choice == 'auto':
        col = base_col if is_lof(code) else base_col.replace('_mid', '_spot')
    elif choice == 'mid':
        col = base_col
    elif choice == 'spot':
        col = base_col.replace('_mid', '_spot')
    else:
        col = base_col
    conn = db._get_conn()
    try:
        row = conn.execute(f"SELECT {col} FROM exchange_rate ORDER BY date DESC LIMIT 1").fetchone()
        return float(row[0]) if row and row[0] is not None else None
    finally:
        conn.close()


def load_basket_weights(db, code: str) -> List[Dict[str, Any]]:
    """取该基金最新日期的篮子权重 [{'symbol': str, 'weight': float}, ...]。"""
    conn = db._get_conn()
    try:
        rows = conn.execute(
            "SELECT underlying_symbol, weight FROM fund_basket_weights "
            "WHERE fund_code=? AND date=(SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)",
            (code, code),
        ).fetchall()
        return [{'symbol': s, 'weight': float(w)} for s, w in rows]
    finally:
        conn.close()
