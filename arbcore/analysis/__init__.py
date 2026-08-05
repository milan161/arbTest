# arbcore/analysis/__init__.py
# [AI-2026-08-05] 聚合分析层：喂基金代码一步出「实时三件套」/「静态估值」/「期货估值」，便于 Debug/核对。
from .realtime_analysis import analyze_realtime
from .static_analysis import analyze_static
from .realtime_futures_analysis import analyze_realtime_futures, analyze_realtime_pure_futures

__all__ = ['analyze_realtime', 'analyze_static',
           'analyze_realtime_futures', 'analyze_realtime_pure_futures']
