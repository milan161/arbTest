# -*- coding: utf-8 -*-
# arbcore/analysis/static_analysis.py - 静态估值聚合层（薄封装）
#
# [AI-2026-08-05] 新增：喂基金代码 → 静态估值(单日) + 溢价，只读不写库，便于 Debug。
# 复用 StaticValuationCalculator.analyze_latest()（引擎新增的只读方法）。
#
# 用法:
#   from arbcore.analysis import analyze_static
#   s = analyze_static('161116')                 # 最新一日
#   s = analyze_static('501018', date='2026-08-04')  # 指定日
from typing import Dict, Any, Optional

from arbcore.database.db_manager import DatabaseManager
from arbcore.calculators.static_valuation import StaticValuationCalculator
from .common import load_fund_config

# 溢价口径（AGENTS.md TOP2 铁律）：这些分类静态溢价用 T 价 / T-1 净值
_T_MINUS_1_NAV_CATS = {'QDII欧美', '黄金原油'}


def analyze_static(code: str, date: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """喂基金代码 → 静态估值 + 溢价（只读，不写库）。

    Args:
        code: 基金代码
        date: 指定估值日 'YYYY-MM-DD'；缺省取最新一日

    Returns:
        {
          'code','name','category','date',
          'nav','close','static_val',
          'premium'(小数, 按分类分支)   # QDII欧美/黄金原油=T价/T-1净值；其余=T价/T净值
        } 或 None（数据缺失）
    """
    code = str(code)
    fund = load_fund_config(code)
    db = DatabaseManager()
    calc = StaticValuationCalculator(db)
    return calc.analyze_latest(fund, date=date)
