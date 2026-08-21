"""
[AI-2026-07-07] 市场日历服务
整合 exchange_calendars 和 chinese_calendar，统一判断各交易所是否开市。

支持的交易所：
- US (NYSE/NASDAQ) → 美股 ETF (GLD, XOP, SPY, QQQ...)
- XHKG → 港股指数 + ^XXX-HK 篮子锚点
- JPX → ^XXX-JP 篮子锚点
- XSWX (SIX Swiss) → ^XXX-EU 篮子锚点
- A股 (chinese_calendar) → A股指数 + 国内LOF

用法：
    from arbcore.utils.market_calendar import is_trading_day, symbol_to_exchange
    is_trading_day('NYSE', date(2026, 7, 3))  # False (Independence Day)
    symbol_to_exchange('^GLD-EU')  # 'XSWX'
"""
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# exchange_calendars 延迟加载（首次使用才初始化）
# ---------------------------------------------------------------------------
_HAS_EXCHANGE_CALENDARS = False
_CAL_CHECK_DONE = False   # 【AI-2026-07-22】防止缺失依赖时每次调用都重新尝试并刷日志
_cal_cache: dict = {}

def _ensure_exchange_calendars():
    global _HAS_EXCHANGE_CALENDARS, _CAL_CHECK_DONE
    if _HAS_EXCHANGE_CALENDARS:
        return
    if _CAL_CHECK_DONE:
        return  # 已尝试过（成功或失败），不再重复
    _CAL_CHECK_DONE = True
    try:
        import exchange_calendars as ec
        # 验证核心交易所可用
        for name in ('NYSE', 'XHKG', 'JPX', 'XSWX'):
            _cal_cache[name] = ec.get_calendar(name)
        _HAS_EXCHANGE_CALENDARS = True
        logger.info(f"[MARKET-CAL] exchange_calendars 加载成功，{len(_cal_cache)} 个交易所日历")
    except Exception as e:
        logger.warning(f"[MARKET-CAL] exchange_calendars 加载失败: {e}，所有非A股交易所将按 US 日历备用源")

# ---------------------------------------------------------------------------
# A股日历（复用 chinese_calendar）
# ---------------------------------------------------------------------------
_HAS_CHINESE_CALENDAR = False
try:
    from chinese_calendar import is_workday as _cal_is_workday
    _HAS_CHINESE_CALENDAR = True
except ImportError:
    logger.warning("[MARKET-CAL] chinese_calendar 未安装，A股判断仅依赖周末过滤")

# 2026年A股休市硬编码备用源
_HOLIDAYS_2026 = frozenset({
    date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
    date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
    date(2026, 2, 20), date(2026, 2, 21), date(2026, 2, 22), date(2026, 2, 23),
    date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
    date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
    date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
    date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7),
})

# ---------------------------------------------------------------------------
# 符号 → 交易所 映射规则
# ---------------------------------------------------------------------------

# 区域后缀 → 交易所
_SUFFIX_TO_EXCHANGE = {
    '-EU': 'XSWX',   # 欧洲（瑞士）
    '-JP': 'JPX',    # 日本（东京）
    '-HK': 'XHKG',   # 香港
}

# 裸美股ETF → 交易所（仅核心标的，其余默认 US）
_US_ETF_EXCHANGE_MAP = {
    # 默认走 NYSE
    'XOP': 'NYSE', 'GLD': 'NYSE', 'USO': 'NYSE', 'SLV': 'NYSE',
    'SPY': 'NYSE', 'INDA': 'NYSE', 'EEM': 'NYSE', 'EWJ': 'NYSE',
    'XBI': 'NYSE', 'XLE': 'NYSE', 'XLI': 'NYSE', 'XLK': 'NYSE',
    'XLF': 'NYSE', 'XLV': 'NYSE', 'XLY': 'NYSE', 'XLU': 'NYSE',
    'XLB': 'NYSE', 'XLRE': 'NYSE',
    # 走 NASDAQ
    'QQQ': 'NASDAQ', 'SOXX': 'NASDAQ', 'SMH': 'NASDAQ',
    'ARKK': 'NASDAQ', 'ARKG': 'NASDAQ', 'ARKQ': 'NASDAQ',
    'BOTZ': 'NASDAQ', 'FINX': 'NASDAQ', 'AIQ': 'NASDAQ',
    'KWEB': 'NASDAQ', 'TQQQ': 'NASDAQ', 'SQQQ': 'NASDAQ',
}

# A股指数前缀 → A股
_A_SHARE_PREFIXES = ('399', '000', '001', '159', '930', '931', '932', 'SZ')

# 港股指数前缀
_HK_INDEX_PREFIXES = ('HSI', 'HSTECH', 'HSCEI', 'HSCI', 'HSCCI', 'HSSCNE',
                      'HSSI', 'HSMI', 'HSSFML25')

# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def symbol_to_exchange(symbol: str) -> Optional[str]:
    """
    根据篮子符号或指数代码判断所属交易所。
    
    Args:
        symbol: 如 'GLD', '^GLD-EU', '^INDA-HK', '399300', 'HSI', 'SZ159560'
    
    Returns:
        交易所代码: 'NYSE' | 'NASDAQ' | 'XHKG' | 'JPX' | 'XSWX' | 'A_SHARE' | None
    """
    if not symbol or symbol == '-':
        return None
    
    clean = symbol.strip().upper().replace('^', '')

    # 1. 区域后缀检查（优先）
    for suffix, exchange in _SUFFIX_TO_EXCHANGE.items():
        if clean.endswith(suffix):
            return exchange

    # 2. 港股指数（放在美股备用源前）
    if any(clean.startswith(p) for p in _HK_INDEX_PREFIXES):
        return 'XHKG'
    
    # [AI-2026-07-09] 日本指数 → JPX
    if clean in ('N225', 'NKY', 'NIKKEI', 'TOPIX', 'TOPX'):
        return 'JPX'
    
    # 3. A股指数（6位数字 或 SZ/SH 前缀）
    if clean.startswith('SZ') or clean.startswith('SH'):
        return 'A_SHARE'
    if clean.isdigit() and len(clean) == 6:
        return 'A_SHARE'
    if any(clean.startswith(p) for p in _A_SHARE_PREFIXES):
        return 'A_SHARE'
    
    # 4. 裸美股 ETF
    base = clean.split('-')[0]
    if base in _US_ETF_EXCHANGE_MAP:
        return _US_ETF_EXCHANGE_MAP[base]
    # 所有 2-5 位大写字母组合 → 默认美股
    if base.isalpha() and 2 <= len(base) <= 5:
        return 'NYSE'
    
    # 5. 无法识别
    logger.debug(f"[MARKET-CAL] 无法识别交易所: {symbol}")
    return None


def is_trading_day(exchange: str, d: date = None) -> bool:
    """
    判断指定日期在指定交易所是否为交易日。

    Args:
        exchange: 'NYSE' | 'NASDAQ' | 'XHKG' | 'JPX' | 'XSWX' | 'A_SHARE'
        d: 日期，默认今天

    Returns:
        True = 交易日
    """
    if d is None:
        d = date.today()
    
    # A股用 chinese_calendar
    if exchange == 'A_SHARE':
        if d.weekday() >= 5:
            return False
        if _HAS_CHINESE_CALENDAR:
            return _cal_is_workday(d)
        return d not in _HOLIDAYS_2026
    
    # 美股（NYSE 和 NASDAQ 日历几乎一致，共用 NYSE）
    if exchange in ('NYSE', 'NASDAQ'):
        _ensure_exchange_calendars()
        if not _HAS_EXCHANGE_CALENDARS:
            # 备用源：仅周末过滤
            return d.weekday() < 5
        cal = _cal_cache.get('NYSE')
        if cal:
            return cal.is_session(d)
        return d.weekday() < 5
    
    # 港股 / 日本 / 瑞士
    _ensure_exchange_calendars()
    if not _HAS_EXCHANGE_CALENDARS:
        return d.weekday() < 5  # 备用源
    cal = _cal_cache.get(exchange)
    if cal:
        return cal.is_session(d)
    return d.weekday() < 5


def is_us_trading_day(d: date = None) -> bool:
    """美股是否交易日"""
    return is_trading_day('NYSE', d)


def is_hk_trading_day(d: date = None) -> bool:
    """港股是否交易日"""
    return is_trading_day('XHKG', d)


# [AI-2026-08-04] A股可交易时段判断（东哥拍板：套利只在 A 股盘中进行）
def is_a_share_session(now_dt: datetime = None) -> bool:
    """判断当前是否处于 A 股可交易时段（北京时间 周一~周五 9:30-15:00，含午休）。

    口径来源（东哥 2026-08-04 拍板）：套利的前提是能实时买卖 LOF，因此系统只关心
    北京时间 9:30-15:00。此窗口之外一律视为"估值冻结"，不需要任何实时外部行情。

    实现要点：
    1. **强制 UTC+8**，与运行机器时区无关。东京 VPS / Oracle ARM 若时区配错，
       用 datetime.now() 会把 JST 13:07（=CST 12:07）误判成非交易时段。
    2. 交易日走 is_trading_day('A_SHARE')，能识别国庆/春节等节假日（内部已含降级）。
    3. 含午休 11:30-13:00 —— 午休期间 LOF 虽不能成交，但估值仍在滚动、开盘前需预热
       连接，切断反而会导致 13:00 复盘瞬间无数据。
    """
    if now_dt is None:
        now_dt = datetime.now(timezone(timedelta(hours=8)))  # UTC+8 全年不变（中国无夏令时）
    if not is_trading_day('A_SHARE', now_dt.date()):
        return False
    t = now_dt.hour * 60 + now_dt.minute
    return 570 <= t <= 900  # 9:30=570, 15:00=900


# [AI-2026-08-04] 美股/港股盘口展示窗口（东哥拍板）：9:30-16:00 北京时间，周一~周五。
# 套利交易只在 A 股盘 9:30-15:00；但港股 16:00 收盘、IB/Futu 夜盘(OVERNIGHT)也 16:00 结束，
# 故美股/港股盘口展示放宽到 16:00；16:00 之后一律不显示（连冻结值都不留）。
# 仅用于美股/港股实时盘口的"是否展示"判定；A 股仍走 is_a_share_session（15:00 冻结），两者互不干扰。
# [AI-2026-08-07] 东哥修改：盘口展示窗口提前到 8:30（8:30=510），原 9:30=570
# [AI-2026-08-19] 注意：此窗口仅服务 IB（未购买行情，仅 OVERNIGHT 8:30-16:00 免费）。
#   富途促销期全时段免费，其门禁在 futu_reader.get_prices / get_dual_quote 中单独放开（不依赖本函数）。
def is_quote_window(now_dt: datetime = None) -> bool:
    """判断当前是否处于美股/港股盘口展示时段（北京时间 8:30-16:00，含午休，周一~周五）。"""
    if now_dt is None:
        now_dt = datetime.now(timezone(timedelta(hours=8)))  # UTC+8 全年不变（中国无夏令时）
    if not is_trading_day('A_SHARE', now_dt.date()):
        return False
    t = now_dt.hour * 60 + now_dt.minute
    return 510 <= t <= 960  # [AI-2026-08-07] 8:30=510, 16:00=960


def is_shfe_open(now_dt: datetime = None) -> bool:
    """
    [2026-07-30] 判断上海期货交易所(SHFE)当前是否处于连续交易时段。
    用于实时估值守卫：休市时段（含午夜-早盘间隙、周末、节假日）新浪 nf_AG0
    仍返回上一交易时段的收盘价，若直接当作"实时"会误导用户，故非交易时段
    不应产生 rt_val / si_val。

    沪银(AG)交易时段（北京时间）：
      - 夜盘 21:00 ~ 次日 02:30（跨零点，归属前一交易日）
      - 上午 09:00 ~ 10:15
      - 上午 10:30 ~ 11:30
      - 下午 13:30 ~ 15:00
    SHFE 仅在 A 股交易日开市（与 A 股同休假日历）。
    """
    if now_dt is None:
        now_dt = datetime.now()
    t = now_dt.time()
    # 夜盘 00:00~02:30 在时间上属于"前一交易日"的开盘延续；
    # 若前一交易日非 A 股交易日，则不视为开盘（避免周末凌晨误判为开盘）。
    session_date = now_dt.date()
    if t < time(2, 30):
        session_date = session_date - timedelta(days=1)
    if not is_trading_day('A_SHARE', session_date):
        return False
    # 夜盘
    if t >= time(21, 0) or t < time(2, 30):
        return True
    # 上午盘（两段）
    if time(9, 0) <= t < time(10, 15):
        return True
    if time(10, 30) <= t < time(11, 30):
        return True
    # 下午盘
    if time(13, 30) <= t < time(15, 0):
        return True
    return False



# ---------------------------------------------------------------------------
# 便捷判断：给定符号或指数列表，按交易所分类
# ---------------------------------------------------------------------------

def classify_by_exchange(symbols: list) -> dict:
    """
    将符号列表按交易所分组。
    
    Returns:
        {'NYSE': [...], 'XHKG': [...], 'A_SHARE': [...], 'JPX': [...], 'XSWX': [...], None: [...]}
    """
    result = {}
    for sym in symbols:
        ex = symbol_to_exchange(sym)
        result.setdefault(ex, []).append(sym)
    return result


def filter_closed_markets(symbols: list, d: date = None) -> (list, list):
    """
    将符号列表分为「交易所已闭市」和「交易所开市中」两组。
    
    Returns:
        (closed_symbols, open_symbols)
    """
    if d is None:
        d = date.today()
    closed, opened = [], []
    grouped = classify_by_exchange(symbols)
    for ex, syms in grouped.items():
        if ex is None:
            opened.extend(syms)  # 无法识别的按开市处理
        elif is_trading_day(ex, d):
            opened.extend(syms)
        else:
            closed.extend(syms)
    return closed, opened
