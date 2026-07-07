# 通用工具模块
# 重试、熔断器、配置管理、健康监控等
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

_HAS_CALENDAR = False
try:
    from chinese_calendar import is_workday as _cal_is_workday
    _HAS_CALENDAR = True
except ImportError:
    logger.warning("chinese_calendar 未安装，A股交易日判断仅依赖周末过滤。建议: pip install chinese-calendar")

# 备用硬编码 2026 年 A 股休市日（当 chinese_calendar 不可用时兜底）
_HOLIDAYS_2026 = frozenset({
    # 元旦
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    # 春节 2/17-2/23
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
    date(2026, 2, 20), date(2026, 2, 21), date(2026, 2, 22), date(2026, 2, 23),
    # 清明节 4/4-4/6
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    # 劳动节 5/1-5/3
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    # 端午节 6/19-6/21
    date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
    # 中秋节+国庆节 10/1-10/7
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
    # 国庆调休上班日（补班）
    # 2026 年国庆调休: 10/10（周六）上班（待确认）
})


def is_a_share_trading_day(d: date = None) -> bool:
    """
    判断指定日期是否为 A 股交易日。
    覆盖：法定节假日 + 周末 + 调休补班。

    Args:
        d: 日期，默认今天

    Returns:
        True = A 股正常交易，False = 休市
    """
    if d is None:
        d = date.today()

    # 周末快速过滤
    if d.weekday() >= 5:  # 周六=5, 周日=6
        return False

    # 优先 chinese_calendar（更精准，含调休）
    if _HAS_CALENDAR:
        return _cal_is_workday(d)

    # 兜底：硬编码列表
    return d not in _HOLIDAYS_2026


def is_a_share_trading_hour(dt: datetime = None) -> bool:
    """
    判断当前是否在 A 股交易时段内（9:15-15:30）。
    先检查交易日，再检查时间段。
    """
    if dt is None:
        dt = datetime.now()
    if not is_a_share_trading_day(dt.date()):
        return False
    hour = dt.hour
    minute = dt.minute
    # 集合竞价 9:15 开始，收盘 15:00，15:00-15:30 仍可撤单/申赎
    if hour < 9 or (hour == 9 and minute < 15) or hour >= 15 and minute > 30:
        return False
    return True


from .retry_manager import RetryManager, CircuitBreaker, create_retry_manager, create_circuit_breaker
from .health_monitor import HealthMonitor
from .config_manager import ConfigManager
from .market_calendar import (is_trading_day, is_us_trading_day, is_hk_trading_day,
                               symbol_to_exchange, classify_by_exchange, filter_closed_markets)

__all__ = [
    'RetryManager',
    'CircuitBreaker',
    'create_retry_manager',
    'create_circuit_breaker',
    'HealthMonitor',
    'ConfigManager',
    'is_a_share_trading_day',
    'is_a_share_trading_hour',
    'is_trading_day',
    'is_us_trading_day',
    'is_hk_trading_day',
    'symbol_to_exchange',
    'classify_by_exchange',
    'filter_closed_markets',
]
