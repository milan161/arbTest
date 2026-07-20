import os
import sys
import json
import time
import threading
import functools
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import pandas as pd
from typing import List, Dict, Any, Optional, Set
import logging
import requests
import yaml

logger = logging.getLogger(__name__)

# [V11.0] 加载 lof_config.yaml 获取基金配置（rate_type 等字段不在数据库中的）
_CONFIG_YAML_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'arbcore', 'config', 'lof_config.yaml'))
_FUNDS_WITH_SPOT_RATE: Set[str] = set()
_FUNDS_SUB_CATEGORY: Dict[str, str] = {}
# [AI-2026-07-20] YAML 中的 trade_etf（用于实时估值，如 SPY/QQQ，区别于 related_index .INX/.NDX）
_YAML_TRADE_ETF: Dict[str, str] = {}
# [AI-2026-07-20] YAML 中的 trade_future（纯期货/期货校准对冲标的，如 NK/MNQ/MES/MGC）
_YAML_TRADE_FUTURE: Dict[str, str] = {}
# [AI-2026-07-20] YAML 中的 valuation_portfolio（数据库 unified_fund_list 没有此列）
_YAML_VALUATION_PORTFOLIO: Dict[str, list] = {}
try:
    with open(_CONFIG_YAML_PATH, 'r', encoding='utf-8') as f:
        yaml_cfg = yaml.safe_load(f)
        fund_list = yaml_cfg.get('funds', []) if isinstance(yaml_cfg, dict) else yaml_cfg or []
        for item in fund_list:
            if isinstance(item, dict):
                code = item.get('code', '')
                if item.get('rate_type') == 'spot':
                    _FUNDS_WITH_SPOT_RATE.add(code)
                if 'sub_category' in item:
                    _FUNDS_SUB_CATEGORY[code] = item['sub_category']
                # [AI-2026-07-20] 缓存 trade_etf / trade_future / valuation_portfolio（数据库无这些列）
                if item.get('trade_etf'):
                    _YAML_TRADE_ETF[code] = item['trade_etf']
                if item.get('trade_future'):
                    _YAML_TRADE_FUTURE[code] = item['trade_future']
                if item.get('valuation_portfolio'):
                    _YAML_VALUATION_PORTFOLIO[code] = item['valuation_portfolio']
    logger.info(f"[FX] 在岸价基金({len(_FUNDS_WITH_SPOT_RATE)}只): {_FUNDS_WITH_SPOT_RATE}")
except Exception as e:
    logger.warning(f"[FX] 读取lof_config.yaml获取rate_type/sub_category失败: {e}")

# [V11.0] 实时在岸价缓存（15秒 TTL）
_SPOT_FX_CACHE: Dict[str, float] = {'rate': 0.0, 'time': 0.0}

def _get_realtime_spot_fx() -> float:
    """从新浪获取 USD/CNY 实时在岸价（实盘汇率），15秒缓存"""
    now = time.time()
    if now - _SPOT_FX_CACHE['time'] < 15 and _SPOT_FX_CACHE['rate'] > 0:
        return _SPOT_FX_CACHE['rate']
    try:
        resp = requests.get(
            "http://hq.sinajs.cn/list=fx_susdcny",
            headers={"Referer": "https://finance.sina.com.cn/"},
            timeout=3.0,
            proxies={"http": None, "https": None}
        )
        resp.encoding = 'gbk'
        if resp.text and '="' in resp.text:
            parts = resp.text.split('"')[1].split(',')
            if len(parts) >= 2:
                rate = float(parts[1])
                if rate > 0:
                    _SPOT_FX_CACHE['rate'] = rate
                    _SPOT_FX_CACHE['time'] = now
                    logger.debug(f"[FX] 新浪在岸价: {rate}")
                    return rate
    except Exception as e:
        logger.warning(f"[FX] 获取新浪在岸价失败: {e}")
    # 兜底：用缓存旧值
    if _SPOT_FX_CACHE['rate'] > 0:
        return _SPOT_FX_CACHE['rate']
    return 0.0

# [债券ETF] 引入债券ETF估值服务
from services.bond_etf_valuation import get_bond_etf_valuation, BOND_ETF_META

# 债券ETF代码集合
BOND_ETF_CODES = set(BOND_ETF_META.keys())

# ============================================================
# [V8.1] 轻量级 Dashboard 缓存（5秒 TTL）
# 解决频繁 TAB 切换时重复拉取全量数据导致页面转圈的问题
# ============================================================
class DashboardCache:
    """FIFO 缓存，key = f"{watchlist_str}:{category}", TTL = 5s"""
    def __init__(self, ttl: float = 5.0):
        self._cache: Dict[str, tuple] = {}  # key -> (timestamp, data)
        self._ttl = ttl

    def get(self, key: str) -> Optional[List[Dict]]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.monotonic() - ts > self._ttl:
            del self._cache[key]
            return None
        return data

    def set(self, key: str, data: List[Dict]):
        self._cache[key] = (time.monotonic(), data)

    def invalidate(self):
        """强制全部失效（手动刷新时调用）"""
        self._cache.clear()

_dashboard_cache = DashboardCache()
# [AI-2026-07-16] valuation_meta 缓存（5秒 TTL），避免首次冷启动超时
_valuation_meta_cache = DashboardCache(ttl=5.0)

# [V10.1] 日内不变数据 — 启动时加载一次，当天不再查库
_daily_snapshot = {
    'usd_cny_mid': None,
    'usd_cny_spot': None,
    'loaded': False,
}

def _ensure_daily_snapshot(conn):
    """中间价+在岸价只加载一次（启动时），当天不变"""
    if _daily_snapshot['loaded']:
        return
    try:
        fx_df = pd.read_sql(
            "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn
        )
        if not fx_df.empty and fx_df.iloc[0]['usd_cny_mid'] > 0:
            _daily_snapshot['usd_cny_mid'] = fx_df.iloc[0]['usd_cny_mid']
        # 加载实时在岸价（用于 spot rate 基金）
        _daily_snapshot['usd_cny_spot'] = _get_realtime_spot_fx()
        if _daily_snapshot['usd_cny_spot'] <= 0:
            logger.warning("[SNAPSHOT] 在岸价获取失败，将用中间价兜底（周末/非交易时段可能如此）")
        _daily_snapshot['loaded'] = True
        logger.info(f"[SNAPSHOT] usd_cny_mid={_daily_snapshot['usd_cny_mid']}, usd_cny_spot={_daily_snapshot['usd_cny_spot']}")
    except Exception as e:
        logger.warning(f"[SNAPSHOT] 加载汇率失败: {e}")

# [AI-2026-07-09] 分类已简化为：数据库 category 值与主看板 TAB 名一一对应，无子分类映射。
# 传入的 category 直接作为 SQL 过滤值使用。

# ============================================================
# [V7.1] 内置东财SSE白银期货长连接阅读器
# 程序3独立直连东财推流，无需依赖程序1(5000端口)
# ============================================================
class SSEFuturesReader:
    """
    东财上期所白银期货(AGm)实时推流读取器。
    - 常驻后台线程，长连接到 https://81.futsseapi.eastmoney.com/sse/113_agm_qt
    - 自动重连，自动解析价格、结算价、VWAP
    - 程序3与程序1同时运行时，互不冲突（各自独立连接SSE推流，读同一组数据）
    """
    def __init__(self):
        self.ag0_price = 0.0
        self.ag0_settlement = 0.0
        self.ag0_vwap = 0.0
        self.running = False
        self._thread = None

    def start(self):
        """启动后台SSE监听线程（幂等：已运行则跳过）"""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="SSE-Silver")
        self._thread.start()
        logger.info("[SSE] 白银期货SSE后台线程已启动 (东财 113_agm_qt)")

    def stop(self):
        self.running = False

    def _is_trading_time(self) -> bool:
        """沪银交易时段：周一~周五 09:00-11:30, 13:30-15:00, 21:00-次日03:00; 周六 00:00-03:00"""
        import time as _t
        now = _t.localtime()
        h, m, wd = now.tm_hour, now.tm_min, now.tm_wday
        if 0 <= wd <= 4:
            if (h == 9 and m >= 0) or h == 10 or (h == 11 and m < 30): return True
            if (h == 13 and m >= 30) or h == 14 or (h == 15 and m == 0): return True
            if h >= 21 or h < 3: return True
        elif wd == 5 and h < 3: return True
        return False

    def _listen_loop(self):
        import requests
        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        retry_delay = 2.0
        while self.running:
            if not self._is_trading_time():
                time.sleep(15)
                continue
            try:
                res = requests.get(url, stream=True, timeout=(5, 60),
                                   verify=False, proxies={"http": None, "https": None})
                if res.status_code == 200:
                    retry_delay = 2.0
                    for line in res.iter_lines():
                        if not self.running:
                            break
                        if line:
                            decoded = line.decode('utf-8', errors='replace')
                            if decoded.startswith('data:'):
                                try:
                                    d = json.loads(decoded[5:]).get('qt', {})
                                    if 'p' in d:
                                        self.ag0_price = float(d['p'])
                                    if 'fzjsj' in d and d['fzjsj'] != '-':
                                        self.ag0_settlement = float(d['fzjsj'])
                                    elif 'rzjsj' in d and d['rzjsj'] != '-':
                                        self.ag0_settlement = float(d['rzjsj'])
                                    if 'cje' in d and 'vol' in d and d.get('vol', 0) > 0:
                                        self.ag0_vwap = d['cje'] / (d['vol'] * 15)
                                    elif 'av' in d and d['av'] != '-':
                                        self.ag0_vwap = float(d['av'])
                                except Exception:
                                    pass
                res.close()
            except Exception as e:
                logger.debug(f"[SSE] 白银长连接断开: {e}，{retry_delay:.0f}s后重连...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60.0)


# 全局单例 —— 在模块第一次被导入时创建，随后自动启动
_sse_reader = SSEFuturesReader()
_sse_reader.start()

# [AI-2026-07-02] AG0 期货盘口：东财 SSE 价格 + 新浪买卖盘口
def _get_ag0_future_quote():
    """获取沪银 AG0 实时盘口数据（东财 SSE 价格 + 新浪 bid/ask）"""
    quote = None
    # 优先：东财 SSE 价格和结算价
    if _sse_reader.ag0_price > 0:
        quote = {
            'price': _sse_reader.ag0_price,
            'bid': _sse_reader.ag0_price,
            'ask': _sse_reader.ag0_price,
            'settlement': _sse_reader.ag0_settlement,
            'vwap': _sse_reader.ag0_vwap,
            'source': '东财SSE'
        }
    # 补充：新浪 nf_AG0 获取买卖盘口
    try:
        import requests
        r = requests.get('http://hq.sinajs.cn/list=nf_AG0',
                         headers={'Referer': 'https://finance.sina.com.cn/'}, timeout=2.0)
        if r.status_code == 200 and '="' in r.text:
            parts = r.text.split('"')[1].split(',')
            if len(parts) >= 11:
                sina_price = float(parts[8]) if parts[8] else 0.0
                sina_settle = float(parts[10]) if parts[10] else 0.0
                sina_bid = float(parts[6]) if len(parts) > 6 and parts[6] else 0.0
                sina_ask = float(parts[7]) if len(parts) > 7 and parts[7] else 0.0
                if not quote:
                    quote = {'price': sina_price, 'source': '新浪'}
                # 用新浪覆盖 bid/ask（更准），保留东财的结算价
                if sina_bid > 0:
                    quote['bid'] = sina_bid
                if sina_ask > 0:
                    quote['ask'] = sina_ask
                if sina_settle > 0:
                    quote['settlement'] = sina_settle
                quote['source'] = '东财SSE+新浪'
    except Exception:
        pass
    return quote

# [V10.2] 指数涨跌幅日内缓存：同指数同日只查一次新浪
_index_pct_cache = {}  # "HSCEI_2026-06-18" -> float

_index_pct_cache_time = {}
def get_index_change_percent(symbol: str) -> float:
    """
    [新浪/腾讯指数极速接口] 直接拉取指数日内涨跌幅百分比
    无感对接国内指数（000xxx, 399xxx）、恒生指数HSI等，无需频繁维护静态基准价
    """
    import requests
    headers_sina = {
        'Referer': 'https://finance.sina.com.cn/',
        'Accept': 'text/event-stream'  # [V7.2] 借鉴长连接头部以提高稳定性
    }
    headers_tencent = {
        'Referer': 'https://finance.qq.com/',
        'User-Agent': 'Mozilla/5.0'
    }
    
    clean_sym = symbol.strip().upper()
    if clean_sym.endswith('.CSI'):
        clean_sym = clean_sym[:-4]
    
    global _index_pct_cache, _index_pct_cache_time
    import time
    cache_key = clean_sym
    now_ts = time.time()
    if cache_key in _index_pct_cache_time and now_ts - _index_pct_cache_time[cache_key] < 60 and cache_key in _index_pct_cache:
        return _index_pct_cache[cache_key]

    result = 0.0
    try:
        # 1. 港股常见指数 - 必须先检查更长的字符串 HSTECH/HSCEI，再检查 HSI
        if 'HSTECH' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSTECH", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSTECH 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'HSCEI' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSCEI", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSCEI 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'HSI' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSI", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSI 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'CES300' in clean_sym or 'CES300.HI' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkCES300", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 CES300 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
                    
        # [AI-2026-07-09] 日经225(N225) — 新浪全球指数接口 int_nikkei
        elif clean_sym in ('N225', 'NKY', 'NIKKEI'):
            r = requests.get("http://hq.sinajs.cn/list=int_nikkei", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 4:
                    # 新浪全球指数格式: 名称,当前价,涨跌额,涨跌幅%
                    result = float(parts[3])
                    logger.info(f"[INDEX-SINA] 获取日经225 {clean_sym} 涨跌幅: {result}%")
                    
        # 2. A股指数 (6位代码)
        elif clean_sym.isdigit() and len(clean_sym) == 6:
            # 优先尝试新浪接口
            if clean_sym.startswith('399') or clean_sym.startswith('159') or clean_sym.startswith('3999'):
                url = f"http://hq.sinajs.cn/list=s_sz{clean_sym}"
            else:
                url = f"http://hq.sinajs.cn/list=s_sh{clean_sym}"
                
            r = requests.get(url, headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 4 and float(parts[3]) != 0.0:
                    logger.info(f"[INDEX-SINA] 获取A股指数 {clean_sym} 涨跌幅: {parts[3]}%")
                    result = float(parts[3])
                    
            # [V7.2] 新浪降级策略：使用腾讯接口兜底 (完美解决新浪没有中证指数的问题)
            if result == 0.0:
                prefix = 'sz' if clean_sym.startswith(('399', '159')) else 'sh'
                url_tencent = f"http://qt.gtimg.cn/q={prefix}{clean_sym}"
                r_tc = requests.get(url_tencent, headers=headers_tencent, timeout=1.5)
                if r_tc.status_code == 200 and 'v_' in r_tc.text:
                    tc_parts = r_tc.text.split('"')[1].split('~')
                    if len(tc_parts) >= 33:
                        logger.info(f"[INDEX-TENCENT] 兜底获取指数 {clean_sym} 涨跌幅: {tc_parts[32]}%")
                        result = float(tc_parts[32])
    except Exception as e:
        logger.debug(f"Index fetch failed for {symbol}: {e}")
    # 写入日内缓存
    if result != 0.0:
        _index_pct_cache[cache_key] = result
        _index_pct_cache_time[cache_key] = time.time()
    return result

_prefetch_cache = {}
_prefetch_cache_time = 0

# [V10.9] 非标代码映射表（模块级，prefetch_index_changes 和 fallback 共用）
_INDEX_CODE_MAP = {
    '中小100': '399011', '移动互联': '399363', '中证500': '000905',
    '中证TMT': '399989', '中证白酒': '399997', '中证消费': '399932',
    '中证养老': '399812', '中证银行': '399986', '国证有色': '399395',
    '证券公司': '399975', '国企改革': '399974',
    'SZ399989': '399989', 'SZ399990': '399990', 'SZ399993': '399993',
    'H30094': '000852', '950090': '000852',
    '930713': '399006', '930875': '399006',
    '930720': '399005', '930997': '399005',
    '000922': '399001', '000961': '399330', '000979': '399441',
    'CES300.HI': '399300',
    'KWEB': None, 'RSPH': None,
}

def _clean_index_symbol(sym: str) -> str:
    """对指数符号做清洗和映射，返回可用于 index_history 查询的代码"""
    clean = sym.strip().upper()
    if not clean:
        return ''
    # 映射表
    if clean in _INDEX_CODE_MAP:
        return _INDEX_CODE_MAP[clean] or ''
    # ^ 前缀（如 ^HSI）
    if clean.startswith('^'):
        clean = clean[1:]
    # .CSI 后缀
    if clean.endswith('.CSI'):
        clean = clean[:-4]
    # SZ/SH 前缀
    if clean.startswith('SZ') or clean.startswith('SH'):
        clean = clean[2:]
    # 再次查映射表
    if clean in _INDEX_CODE_MAP:
        return _INDEX_CODE_MAP[clean] or ''
    # HK 指数保持原样
    # A股 6位纯数字保持原样
    return clean

def _is_hk_index_symbol(clean_sym: str) -> bool:
    """判断清洗后的符号是否为港股指数"""
    if not clean_sym:
        return False
    hk_prefixes = ('HSI', 'HSTECH', 'HSCEI', 'HSCI', 'HSCCI', 'HSSCNE',
                   'HSSI', 'HSMI', 'HSSFML25', 'HSSCBBAI',
                   'HSHK', 'HSCIC', 'HSI50', 'HSML25', 'HSCC',
                   'HSCE', 'HSH', 'HSI100', 'HSI200', 'HSI500',
                   'HSCON', 'HSFIN', 'HSIND', 'HSENER', 'HSUTIL',
                   'HSPROP', 'HSINFO', 'HSIT', 'HSMT', 'HSCONS',
                   'HSMED', 'HSHEAL', 'HSRE', 'HSCOM', 'HSFIN25',
                   'HSHK50', 'HSCN', 'HSINT', 'HSREIT', 'HSUTIL')
    return any(clean_sym.upper().startswith(p) for p in hk_prefixes)

def _is_a_share_index_symbol(clean_sym: str) -> bool:
    """判断清洗后的符号是否为A股指数（6位纯数字）"""
    if not clean_sym:
        return False
    return clean_sym.isdigit() and len(clean_sym) == 6

def _classify_index_symbol(sym: str) -> str:
    """
    对单个 symbol 做清洗 + 分类，返回 ('a_share'|'hk'|'other', original_sym)
    """
    if not sym or sym == '-':
        return ('skip', '')
    clean = _clean_index_symbol(sym)
    if not clean:
        return ('skip', '')
    # 美股ETF 标记为 skip（走IB/Futu）
    US_ETF_KEYWORDS = {'XOP', 'GLD', 'USO', 'SPY', 'QQQ', 'XBI', 'XLY', 'SOXX',
                       'ARKK', 'ARKG', 'EEM', 'VWO', 'INDA', 'EWJ', 'KWEB', 'RSPH',
                       'LQD', 'HYG', 'TLT', 'IEF', 'SHY', 'AGG', 'BND'}
    if any(etf in clean.upper() for etf in US_ETF_KEYWORDS):
        return ('skip', '')
    if _is_a_share_index_symbol(clean):
        return ('a_share', sym)
    if _is_hk_index_symbol(clean):
        return ('hk', sym)
    return ('other', sym)

def _build_index_daily_fallback(symbols: List[str], conn, now) -> Dict[str, Dict[str, float]]:
    """[V10.16] 从 index_history 兜底读取最新收盘价，并计算真实涨跌幅

    涨跌幅 = (最新收盘价 - 前一个交易日收盘价) / 前一个交易日收盘价 × 100

    index_history 表包含 84 个指数、12946 条记录（含全部港股/A股/CSI），
    由 backfill_tdx_index.py 通过 TDX 回补写入。

    场景举例：
    - 周一 17:00（收盘后）：最新=周一收盘价, 前一=上周五收盘价 → pct=周一真实涨跌幅
    - 周六（周末）：最新=上周五收盘价, 前一=上周四收盘价 → pct=上周五真实涨跌幅
    - 盘中（当天数据已入库）：最新=今天盘中, 前一=昨天收盘价 → pct 就是实时涨跌幅
    """
    if not conn or not symbols:
        return {}

    # 1. 清洗所有符号
    orig_to_clean = {}
    clean_set = set()
    for sym in symbols:
        if not sym or sym == '-':
            continue
        c = _clean_index_symbol(sym)
        if c:
            orig_to_clean[sym] = c
            clean_set.add(c)

    if not clean_set:
        return {}

    # 2. 从 index_history 用 ROW_NUMBER pivot 取每个 symbol 最新两条收盘价
    #    LAG 在 rn=1 行永远是 NULL，所以改用 rn=1 和 rn=2 的 GROUP BY pivot
    placeholders = ','.join(['?' for _ in clean_set])
    rows = conn.execute(f"""
        SELECT symbol,
            MAX(CASE WHEN rn = 1 THEN close END) as latest_close,
            MAX(CASE WHEN rn = 2 THEN close END) as prev_close
        FROM (
            SELECT symbol, close,
                ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
            FROM index_history
            WHERE symbol IN ({placeholders})
        )
        WHERE rn IN (1, 2)
        GROUP BY symbol
    """, list(clean_set)).fetchall()

    # 3. 计算真实涨跌幅
    db_data = {}
    for symbol, latest_price, prev_price in rows:
        if latest_price and latest_price > 0:
            if prev_price and prev_price > 0 and prev_price != latest_price:
                pct = (latest_price - prev_price) / prev_price * 100
            else:
                pct = 0.0  # 只有一条记录或价格平盘
            db_data[symbol] = {"price": latest_price, "pct": round(pct, 4)}

    # 3.5 [FIX] 当清洗后的符号在数据库中没有数据时，尝试用原始符号查询
    # 例如: 930713.CSI -> 映射到 399006，但399006没有数据，而930713.CSI有数据
    missing_clean = clean_set - set(db_data.keys())
    if missing_clean:
        clean_to_orig = {}
        for orig_sym, clean_sym in orig_to_clean.items():
            if clean_sym in missing_clean:
                clean_to_orig[clean_sym] = orig_sym
        
        orig_symbols_to_query = list(clean_to_orig.values())
        if orig_symbols_to_query:
            placeholders2 = ','.join(['?' for _ in orig_symbols_to_query])
            rows2 = conn.execute(f"""
                SELECT symbol,
                    MAX(CASE WHEN rn = 1 THEN close END) as latest_close,
                    MAX(CASE WHEN rn = 2 THEN close END) as prev_close
                FROM (
                    SELECT symbol, close,
                        ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) as rn
                    FROM index_history
                    WHERE symbol IN ({placeholders2})
                )
                WHERE rn IN (1, 2)
                GROUP BY symbol
            """, orig_symbols_to_query).fetchall()
            
            for symbol, latest_price, prev_price in rows2:
                if latest_price and latest_price > 0:
                    if prev_price and prev_price > 0 and prev_price != latest_price:
                        pct = (latest_price - prev_price) / prev_price * 100
                    else:
                        pct = 0.0
                    for clean_sym, orig_sym in clean_to_orig.items():
                        if orig_sym == symbol:
                            db_data[clean_sym] = {"price": latest_price, "pct": round(pct, 4)}
                            break

    # 4. 映射回原始 symbols
    res = {}
    for orig_sym, clean_sym in orig_to_clean.items():
        data = db_data.get(clean_sym)
        if data:
            res[orig_sym] = data

    return res


def prefetch_index_changes(symbols: List[str], conn=None) -> Dict[str, Dict[str, float]]:
    """
    [V10.16] 收盘后不再爬实时数据：
    [AI-2026-07-07] 改用 exchange_calendars 日历判断各市场交易日

    - 非交易日（周末/假期）→ 全部指数走 index_history 收盘价，不调任何 API
    - 某交易所非交易日（如美股假期A股正常）→ 该交易所指数走 DB 兜底
    - 15:00后 A股指数 → 直接取 index_history 收盘价，不调API
    - 16:00后 港股指数 → 直接取 index_history 收盘价，不调API
    - 交易时段内 → 正常拉腾讯/新浪/东财API
    """
    global _prefetch_cache, _prefetch_cache_time
    import time
    # [V10.17] 缓存改为 symbol-aware：必须所有请求的符号都在缓存中才返回
    requested_set = set(s for s in symbols if s and s != '-')
    if time.time() - _prefetch_cache_time < 60 and _prefetch_cache:
        if requested_set.issubset(_prefetch_cache.keys()):
            return _prefetch_cache
    if not symbols:
        return {}

    now = datetime.now()
    from arbcore.utils.market_calendar import symbol_to_exchange, is_trading_day

    # ====== Step 0: 按交易所分组 ======
    exchange_syms = {}  # {exchange: [syms]}
    for sym in symbols:
        if not sym or sym == '-':
            continue
        ex = symbol_to_exchange(sym)
        if ex is None:
            continue  # 无法识别的跳过
        exchange_syms.setdefault(ex, []).append(sym)

    # ====== Step 1: 判断各交易所今日是否开市 + 盘中/收盘 ======
    db_results = {}
    api_syms = []

    for ex, syms in exchange_syms.items():
        # 1a. 是否交易日？
        if not is_trading_day(ex, now.date()):
            # 非交易日 → 全部走 DB 兜底
            if conn:
                try:
                    part = _build_index_daily_fallback(syms, conn, now)
                    if part:
                        db_results.update(part)
                        logger.info(f"[INDEX-DB] {ex} 非交易日 {now.date()}，"
                                    f"{len(part)}/{len(syms)} 个指数取上一交易日收盘价")
                except Exception as e:
                    logger.warning(f"[INDEX-DB] {ex} 兜底失败: {e}")
            continue

        # 1b. 交易日内：判断是否已收盘
        if ex == 'A_SHARE':
            closed = now.hour >= 15
        elif ex == 'XHKG':
            closed = now.hour >= 16
        elif ex == 'JPX':
            # [AI-2026-07-20] 日本指数(N225)通过新浪全球指数API获取 int_nikkei，24/7返回最新收盘价
            # 日本股市 08:00-14:00 CST (09:00-15:00 JST)，但收盘后新浪仍有当日收盘数据
            # 设为始终可API获取，用于写入 index_history 供 T-1 静态估值使用
            closed = False
        else:
            # 其他交易所（如美股指数）默认不在此API获取
            closed = True

        if closed:
            if conn:
                try:
                    part = _build_index_daily_fallback(syms, conn, now)
                    if part:
                        db_results.update(part)
                except Exception as e:
                    logger.warning(f"[INDEX-DB] {ex} 收盘兜底失败: {e}")
        else:
            api_syms.extend(syms)

    # ====== Step 2: 还在交易时段的 → 调 API ======
    api_results = {}
    if api_syms:
        api_results = _fetch_realtime_indices(api_syms, now)

    # [AI-2026-07-09] N225历史存储：每次获取实时数据后写入index_history，供T-1静态估值使用
    # N225历史无法通过TDX回采（新浪/东财均不支持历史K线），必须靠实时抓取积累
    if api_results:
        try:
            today_str = now.strftime('%Y-%m-%d')
            import sqlite3
            # [AI-2026-07-13] 修复路径少一层的问题：从 services/ 需往上3层到项目根，再到 database/
            db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'database', 'arb_master.db')
            conn_write = sqlite3.connect(db_path)
            for sym, data in api_results.items():
                if sym in ('N225', '.INX', '.NDX') and data.get('price', 0) > 0:
                    conn_write.execute(
                        "INSERT OR REPLACE INTO index_history (symbol, date, close, source) VALUES (?, ?, ?, ?)",
                        (sym, today_str, data['price'], 'sina')
                    )
                    logger.info(f"[INDEX-HISTORY] 写入 {sym} {today_str} close={data['price']}")
            conn_write.commit()
            conn_write.close()
        except Exception as e:
            logger.warning(f"写入N225历史数据异常: {e}")

    # ====== Step 3: 合并并缓存 ======
    res = {**db_results, **api_results}
    if res:
        _prefetch_cache = res
        _prefetch_cache_time = time.time()
    elif _prefetch_cache:
        return _prefetch_cache

    return res


def _fetch_realtime_indices(symbols: List[str], now) -> Dict[str, Dict[str, float]]:
    """
    [V10.14] 从腾讯→新浪→东财 三级瀑布获取实时指数行情
    仅用于还在交易时段的指数（收盘后的指数已在 prefetch_index_changes 中走DB兜底）
    """
    if not symbols:
        return {}

    # [V10.14] 统一使用模块级 _INDEX_CODE_MAP，不再重复定义
    US_ETF_KEYWORDS = {'XOP', 'GLD', 'USO', 'SPY', 'QQQ', 'XBI', 'XLY', 'SOXX',
                       'ARKK', 'ARKG', 'EEM', 'VWO', 'INDA', 'EWJ', 'KWEB', 'RSPH',
                       'LQD', 'HYG', 'TLT', 'IEF', 'SHY', 'AGG', 'BND'}

    # [V10.19] HK非标指数→标准指数别名映射
    # 腾讯/新浪只支持 HSI/HSCEI/HSTECH 三个标准HK指数
    # 其他HK指数（HSCI/HSCCI/HSSCNE/HSSI/HSMI）通过此表映射到最接近的标准指数
    _HK_INDEX_ALIAS_MAP = {
        'HSCI': 'HSI',       # 恒生综合指数 → 恒生指数
        'HSCCI': 'HSI',      # 恒生中国内地100 → 恒生指数
        'HSSCNE': 'HSCEI',   # 恒生新经济 → 国企指数
        'HSSI': 'HSCEI',     # 恒生小型股 → 国企指数
        'HSMI': 'HSCEI',     # 恒生中型股 → 国企指数
    }

    # [V10.19] CSI代码(930xxx/931xxx等)不应走腾讯sh/sz查询，应直接走东财
    def _is_csi_index_code(code: str) -> bool:
        """判断是否为中证指数代码（如930914, 931234等）"""
        return code.isdigit() and len(code) == 6 and (code.startswith('930') or code.startswith('931') or code.startswith('932'))

    import requests
    headers_tencent = {'Referer': 'https://finance.qq.com/', 'User-Agent': 'Mozilla/5.0'}
    headers_sina = {'Referer': 'https://finance.sina.com.cn/', 'Accept': 'text/event-stream'}
    
    tencent_requests = set()
    sina_requests = set()
    tc_to_syms = {}
    sina_to_syms = {}
    
    for sym in symbols:
        if not sym or sym == '-': continue
        clean_sym = sym.strip().upper()

        if any(etf in clean_sym for etf in US_ETF_KEYWORDS):
            continue

        if clean_sym in _INDEX_CODE_MAP:
            mapped = _INDEX_CODE_MAP[clean_sym]
            if mapped is None:
                continue
            clean_sym = mapped

        if clean_sym.endswith('.CSI'): clean_sym = clean_sym[:-4]
        if clean_sym.startswith('SZ') or clean_sym.startswith('SH'): clean_sym = clean_sym[2:]
        if clean_sym in _INDEX_CODE_MAP:
            clean_sym = _INDEX_CODE_MAP[clean_sym]
        
        tc_req = ""
        sina_req = ""
        ret_code = ""
        
        # [V10.19] CSI代码(如930914)跳过腾讯/新浪，直接走东财
        if _is_csi_index_code(clean_sym):
            # CSI代码腾讯sh/sz查询返回无意义数据(如sh930914→v_pv_none_match)
            # 跳过腾讯/新浪，让东财兜底处理
            continue
        elif clean_sym.isdigit() and len(clean_sym) == 6:
            if clean_sym.startswith('399') or clean_sym.startswith('159') or clean_sym.startswith('3999'):
                tc_req = f"sz{clean_sym}"
                sina_req = f"s_sz{clean_sym}"
            else:
                tc_req = f"sh{clean_sym}"
                sina_req = f"s_sh{clean_sym}"
            ret_code = clean_sym
        # [V10.19] 港股指数→精确匹配，并在res中同时写入原始sym和别名对应关系
        elif clean_sym == 'HSTECH':
            tc_req, sina_req, ret_code = "hkHSTECH", "rt_hkHSTECH", "HSTECH"
        elif clean_sym == 'HSCEI':
            tc_req, sina_req, ret_code = "hkHSCEI", "rt_hkHSCEI", "HSCEI"
        elif clean_sym == 'HSI':
            tc_req, sina_req, ret_code = "hkHSI", "rt_hkHSI", "HSI"
        elif clean_sym in _HK_INDEX_ALIAS_MAP:
            # 非标HK指数→映射到标准指数，同时记录映射关系
            # 例如 HSCI→HSI, HSCCI→HSI, HSSI→HSCEI 等
            mapped = _HK_INDEX_ALIAS_MAP[clean_sym]
            if mapped == 'HSI':
                tc_req, sina_req, ret_code = "hkHSI", "rt_hkHSI", "HSI"
            elif mapped == 'HSCEI':
                tc_req, sina_req, ret_code = "hkHSCEI", "rt_hkHSCEI", "HSCEI"
            elif mapped == 'HSTECH':
                tc_req, sina_req, ret_code = "hkHSTECH", "rt_hkHSTECH", "HSTECH"
            else:
                continue
            # 在tc_to_syms/sina_to_syms中同时注册原始sym和ret_code的映射
            # 这样API返回ret_code时，能将数据写入res[original_sym]
        elif clean_sym.startswith('.') and len(clean_sym) <= 10:
            # [V10.13] 美股指数（.INX, .NDX, .SP500-45 等）走新浪获取
            sina_req = f"s_sh{clean_sym}"
            ret_code = clean_sym
        # [AI-2026-07-09] 日经225(N225) — 新浪全球指数接口 int_nikkei
        elif clean_sym in ('N225', 'NKY', 'NIKKEI'):
            sina_req = "int_nikkei"
            ret_code = "N225"
        else:
            continue
            
        tencent_requests.add(tc_req)
        tc_to_syms.setdefault(ret_code, []).append(sym)
        sina_to_syms.setdefault(ret_code, []).append(sym)
        # [AI-2026-07-20] 全球指数（sina_req != ret_code）额外注册 sina_req 键
        # 新浪响应变量名（如 int_nikkei）经解析后提取的是 sina_req，不是 ret_code
        # 例如 N225: ret_code="N225", sina_req="int_nikkei", 新浪返回 hq_str_int_nikkei
        if sina_req and sina_req != ret_code:
            sina_to_syms.setdefault(sina_req, []).append(sym)

    res = {}
    
    # 1. 优先从腾讯获取
    if tencent_requests:
        url_tc = f"http://qt.gtimg.cn/q={','.join(tencent_requests)}"
        try:
            r_tc = requests.get(url_tc, headers=headers_tencent, timeout=2.0)
            if r_tc.status_code == 200:
                for line in r_tc.text.split(';'):
                    if 'v_' not in line or '=' not in line: continue
                    data_str = line.split('=')[1].strip(' "')
                    tc_parts = data_str.split('~')
                    if len(tc_parts) >= 33:
                        code = tc_parts[2]
                        if code in tc_to_syms:
                            for original_sym in tc_to_syms[code]:
                                res[original_sym] = {"price": float(tc_parts[3]), "pct": float(tc_parts[32])}
                            logger.info(f"[INDEX-TENCENT] 获取指数 {code} 价格: {tc_parts[3]} 涨跌幅: {tc_parts[32]}%")
        except Exception as e:
            logger.warning(f"预取腾讯指数异常: {e}")

    # 2. 对于腾讯没拿到数据的指数，用新浪接口兜底
    missing_sina_reqs = set()
    for ret_code, syms in sina_to_syms.items():
        if any(s not in res for s in syms):
            if ret_code.isdigit():
                if ret_code.startswith('399') or ret_code.startswith('159') or ret_code.startswith('3999'):
                    missing_sina_reqs.add(f"s_sz{ret_code}")
                else:
                    missing_sina_reqs.add(f"s_sh{ret_code}")
            # [AI-2026-07-09] 日经225等全球指数 — 直接用新浪全球指数接口名
            elif ret_code == 'N225':
                missing_sina_reqs.add("int_nikkei")
            else:
                missing_sina_reqs.add(f"rt_hk{ret_code}")
                
    if missing_sina_reqs:
        url = f"http://hq.sinajs.cn/list={','.join(missing_sina_reqs)}"
        try:
            r = requests.get(url, headers=headers_sina, timeout=2.0)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if '="' not in line: continue
                    var_name = line.split('=')[0].strip()
                    parts = line.split('"')[1].split(',')
                    if var_name.startswith('var hq_str_s_sh') or var_name.startswith('var hq_str_s_sz'):
                        code = var_name[-6:]
                        if len(parts) >= 4 and float(parts[3]) != 0.0:
                            if code in sina_to_syms:
                                for original_sym in sina_to_syms[code]:
                                    if original_sym not in res:
                                        res[original_sym] = {"price": float(parts[1]), "pct": float(parts[3])}
                    elif var_name.startswith('var hq_str_rt_hk'):
                        code = var_name.split('rt_hk')[1]
                        if len(parts) >= 9:
                            if code in sina_to_syms:
                                for original_sym in sina_to_syms[code]:
                                    if original_sym not in res:
                                        res[original_sym] = {"price": float(parts[6]), "pct": float(parts[8])}
                    elif var_name.startswith('var hq_str_s_sh.'):
                        # [V10.13] 美股指数新浪格式: var hq_str_s_sh.INX="..."
                        # 新浪美股指数返回格式: 名称,当前点位,涨跌额,涨跌幅%,最高,最低,昨收,...
                        code = var_name.replace('var hq_str_s_sh.', '')
                        if len(parts) >= 4 and float(parts[3]) != 0.0:
                            if code in sina_to_syms:
                                for original_sym in sina_to_syms[code]:
                                    if original_sym not in res:
                                        res[original_sym] = {"price": float(parts[1]), "pct": float(parts[3])}
                                        logger.info(f"[INDEX-SINA-US] 获取指数 {original_sym} 价格: {parts[1]} 涨跌幅: {parts[3]}%")
                    # [AI-2026-07-09] 新浪全球指数格式（日经225等）: var hq_str_int_nikkei="名称,价格,涨跌,涨跌幅%,日期,..."
                    elif var_name.startswith('var hq_str_int_'):
                        code = var_name.replace('var hq_str_', '')
                        if code in sina_to_syms:
                            for original_sym in sina_to_syms[code]:
                                if original_sym not in res:
                                    if len(parts) >= 4:
                                        res[original_sym] = {"price": float(parts[1]), "pct": float(parts[3])}
                                        logger.info(f"[INDEX-SINA-GLOBAL] 获取指数 {original_sym} 价格: {parts[1]} 涨跌幅: {parts[3]}%")
        except Exception as e:
            logger.warning(f"预取新浪指数兜底异常: {e}")

    # [V10.12] 3. 东财API兜底：港股/CSI非标指数（腾讯/新浪不识别的）
    # 东财 secid 映射规则：
    #   HSSI, HSMI, HSFML25, HSSCBBAI → 124.{code}
    #   HSCEI → 100.{code}
    #   CSI前缀 → 2.{code[3:]}
    #   其余港股(HSI, HSCI, HSCCI, HSSCNE等) → 116.{code}
    EM_SECID_MAP = {
        'HSSI': '124.HSSI', 'HSMI': '124.HSMI', 'HSSFML25': '124.HSSFML25',
        'HSSCBBAI': '124.HSSCBBAI', 'HSCEI': '100.HSCEI',
    }
    EM_HK_KEYWORDS = {'HSI', 'HSCI', 'HSCCI', 'HSSCNE', 'HSTECH'}

    em_requests = {}  # original_sym -> secid
    for sym in symbols:
        if not sym or sym == '-': continue
        clean_sym = sym.strip().upper()
        if any(etf in clean_sym for etf in US_ETF_KEYWORDS):
            continue
        if sym in res:
            continue  # 已有数据，跳过
        # 已在腾讯/新浪获取成功的 ret_code 也跳过
        # 判断是否需要东财兜底
        secid = None
        if clean_sym in EM_SECID_MAP:
            secid = EM_SECID_MAP[clean_sym]
        elif clean_sym[:3] == 'CSI':
            secid = f"2.{clean_sym[3:]}"
        elif clean_sym.startswith('H') and any(kw in clean_sym for kw in EM_HK_KEYWORDS):
            secid = f"116.{clean_sym}"
        elif clean_sym.endswith('.CSI'):
            # 930914.CSI → 2.930914
            code_part = clean_sym[:-4]
            if code_part.isdigit():
                secid = f"2.{code_part}"
        if secid:
            em_requests[sym] = secid

    if em_requests:
        headers_em = {
            'Referer': 'https://quote.eastmoney.com/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        }
        for original_sym, secid in em_requests.items():
            try:
                url_em = f"https://push2.eastmoney.com/api/qt/stock/get"
                params_em = {
                    'secid': secid,
                    'fields': 'f43,f58,f170',
                    'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                    'fltt': '1',
                }
                r_em = requests.get(url_em, params=params_em, headers=headers_em, timeout=3.0)
                data_em = r_em.json()
                if data_em.get('rc') == 0 and data_em.get('data'):
                    d = data_em['data']
                    price = d.get('f43', 0)
                    pct = d.get('f170', 0)
                    name = d.get('f58', '')
                    # 东财 f43/f170 已经是实际值（fltt=1时），无需除以100
                    if price and price > 0:
                        res[original_sym] = {"price": float(price), "pct": float(pct)}
                        logger.info(f"[INDEX-EASTMONEY] 获取指数 {original_sym}({secid}) 价格: {price} 涨跌幅: {pct}%")
            except Exception as e:
                logger.debug(f"东财获取 {original_sym}({secid}) 失败: {e}")

    # 4. 增加未获取到的指数 Debug 记录（跳过美股ETF和已映射的非标代码）
    # [V10.13] 美股相关符号（含 S&P 系列、美股指数代理 .INX/.NDX 等）全部跳过，不报 DEBUG
    US_RELATED_SYMBOLS = {'.INX', '.NDX', '.SPHCMSHP', '.SPACEVCP', 'VNQ', 'H11136'}
    for sym in symbols:
        if not sym or sym == '-': continue
        clean_sym_check = sym.strip().upper()
        if any(etf in clean_sym_check for etf in US_ETF_KEYWORDS):
            continue  # 美股ETF不报错，它们走IB/Futu
        if clean_sym_check in US_RELATED_SYMBOLS:
            continue  # 美股相关符号不报错
        if clean_sym_check in _INDEX_CODE_MAP:
            continue  # 已映射的代码不报错
        if sym not in res:
            logger.debug(f"[INDEX-DEBUG] 指数行情完全缺失: {sym} (未匹配到腾讯/新浪数据)")

    return res

class FundService:
    def __init__(self, db, market_data_service=None, config_service=None):
        self.db = db
        self.market_data_service = market_data_service
        self.config_service = config_service
        self._calculator = None
    
    def _get_calculator(self):
        """懒加载估值计算器"""
        if self._calculator is None:
            try:
                from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
                self._calculator = DynamicValuationCalculator(self.db)
            except Exception as e:
                logger.error(f"初始化估值计算器失败: {e}")
        return self._calculator

    def get_unified_dashboard_data(self, watchlist: List[str] = None, category: str = None) -> List[Dict[str, Any]]:
        """
        [V8.1] 性能大修：SQL 级过滤 + 5秒缓存 + 批量历史查询
        """
        # ── 缓存 key ──
        cache_key = f"{','.join(sorted(watchlist)) if watchlist else ''}:{category or ''}"
        cached = _dashboard_cache.get(cache_key)
        if cached is not None:
            return cached

        conn = self.db._get_conn()
        try:
            # ── 1. SQL 级过滤基金列表（不下拉全量数据） ──
            where_clause = ""
            params: List[Any] = []
            if watchlist:
                placeholders = ",".join("?" for _ in watchlist)
                where_clause = f"WHERE fund_code IN ({placeholders})"
                params.extend(watchlist)
            elif category:
                # [AI-2026-07-09] 分类已简化，category 直接对应数据库值
                cats = [category]
                placeholders = ",".join("?" for _ in cats)
                where_clause = f"WHERE category IN ({placeholders})"
                params.extend(cats)

            funds_df = pd.read_sql_query(
                f"SELECT fund_code, fund_name, category, related_index, pos_ratio, idx_code, idx_name FROM unified_fund_list {where_clause}",
                conn, params=params
            )

            if funds_df is None or funds_df.empty:
                _dashboard_cache.set(cache_key, [])
                return []

            # [AI-2026-07-20] 从结果中剔除暂停分类的基金（不生成快照、不占 CPU）
            # 注意：paused_set 可能在本方法前面已定义（指数过滤处），也可能未定义
            if 'paused_set' not in dir():
                try:
                    import json
                    raw = self.db.get_app_setting('paused_categories', None)
                    paused_set = set(json.loads(raw)) if raw else set()
                except Exception:
                    paused_set = set()
            if paused_set:
                before = len(funds_df)
                funds_df = funds_df[~funds_df['category'].isin(paused_set)]
                if len(funds_df) < before:
                    logger.info(f"[DASHBOARD-FILTER] 过滤暂停分类，{before} -> {len(funds_df)} 只基金")

            # ── 2. 批量获取 fund_purchase_status 状态费率（AKShare 日更）──
            status_df = pd.read_sql_query(
                "SELECT fund_code, purchase_status, redemption_status, purchase_fee, redemption_fee, purchase_limit FROM fund_purchase_status",
                conn
            )
            status_dict = status_df.set_index('fund_code').to_dict('index')

            # ── 3. 一次性批量拉取所有基金的历史记录 ──
            codes = funds_df['fund_code'].tolist()
            code_placeholders = ",".join("?" for _ in codes)
            hist_df = pd.read_sql_query(
                f"""
                SELECT fund_code, date, price, nav, static_val, static_premium,
                       volume, shares, shares_added, turnover_rate
                FROM (
                    SELECT fund_code, date, price, nav, static_val,
                           premium as static_premium, volume, shares,
                           shares_added, turnover_rate,
                           ROW_NUMBER() OVER (
                               PARTITION BY fund_code ORDER BY date DESC
                           ) AS rn
                    FROM unified_fund_history
                    WHERE fund_code IN ({code_placeholders})
                )
                WHERE rn <= 10
                ORDER BY fund_code, date DESC
                """,
                conn,
                params=codes,
            )
            # 按 fund_code 分组，每组取前 10 条
            hist_grouped = hist_df.groupby('fund_code') if not hist_df.empty else {}

            # 【V7.0 工业级升级】 批量预取所有跟踪指数的日内涨跌幅
            # [AI-2026-07-20] 根据 paused_categories 过滤：暂停的分类不抓指数
            try:
                import json
                raw = self.db.get_app_setting('paused_categories', None)
                paused_set = set(json.loads(raw)) if raw else set()
            except Exception:
                paused_set = {'QDII亚洲', '国内LOF', '现金管理'}
            if paused_set:
                filtered_funds = funds_df[~funds_df['category'].isin(paused_set)]
                indices_to_fetch = filtered_funds['related_index'].dropna().tolist()
                if indices_to_fetch:
                    logger.info(f"[INDEX-FILTER] 暂停分类 {sorted(paused_set)}，仅抓取 {len(indices_to_fetch)} 个指数")
                else:
                    indices_to_fetch = []
            else:
                indices_to_fetch = funds_df['related_index'].dropna().tolist()
            
            index_changes_map = prefetch_index_changes(indices_to_fetch, conn=conn)

            # 预查哪些基金有完整权重篮子（跳过简化指数估值，直接用计算器）
            funds_with_basket = set()
            try:
                basket_codes_df = pd.read_sql("SELECT DISTINCT fund_code FROM fund_basket_weights", conn)
                funds_with_basket = set(basket_codes_df['fund_code'].tolist())
            except:
                pass

            # [V9.1] 并发预取所有基金的实时行情（解决序列调用 get_realtime_quote ~5s 卡顿）
            quotes_dict = {}
            if self.market_data_service:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=8) as executor:
                    fut_map = {executor.submit(self.market_data_service.get_realtime_quote, c): c for c in codes}
                    for fut in as_completed(fut_map):
                        c = fut_map[fut]
                        try:
                            rt = fut.result()
                            if rt and rt.get('price'):
                                quotes_dict[c] = rt
                        except Exception:
                            pass

            result = []
            for _, fund in funds_df.iterrows():
                code = fund['fund_code']
                category = fund.get('category', '')

                # [AI-2026-07-20] 暂停分类 ❌ 直接跳过，不计算实时估值、不产生 WARNING 日志
                if category in paused_set:
                    result.append({
                        'fund_code': code,
                        'fund_name': fund.get('fund_name', ''),
                        'category': category,
                        'price': 0, 'nav': 0,
                        'static_val': 0, 'static_premium': 0,
                        'rt_val': None, 'rt_premium': None,
                        'sub_category': _FUNDS_SUB_CATEGORY.get(code, ''),
                    })
                    continue

                # ── 3a. 从批量历史数据中提取该基金的 metrics ──
                if not hist_df.empty and code in hist_grouped.groups:
                    metrics_df = hist_grouped.get_group(code).head(10)
                else:
                    metrics_df = pd.DataFrame()

                metrics = {'price': 0, 'nav': 0, 'static_val': 0, 'static_premium': 0,
                           'rt_val': None, 'rt_premium': None, 'sub_category': _FUNDS_SUB_CATEGORY.get(code, '')}

                if not metrics_df.empty:
                    valid_navs = metrics_df[metrics_df['nav'] > 0]
                    if not valid_navs.empty:
                        metrics['nav'] = valid_navs.iloc[0]['nav']
                        metrics['nav_date'] = valid_navs.iloc[0]['date']

                    valid_vals = metrics_df[metrics_df['static_val'] > 0]
                    if not valid_vals.empty and float(valid_vals.iloc[0]['static_val']) > 0:
                        val = float(valid_vals.iloc[0]['static_val'])
                        if metrics.get('nav', 0) > 0 and abs(val - metrics['nav']) / metrics['nav'] > 0.5:
                            metrics['static_val'] = metrics['nav']
                        else:
                            metrics['static_val'] = val
                    else:
                        metrics['static_val'] = metrics.get('nav', 0)

                    valid_prices = metrics_df.dropna(subset=['price'])
                    if not valid_prices.empty:
                        metrics['price'] = valid_prices.iloc[0]['price']

                    for col in ['volume', 'shares', 'shares_added', 'turnover_rate']:
                        valid_series = metrics_df.dropna(subset=[col])
                        metrics[col] = float(valid_series.iloc[0][col]) if not valid_series.empty else 0.0

                    if metrics.get('shares_added') == 0.0:
                        valid_shares = metrics_df.dropna(subset=['shares'])
                        if len(valid_shares) >= 2:
                            shares_t = float(valid_shares.iloc[0]['shares'])
                            shares_t1 = float(valid_shares.iloc[1]['shares'])
                            metrics['shares_added'] = float(shares_t - shares_t1)

                    if metrics.get('turnover_rate') == 0.0:
                        vol = metrics.get('volume', 0)  # 成交额(万元)
                        sh = metrics.get('shares', 0)  # 份额(万份)
                        price = metrics.get('price', 0)  # 现价
                        if vol > 0 and sh > 0 and price > 0:
                            metrics['turnover_rate'] = (vol / (price * sh)) * 100  # 换手率(%) = 成交额/(现价×份额) × 100

                    # [AI-2026-07-09] 修复涨跌幅：prev_close 必须是"昨收"（前一日收盘价），
                    # 不能是 iloc[0]（当日最新价，与现价相同会导致涨跌幅≈0 或错乱）。
                    # valid_prices 按日期降序（iloc[0]=当日），昨收取 iloc[1]，不足则用 iloc[0] 兜底。
                    if not valid_prices.empty:
                        if len(valid_prices) >= 2:
                            metrics['prev_close'] = valid_prices.iloc[1]['price']
                        else:
                            metrics['prev_close'] = valid_prices.iloc[0]['price']
                    else:
                        metrics['prev_close'] = 0

                # ── 4. 实时价格（从预取的 quotes_dict 取，避免逐只序列调用） ──
                if self.market_data_service and code in quotes_dict:
                    rt = quotes_dict[code]
                    metrics['price'] = rt['price']
                    if rt.get('amount'):
                        metrics['volume'] = rt['amount']  # 通达信amount已是万元，直接存储
                elif self.market_data_service:
                    try:
                        rt = self.market_data_service.get_realtime_quote(code)
                        if rt and rt.get('price'):
                            metrics['price'] = rt['price']
                            if rt.get('amount'):
                                metrics['volume'] = rt['amount']  # 通达信amount已是万元，直接存储
                    except Exception as e:
                        logger.error(f"Error getting realtime quote for {code}: {e}")

                # ── [债券ETF] 511880/511360/511520 估值 ──
                if code in BOND_ETF_CODES:
                    try:
                        bv = get_bond_etf_valuation(self.db, self.market_data_service)
                        val = bv.get_valuation(code)
                        est_nav = val.get('estimated_nav')
                        if est_nav and est_nav > 0:
                            metrics['rt_val'] = round(est_nav, 4)
                            metrics['bond_etf_method'] = val.get('method', '')
                            metrics['avg_daily_growth'] = val.get('avg_daily_growth')
                            metrics['treasury_index_pct'] = val.get('treasury_index_pct')
                            # 国债指数实时价 (511360用sh000012, 511520不用)
                            if code == '511360':
                                ti_data = bv._get_treasury_index_data()
                                if ti_data:
                                    metrics['treasury_index_price'] = ti_data.get('price')
                            # 511520: 日均票息 + T2609期货方向
                            if code == '511520':
                                metrics['daily_coupon'] = val.get('daily_coupon')
                                metrics['futures_pct'] = val.get('futures_pct')
                                metrics['futures_coefficient'] = val.get('futures_coefficient')
                            # 用预估净值作为静态估值（因为没有数据库历史记录）
                            metrics['static_val'] = round(est_nav, 4)
                            # 用最新实际净值作为昨收价（用于涨跌幅计算）
                            latest_nav = val.get('latest_nav')
                            if latest_nav and latest_nav > 0:
                                metrics['nav'] = round(latest_nav, 4)
                                metrics['prev_close'] = round(latest_nav, 4)
                            if metrics.get('price', 0) > 0:
                                metrics['rt_premium'] = round((metrics['price'] / est_nav - 1) * 100, 3)
                            if metrics.get('price', 0) > 0:
                                metrics['bond_spread'] = round(metrics['price'] - est_nav, 4)
                    except Exception as e:
                        logger.error(f"[BondETF] 估值失败 {code}: {e}")
                else:
                    # ── 5–6. 原有实时估值计算 ──
                    metrics['rt_val'] = None
                    metrics['rt_premium'] = None

                # 尝试实时计算估值 (仅非债券ETF已有，此处保留原逻辑)
                try:
                    if code == '161226':
                        import requests
                        ag_future_price, settlement_price, vwap = 0.0, 0.0, 0.0
                        
                        # [优先级1] 本程序自带的东财SSE长连接阅读器（最精准，无需程序1）
                        if _sse_reader.ag0_price > 0 and _sse_reader.ag0_settlement > 0:
                            ag_future_price = _sse_reader.ag0_price
                            settlement_price = _sse_reader.ag0_settlement
                            vwap = _sse_reader.ag0_vwap
                        
                        # [优先级2] 若SSE还没数据（刚启动），尝试从程序1(5000端口)获取
                        if ag_future_price <= 0 or settlement_price <= 0:
                            try:
                                r = requests.get("http://127.0.0.1:5000/api/futures", timeout=1.0)
                                if r.status_code == 200:
                                    f_data = r.json()
                                    ag0 = f_data.get('AG0', {})
                                    ag_future_price = float(ag0.get('price', 0))
                                    settlement_price = float(ag0.get('settlement', 0))
                                    vwap = float(ag0.get('vwap', 0))
                            except:
                                pass
                        
                        # [优先级3] 降级：新浪 nf_AG0 接口兜底
                        if ag_future_price <= 0 or settlement_price <= 0:
                            try:
                                headers = {'Referer': 'https://finance.sina.com.cn/'}
                                r = requests.get("http://hq.sinajs.cn/list=nf_AG0", headers=headers, timeout=1.5)
                                if r.status_code == 200 and '="' in r.text:
                                    parts = r.text.split('"')[1].split(',')
                                    if len(parts) >= 11:
                                        ag_future_price = float(parts[8])   # 最新价
                                        settlement_price = float(parts[10])  # 昨结算价
                                        # 新浪接口 part[9] 即为今日动态结算均价(VWAP)
                                        vwap = float(parts[9]) if len(parts) > 9 else 0.0
                            except:
                                pass
                                
                        nav_home = float(metrics.get('nav', 0))
                        if ag_future_price > 0 and settlement_price > 0 and nav_home > 0:
                            # 🚀 为了让前端展示 AG0 盘口数据
                            metrics['ag0_price'] = ag_future_price
                            metrics['ag0_settlement'] = settlement_price
                            
                            # 参考估值 (rt_val) = 昨天净值 * (实时成交价 / 昨结算价)
                            rt_val = nav_home * (ag_future_price / settlement_price)
                            metrics['rt_val'] = round(rt_val, 4)
                            if metrics['price'] > 0:
                                metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                                
                            # 🚀 官方估值 (static_val) = 昨天净值 * (VWAP / 昨结算价)
                            if vwap > 0:
                                metrics['static_val'] = round(nav_home * (vwap / settlement_price), 4)
                            else:
                                # 如果盘中没取到 vwap，就降级为 NAV (避免出现脏数据)
                                metrics['static_val'] = nav_home
                                
                            # 联动计算官方溢价
                            if metrics['static_val'] > 0 and metrics.get('price', 0) > 0:
                                metrics['static_premium'] = round((metrics['price'] / metrics['static_val'] - 1) * 100, 3)
                        
                        # [SI 实时估值] 基于 COMEX 白银期货的实时估值（和 Woody GetRealtimeNetValue 一致）
                        # [AI-2026-07-03] 传入 settlement_price(AG0昨结算) 给公式做比值基准
                        if self.market_data_service:
                            try:
                                si_result = self.market_data_service.get_si_based_valuation(
                                    nav_t1=nav_home,
                                    calibration_factor=1.0,
                                    position=float(fund.get('pos_ratio') or 0.95),
                                    ag0_prev_settle=settlement_price,
                                    ag0_realtime=ag_future_price
                                )
                                if si_result and si_result.get('nav') and si_result['nav'] > 0:
                                    metrics['si_val'] = si_result['nav']
                                    if metrics.get('price', 0) > 0:
                                        metrics['si_premium'] = round((metrics['price'] / metrics['si_val'] - 1) * 100, 3)
                                    else:
                                        metrics['si_premium'] = None
                            except Exception as e:
                                logger.debug(f"[161226] SI 实时估值失败: {e}")
                                metrics['si_val'] = None
                                metrics['si_premium'] = None


                    # 3.2 【普通国内LOF/QDII亚洲极速估值】 - 仅对无权重篮子且无trade_etf的基金使用简化指数估值
                    # [AI-2026-07-20] 有 YAML trade_etf（如161125→SPY, 161130→QQQ）的基金跳过指数估值，走3.3 ETF实时估值
                    rel_idx = fund.get('related_index', '')
                    idx_category, _ = _classify_index_symbol(rel_idx)
                    is_us_etf = (idx_category == 'skip')  # 美股ETF在_classify_index_symbol中返回'skip'
                    if not metrics.get('rt_val') and code not in funds_with_basket and not is_us_etf and not _YAML_TRADE_ETF.get(code, ''):
                        nav_home = float(metrics.get('nav', 0))
                        if rel_idx and rel_idx != '-' and nav_home > 0:
                            idx_data = index_changes_map.get(rel_idx)
                            if idx_data is not None and isinstance(idx_data, dict):
                                pct = idx_data.get('pct', 0.0)
                                metrics['index_close'] = idx_data.get('price', 0.0)
                                metrics['index_pct'] = pct
                                # [V10.15] pct!=0：用实时涨跌幅计算 rt_val
                                # pct==0：指数未变化（收盘后/非交易日/平盘）→ rt_val=最新净值
                                pos = float(fund.get('pos_ratio') or 0.95)
                                rt_val = nav_home * (1.0 + pos * (pct / 100.0))
                                metrics['rt_val'] = round(rt_val, 4)
                                if metrics.get('price', 0) > 0:
                                    metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                            else:
                                # [FIX] 无实时数据时设置为0，前端统一显示 '-'
                                # 注：index_changes_map 中找不到该指数，可能原因：
                                # 1. index_history 表没有该指数数据
                                # 2. related_index 字段值为文本描述而非代码
                                # 3. 数据源异常
                                metrics['index_pct'] = 0.0
                                metrics['index_close'] = 0.0

                    # 3.3 【美股原油/黄金等高价值一篮子基金】 - 保持原有基于 lof_config.yaml 的矩阵公式推演
                    calculator = self._get_calculator() if not metrics.get('rt_val') else None
                    if calculator:
                        # 获取基金配置(动态从数据库构建，彻底废弃 yaml)
                        # [AI-2026-07-20] trade_etf 优先从 YAML 取（SPY/QQQ），YAML 无值时降级用 related_index（.INX）
                        yaml_trade_etf = _YAML_TRADE_ETF.get(code, '')
                        resolved_trade_etf = yaml_trade_etf or fund.get('related_index', '')
                        fund_cfg = {
                            "code": code,
                            "trade_etf": resolved_trade_etf,
                            "holdings": {"equity_ratio": float(fund.get('pos_ratio') or 0.95) * 100},
                            "trade_future": "CL" if "原油" in str(fund.get('fund_name')) else ("GC" if "金" in str(fund.get('fund_name')) else ("AG0" if "白银" in str(fund.get('fund_name')) else ""))
                        }
                        try:
                            basket_df = pd.read_sql("SELECT underlying_symbol as symbol, weight FROM fund_basket_weights WHERE fund_code=? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)", conn, params=(code, code))
                            if not basket_df.empty:
                                fund_cfg["valuation_portfolio"] = basket_df.to_dict('records')
                            else:
                                # [AI-2026-07-20] valuation_portfolio 优先从 YAML 加载（数据库无此列），再降级到 hedging_portfolio
                                yaml_portfolio = _YAML_VALUATION_PORTFOLIO.get(code) or fund.get('valuation_portfolio') or fund.get('hedging_portfolio')
                                if yaml_portfolio:
                                    fund_cfg["valuation_portfolio"] = yaml_portfolio
                        except:
                            pass
                        
                        if fund_cfg:
                            # 获取最新汇率
                            current_fx = None 
                            try:
                                # [V10.1] 汇率当天不变，直接读内存
                                _ensure_daily_snapshot(conn)
                                current_fx = _daily_snapshot.get('usd_cny_mid')
                                # [V11.0] 在岸价基金：用快照里的在岸价（启动时已从新浪加载）
                                if code in _FUNDS_WITH_SPOT_RATE:
                                    spot_fx = _daily_snapshot.get('usd_cny_spot', 0)
                                    if spot_fx > 0:
                                        current_fx = spot_fx
                                        logger.debug(f"[{code}] 使用快照在岸价: {spot_fx}")
                                    else:
                                        current_fx = 0  # 在岸价不可用，禁止用中间价兜底
                                        logger.warning(f"[{code}] 快照在岸价为空，跳过估值")
                            except Exception as e:
                                logger.warning(f"[{code}] 获取快照汇率失败: {e}")
                            
                            # [AI-2026-07-06] 篮子基金ETF行情缺失标记（INDA低流动性场景专用）
                            _basket_missing_etf = False
                            if current_fx and current_fx > 0:
                                # 获取实时 ETF 价格
                                current_etfs = {}
                                if self.market_data_service:
                                    portfolio = fund_cfg.get('valuation_portfolio', [])
                                    from arbcore.utils.market_calendar import symbol_to_exchange, is_trading_day
                                    now_dt = datetime.now()
                                    for item in portfolio:
                                        raw_sym = item.get('symbol', '')
                                        sym_base = raw_sym.replace('^', '')
                                        # 去掉地区后缀，得到基础代码 USO/GLD
                                        has_suffix = False
                                        for suffix in ['-EU', '-JP', '-HK']:
                                            if sym_base.endswith(suffix):
                                                sym_base = sym_base[:-len(suffix)]
                                                has_suffix = True
                                                break
                                        # [AI-2026-07-07] 检查该组件对应的交易所今天是否开市
                                        # 有后缀的 → 查对应的区域交易所；无后缀的 → 美股(NYSE)
                                        ex = symbol_to_exchange(raw_sym)
                                        if ex and not is_trading_day(ex, now_dt.date()):
                                            logger.debug(f"[{code}] 跳过 {raw_sym}（{ex} 今日休市）")
                                            continue
                                        q = self.market_data_service.get_realtime_quote(sym_base)
                                        # [AI-2026-07-20] 实时估值必须用买一价 bid，禁止用成交价 price（见 AGENTS.md 7.3.4）
                                        if q and q.get('bid') and q['bid'] > 0:
                                            current_etfs[sym_base] = q['bid']
                                        elif q and q.get('price'):
                                            current_etfs[sym_base] = q['price']
                                    # [AI-2026-07-06] 篮子基金所有ETF组件均无实时行情时标记
                                    if portfolio and not current_etfs:
                                        _basket_missing_etf = True
                                
                                # 计算实时估值
                                res = calculator.calculate(fund_cfg, current_fx, current_etfs)
                                val_res = res.get('rt_val') if res else None
                                if val_res and val_res > 0:
                                    metrics['rt_val'] = round(val_res, 4)
                                    # 重新计算溢价率
                                    if metrics['price'] > 0:
                                        metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)

                            # 尝试用 trade_etf 兜底 [V10.8]
                            # basket为空时（如162411的XOP），直接用 trade_etf 获取实时ETF价格做 hedge 估值
                            # 放在 current_fx 条件外，让无basket基金也能走魔法公式
                            if not metrics.get('rt_val'):
                                trade_etf = fund_cfg.get('trade_etf', '')
                                if trade_etf and self.market_data_service:
                                    # [V10.9] 跳过指数类符号（HSI/HSTECH等），指数走 get_index_change_percent 路径
                                    from arbcore.config.symbol_source_map import get_symbol_source
                                    if get_symbol_source(trade_etf) == 'SINA':
                                        pass  # 指数符号不加入实时行情查询
                                    else:
                                        # [AI-2026-07-20] 实时估值用买一价 bid，无 bid 时降级用成交价 price
                                        try:
                                            q = self.market_data_service.get_realtime_quote(trade_etf)
                                            etf_price = 0
                                            if q and q.get('bid') and q['bid'] > 0:
                                                etf_price = q['bid']
                                            elif q and q.get('price') and q['price'] > 0:
                                                etf_price = q['price']
                                            # ⬇️ 估值计算：bid/price 取到后统一加载 base_data 计算，防止 bid 分支漏算
                                            if etf_price > 0:
                                                base_data = calculator.get_base_data(code)
                                                if base_data:
                                                    b_nav = float(base_data.get('nav', 0) or 0)
                                                    b_hedge = float(base_data.get('hedge', 0) or 0)
                                                    b_position = base_data.get('position', None)
                                                    if pd.isna(b_position) or b_position is None:
                                                        b_position = float(fund.get('pos_ratio') or 0.95)
                                                    # [V11.0] 在岸价基金：用快照在岸价，不降级
                                                    if code in _FUNDS_WITH_SPOT_RATE:
                                                        spot_fx = _daily_snapshot.get('usd_cny_spot', 0)
                                                        fx = spot_fx if spot_fx > 0 else 0
                                                    else:
                                                        # current_fx 可能为空，从 base_data 兜底
                                                        fx = current_fx if (current_fx and current_fx > 0) else float(base_data.get('exchange_rate', 0) or 0)
                                                    if b_nav > 0 and b_hedge > 0 and fx > 0:
                                                        # val = nav * (1 - pos) + (etf_price * fx) / hedge
                                                        val_res = b_nav * (1.0 - b_position) + (etf_price * fx) / b_hedge
                                                        if val_res > 0:
                                                            metrics['rt_val'] = round(val_res, 4)
                                                            if metrics['price'] > 0:
                                                                metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)
                                        except Exception as e:
                                            logger.warning(f"{code} trade_etf({trade_etf}) 实时行情获取失败: {e}")
                except Exception as e:
                    logger.error(f"实时计算 {code} 估值失败: {e}")

                # [V6.1] 备用兜底：如果实时计算失败（例如未连行情源，或美股休市无最新价），从采样表获取最近一次的记录
                if not metrics.get('rt_val') or metrics['rt_val'] <= 0:
                    # [AI-2026-07-06] 篮子基金ETF行情缺失时跳过stale兜底（INDA等低流动性场景）
                    if _basket_missing_etf:
                        metrics['rt_val'] = 0
                        metrics['rt_premium'] = 0
                    else:
                        try:
                            sample_query = "SELECT rt_val, premium FROM fund_intraday_quotes WHERE fund_code=? ORDER BY date DESC, time DESC LIMIT 1"
                            sample_df = pd.read_sql(sample_query, conn, params=(code,))
                            if not sample_df.empty and sample_df.iloc[0]['rt_val'] > 0:
                                metrics['rt_val'] = sample_df.iloc[0]['rt_val']
                                metrics['rt_premium'] = sample_df.iloc[0]['premium']
                            else:
                                metrics['rt_val'] = 0
                                metrics['rt_premium'] = 0
                        except Exception as e:
                            logger.error(f"从采样表获取 {code} 历史记录失败: {e}")
                            metrics['rt_val'] = 0
                            metrics['rt_premium'] = 0

                # 3. [V4.0] 灵魂逻辑重算 (确保静态溢价率和涨跌幅不为 0)
                cp = float(metrics.get('price') or 0)
                sv = float(metrics.get('static_val') or 0)
                pc = float(metrics.get('prev_close') or 0)
                
                if cp > 0 and sv > 0:
                    metrics['static_premium'] = (cp / sv - 1) * 100
                if cp > 0 and pc > 0:
                    metrics['price_change'] = (cp / pc - 1) * 100
                else:
                    metrics['price_change'] = 0
                
                # 4. [V4.0] 精度规范：现价3位、溢价率3位、涨跌幅2位
                # 先创建 fund_dict 用于存储基金数据
                fund_dict = fund.to_dict()
                fund_dict.update(metrics)
                
                # 精度处理
                for k in ['price', 'nav', 'static_val', 'rt_val']:
                    if k in fund_dict and fund_dict[k]:
                        fund_dict[k] = round(float(fund_dict[k]), 4 if k != 'price' else 3)
                # 溢价率3位小数
                for k in ['static_premium', 'rt_premium']:
                    if k in fund_dict and fund_dict[k]:
                        fund_dict[k] = round(float(fund_dict[k]), 3)
                # 涨跌幅2位小数
                if 'price_change' in fund_dict and fund_dict['price_change']:
                    fund_dict['price_change'] = round(float(fund_dict['price_change']), 2)
                
                # 状态与费率
                pure_code = code.split('.')[0] if '.' in code else code
                st = status_dict.get(pure_code) or status_dict.get(code) or {}
                fund_dict['purchase_status'] = st.get('purchase_status', '未知')
                fund_dict['redemption_status'] = st.get('redemption_status', '未知')
                fund_dict['purchase_fee'] = st.get('purchase_fee', '-')
                fund_dict['redemption_fee'] = st.get('redemption_fee', '-')
                fund_dict['purchase_limit'] = st.get('purchase_limit', None)
                
                # 指数信息
                fund_dict['idx_code'] = fund.get('idx_code', '-')
                fund_dict['idx_name'] = fund.get('idx_name', '-')

                # 💡 强力防 NaN 注入：将所有 pd.isna 的值转换为 None，防止 json 序列化抛出 ValueError
                for k, v in list(fund_dict.items()):
                    if pd.isna(v):
                        fund_dict[k] = None

                result.append(fund_dict)
            logger.info(f"Dashboard数据生成完成，共 {len(result)} 只基金")
            _dashboard_cache.set(cache_key, result)
            return result
        except Exception as e:
            import traceback
            logger.error(f"get_unified_dashboard_data 失败: {e}")
            logger.error(traceback.format_exc())
            _dashboard_cache.set(cache_key, [])
            return []
        finally:
            conn.close()

    def get_fund_history(self, fund_code: str) -> List[Dict[str, Any]]:
        """
        历史对账数据（验算用）。
        - 不使用 bfill 填充净值（防止今天/昨天出现虚假的旧净值）
        - 不过滤当天行（exchange_rate LEFT JOIN 可能带回当天汇率，用于显示）
        - 不将 None 填充为 0（让前端正确显示 '-'）
        """
        conn = self.db._get_conn()
        try:
            today = datetime.now().strftime('%Y-%m-%d')

            # 1. 基础历史数据 (包含静态估值、汇率、并从 fund_daily_factors 回填缺失的净值 + hedge)
            query_hist = """
            SELECT h.date, h.price, 
                   COALESCE(h.nav, f.nav) as nav,
                   h.static_val, h.premium as static_premium, h.calibration,
                   h.index_close, h.index_pct, h.shares, h.shares_added, h.turnover_rate, h.volume,
                   h.valuation_error,
                    r.usd_cny_mid, r.hkd_cny_mid, r.jpy_cny_mid,
                    f.hedge
            FROM unified_fund_history h
            LEFT JOIN exchange_rate r ON h.date = r.date
            LEFT JOIN fund_daily_factors f ON h.date = f.date AND h.fund_code = f.fund_code
            WHERE h.fund_code = ? ORDER BY h.date DESC LIMIT 60
            """
            df = pd.read_sql(query_hist, conn, params=(fund_code,))
            if df.empty: return []

            # 判断基金类型：港币/日元基金，在返回的 usd_cny_mid 字段里替换对应汇率
            is_hkd_fund = False
            is_jp_fund = False
            try:
                fund_info_df = pd.read_sql("SELECT category, idx_name FROM unified_fund_list WHERE fund_code=? LIMIT 1", conn, params=(fund_code,))
                if not fund_info_df.empty:
                    cat = str(fund_info_df.iloc[0]['category'] or '')
                    idx_name = str(fund_info_df.iloc[0]['idx_name'] or '')
                    if '亚洲' in cat or '恒生' in idx_name or '香港' in idx_name or 'H股' in idx_name or '港币' in idx_name:
                        is_hkd_fund = True
                    if '日本' in cat:
                        is_jp_fund = True
            except:
                pass

            if is_hkd_fund and 'hkd_cny_mid' in df.columns:
                df['usd_cny_mid'] = df['hkd_cny_mid']
            if is_jp_fund and 'jpy_cny_mid' in df.columns:
                df['usd_cny_mid'] = df['jpy_cny_mid']

            # 计算估值误差（绝对差值）: val_error_pct = static_val - nav（非百分比）
            # [AI-2026-07-04] 改为绝对差值，不再用百分比
            if 'valuation_error' in df.columns:
                df['val_error_pct'] = df['valuation_error']
            mask = df['val_error_pct'].isna() if 'val_error_pct' in df.columns else pd.Series([True] * len(df))
            valid_mask = mask & (df['static_val'] > 0) & (df['nav'] > 0)
            if valid_mask.any():
                if 'val_error_pct' not in df.columns:
                    df['val_error_pct'] = 0.0
                df.loc[valid_mask, 'val_error_pct'] = df.loc[valid_mask, 'static_val'] - df.loc[valid_mask, 'nav']

            # 找最新有效净值（用于展示，不填充到行数据里）
            valid_nav_rows = df[df['nav'] > 0]
            if not valid_nav_rows.empty:
                latest_nav = valid_nav_rows.iloc[0]['nav']
                latest_nav_date = valid_nav_rows.iloc[0]['date']
            else:
                latest_nav, latest_nav_date = 0, '-'

            # 计算各项变动百分比
            # 注意: shift(-1) 获取前一交易日（因为倒序）。对 None/0 要特别处理防止除零
            def safe_pct_change(series):
                shifted = series.shift(-1)
                result = pd.Series([None] * len(series), index=series.index)
                valid = (shifted.notna()) & (shifted != 0) & (series.notna())
                result[valid] = (series[valid] / shifted[valid] - 1) * 100
                return result

            if 'usd_cny_mid' in df.columns:
                # 汇率不 bfill：中国假期（如端午）不公布中间价，应显示 '-'
                df['usd_cny_mid_chg'] = safe_pct_change(df['usd_cny_mid'])
            df['price_chg'] = safe_pct_change(df['price'])
            df['nav_chg'] = safe_pct_change(df['nav'])
            df['static_val_chg'] = safe_pct_change(df['static_val'])

            # 回填 shares_added：若数据库里为 NULL/0，用相邻两天 shares 差值计算
            # df 按 date DESC 排列，shift(-1) 取前一交易日（更早的那天）
            if 'shares' in df.columns:
                mask_sa = df['shares_added'].isna() | (df['shares_added'] == 0)
                if mask_sa.any():
                    prev_shares = df['shares'].shift(-1)
                    calc = df['shares'] - prev_shares
                    df.loc[mask_sa, 'shares_added'] = calc[mask_sa]

            # 清理 NaN/Inf（不填充 0，保留 None 让前端显示 '-'）
            import numpy as np
            df = df.replace([np.inf, -np.inf], np.nan)

            # 过滤：非交易日行（仅有份额数据无实际行情）排除
            # 条件：price/nav/static_val 全为 None → 删除（shares 单独存在无意义）
            df = df.dropna(subset=['price', 'nav', 'static_val'], how='all')

            # [债券ETF] 为现金管理基金回溯计算静态估值
            if fund_code in BOND_ETF_CODES and not df.empty:
                try:
                    bv = get_bond_etf_valuation(conn, None)
                    fund_meta = BOND_ETF_META.get(fund_code, {})
                    
                    if fund_code == '511360':
                        # ══ 511360: 国债指数跟踪法回溯 ══
                        treasury_hist = bv.get_treasury_history(days=60)
                        # 建立日期→涨跌幅映射 (当天close vs 前一天close)
                        pct_map = {}
                        for j in range(len(treasury_hist) - 1):
                            today_close = treasury_hist[j]['close']
                            yesterday_close = treasury_hist[j + 1]['close']
                            if yesterday_close > 0:
                                pct = (today_close / yesterday_close - 1) * 100
                                pct_map[treasury_hist[j]['date']] = pct
                        
                        # 511360 周一计提周末两天利息，需要日均增长做基数
                        avg_growth_511360 = bv.calc_avg_daily_growth(fund_code, days=20)
                        # 连续公式参数: 底仓票息 + 国债指数敏感度
                        daily_coupon_511360 = BOND_ETF_META.get('511360', {}).get('daily_coupon', 0.003)
                        idx_coeff_511360 = BOND_ETF_META.get('511360', {}).get('idx_coefficient', 0.07)

                        from datetime import datetime as _dt
                        df_sorted = df.sort_values('date', ascending=True).reset_index(drop=True)
                        for i in range(len(df_sorted)):
                            if i == 0:
                                df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = df_sorted.iloc[i]['nav']
                            else:
                                prev_nav = df_sorted.iloc[i - 1]['nav']
                                # 跳过前一日净值缺失的行
                                if prev_nav is None or pd.isna(prev_nav) or prev_nav <= 0:
                                    df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = None
                                    continue
                                
                                row_date = str(df_sorted.iloc[i]['date'])[:10]
                                idx_pct = pct_map.get(row_date)
                                
                                # 周一：加上周末两天利息 (511360在周一计提)
                                weekend_bonus = 0.0
                                try:
                                    row_dt = _dt.strptime(row_date, '%Y-%m-%d')
                                    if row_dt.weekday() == 0 and avg_growth_511360 is not None:
                                        weekend_bonus = avg_growth_511360 * 2
                                except:
                                    pass

                                # 连续公式: prev_nav + 底仓票息 + 指数敏感度 × 涨跌幅 + 周末利息
                                if idx_pct is not None:
                                    idx_adj = idx_pct * idx_coeff_511360
                                    estimated_nav = prev_nav + daily_coupon_511360 + idx_adj + weekend_bonus
                                else:
                                    estimated_nav = prev_nav + daily_coupon_511360 + weekend_bonus
                                
                                df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = round(estimated_nav, 4)
                        
                        df = df_sorted.sort_values('date', ascending=False).reset_index(drop=True)
                        logger.info(f"[BondETF] 511360 国债指数跟踪法回溯完成")
                    else:
                        # ══ 511880/其他: 日均增长法回溯 ══
                        avg_growth = bv.calc_avg_daily_growth(fund_code, days=20)
                        weekend_on = fund_meta.get('weekend_on')
                        
                        if avg_growth is not None:
                            from datetime import datetime as _dt
                            df_sorted = df.sort_values('date', ascending=True).reset_index(drop=True)
                            estimated_nav = df_sorted.iloc[0]['nav'] if len(df_sorted) > 0 else latest_nav
                            
                            for i in range(len(df_sorted)):
                                if i == 0:
                                    df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = df_sorted.iloc[i]['nav']
                                else:
                                    prev_nav_gen = df_sorted.iloc[i-1]['nav']
                                    # 跳过前一日净值缺失的行
                                    if prev_nav_gen is None or pd.isna(prev_nav_gen) or prev_nav_gen <= 0:
                                        df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = None
                                        continue
                                    
                                    try:
                                        row_dt = _dt.strptime(str(df_sorted.iloc[i]['date'])[:10], '%Y-%m-%d')
                                    except (ValueError, TypeError):
                                        row_dt = None
                                    
                                    daily_gain = avg_growth
                                    if row_dt:
                                        if weekend_on == 'friday' and row_dt.weekday() == 4:
                                            daily_gain = avg_growth * 3
                                        elif weekend_on == 'monday' and row_dt.weekday() == 0:
                                            daily_gain = avg_growth * 3
                                    
                                    estimated_nav = prev_nav_gen + daily_gain
                                    df_sorted.iloc[i, df_sorted.columns.get_loc('static_val')] = round(estimated_nav, 4)
                            
                            df = df_sorted.sort_values('date', ascending=False).reset_index(drop=True)
                            logger.info(f"[BondETF] 静态估值回溯完成 {fund_code}, 日均增长={avg_growth}")
                except Exception as e:
                    logger.warning(f"[BondETF] 静态估值回溯失败 {fund_code}: {e}")

            # 2. 构建返回数据
            import math
            
            # [511360] 获取国债指数历史数据，附加到每行
            treasury_map = {}
            if fund_code == '511360':
                try:
                    bv2 = get_bond_etf_valuation(conn, None)
                    treasury_hist = bv2.get_treasury_history(days=60)
                    for j in range(len(treasury_hist) - 1):
                        today_close = treasury_hist[j]['close']
                        yesterday_close = treasury_hist[j + 1]['close']
                        pct = (today_close / yesterday_close - 1) * 100 if yesterday_close > 0 else 0
                        treasury_map[treasury_hist[j]['date']] = {
                            'idx_close': today_close,
                            'idx_pct': round(pct, 4),
                        }
                except Exception as e:
                    logger.warning(f"[BondETF] 获取000012历史数据失败: {e}")
            
            # [511520] 获取国债期货历史数据，附加到每行
            futures_map = {}
            if fund_code == '511520':
                try:
                    cursor = conn.cursor()
                    # 拉 T2609 和 TF2609，取均值
                    t_rows = cursor.execute(
                        "SELECT date, close_price, close_pct FROM futures_daily WHERE symbol='T2609' AND date>='2026-01-01' ORDER BY date DESC"
                    ).fetchall()
                    tf_rows = cursor.execute(
                        "SELECT date, close_price, close_pct FROM futures_daily WHERE symbol='TF2609' AND date>='2026-01-01' ORDER BY date DESC"
                    ).fetchall()
                    t_map = {r[0]: (r[1], r[2]) for r in t_rows}
                    tf_map = {r[0]: (r[1], r[2]) for r in tf_rows}
                    all_dates = sorted(set(list(t_map.keys()) + list(tf_map.keys())), reverse=True)
                    for d in all_dates:
                        t_close, t_pct = t_map.get(d, (None, None))
                        tf_close, tf_pct = tf_map.get(d, (None, None))
                        # 取均值
                        if t_close and tf_close:
                            avg_close = round((t_close + tf_close) / 2, 3)
                        elif t_close:
                            avg_close = t_close
                        elif tf_close:
                            avg_close = tf_close
                        else:
                            continue
                        # 涨幅取均值
                        if t_pct is not None and tf_pct is not None:
                            avg_pct = round((t_pct + tf_pct) / 2, 4)
                        elif t_pct is not None:
                            avg_pct = t_pct
                        elif tf_pct is not None:
                            avg_pct = tf_pct
                        else:
                            avg_pct = None
                        futures_map[d] = {
                            'futures_close': avg_close,
                            'futures_pct': avg_pct,
                        }
                except Exception as e:
                    logger.warning(f"[BondETF] 获取国债期货历史数据失败: {e}")

            # [通用] 获取该基金跟踪的ETF历史价格（如162411→XOP，160719→GLD+^GLD-EU，501225→SOXX）
            etf_price_map = {}  # {symbol: {date: {price, chg}}}
            try:
                # 1) 从 related_index 获取主 ETF
                fl_row = conn.execute("SELECT related_index FROM unified_fund_list WHERE fund_code=?", (fund_code,)).fetchone()
                trade_etf = fl_row[0] if fl_row and fl_row[0] and fl_row[0] != '-' else ''
                etf_symbols = [trade_etf] if trade_etf else []

                # 2) 从 basket 获取所有 ETF 符号（含锚点变体如 ^GLD-EU）
                basket_rows = conn.execute(
                    "SELECT DISTINCT underlying_symbol FROM fund_basket_weights WHERE fund_code=? AND date=(SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)",
                    (fund_code, fund_code)
                ).fetchall()
                for br in basket_rows:
                    sym = br[0]
                    if sym and sym not in etf_symbols:
                        etf_symbols.append(sym)

                # 3) 逐个查询净值（仅 netvalue，禁止兜底 price）
                for sym in etf_symbols:
                    etf_rows = conn.execute(
                        "SELECT date, netvalue FROM usa_etf_daily_prices WHERE symbol=? AND netvalue IS NOT NULL AND netvalue > 0 ORDER BY date DESC",
                        (sym,)
                    ).fetchall()
                    if etf_rows:
                        prices = {r[0]: r[1] for r in etf_rows if r[1] is not None}
                        dates_sorted = sorted(prices.keys(), reverse=True)
                        etf_chg = {}
                        for i in range(len(dates_sorted) - 1):
                            d_curr, d_prev = dates_sorted[i], dates_sorted[i + 1]
                            if prices[d_prev] and prices[d_prev] > 0 and prices[d_curr] and prices[d_curr] > 0:
                                etf_chg[d_curr] = (prices[d_curr] / prices[d_prev] - 1) * 100
                        etf_price_map[sym] = {
                            d: {'price': prices[d], 'chg': etf_chg.get(d)} for d in prices
                        }
            except Exception as e:
                logger.warning(f"[FundHistory] 获取ETF历史价格失败 {fund_code}: {e}")

            # [AI] 从 index_history 获取真正的指数数据，覆盖可能被错误写入 SPY 的 index_close
            real_index_map = {}
            if trade_etf:
                try:
                    idx_rows = conn.execute("SELECT date, close FROM index_history WHERE symbol=? ORDER BY date DESC", (trade_etf,)).fetchall()
                    if idx_rows:
                        idx_prices = {r[0]: r[1] for r in idx_rows}
                        idx_dates = sorted(idx_prices.keys(), reverse=True)
                        for i in range(len(idx_dates) - 1):
                            d_curr, d_prev = idx_dates[i], idx_dates[i + 1]
                            if idx_prices[d_prev] and idx_prices[d_prev] > 0:
                                chg = (idx_prices[d_curr] / idx_prices[d_prev] - 1) * 100
                                real_index_map[d_curr] = {'close': idx_prices[d_curr], 'pct': round(chg, 4)}
                        if len(idx_dates) > 0:
                            real_index_map[idx_dates[-1]] = {'close': idx_prices[idx_dates[-1]], 'pct': None}
                except:
                    pass

            # [AI-2026-07-20] 从 usa_etf_daily_prices.netvalue 获取ETF真实NAV（XOP/GLD等）
            # real_index_map 为空说明 index_history 无该 ETF 数据，从 usa_etf_daily_prices 补充
            usa_netvalue_map = {}
            yaml_trade_etf = _YAML_TRADE_ETF.get(fund_code, '')
            if yaml_trade_etf and not real_index_map:
                try:
                    nv_rows = conn.execute(
                        "SELECT date, netvalue FROM usa_etf_daily_prices WHERE symbol=? AND netvalue IS NOT NULL AND netvalue > 0 ORDER BY date DESC",
                        (yaml_trade_etf,)
                    ).fetchall()
                    if nv_rows:
                        nv_dict = {r[0]: r[1] for r in nv_rows}
                        nv_dates = sorted(nv_dict.keys(), reverse=True)
                        for i in range(len(nv_dates) - 1):
                            d_curr, d_prev = nv_dates[i], nv_dates[i + 1]
                            if nv_dict[d_prev] and nv_dict[d_prev] > 0:
                                chg = (nv_dict[d_curr] / nv_dict[d_prev] - 1) * 100
                                usa_netvalue_map[d_curr] = {'close': nv_dict[d_curr], 'pct': round(chg, 4)}
                        if len(nv_dates) > 0:
                            usa_netvalue_map[nv_dates[-1]] = {'close': nv_dict[nv_dates[-1]], 'pct': None}
                except Exception as e:
                    logger.warning(f"[FundHistory] usa_netvalue_map 构建失败 {yaml_trade_etf}: {e}")

            data_list = []
            for _, row in df.iterrows():
                item = {}
                for k in df.columns:
                    v = row[k]
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        continue  # 跳过 NaN/Inf，前端自然显示 '-'
                    if v is not None:
                        item[k] = v

                item['nav_date'] = latest_nav_date
                item['latest_nav'] = latest_nav

                # [AI-2026-06-28] 静态溢价已由入库时用 T-1 净值算好，直接使用 h.premium
                # 不再覆盖计算，避免 AI 瞎改

                # [511360] 附加国债指数数据
                if fund_code == '511360':
                    row_date = str(item.get('date', ''))[:10]
                    idx_data = treasury_map.get(row_date)
                    if idx_data:
                        item['idx_close'] = idx_data['idx_close']
                        item['idx_pct'] = idx_data['idx_pct']

                # [AI] 覆盖真实指数数据
                if real_index_map and trade_etf:
                    row_date = str(item.get('date', ''))[:10]
                    if row_date in real_index_map:
                        item['index_close'] = real_index_map[row_date]['close']
                        item['index_pct'] = real_index_map[row_date]['pct']
                    else:
                        item['index_close'] = None
                        item['index_pct'] = None

                # [AI-2026-07-20] 从 usa_etf_daily_prices.netvalue 补充ETF真实NAV
                if item.get('index_close') is None and usa_netvalue_map:
                    row_date = str(item.get('date', ''))[:10]
                    if row_date in usa_netvalue_map:
                        item['index_close'] = usa_netvalue_map[row_date]['close']
                        item['index_pct'] = usa_netvalue_map[row_date]['pct']

                # [511520] 附加国债期货数据 + 回测预估净值
                if fund_code == '511520':
                    row_date = str(item.get('date', ''))[:10]
                    fut_data = futures_map.get(row_date)
                    if fut_data:
                        item['futures_close'] = fut_data['futures_close']
                        item['futures_pct'] = fut_data['futures_pct']

                    # 回测: 用前一日NAV + 日均票息 + T2609方向修正 → 预估今日NAV
                    daily_coupon = BOND_ETF_META.get('511520', {}).get('daily_coupon', 0.0082)
                    t_pct = fut_data.get('futures_pct') if fut_data else None
                    if len(data_list) > 0 and t_pct is not None:
                        prev_item = data_list[-1]
                        prev_nav = prev_item.get('nav')
                        if prev_nav and prev_nav > 0:
                            estimated_nav = prev_nav + daily_coupon + prev_nav * t_pct / 100 * 1.0
                            item['estimated_nav'] = round(estimated_nav, 4)
                            item['estimation_error'] = round(estimated_nav - item.get('nav', 0), 4) if item.get('nav') else None
                            item['estimation_error_pct'] = round(abs(estimated_nav - item.get('nav', 0)) / item.get('nav', 1) * 100, 4) if item.get('nav') and item.get('nav', 0) > 0 else None

                # [通用] 附加ETF历史价格（如XOP价格、XOP价格涨跌幅）
                if etf_price_map:
                    row_date = str(item.get('date', ''))[:10]
                    for etf_sym, sym_data in etf_price_map.items():
                        ed = sym_data.get(row_date)
                        if ed:
                            item[f'{etf_sym}_price'] = ed['price']
                            item[f'{etf_sym}_price_chg'] = ed.get('chg')

                data_list.append(item)

            return data_list
        finally:
            conn.close()

    def get_market_overview(self, market_data_service=None) -> Dict[str, Any]:
        conn = self.db._get_conn()
        res = {"rates": {}, "usd_change": 0, "hkd_change": 0, "active_sources": [], "stats": {"fund_count": 0}}
        
        # [V4.6] 修复行情状态未显示的 Bug
        if market_data_service:
            res["active_sources"] = market_data_service.get_active_source_names()
            
        try:
            rates_df = pd.read_sql_query("SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 2", conn)
            if not rates_df.empty:
                row_dict = rates_df.iloc[0].to_dict()
                # [AI-2026-07-07] 将 NaN 转为 None，避免 JSON 序列化崩溃（SQL NULL → pandas NaN → JSON 非法）
                res["rates"] = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}
                # 计算涨跌幅（百分比）
                if len(rates_df) >= 2:
                    current = rates_df.iloc[0]
                    previous = rates_df.iloc[1]
                    # USD/CNY 涨跌幅
                    if 'usd_cny_mid' in current and pd.notna(current.get('usd_cny_mid')) and pd.notna(previous.get('usd_cny_mid')):
                        prev_val = previous['usd_cny_mid']
                        curr_val = current['usd_cny_mid']
                        if prev_val != 0:
                            res["usd_change"] = ((curr_val - prev_val) / prev_val) * 100
                    # HKD/CNY 涨跌幅
                    if 'hkd_cny_mid' in current and pd.notna(current.get('hkd_cny_mid')) and pd.notna(previous.get('hkd_cny_mid')):
                        prev_val = previous['hkd_cny_mid']
                        curr_val = current['hkd_cny_mid']
                        if prev_val != 0:
                            res["hkd_change"] = ((curr_val - prev_val) / prev_val) * 100
                    # JPY/CNY 涨跌幅
                    if 'jpy_cny_mid' in current and pd.notna(current.get('jpy_cny_mid')) and pd.notna(previous.get('jpy_cny_mid')):
                        prev_val = previous['jpy_cny_mid']
                        curr_val = current['jpy_cny_mid']
                        if prev_val != 0:
                            res["jpy_change"] = ((curr_val - prev_val) / prev_val) * 100
            count_df = pd.read_sql_query("SELECT count(*) as count FROM unified_fund_list", conn)
            res["stats"]["fund_count"] = int(count_df.iloc[0]['count']) if not count_df.empty else 0
        except: pass
        finally: conn.close()
        return res

    def get_fund_intraday(self, fund_code: str, date: str = None) -> List[Dict[str, Any]]:
        if not date: date = pd.Timestamp.now().strftime('%Y-%m-%d')
        conn = self.db._get_conn()
        try:
            query = "SELECT time, price, rt_val, premium FROM fund_intraday_quotes WHERE fund_code = ? AND date = ? ORDER BY time ASC"
            return pd.read_sql(query, conn, params=(fund_code, date)).to_dict(orient='records')
        finally: conn.close()

    def get_fund_basket(self, fund_code: str) -> List[Dict[str, Any]]:
        conn = self.db._get_conn()
        try:
            query = "SELECT underlying_symbol, weight, date FROM fund_basket_weights WHERE fund_code = ? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code = ?)"
            return pd.read_sql_query(query, conn, params=(fund_code, fund_code)).to_dict(orient='records')
        finally: conn.close()
    
    def get_valuation_meta(self, code: str) -> dict:
        """
        估值元数据（深度分析页用）
        从 main.py 路由内联逻辑迁移至 Service 层
        """
        # [AI-2026-07-16] 5秒缓存，避免首次冷启动超时
        cached = _valuation_meta_cache.get(code)
        if cached is not None:
            return cached
        import traceback
        conn = self.db._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT fund_name, related_index, pos_ratio FROM unified_fund_list WHERE fund_code=?",
                (code,)
            )
            f_row = cursor.fetchone()
            if not f_row:
                return {"status": "error", "message": f"Fund {code} not found in database"}

            # [AI-2026-07-20] trade_future 优先从 YAML 读取（NK/MNQ/MES/MGC 等），
            # 名字推断仅作兜底（原油→CL / 金→GC / 白银→AG0）。
            # 修复：QDII日本/纳指等原硬编码推断全落到空串，导致纯期货/期货校准功能失效。
            trade_future = _YAML_TRADE_FUTURE.get(code, '')
            if not trade_future:
                if "原油" in str(f_row[0]) or "USO" in str(f_row[1]):
                    trade_future = "CL"
                elif "金" in str(f_row[0]) or "GLD" in str(f_row[1]):
                    trade_future = "GC"
                elif "白银" in str(f_row[0]):
                    trade_future = "AG0"

            # [AI-2026-07-20] trade_etf 优先从 YAML 取（SPY/QQQ），避免用 related_index（.INX/.NDX）
            fund_cfg = {
                "code": code,
                "trade_etf": _YAML_TRADE_ETF.get(code) or f_row[1] or '',
                "position": float(f_row[2] or 0.95) * 100,
                "trade_future": trade_future
            }

            basket_df = pd.read_sql(
                "SELECT underlying_symbol as symbol, weight FROM fund_basket_weights "
                "WHERE fund_code=? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)",
                conn, params=(code, code)
            )
            if not basket_df.empty:
                fund_cfg["valuation_portfolio"] = basket_df.to_dict('records')
            else:
                # [AI-2026-07-20] valuation_portfolio 优先从模块级 YAML dict 加载，再尝试 config_service
                try:
                    yaml_portfolio = _YAML_VALUATION_PORTFOLIO.get(code) or (self.config_service.get_fund_config(code).get('valuation_portfolio', None) if self.config_service else None)
                    if yaml_portfolio:
                        fund_cfg["valuation_portfolio"] = yaml_portfolio
                except Exception:
                    pass

            # 获取底层的 calculator 基准数据
            calculator = self._get_calculator()
            base_data = calculator.get_base_data(code) if calculator else None

            # 动态推演 Hedge 值（如果数据库里为空）
            if base_data and (not base_data.get('hedge') or float(base_data.get('hedge', 0)) <= 0):
                try:
                    trade_etf = fund_cfg.get('trade_etf', '')
                    if trade_etf:
                        base_etf_price = base_data.get(trade_etf) or base_data.get(f"^{trade_etf}")
                        base_nav = base_data.get('nav')
                        base_pos = base_data.get('position')
                        if base_pos is None or float(base_pos) <= 0:
                            base_pos = float(fund_cfg.get('position', 95.0)) / 100.0
                        base_fx = base_data.get('exchange_rate')
                        if base_etf_price and base_nav and base_pos and base_fx:
                            calc_hedge = (float(base_etf_price) * float(base_fx)) / (float(base_nav) * float(base_pos))
                            base_data['hedge'] = calc_hedge
                except Exception as e:
                    logger.error(f"Failed to calculate missing hedge: {e}")

            # 获取最新汇率
            fx_df = pd.read_sql(
                "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn
            )
            latest_fx = float(fx_df.iloc[0]['usd_cny_mid']) if not fx_df.empty else 7.0

            # 获取最新实时行情 (用于标的 ETF 价格和期货价格)
            portfolio = fund_cfg.get('valuation_portfolio', [])
            etf_symbols = []
            for item in portfolio:
                sym = item.get('symbol', '').replace('^', '')
                for suffix in ['-EU', '-JP', '-HK']:
                    if sym.endswith(suffix):
                        sym = sym[:-len(suffix)]
                        break
                etf_symbols.append(sym)

            # [V10.8] basket为空时用 trade_etf 兜底获取行情（如162411→XOP）
            if not etf_symbols:
                trade_etf = fund_cfg.get('trade_etf', '')
                if trade_etf:
                    # [V10.9] 跳过指数类符号（HSI/HSTECH/399300等），指数无可用的实时行情
                    from arbcore.config.symbol_source_map import get_symbol_source
                    if get_symbol_source(trade_etf) == 'SINA':
                        pass  # 指数符号不加入实时行情查询
                    else:
                        etf_symbols.append(trade_etf)
            # [V10.9] 加入基金自身行情（供 Lazy 保守/内卷模式使用 lof_bid/lof_ask）
            if code not in etf_symbols:
                etf_symbols.append(code)

            # [AI-2026-07-16] 并行获取行情，避免顺序等待导致超时
            realtime_quotes = {}
            def _fetch_quote(sym):
                try:
                    q = self.market_data_service.get_realtime_quote(sym) if self.market_data_service else None
                    if q:
                        return sym, {
                            'price': q.get('price'),
                            'bid': q.get('bid'),
                            'ask': q.get('ask'),
                            'bid_size': q.get('bid_size', 0),
                            'ask_size': q.get('ask_size', 0),
                            'source': q.get('source', '')
                        }
                    return sym, None
                except Exception as e:
                    logger.error(f"Error getting quote for {sym}: {e}")
                    return sym, None
            with ThreadPoolExecutor(max_workers=min(len(etf_symbols) or 1, 5)) as pool:
                for sym, result in pool.map(_fetch_quote, etf_symbols):
                    realtime_quotes[sym] = result

            future_symbol = fund_cfg.get('trade_future', '')
            future_quote = None
            if future_symbol:
                # [AI-2026-07-02] AG0 沪银期货：优先从东财 SSE + 新浪获取实时数据
                if future_symbol == 'AG0':
                    future_quote = _get_ag0_future_quote()
                else:
                    try:
                        q = self.market_data_service.get_realtime_quote(future_symbol) if self.market_data_service else None
                        if q:
                            future_quote = {
                                'price': q.get('price'),
                                'bid': q.get('bid'),  # None = 等待数据/非夜盘
                                'ask': q.get('ask'),
                                'source': q.get('source', '')
                            }
                        else:
                            future_quote = None
                    except Exception as e:
                        logger.error(f"Error getting future quote for {future_symbol}: {e}")
                        future_quote = None

            # 获取 T-1 基准估值日数据
            t1_data = {}
            try:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT h.date, COALESCE(h.nav, f.nav) as nav, h.static_val,
                           r.usd_cny_mid, h.calibration, h.price
                    FROM unified_fund_history h
                    LEFT JOIN exchange_rate r ON h.date = r.date
                    LEFT JOIN fund_daily_factors f ON h.date = f.date AND h.fund_code = f.fund_code
                    WHERE h.fund_code = ?
                    ORDER BY h.date DESC LIMIT 1
                """, (code,))
                row = cursor.fetchone()
                if row:
                    t1_data = {
                        "date": row[0],
                        "nav": float(row[1]) if row[1] is not None else 0.0,
                        "static_val": float(row[2]) if row[2] is not None else 0.0,
                        "exchange_rate": float(row[3]) if row[3] is not None else 0.0,
                        "calibration": float(row[4]) if row[4] is not None else 0.0,
                        "price": float(row[5]) if row[5] is not None else 0.0
                    }

                    # 如果没有独立校准值，查找全局期货校准值兜底
                    if t1_data["calibration"] == 0.0 and future_symbol:
                        base_fsym = future_symbol
                        if 'MGC' in future_symbol or 'GC' in future_symbol:
                            base_fsym = 'GC'
                        elif 'MCL' in future_symbol or 'CL' in future_symbol:
                            base_fsym = 'CL'
                        elif 'MNQ' in future_symbol or 'NQ' in future_symbol:
                            base_fsym = 'NQ'
                        elif 'MES' in future_symbol or 'ES' in future_symbol:
                            base_fsym = 'ES'

                        cursor.execute("""
                            SELECT calibration FROM futures_daily
                            WHERE symbol = ? AND calibration IS NOT NULL
                            ORDER BY date DESC LIMIT 1
                        """, (base_fsym,))
                        crow = cursor.fetchone()
                        if crow:
                            t1_data["calibration"] = float(crow[0])
                            if base_data:
                                base_data['calibration'] = float(crow[0])

                    # 获取该 T-1 日期对应的 ETF 收盘价
                    etf_prices = []
                    for item in portfolio:
                        symbol = item.get('symbol', '')
                        if not symbol:
                            continue
                        alt_symbol = symbol if symbol.startswith('^') else f"^{symbol}"
                        cursor.execute("""
                            SELECT COALESCE(NULLIF(netvalue, 0), price) as price
                            FROM usa_etf_daily_prices
                            WHERE symbol IN (?, ?) AND date = ?
                        """, (symbol, alt_symbol, row[0]))
                        p_row = cursor.fetchone()
                        p_val = float(p_row[0]) if p_row and p_row[0] is not None else 0.0
                        # [AI-2026-07-16] 精确日期未取到，往前找最近一日
                        if p_val <= 0:
                            cursor.execute("""
                                SELECT COALESCE(NULLIF(netvalue, 0), price) as price
                                FROM usa_etf_daily_prices
                                WHERE symbol IN (?, ?) AND date <= ? AND price > 0
                                ORDER BY date DESC LIMIT 1
                            """, (symbol, alt_symbol, row[0]))
                            fb_row = cursor.fetchone()
                            if fb_row:
                                p_val = float(fb_row[0])

                        display_symbol = symbol
                        for suffix in ['-EU', '-JP', '-HK']:
                            if display_symbol.endswith(suffix) and not display_symbol.startswith('^'):
                                display_symbol = f"^{display_symbol}"
                                break

                        base_price = 0
                        if base_data:
                            base_price = float(base_data.get(display_symbol, base_data.get(symbol, 0)))

                        pct_change = 0
                        if base_price > 0:
                            pct_change = (p_val / base_price - 1) * 100

                        etf_prices.append({
                            "symbol": display_symbol,
                            "price": p_val,
                            "pct_change": pct_change
                        })
                    t1_data["etfs_info"] = etf_prices

                    # 如果 T-1 的静态估值为 0，则利用 T-2 的基准数据和 T-1 的 ETF 收盘价进行动态推演
                    if t1_data["static_val"] <= 0 and base_data and calculator:
                        try:
                            t1_etfs = {info["symbol"].lstrip('^'): info["price"] for info in etf_prices}
                            for info in etf_prices:
                                t1_etfs[info["symbol"]] = info["price"]

                            t1_fx = t1_data["exchange_rate"] if t1_data["exchange_rate"] > 0 else base_data.get("exchange_rate", 7.0)

                            calc_res = calculator.calculate(fund_cfg, t1_fx, t1_etfs)
                            if calc_res and calc_res.get('rt_val'):
                                t1_data["static_val"] = float(calc_res['rt_val'])
                        except Exception as e:
                            logger.error(f"Failed to dynamically calculate T-1 static_val: {e}")
            except Exception as e:
                logger.warning(f"获取 T-1 估值日数据失败: {e}")

            # 格式化 base_data 以免 JSON 序列化失败
            formatted_base_data = {}
            if base_data:
                import numpy as np
                for k, v in base_data.items():
                    if pd.isna(v):
                        formatted_base_data[k] = None
                    elif isinstance(v, (np.integer, int)):
                        formatted_base_data[k] = int(v)
                    elif isinstance(v, (np.floating, float)):
                        formatted_base_data[k] = float(v)
                    else:
                        formatted_base_data[k] = str(v)

            # [债券ETF] 为现金管理基金添加额外估值信息
            bond_extra = {}
            if code in BOND_ETF_CODES:
                try:
                    bv = get_bond_etf_valuation(conn, self.market_data_service)
                    val = bv.get_valuation(code)
                    bond_extra = {
                        "avg_daily_growth": val.get('avg_daily_growth'),
                        "bond_etf_method": val.get('method', ''),
                        "treasury_index_pct": val.get('treasury_index_pct'),
                        "estimated_nav": val.get('estimated_nav'),
                        "latest_nav": val.get('latest_nav'),
                        "latest_nav_date": val.get('latest_nav_date'),
                        # 国债期货数据 (511520专用)
                        "futures_pct": val.get('futures_pct'),
                        "tf_pct": val.get('tf_pct'),
                        "futures_adjustment": val.get('futures_adjustment'),
                        "total_adjustment": val.get('total_adjustment'),
                    }
                except Exception as e:
                    logger.error(f"[BondETF] 估值元数据获取失败 {code}: {e}")
            
            result = {
                "status": "ok",
                "fund_config": fund_cfg,
                "base_data": formatted_base_data,
                "t1_data": t1_data,
                "latest_exchange_rate": latest_fx,
                "realtime_quotes": realtime_quotes,
                "future_quote": future_quote,
                **bond_extra
            }
            _valuation_meta_cache.set(code, result)
            return result
        except Exception as e:
            logger.error(f"Error getting valuation meta for {code}: {e}")
            logger.error(traceback.format_exc())
            return {"status": "error", "message": str(e)}
        finally:
            conn.close()

    def get_my_watchlist(self) -> List[str]:
        """
        [V6.0] 获取"我的自选"基金列表
        优先从fund_watchlist表读取，如果为空则返回所有基金（兼容旧版本）

        注意：用户的自选基金主要存在于浏览器 localStorage，由前端通过 URL 参数传入后端。
        本函数供后台 snapshot 服务使用（backup 路径），fund_watchlist 表为空属于正常情况。
        """
        conn = self.db._get_conn()
        try:
            # 查询自选基金表
            cursor = conn.execute("SELECT fund_code FROM fund_watchlist ORDER BY fund_code")
            watchlist = [row[0] for row in cursor.fetchall()]
            
            # 如果自选表为空，返回所有基金（兼容旧版本，全部采样）
            # [V10.3] 降级为 DEBUG：fund_watchlist 表空是正常状态（用户自选在 localStorage），
            #          不应每3秒打 INFO 日志刷屏
            if not watchlist:
                logger.debug("[Snapshot] fund_watchlist 表为空，采样服务兼容模式：处理所有基金")
                all_funds_cursor = conn.execute("SELECT fund_code FROM unified_fund_list ORDER BY fund_code")
                watchlist = [row[0] for row in all_funds_cursor.fetchall()]
                return watchlist
            
            logger.debug(f"[Snapshot] 采样服务使用数据库自选列表: {len(watchlist)} 只基金")
            return watchlist
        finally:
            conn.close()
