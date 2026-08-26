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

# [AI-2026-07-29] 收编：valuation_method 改从主 YAML 读取，删 valuation_mapping 硬编码；统一用 resolve_method 按 category 补充默认方法
from arbcore.calculators.valuation_data_engine import resolve_method
# [AI-2026-07-27] 统一估值核心（估值引擎+数据引擎分离）：QDII日本实时复用篮子公式，NK期货价作单组件
from arbcore.calculators.unified_valuation import basket_valuation
# [2026-07-31] 收盘后冻结实时估值（15:00 快照覆盖 live 值）
from services.realtime_freeze import apply_freeze_to_dashboard, update_rt_cache

# [AI-2026-07-23] 期货结算价缓存（30秒 TTL），避免前端轮询刷屏新浪
_FUTURES_CACHE_TTL = 30
_futures_cache = {'data': None, 'time': 0.0}

# [AI-2026-08-21] 新浪请求节流：15秒间隔防封IP（共享工具模块）
from arbcore.utils.sina_throttle import throttle_sina_request as _throttle_sina_request

logger = logging.getLogger(__name__)

# [B1+B3-2026-08-26] 新浪 hq.sinajs.cn 强制 IPv4：根治 IPv6 半通导致 29~131s 挂死。
# 复用项目已验证的正确 adapter（send 内临时覆盖 socket.getaddrinfo 只返回 IPv4，保留域名 SNI），
# 与 market_data_service._sina_session / 下方 SSE 会话同思路。所有 hq.sinajs.cn 请求统一走本 session。
import socket as _socket
from requests.adapters import HTTPAdapter as _HTTPAdapter

class _SinaForceIPv4Adapter(_HTTPAdapter):
    def send(self, request, **kwargs):
        _orig = _socket.getaddrinfo
        def _ipv4_only(*a, **kw):
            return [r for r in _orig(*a, **kw) if r[0] == _socket.AF_INET]
        _socket.getaddrinfo = _ipv4_only
        try:
            return super().send(request, **kwargs)
        finally:
            _socket.getaddrinfo = _orig

_sina_session = requests.Session()
_sina_session.mount("http://", _SinaForceIPv4Adapter())
_sina_session.mount("https://", _SinaForceIPv4Adapter())
# [B1+B3] 强制不走系统/环境代理，直连 hq.sinajs.cn（与原有 requests.get(proxies={...:None}) 行为一致）
_sina_session.proxies.update({"http": None, "https": None})

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


def _sanitize_json_floats(obj):
    """[AI-2026-08-17] 递归把 NaN/Inf 洗成 None，避免 FastAPI 序列化
    'Out of range float values are not JSON compliant' 崩溃（如 164906 的 KWEB
    netvalue 缺失导致 components[].base_price=NaN）。洗成 None = 前端显 '--'，
    符合 SUPREME 铁律「缺失显 --，绝不兜底」——仅做 JSON 安全清洗，不填默认值。"""
    if isinstance(obj, float):
        if obj != obj or obj in (float('inf'), float('-inf')):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_json_floats(v) for v in obj]
    return obj


def _scalar_level(v):
    """[AI-2026-08-17] A股实时源(tdx/sina/guojin/galaxy/tencent)的 bid/ask 为5档list，
    IB/FUTU 分支为标量买一/卖一。估值路径只取买一/卖一标量（list[0]），
    不改动 market_data_service.get_realtime_quote 的出口语义（五档盘口接口依赖5档list）。
    list 首档为 None/空 → 返回 0（无盘口，由调用方走 price 分支或显'等待数据'）。"""
    if isinstance(v, (list, tuple)) and v:
        return float(v[0]) if v[0] is not None else 0
    return v


# [AI-2026-08-17] 判断某基金实时估值是否依赖 FUTU 行情源：其估值依赖的全部 symbol
#   （篮子权重 fund_basket_weights + YAML trade_etf + related_index + valuation_portfolio）中，
#   任一在 source_routing 里被路由到 'FUTU'（即非 IB 核心标的）。
# 用于 rt_val 为空时区分「源未连(缺FUTU)」与「盘后无行情/正常缺失」，前端据此显示「缺FUTU」提示。
def _fund_requires_futu(code: str, basket_symbols_by_fund: Dict[str, set], fund: dict = None) -> bool:
    syms: set = set(basket_symbols_by_fund.get(code, set()))
    if fund is not None:
        # [AI-2026-08-17] 补齐非 fund_basket_weights 路径的依赖 symbol
        #   （161126→RSPH、159561→DAX 等走 trade_etf；501300 等走 valuation_portfolio）
        te = _YAML_TRADE_ETF.get(code)
        if te:
            syms.add(te)
        ri_raw = fund.get('related_index', '') if hasattr(fund, 'get') else ''
        ri = _normalize_empty_symbol(ri_raw)
        if ri:
            syms.add(ri)
        vp = _YAML_VALUATION_PORTFOLIO.get(code)
        if vp:
            for item in vp:
                if not isinstance(item, dict):
                    continue
                s = item.get('symbol') or item.get('underlying_symbol')
                if s:
                    syms.add(s)
    if not syms:
        return False
    try:
        from arbcore.config.source_routing import get_symbol_source
    except Exception:
        return False
    for raw in syms:
        base = str(raw).replace('^', '')
        for suf in ('-EU', '-JP', '-HK'):
            if base.endswith(suf):
                base = base[:-len(suf)]
                break
        try:
            if get_symbol_source(base) == 'FUTU':
                return True
        except Exception:
            continue  # 未在 YAML 声明的 symbol 不计入 FUTU 依赖
    return False


def _normalize_empty_symbol(val) -> str:
    """DB/配置中常用 '-' / None / 空串 表示"无值"，归一为空串，避免哨兵值被当真实 symbol 路由。
    [2026-07-29] 含中文/全角等非 ASCII 字符的（如 related_index 的 '中小100'/'中证500'）也不是可路由
    symbol，同样归一为空 —— 这类国内指数 LOF 本就走指数路径，不应被当成 trade_etf 去路由。"""
    if val is None:
        return ''
    s = str(val).strip()
    if not s or s == '-':
        return ''
    if any(ord(ch) > 127 for ch in s):  # 含中文等非 ASCII → 不是可路由 symbol
        return ''
    return s
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

def _get_realtime_spot_fx() -> Optional[float]:
    """从新浪获取 USD/CNY 实时在岸价（实盘汇率），15秒缓存"""
    now = time.time()
    if now - _SPOT_FX_CACHE['time'] < 15 and _SPOT_FX_CACHE['rate'] > 0:
        return _SPOT_FX_CACHE['rate']
    try:
        # [Plan C] 合并批量新浪：fx_susdcny 走缓存（自身 15s 缓存仍优先）
        from arbcore.utils.sina_cache import get_sina_quotes
        _raw_map = get_sina_quotes(['fx_susdcny'])
        raw = _raw_map.get('fx_susdcny')
        if raw:
            parts = raw.split(',')
            if len(parts) >= 2:
                rate = float(parts[1])
                if rate > 0:
                    _SPOT_FX_CACHE['rate'] = rate
                    _SPOT_FX_CACHE['time'] = now
                    logger.debug(f"[FX] 新浪在岸价: {rate}")
                    return rate
    except Exception as e:
        logger.warning(f"[FX] 获取新浪在岸价失败: {e}")
    # [AI-2026-08-07] live 失败 → 真源备用：回退 DB exchange_rate.usd_cny_spot
    # （每日 9:20 由 daily_updater 从新浪入库的真值，非假数据，符合铁律）
    db_rate = _get_db_latest_spot('usd_cny_spot')
    if db_rate:
        logger.debug(f"[FX] live在岸价失败，回退DB真值(9:20落库): {db_rate}")
        return db_rate
    # 连 DB 真值也无 → 返 None，显 --，禁止用缓存旧值/0.0 掩盖（SUPREME 铁律）
    return None

# [AI-2026-07-23] JPY/CNY 在岸价缓存（实时估值用）
_JPY_SPOT_FX_CACHE = {'rate': 0.0, 'time': 0.0}

def _get_realtime_jpy_spot_fx() -> Optional[float]:
    """从新浪获取 JPY/CNY 实时在岸价（实盘汇率），15秒缓存

    [AI-2026-07-23] 新浪 fx_sjpycny 返回每1日元汇率（如 0.0416），
    需要乘以 100 转换为每100日元汇率（如 4.16），与数据库 jpy_cny_mid 单位一致。
    参考：woody stockref.php L487-490
    """
    now = time.time()
    if now - _JPY_SPOT_FX_CACHE['time'] < 15 and _JPY_SPOT_FX_CACHE['rate'] > 0:
        return _JPY_SPOT_FX_CACHE['rate']
    try:
        # [Plan C] 合并批量新浪：fx_sjpycny 走缓存（自身 15s 缓存仍优先）
        from arbcore.utils.sina_cache import get_sina_quotes
        _raw_map = get_sina_quotes(['fx_sjpycny'])
        raw = _raw_map.get('fx_sjpycny')
        if raw:
            parts = raw.split(',')
            if len(parts) >= 2:
                # [AI-2026-07-23] 新浪返回每1日元汇率，乘100转每100日元
                rate = float(parts[1]) * 100.0
                if rate > 0:
                    _JPY_SPOT_FX_CACHE['rate'] = rate
                    _JPY_SPOT_FX_CACHE['time'] = now
                    logger.debug(f"[FX] 日元在岸价: {rate}")
                    return rate
    except Exception as e:
        logger.warning(f"[FX] 获取日元在岸价失败: {e}")
    # [AI-2026-08-07] live 失败 → 真源备用：回退 DB exchange_rate.jpy_cny_spot（9:20 落库真值）
    db_rate = _get_db_latest_spot('jpy_cny_spot')
    if db_rate:
        logger.debug(f"[FX] live日元在岸价失败，回退DB真值(9:20落库): {db_rate}")
        return db_rate
    # 连 DB 真值也无 → 返 None，显 --（SUPREME 铁律）
    return None



# [AI-2026-08-07] 真源备用：live 在岸价拉取失败时，回退 DB exchange_rate 表最新落库真值
# （每日 9:20 由 daily_updater 从新浪入库的 usd_cny_spot / jpy_cny_spot，是真实值非假数据，符合铁律）
def _get_db_latest_spot(sym_col: str) -> Optional[float]:
    try:
        import sqlite3, os
        # [AI-2026-08-16] 活库移出仓库根到 D:\Study\arbTest\database（物理隔离防泄漏）；4层dirname到项目根父目录
        db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'database', 'arb_master.db')
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                f"SELECT {sym_col} FROM exchange_rate WHERE {sym_col} IS NOT NULL ORDER BY date DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row and row[0] and float(row[0]) > 0:
            return float(row[0])
    except Exception as e:
        logger.warning(f"[FX] 读取DB在岸价真值({sym_col})失败: {e}")
    return None


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
    'jpy_cny_mid': None,
    'jpy_cny_spot': None,
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
        # [AI-2026-07-23] 防御 None 与 int 比较崩溃
        if not fx_df.empty and pd.notna(fx_df.iloc[0]['usd_cny_mid']) and fx_df.iloc[0]['usd_cny_mid'] > 0:
            _daily_snapshot['usd_cny_mid'] = fx_df.iloc[0]['usd_cny_mid']
        # [AI-2026-07-23] 加载日元中间价和在岸价（QDII日本基金用）
        try:
            fx_df_all = pd.read_sql("SELECT usd_cny_mid, jpy_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
            if not fx_df_all.empty and pd.notna(fx_df_all.iloc[0]['jpy_cny_mid']) and fx_df_all.iloc[0]['jpy_cny_mid'] > 0:
                _daily_snapshot['jpy_cny_mid'] = fx_df_all.iloc[0]['jpy_cny_mid']
        except Exception:
            pass
        # [AI-2026-07-23] 加载日元在岸价（实时估值用）
        _daily_snapshot['jpy_cny_spot'] = _get_realtime_jpy_spot_fx()
        # 加载实时在岸价（用于 spot rate 基金）
        _daily_snapshot['usd_cny_spot'] = _get_realtime_spot_fx()
        if _daily_snapshot['usd_cny_spot'] is None or _daily_snapshot['usd_cny_spot'] <= 0:
            # [AI-2026-08-07] 缺失显 --，不回退中间价（SUPREME 铁律：禁止用旧值/其他源掩盖）
            logger.warning("[SNAPSHOT] 在岸价获取失败（非交易时段/网络异常），ETF实时估值将显 --")
        # [AI-2026-08-02] 日元在岸价落库已移至 daily_updater step3（9:20 清晨刷新，确定时点）。
        #   _ensure_daily_snapshot 只负责加载（读），不负责写库（避免 web 进程首次加载时间不固定）。
        _daily_snapshot['loaded'] = True
        logger.info(f"[SNAPSHOT] usd_cny_mid={_daily_snapshot['usd_cny_mid']}, usd_cny_spot={_daily_snapshot['usd_cny_spot']}, jpy_cny_mid={_daily_snapshot['jpy_cny_mid']}")
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
        from requests.adapters import HTTPAdapter
        import socket

        # [AI-2026-08-21] 强制 IPv4：域名 81.futsseapi.eastmoney.com 解析到 IPv6，
        # 本地 IPv6 路由半通导致 SSE 长连接建链后零数据(Read timeout)、ag0_price 恒为 0。
        # adapter 在每次请求期间临时覆盖 socket.getaddrinfo 使其只返回 IPv4 记录，
        # 保留域名 SNI 不变（避免 IP 直连的证书/SNI 问题），与 ARM 钉 hosts IPv4 思路一致。
        _orig_getaddrinfo = socket.getaddrinfo
        class _ForceIPv4Adapter(HTTPAdapter):
            def send(self, request, **kwargs):
                def _ipv4_only(*a, **kw):
                    return [r for r in _orig_getaddrinfo(*a, **kw) if r[0] == socket.AF_INET]
                socket.getaddrinfo = _ipv4_only
                try:
                    return super().send(request, **kwargs)
                finally:
                    socket.getaddrinfo = _orig_getaddrinfo

        _session = requests.Session()
        _session.mount("https://", _ForceIPv4Adapter())

        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        retry_delay = 2.0
        while self.running:
            if not self._is_trading_time():
                time.sleep(15)
                continue
            try:
                res = _session.get(url, stream=True, timeout=(5, 60),
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
        # [Plan C] 合并批量新浪：nf_AG0 走缓存（同时根治原 requests.get 未挂 IPv4 的挂死）
        from arbcore.utils.sina_cache import get_sina_quotes
        _raw_map = get_sina_quotes(['nf_AG0'])
        raw = _raw_map.get('nf_AG0')
        if raw:
            parts = raw.split(',')
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
def get_index_change_percent(symbol: str) -> Optional[float]:
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

    result = None
    try:
        # 1. 港股常见指数 - 必须先检查更长的字符串 HSTECH/HSCEI，再检查 HSI
        if 'HSTECH' in clean_sym:
            _throttle_sina_request()
            r = _sina_session.get("http://hq.sinajs.cn/list=rt_hkHSTECH", headers=headers_sina, timeout=3.0)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSTECH 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'HSCEI' in clean_sym:
            _throttle_sina_request()
            r = _sina_session.get("http://hq.sinajs.cn/list=rt_hkHSCEI", headers=headers_sina, timeout=3.0)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSCEI 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'HSI' in clean_sym:
            _throttle_sina_request()
            r = _sina_session.get("http://hq.sinajs.cn/list=rt_hkHSI", headers=headers_sina, timeout=3.0)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSI 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
        elif 'CES300' in clean_sym or 'CES300.HI' in clean_sym:
            _throttle_sina_request()
            r = _sina_session.get("http://hq.sinajs.cn/list=rt_hkCES300", headers=headers_sina, timeout=3.0)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 CES300 涨跌幅: {parts[8]}%")
                    result = float(parts[8])
                    
        # [AI-2026-07-09] 日经225(N225) — 新浪全球指数接口 int_nikkei
        elif clean_sym in ('N225', 'NKY', 'NIKKEI'):
            _throttle_sina_request()
            r = _sina_session.get("http://hq.sinajs.cn/list=int_nikkei", headers=headers_sina, timeout=3.0)
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
                
            r = _sina_session.get(url, headers=headers_sina, timeout=3.0)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 4 and float(parts[3]) != 0.0:
                    logger.info(f"[INDEX-SINA] 获取A股指数 {clean_sym} 涨跌幅: {parts[3]}%")
                    result = float(parts[3])
                    
            # [V7.2] 新浪优先、腾讯作为备用源（完美解决新浪没有中证指数的问题）
            if result == 0.0:
                prefix = 'sz' if clean_sym.startswith(('399', '159')) else 'sh'
                url_tencent = f"http://qt.gtimg.cn/q={prefix}{clean_sym}"
                r_tc = requests.get(url_tencent, headers=headers_tencent, timeout=1.5)
                if r_tc.status_code == 200 and 'v_' in r_tc.text:
                    tc_parts = r_tc.text.split('"')[1].split('~')
                    if len(tc_parts) >= 33:
                        # [AI-2026-08-07] 腾讯备用源补取属正常行为，降级DEBUG避免刷屏（数据逻辑不变）
                        logger.debug(f"[INDEX-TENCENT] 备用源获取指数 {clean_sym} 涨跌幅: {tc_parts[32]}%")
                        result = float(tc_parts[32])
    except Exception as e:
        logger.debug(f"Index fetch failed for {symbol}: {e}")
    # 写入日内缓存
    if result is not None:
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
    'H30094': '000852',
    '930713': '399006', '930875': '399006',
    '930720': '399005', '930997': '399005',
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

def _build_index_daily_backup(symbols: List[str], conn, now) -> Dict[str, Dict[str, float]]:
    """[V10.16] 从 index_history 备用源读取最新收盘价，并计算真实涨跌幅

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
    - 某交易所非交易日（如美股假期A股正常）→ 该交易所指数走 DB 备用源
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
    _t_db_start = time.perf_counter()  # [埋点A] Step1 DB备用源开始

    for ex, syms in exchange_syms.items():
        # 1a. 是否交易日？
        if not is_trading_day(ex, now.date()):
            # 非交易日 → 全部走 DB 备用源
            if conn:
                try:
                    part = _build_index_daily_backup(syms, conn, now)
                    if part:
                        db_results.update(part)
                        logger.debug(f"[INDEX-DB] {ex} 非交易日 {now.date()}，"
                                     f"{len(part)}/{len(syms)} 个指数取上一交易日收盘价")
                except Exception as e:
                    logger.warning(f"[INDEX-DB] {ex} 备用源读取失败: {e}")
            continue

        # 1b. 交易日内：判断是否已收盘
        if ex == 'A_SHARE':
            closed = now.hour >= 15
        elif ex == 'XHKG':
            closed = now.hour >= 16
        elif ex == 'JPX':
            # [AI-2026-07-22] 日本指数(N225)不再需要实时行情，直接始终判定为收盘以读取 index_history 的 Yahoo 数据备用源
            closed = True
        else:
            # 其他交易所（如美股指数）默认不在此API获取
            closed = True

        if closed:
            if conn:
                try:
                    part = _build_index_daily_backup(syms, conn, now)
                    if part:
                        db_results.update(part)
                except Exception as e:
                    logger.warning(f"[INDEX-DB] {ex} 收盘备用源读取失败: {e}")
        else:
            api_syms.extend(syms)
    _t_db_end = time.perf_counter()  # [埋点A] Step1 DB备用源结束

    # ====== Step 2: 还在交易时段的 → 调 API ======
    api_results = {}
    _t_api_start = time.perf_counter()  # [埋点A]
    if api_syms:
        api_results = _fetch_realtime_indices(api_syms, now)
    _t_api_end = time.perf_counter()  # [埋点A]

    # [AI-2026-07-09] N225历史存储：每次获取实时数据后写入index_history，供T-1静态估值使用
    # N225历史无法通过TDX回采（新浪/东财均不支持历史K线），必须靠实时抓取积累
    if api_results:
        try:
            today_str = now.strftime('%Y-%m-%d')
            import sqlite3
            # [AI-2026-07-13] 修复路径少一层的问题：从 services/ 需往上3层到项目根，再到 database/
            # [AI-2026-08-16] 活库移出仓库根到 D:\Study\arbTest\database（物理隔离防泄漏）；4层dirname到项目根父目录
            db_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'database', 'arb_master.db')
            conn_write = sqlite3.connect(db_path)
            for sym, data in api_results.items():
                if sym in ('.INX', '.NDX') and data.get('price', 0) > 0:
                    # [AI-2026-07-22] 将 INSERT OR REPLACE 改为 INSERT OR IGNORE，防止新浪实时数据覆盖 Yahoo 历史数据
                    conn_write.execute(
                        "INSERT OR IGNORE INTO index_history (symbol, date, close, source) VALUES (?, ?, ?, ?)",
                        (sym, today_str, data['price'], 'sina')
                    )
                    logger.debug(f"[INDEX-HISTORY] 写入 {sym} {today_str} close={data['price']}")
            conn_write.commit()
            conn_write.close()
        except Exception as e:
            logger.warning(f"写入N225历史数据异常: {e}")

    # ====== Step 3: 合并并缓存 ======
    logger.info(
        "[INDEX-PROFILE] syms=%d db_backup=%dms api_fetch=%dms total=%dms",
        len(symbols),
        int((_t_db_end - _t_db_start) * 1000),
        int((_t_api_end - _t_api_start) * 1000),
        int((_t_api_end - _t_db_start) * 1000),
    )
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
    仅用于还在交易时段的指数（收盘后的指数已在 prefetch_index_changes 中走DB备用源）
    """
    if not symbols:
        return {}

    # [V10.14] 统一使用模块级 _INDEX_CODE_MAP，不再重复定义
    US_ETF_KEYWORDS = {'XOP', 'GLD', 'USO', 'SPY', 'QQQ', 'XBI', 'XLY', 'SOXX',
                       'ARKK', 'ARKG', 'EEM', 'VWO', 'INDA', 'EWJ', 'KWEB', 'RSPH',
                       'LQD', 'HYG', 'TLT', 'IEF', 'SHY', 'AGG', 'BND'}

    # [AI-2026-08-05] 删除 _HK_INDEX_ALIAS_MAP 别名兜底（违反"不兜底"铁律）
    # 原逻辑把 HSMI/HSSI/HSCCI/HSCI/HSSCNE 映射到 HSCEI/HSI 取实时数据 → 指数价/涨跌幅完全错误
    # 实测新浪 rt_hk{sym} 直接支持所有港股指数（HSMI/HSSI/HSCCI/HSCI/HSSCNE 全部返回真实数据），无需映射

    # [V10.19] CSI代码(930xxx/931xxx等)不应走腾讯sh/sz查询，应直接走东财
    def _is_csi_index_code(code: str) -> bool:
        """判断是否为中证指数代码（如930914, 931234等）"""
        return code.isdigit() and len(code) == 6 and (code.startswith('930') or code.startswith('931') or code.startswith('932'))

    import requests
    import time  # [埋点A] 性能分段诊断
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
            # 跳过腾讯/新浪，让东财作为备用源处理
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
        elif clean_sym in ('HSMI', 'HSSI', 'HSCCI', 'HSCI', 'HSSCNE'):
            # [AI-2026-08-05] 新浪 rt_hk{sym} 直接支持这些港股指数（删除原 _HK_INDEX_ALIAS_MAP 别名兜底，符合"不兜底"铁律）
            # 实测：新浪 rt_hkHSMI/rt_hkHSSI/rt_hkHSCCI/rt_hkHSCI/rt_hkHSSCNE 全部返回真实实时数据
            # 腾讯 qt.gtimg 仅支持 HSCCI/HSCI，不支持 HSMI/HSSI/HSSCNE（返回 v_pv_none_match）
            if clean_sym in ('HSCCI', 'HSCI'):
                tc_req = f"hk{clean_sym}"
            sina_req = f"rt_hk{clean_sym}"
            ret_code = clean_sym
        elif clean_sym.startswith('.') and len(clean_sym) <= 10:
            # [V10.13] 美股指数（.INX, .NDX, .SP500-45 等）走新浪获取
            sina_req = f"s_sh{clean_sym}"
            ret_code = clean_sym
        else:
            continue
            
        if tc_req:
            tencent_requests.add(tc_req)
        tc_to_syms.setdefault(ret_code, []).append(sym)
        sina_to_syms.setdefault(ret_code, []).append(sym)
        # [AI-2026-07-20] 全球指数（sina_req != ret_code）额外注册 sina_req 键
        # 新浪响应变量名（如 int_nikkei）经解析后提取的是 sina_req，不是 ret_code
        # 例如 N225: ret_code="N225", sina_req="int_nikkei", 新浪返回 hq_str_int_nikkei
        if sina_req and sina_req != ret_code:
            sina_to_syms.setdefault(sina_req, []).append(sym)

    res = {}
    
    # [AI-2026-08-04] 东哥拍板：A股实时行情非腾讯 qt.gtimg 实时。改为新浪优先、腾讯作为备用源。
    # 2. 优先从新浪获取（res 为空时全量尝试）
    missing_sina_reqs = set()
    for ret_code, syms in sina_to_syms.items():
        if any(s not in res for s in syms):
            if ret_code.isdigit():
                if ret_code.startswith('399') or ret_code.startswith('159') or ret_code.startswith('3999'):
                    missing_sina_reqs.add(f"s_sz{ret_code}")
                else:
                    missing_sina_reqs.add(f"s_sh{ret_code}")
            else:
                missing_sina_reqs.add(f"rt_hk{ret_code}")

    _t_sina_start = time.perf_counter()  # [埋点A]
    if missing_sina_reqs:
        try:
            # [Plan C] 合并批量新浪：同一节流窗口内多次调用 coalesce 为一次批量 GET
            from arbcore.utils.sina_cache import get_sina_quotes
            _sina_raw_map = get_sina_quotes(list(missing_sina_reqs))
            for req in missing_sina_reqs:
                raw = _sina_raw_map.get(req)
                if not raw:
                    continue
                line = f"var hq_str_{req}=\"{raw}\""
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
                                    logger.debug(f"[INDEX-SINA-US] 获取指数 {original_sym} 价格: {parts[1]} 涨跌幅: {parts[3]}%")
                elif var_name.startswith('var hq_str_int_'):
                    # [AI-2026-07-09] 新浪全球指数格式（日经225等）: var hq_str_int_nikkei="名称,价格,涨跌,涨跌幅%,日期,..."
                    code = var_name.replace('var hq_str_', '')
                    if code in sina_to_syms:
                        for original_sym in sina_to_syms[code]:
                            if original_sym not in res:
                                if len(parts) >= 4:
                                    res[original_sym] = {"price": float(parts[1]), "pct": float(parts[3])}
                                    logger.debug(f"[INDEX-SINA-GLOBAL] 获取指数 {original_sym} 价格: {parts[1]} 涨跌幅: {parts[3]}%")
        except Exception as e:
            logger.warning(f"预取新浪指数异常: {e}")
    _t_sina_end = time.perf_counter()  # [埋点A]

    # [AI-2026-08-04] 新浪优先后，腾讯仅补充新浪未拿到的指数（非主力源）
    # 1. 腾讯备用源补充
    _t_tc_start = time.perf_counter()  # [埋点A]
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
                                if original_sym not in res:
                                    res[original_sym] = {"price": float(tc_parts[3]), "pct": float(tc_parts[32])}
                            # [AI-2026-08-07] 腾讯备用源补取属正常行为，降级DEBUG避免刷屏（数据逻辑不变）
                            logger.debug(f"[INDEX-TENCENT] 备用源获取指数 {code} 价格: {tc_parts[3]} 涨跌幅: {tc_parts[32]}%")
        except Exception as e:
            logger.warning(f"预取腾讯指数异常: {e}")
    _t_tc_end = time.perf_counter()  # [埋点A]

    # [V10.12] 3. 东财API备用源：港股/CSI非标指数（腾讯/新浪不识别的）
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
        # 判断是否需要东财备用源
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

    _t_em_start = time.perf_counter()  # [埋点A]
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
    _t_em_end = time.perf_counter()  # [埋点A]

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

    logger.info(
        "[INDEX-API-PROFILE] sina=%dms tencent=%dms eastmoney=%dms",
        int((_t_sina_end - _t_sina_start) * 1000),
        int((_t_tc_end - _t_tc_start) * 1000),
        int((_t_em_end - _t_em_start) * 1000),
    )
    return res

class FundService:
    def __init__(self, db, market_data_service=None, config_service=None):
        self.db = db
        self.market_data_service = market_data_service
        self.config_service = config_service
        self._calculator = None
        # [AI-2026-08-26] 盘后兜底防并发锁（防 _step4_fetch_prices 子进程风暴）
        self._ensure_close_lock = threading.Lock()
    
    def _get_calculator(self):
        """懒加载估值计算器"""
        if self._calculator is None:
            try:
                from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
                self._calculator = DynamicValuationCalculator(self.db)
            except Exception as e:
                logger.error(f"初始化估值计算器失败: {e}")
        return self._calculator

    def get_realtime_valuation_detail(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只基金实时估值明细（供 H5 详情页展示计算依据）。

        [AI-2026-08-03] 目前完整支持「篮子基金」（黄金原油/QDII欧美/白银/混合跨境）路径；
        其他类别返回基础信息 + 当前可得行情，rt_val 细节逐步补齐。
        返回字段：
          fund_code, fund_name, category, nav, nav_date,
          price, realtime_price, rt_val, rt_premium,
          position, fx_base, fx_current, hedge, base_date,
          components[symbol/weight/base_price/current_price/bid/ask/bid_size/ask_size/source],
          lof_quote{bid/ask/bid_size/ask_size/price/source}
        """
        code = str(code or '').strip()
        if not code:
            return None
        conn = self.db._get_conn()
        quantity = None  # [AI-2026-08-05] 聚合层对冲数量,默认 None;篮子分支经 analyze_realtime 赋值,供 H5 详情页
        try:
            # 1. 基金基本信息
            fund_df = pd.read_sql(
                "SELECT fund_code, fund_name, category, pos_ratio, related_index FROM unified_fund_list WHERE fund_code=?",
                conn, params=(code,)
            )
            if fund_df.empty:
                return None
            fund = fund_df.iloc[0].to_dict()
            category = str(fund.get('category') or '').strip()
            name = str(fund.get('fund_name') or '').strip()

            # 2. 最新净值(T-1)与历史收盘价（分别取最近有值记录，避免当天 price 已更新但 nav 未公布时 nav 为空）
            nav_df = pd.read_sql(
                "SELECT date, nav FROM unified_fund_history WHERE fund_code=? AND nav IS NOT NULL AND nav > 0 ORDER BY date DESC LIMIT 1",
                conn, params=(code,)
            )
            nav = float(nav_df.iloc[0]['nav']) if not nav_df.empty else None
            nav_date = nav_df.iloc[0]['date'] if not nav_df.empty else None
            # [AI-2026-08-20] 优先取今天收盘价，盘后显示当天官方数据而非昨日收盘
            today_str = datetime.now().strftime('%Y-%m-%d')
            today_price_df = pd.read_sql(
                "SELECT price FROM unified_fund_history WHERE fund_code=? AND date=? AND price IS NOT NULL AND price > 0",
                conn, params=(code, today_str)
            )
            today_price = float(today_price_df.iloc[0]['price']) if not today_price_df.empty else None

            # 3. LOF 实时盘口（A股）
            lof_quote = None
            if self.market_data_service:
                try:
                    lof_quote = self.market_data_service.get_realtime_quote(code)
                except Exception as e:
                    logger.debug(f"[{code}] 获取LOF实时盘口失败: {e}")
            realtime_price = None
            if lof_quote and lof_quote.get('price', 0) > 0:
                realtime_price = float(lof_quote['price'])

            # 优先级：实时价 > 今天收盘价 > 最近收盘价
            if realtime_price:
                price = realtime_price
            elif today_price:
                price = today_price
            else:
                price_df = pd.read_sql(
                    "SELECT price FROM unified_fund_history WHERE fund_code=? AND price IS NOT NULL AND price > 0 ORDER BY date DESC LIMIT 1",
                    conn, params=(code,)
                )
                price = float(price_df.iloc[0]['price']) if not price_df.empty else None
            close_price = price  # 保持close_price变量用于后续逻辑

            # 4. 当前实时估值
            rt_val = None
            rt_premium = None

            # 5. 篮子基金：直接本地计算明细（避免并发 detail 请求反复重算主面板全量）
            components = []
            position = None
            fx_base = None
            fx_current = None
            hedge = None
            base_date = None
            basket_categories = {'黄金原油', 'QDII欧美', '白银', '混合跨境'}  # [AI-2026-08-17] QDII日本不走此篮子分支：详情页应复用主看板 NK 期货路径(get_unified_dashboard_data L1628)，而非 NKY ETF 篮子(usa_etf_daily_prices 无 NKY 数据)
            if category in basket_categories:
                yaml_trade_etf = _YAML_TRADE_ETF.get(code, '')
                resolved_trade_etf = yaml_trade_etf or _normalize_empty_symbol(fund.get('related_index', ''))
                fund_cfg = {
                    "code": code,
                    "trade_etf": resolved_trade_etf,
                    "holdings": {"equity_ratio": float(fund.get('pos_ratio') or 0.95) * 100},
                    "category": category,
                }
                # portfolio
                try:
                    basket_df = pd.read_sql(
                        "SELECT underlying_symbol as symbol, weight FROM fund_basket_weights "
                        "WHERE fund_code=? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)",
                        conn, params=(code, code)
                    )
                    if not basket_df.empty:
                        fund_cfg["valuation_portfolio"] = basket_df.to_dict('records')
                    else:
                        yaml_portfolio = _YAML_VALUATION_PORTFOLIO.get(code) or fund.get('valuation_portfolio') or fund.get('hedging_portfolio')
                        if yaml_portfolio:
                            fund_cfg["valuation_portfolio"] = yaml_portfolio
                except Exception as e:
                    logger.debug(f"[{code}] 读取 basket weights 失败: {e}")

                if fund_cfg.get('valuation_portfolio'):
                    # 当前汇率
                    current_fx = None
                    try:
                        _ensure_daily_snapshot(conn)
                        if category == 'QDII日本':
                            current_fx = _daily_snapshot.get('jpy_cny_mid')
                        else:
                            current_fx = _daily_snapshot.get('usd_cny_mid')
                        if code in _FUNDS_WITH_SPOT_RATE:
                            spot_fx = _daily_snapshot.get('usd_cny_spot') or 0
                            if spot_fx > 0:
                                current_fx = spot_fx
                    except Exception as e:
                        logger.debug(f"[{code}] 取快照汇率失败: {e}")

                    # 当前 ETF 完整盘口
                    current_quotes = {}
                    if self.market_data_service and current_fx and current_fx > 0:
                        portfolio = fund_cfg['valuation_portfolio']
                        required_bases = set()
                        for item in portfolio:
                            raw_sym = item.get('symbol', '')
                            sym_base = raw_sym.replace('^', '')
                            for suffix in ['-EU', '-JP', '-HK']:
                                if sym_base.endswith(suffix):
                                    sym_base = sym_base[:-len(suffix)]
                                    break
                            required_bases.add(sym_base)
                        for sym_base in required_bases:
                            try:
                                q = self.market_data_service.get_realtime_quote(sym_base)
                                if q and (q.get('bid', 0) > 0 or q.get('price', 0) > 0):
                                    current_quotes[sym_base] = q
                            except Exception as e:
                                logger.debug(f"[{code}] 取 {sym_base} 行情失败: {e}")

                    calculator = self._get_calculator()
                    # [AI-2026-08-04] 允许 current_quotes 为空（盘后美股无行情），
                    # 此时仍从基准数据返回仓位/汇率基准/hedge/components 等展示字段，
                    # 不伪造实时价；rt_val/rt_premium 仅在有实时行情时才用 detail 重算。
                    if calculator and current_fx and current_fx > 0:
                        try:
                            fund_cfg['current_price'] = price or 0
                            detail = calculator.calculate_detail(fund_cfg, current_fx, current_quotes)
                            if detail:
                                if current_quotes:
                                    rt_val = detail['rt_val']
                                    rt_premium = detail.get('premium')
                                components = detail.get('components', [])
                                position = detail.get('position')
                                fx_base = detail.get('fx_base')
                                fx_current = detail.get('fx_current')
                                hedge = detail.get('hedge')
                                base_date = detail.get('base_date')
                                # [AI-2026-08-03] 显示用 hedge 直取 fund_daily_factors（woody 推导的近恒定 H）：
                                # 仅详情页展示，不参与估值（估值仍走矩阵公式，避免陈旧 H 污染魔法公式）。
                                # 仅单 ETF（portfolio 单组件）补；多篮子无单一 H，保持 None 显示 '--'。
                                if hedge is None and len(fund_cfg.get('valuation_portfolio') or []) == 1:
                                    try:
                                        _hw = pd.read_sql(
                                            "SELECT hedge FROM fund_daily_factors "
                                            "WHERE fund_code=? AND hedge IS NOT NULL AND hedge>0 "
                                            "ORDER BY date DESC LIMIT 1",
                                            conn, params=(code,))
                                        if not _hw.empty:
                                            hedge = float(_hw.iloc[0]['hedge'])
                                    except Exception as _e:
                                        logger.debug(f"[{code}] 回填显示 hedge 失败: {_e}")
                        except Exception as e:
                            logger.warning(f"[{code}] calculate_detail 失败: {e}")
            # [AI-2026-08-05] 生产接入：聚合层算权威对冲数量(每10万份)，替代 H5 前端手算，
            # 保证前后端单一算法源(消除 preview.html 559-595 分叉)。仅篮子/单ETF类有值，其余 None。
            try:
                from arbcore.analysis import analyze_realtime as _ar_rt
                _ar_etfs = {s: (q.get('price') or q.get('bid') or 0) for s, q in (current_quotes or {}).items()}
                _ar_res = _ar_rt(code, lof_qty=100000, current_price=(price or 0),
                                 current_fx=(current_fx or 0), current_etfs=_ar_etfs)
                quantity = _ar_res.get('quantity') if _ar_res else None
            except Exception as _qe:
                logger.debug(f"[{code}] 聚合层对冲数量计算失败: {_qe}")
                quantity = None
            else:
                # 非篮子基金：复用主面板已算好的 rt_val / rt_premium
                try:
                    dashboard_data = self.get_unified_dashboard_data(watchlist=[code])
                    if dashboard_data:
                        row = dashboard_data[0]
                        rt_val = row.get('rt_val')
                        rt_premium = row.get('rt_premium')
                        if row.get('realtime_price'):
                            realtime_price = float(row['realtime_price'])
                            price = realtime_price
                except Exception as e:
                    logger.debug(f"[{code}] 取主面板实时估值失败: {e}")

            # [AI-2026-08-17] NaN/Inf 安全清洗：防 FastAPI 序列化崩溃(164906 KWEB netvalue 缺失 → base_price=NaN → HTTP 500)
            return _sanitize_json_floats({
                'fund_code': code,
                'fund_name': name,
                'category': category,
                'nav': nav,
                'nav_date': nav_date,
                'price': price,
                'realtime_price': realtime_price,
                'close_price': close_price,
                'rt_val': rt_val,
                'rt_premium': rt_premium,
                'position': position,
                'fx_base': fx_base,
                'fx_current': fx_current,
                'hedge': hedge,
                'base_date': base_date,
                'components': components,
                'quantity': quantity,  # [AI-2026-08-05] 聚合层权威对冲数量(每10万份),H5 替代前端手算
                'lof_quote': {
                    'bid': lof_quote.get('bid') if lof_quote else None,
                    'ask': lof_quote.get('ask') if lof_quote else None,
                    'bid_size': lof_quote.get('bid_size') if lof_quote else None,
                    'ask_size': lof_quote.get('ask_size') if lof_quote else None,
                    'price': lof_quote.get('price') if lof_quote else None,
                    'source': lof_quote.get('source') if lof_quote else None,
                } if lof_quote else None,
            })
        except Exception as e:
            logger.error(f"[{code}] get_realtime_valuation_detail 异常: {e}")
            return None
        finally:
            conn.close()

    def get_unified_dashboard_data(self, watchlist: List[str] = None, category: str = None) -> List[Dict[str, Any]]:
        """
        [V8.1] 性能大修：SQL 级过滤 + 5秒缓存 + 批量历史查询
        """
        import time as _t  # [埋点A] 性能分段诊断
        _prof = {'start': _t.perf_counter()}
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
                # [AI-2026-08-05] 增加 paused_exempt 字段，用于豁免分类暂停
                f"SELECT fund_code, fund_name, category, related_index, pos_ratio, idx_code, idx_name, paused_exempt FROM unified_fund_list {where_clause}",
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
                # [AI-2026-08-05] 豁免基金(paused_exempt=1)不受分类暂停影响，仍展示+计算估值
                mask_paused = funds_df['category'].isin(paused_set) & (funds_df['paused_exempt'] == 0)
                funds_df = funds_df[~mask_paused]
                if len(funds_df) < before:
                    logger.debug(f"[DASHBOARD-FILTER] 过滤暂停分类(保留豁免)，{before} -> {len(funds_df)} 只基金")

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
                       volume, trade_volume, shares, shares_added, turnover_rate
                FROM (
                    SELECT fund_code, date, price, nav, static_val,
                           premium as static_premium, volume, trade_volume, shares,
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
            # [AI-2026-08-05] funds_df 已在上方按 paused_exempt 过滤（豁免基金保留），无需重复过滤
            indices_to_fetch = funds_df['related_index'].dropna().tolist()
            if paused_set:
                logger.debug(f"[INDEX-FILTER] 暂停分类(含豁免) {sorted(paused_set)}，抓取 {len(indices_to_fetch)} 个指数")
            
            index_changes_map = prefetch_index_changes(indices_to_fetch, conn=conn)
            _prof['prefetch_index'] = _t.perf_counter()  # [埋点A] 指数预取段结束

            # 预查哪些基金有完整权重篮子（跳过简化指数估值，直接用计算器）
            funds_with_basket = set()
            basket_symbols_by_fund = {}  # [AI-2026-08-17] code -> set(underlying_symbol)，供「缺FUTU」源依赖判断
            try:
                basket_codes_df = pd.read_sql("SELECT fund_code, underlying_symbol FROM fund_basket_weights", conn)
                funds_with_basket = set(basket_codes_df['fund_code'].tolist())
                for _, r in basket_codes_df.iterrows():
                    basket_symbols_by_fund.setdefault(r['fund_code'], set()).add(r['underlying_symbol'])
            except:
                pass
            _prof['db_read'] = _t.perf_counter()  # [埋点A] DB读取段结束

            # [V9.1] 并发预取所有基金的实时行情（解决序列调用 get_realtime_quote ~5s 卡顿）
            # [B1-2026-08-26] 同时预取篮子成分标的（USO/GLD/XOP/GC/CL/NK/AG…），避免估值循环里
            # 逐基金、逐成分调用 get_realtime_quote 触发新浪 15s 节流+挂死。预取结果按归一化 symbol
            # 写入 quotes_dict，估值循环直接复用缓存，不再触发任何新浪请求。
            quotes_dict = {}
            _prefetch_symbols = list(codes)
            for _comps in basket_symbols_by_fund.values():
                for _s in _comps:
                    if _s and _s not in _prefetch_symbols:
                        _prefetch_symbols.append(_s)
            if self.market_data_service:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=8) as executor:
                    fut_map = {executor.submit(self.market_data_service.get_realtime_quote, c): c for c in _prefetch_symbols}
                    for fut in as_completed(fut_map):
                        c = fut_map[fut]
                        try:
                            rt = fut.result()
                            if rt and rt.get('price'):
                                quotes_dict[c] = rt
                                _norm = rt.get('symbol') or c
                                if _norm != c:
                                    quotes_dict[_norm] = rt
                        except Exception:
                            pass
            _prof['realtime_quotes'] = _t.perf_counter()  # [埋点A] 实时价线程池段结束

            result = []
            for _, fund in funds_df.iterrows():
                code = fund['fund_code']
                _vf_start = time.perf_counter()  # [埋点A] 逐基金计时起点
                category = fund.get('category', '')

                # [AI-2026-07-20] 暂停分类 ❌ 直接跳过，不计算实时估值、不产生 WARNING 日志
                # [AI-2026-08-05] 豁免基金(paused_exempt=1)不跳过，正常计算估值
                if category in paused_set and fund.get('paused_exempt', 0) == 0:
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
                           'rt_val': None, 'rt_premium': None, 'sub_category': _FUNDS_SUB_CATEGORY.get(code, ''),
                           'volume': 0, 'trade_volume': 0, 'shares': 0, 'shares_added': 0, 'turnover_rate': 0}

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
                        p = valid_prices.iloc[0]['price']
                        metrics['price'] = float(p) if p is not None and float(p) > 0 else 0.0

                    for col in ['volume', 'trade_volume', 'shares', 'shares_added']:
                        valid_series = metrics_df.dropna(subset=[col])
                        metrics[col] = float(valid_series.iloc[0][col]) if not valid_series.empty else 0.0

                    # [AI-2026-08-06] 修复：新增份额必须基于【相邻交易日】差值；
                    # 若前一日份额缺失(如 VPS 当日漏采)，则显式留空(None)，禁止跨日兜底造出假差值(如 8-6减8-4)
                    if 'shares' in metrics_df.columns and len(metrics_df) >= 2:
                        _sa = metrics_df.dropna(subset=['shares']).sort_values('date')
                        if len(_sa) >= 2:
                            _prev = _sa['shares'].shift(1)
                            _gap = (pd.to_datetime(_sa['date']) - pd.to_datetime(_sa['date'].shift(1))).dt.days
                            _added = (_sa['shares'] - _prev).where(_prev.notna() & (_gap <= 4))
                            _last = _added.iloc[-1]
                            if pd.notna(_last):
                                metrics['shares_added'] = float(_last)
                            else:
                                metrics['shares_added'] = None  # 中间日缺失，不跨日兜底

                    # [2026-07-30] 换手率(%) = 成交量(手) / 份额(万)，与 woody 网页对齐
                    #   推导：手×100=份；万×10000=份；份/份×100 = 手/万，故 trade_volume/shares 直接为百分比数值
                    # 注意：历史表 turnover_rate 字段是旧口径残留，主面板不再信任，一律重算
                    tv = metrics.get('trade_volume', 0)  # 成交量（手）
                    sh = metrics.get('shares', 0)        # 份额（万份）
                    if tv > 0 and sh > 0:
                        metrics['turnover_rate'] = tv / sh

                    # [AI-2026-07-09] 修复涨跌幅：prev_close 必须是"昨收"（前一日收盘价），
                    # 不能是 iloc[0]（当日最新价，与现价相同会导致涨跌幅≈0 或错乱）。
                    # valid_prices 按日期降序（iloc[0]=当日），昨收取 iloc[1]，不足则显 None（禁止用当日价兜底）。
                    if not valid_prices.empty:
                        if len(valid_prices) >= 2:
                            metrics['prev_close'] = valid_prices.iloc[1]['price']
                        else:
                            # [AI-2026-08-07] 不足两日(无昨收)显 None，禁止用当日价/0 充当昨收（SUPREME 铁律）
                            metrics['prev_close'] = None
                    else:
                        metrics['prev_close'] = None

                # ── 4. 实时价格（从预取的 quotes_dict 取，避免逐只序列调用） ──
                # [AI-2026-07-29] 历史/卡片显示的「收盘价(price)」必须是 DB 官方收盘，
                #   严禁用腾讯实时盘中价覆盖（东哥发现：重启后端后实时 fetcher 生效，
                #   会把盘中最新价盖到历史收盘价上，导致与官方收盘差几分钱）。
                #   实时价单独存 realtime_price，仅供「实时溢价(rt_premium)」使用。
                if self.market_data_service and code in quotes_dict:
                    rt = quotes_dict[code]
                    p = rt.get('price')
                    if p is not None and float(p) > 0:
                        metrics['realtime_price'] = float(p)
                    if rt.get('amount'):
                        metrics['volume'] = rt['amount']  # 成交额（万元），主面板「成交额」列显示
                    # [2026-07-30] 实时成交量（股）→ 手；换手率 = 成交量(手) / 份额(万)，与 woody 对齐
                    if rt.get('volume'):
                        metrics['trade_volume'] = float(rt['volume']) / 100.0  # 股 → 手
                        sh = metrics.get('shares', 0)
                        if sh > 0:
                            metrics['turnover_rate'] = metrics['trade_volume'] / sh  # 直接为百分比数值
                elif self.market_data_service:
                    try:
                        rt = self.market_data_service.get_realtime_quote(code)
                        if rt and rt.get('price'):
                            metrics['realtime_price'] = float(rt['price'])
                            if rt.get('amount'):
                                metrics['volume'] = rt['amount']  # 成交额（万元）
                            if rt.get('volume'):
                                metrics['trade_volume'] = float(rt['volume']) / 100.0  # 股 → 手
                                sh = metrics.get('shares', 0)
                                if sh > 0:
                                    metrics['turnover_rate'] = metrics['trade_volume'] / sh  # 直接为百分比数值
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

                # [AI-2026-07-23] QDII日本基金：NK期货实时估值（Woody 公式）
                # Woody: fVal = NK_real * JPYCNY_real / fFactor, fFactor = NK_base * JPYCNY_base / NAV_base
                # 等价于: rt_val = NAV_base * [(1-pos) + pos * (NK_real/NK_base) * (JPYCNY_real/JPYCNY_base)]
                if category == 'QDII日本' and metrics.get('nav', 0) > 0:
                    try:
                        nk_quote = self.market_data_service.get_realtime_quote('NK') if self.market_data_service else None
                        nk_current = float(nk_quote.get('price', 0) or 0) if nk_quote else 0.0
                        if nk_current > 0:
                            # 获取 T-1 基准日数据（与 NAV 同一天）
                            t1_row = conn.execute("""
                                SELECT h.date, h.nav, COALESCE(r.jpy_cny_spot, r.jpy_cny_mid) AS fx_base
                                FROM unified_fund_history h
                                LEFT JOIN exchange_rate r ON h.date = r.date
                                WHERE h.fund_code = ? AND h.nav > 0 AND (r.jpy_cny_spot > 0 OR r.jpy_cny_mid > 0)
                                ORDER BY h.date DESC LIMIT 1
                            """, (code,)).fetchone()
                            if t1_row:
                                base_date = t1_row[0]
                                nav_base = float(t1_row[1])
                                fx_base = float(t1_row[2])
                                # [AI-2026-07-23] NK 基准结算价：取最新数据（futures_daily 可能缺失历史 NK 数据）
                                nk_base_row = conn.execute(
                                    "SELECT settle_price FROM futures_daily WHERE symbol='NK' AND settle_price > 0 ORDER BY date DESC LIMIT 1"
                                ).fetchone()
                                nk_base = float(nk_base_row[0]) if nk_base_row else 0.0
                                # 当前 JPY/CNY 在岸价（实时估值用对在岸价，不用中间价）
                                fx_current = _daily_snapshot.get('jpy_cny_spot') or 0.0
                                if nk_base > 0 and fx_current > 0 and fx_base > 0 and nav_base > 0:
                                    pos = float(fund.get('pos_ratio', 0.95))
                                    # [AI-2026-07-27] 复用统一估值核心：NK期货价作单组件(weight=1.0)，hedge=None
                                    # 等价于原 Woody 公式 rt_val = nav_base * ((1-pos) + pos*(nk_current/nk_base)*(fx_current/fx_base))
                                    rt_val = basket_valuation(
                                        nav_base, pos,
                                        [{'symbol': 'NKY', 'current_price': nk_current,
                                          'base_price': nk_base, 'weight': 1.0}],
                                        fx_base, fx_current, hedge=None,
                                    )
                                    if rt_val is not None:
                                        metrics['rt_val'] = round(rt_val, 4)
                                        if metrics.get('price', 0) > 0:
                                            metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                    except Exception as e:
                        logger.error(f"[QDII日本] 实时估值计算失败 {code}: {e}")

                # 尝试实时计算估值 (仅非债券ETF已有，此处保留原逻辑)
                try:
                    if code == '161226':
                        import requests
                        from arbcore.utils.market_calendar import is_shfe_open
                        # [2026-07-30 FIX] SHFE 沪银交易时段守卫：休市时段（午夜-早盘间隙、周末、节假日）
                        # 新浪 nf_AG0 仍返回上一交易时段收盘价，若直接当"实时"会误导用户；故非交易时段
                        # 不采信 AG0 价 → rt_val / si_val 保持 None（前端显示 '-'），与沙盘页一致。
                        _ag_session_open = is_shfe_open()
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
                        
                        # [优先级3] 降级：新浪 nf_AG0 接口补充
                        if ag_future_price <= 0 or settlement_price <= 0:
                            try:
                                # [Plan C] 合并批量新浪：nf_AG0 走缓存，不再独立节流
                                from arbcore.utils.sina_cache import get_sina_quotes
                                _raw_map = get_sina_quotes(['nf_AG0'])
                                raw = _raw_map.get('nf_AG0')
                                if raw:
                                    parts = raw.split(',')
                                    if len(parts) >= 11:
                                        ag_future_price = float(parts[8])   # 最新价
                                        settlement_price = float(parts[10])  # 昨结算价
                                        # 新浪接口 part[9] 即为今日动态结算均价(VWAP)
                                        vwap = float(parts[9]) if len(parts) > 9 else 0.0
                            except:
                                pass

                        # [AI-2026-08-21 FIX] 优先级4: SSE/程序1/新浪全部失败 → 回退DB最新收盘价
                        # 解决DNS失败/SSE未就绪时AG0实时价缺失问题
                        if ag_future_price <= 0:
                            try:
                                _conn = self.db._get_conn()
                                _row = _conn.execute(
                                    "SELECT close_price FROM futures_daily WHERE symbol='AG0' AND close_price>0 ORDER BY date DESC LIMIT 1"
                                ).fetchone()
                                if _row and _row[0] and float(_row[0]) > 0:
                                    ag_future_price = float(_row[0])
                                    logger.debug(f"[{code}] AG0 实时价为0，回退数据库最新收盘={ag_future_price}")
                            except Exception as _e:
                                logger.debug(f"[{code}] AG0 收盘DB回退失败: {_e}")

                        # [AI-2026-08-03] 盘中实时结算价可能为 0（今日结算未产生 / 刚启动流未就绪）→ 回退 futures_daily
                        # 最近一条非零 AG0 结算价（即上一交易日官方结算价，盘中稳定不变，是"昨结算价"的正确基准；
                        # 实时流的今日结算价盘中恒为 0，不能当昨结算用）。仅在 SHFE 开盘时段有意义——非开盘时下面守卫会清零。
                        if settlement_price <= 0:
                            try:
                                _conn = self.db._get_conn()
                                _row = _conn.execute(
                                    "SELECT settle_price FROM futures_daily WHERE symbol='AG0' AND settle_price>0 ORDER BY date DESC LIMIT 1"
                                ).fetchone()
                                if _row and _row[0] and float(_row[0]) > 0:
                                    settlement_price = float(_row[0])
                                    logger.debug(f"[{code}] AG0 实时结算价为0，回退数据库昨结算={settlement_price}")
                            except Exception as _e:
                                logger.debug(f"[{code}] AG0 昨结算DB回退失败: {_e}")

                        # [2026-07-30 FIX] 非交易时段丢弃已取到的价格，避免陈旧收盘价当"实时"
                        if not _ag_session_open:
                            logger.debug(f"[{code}] SHFE 当前休市，丢弃 AG0 价(最新价={ag_future_price}/昨结算={settlement_price})，rt_val/si_val 置 None")
                            ag_future_price, settlement_price, vwap = 0.0, 0.0, 0.0

                        nav_home = float(metrics.get('nav', 0))
                        if ag_future_price > 0 and settlement_price > 0 and nav_home > 0:
                            # 🚀 为了让前端展示 AG0 盘口数据
                            metrics['ag0_price'] = ag_future_price
                            metrics['ag0_settlement'] = settlement_price
                            
                            # 参考估值 (rt_val) = 昨天净值 * (实时成交价 / 昨结算价)
                            rt_val = nav_home * (ag_future_price / settlement_price)
                            metrics['rt_val'] = round(rt_val, 4)
                            if metrics.get('price', 0) > 0:
                                metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                                
                            # 🚀 官方估值 (static_val) = 昨天净值 * (VWAP / 昨结算价)
                            # [AI-2026-08-21 FIX] 严禁 fallback 到 NAV：官方估值与 NAV 是"对比"关系(数字近但含义不同)，
                            # VWAP 缺失即视为无官方估值，留 None（前端显示"等待数据"），绝不用 NAV 冒充（违反 SUPREME 铁律）。
                            if vwap > 0:
                                metrics['static_val'] = round(nav_home * (vwap / settlement_price), 4)
                            else:
                                metrics['static_val'] = None

                        # [SI 实时估值] 基于 COMEX 白银期货的实时估值（和 Woody GetRealtimeNetValue 一致）
                        # [AI-2026-08-03] 仅在 SHFE 交易时段内计算：午休/休市已丢弃 AG0 价（见上守卫），此时不计算 SI 估值，
                        #              避免对"昨结算价为0"的误报警（非 Bug，是设计上非交易时段不出 AG0 衍生估值，与 rt_val 列一致）
                        if _ag_session_open and self.market_data_service:
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
                                    # [AI-2026-08-21 FIX] si_premium 改由下方实时溢价三件套用 realtime_price 统一重算
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
                        resolved_trade_etf = yaml_trade_etf or _normalize_empty_symbol(fund.get('related_index', ''))
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
                                # [AI-2026-07-23] QDII日本基金使用日元中间价
                                if category == 'QDII日本':
                                    current_fx = _daily_snapshot.get('jpy_cny_mid')
                                    if not current_fx or current_fx <= 0:
                                        logger.warning(f"[{code}] jpy_cny_mid 不可用，跳过实时估值")
                                else:
                                    current_fx = _daily_snapshot.get('usd_cny_mid')
                                # [V11.0] 在岸价基金：用快照里的在岸价（启动时已从新浪加载）
                                if code in _FUNDS_WITH_SPOT_RATE:
                                    spot_fx = _daily_snapshot.get('usd_cny_spot') or 0
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
                                    required_bases = set()
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
                                        required_bases.add(sym_base)
                                        # [AI-2026-07-07] 检查该组件对应的交易所今天是否开市
                                        # 有后缀的 → 查对应的区域交易所；无后缀的 → 美股(NYSE)
                                        ex = symbol_to_exchange(raw_sym)
                                        if ex and not is_trading_day(ex, now_dt.date()):
                                            logger.debug(f"[{code}] 跳过 {raw_sym}（{ex} 今日休市）")
                                            continue
                                        # [B1-2026-08-26] 优先复用预取的篮子成分价（已含新浪期货路径），绝不再触发新浪请求
                                        q = quotes_dict.get(sym_base) or self.market_data_service.get_realtime_quote(sym_base)
                                        # [AI-2026-07-20] 实时估值必须用买一价 bid，禁止用成交价 price（见 AGENTS.md 7.3.4）
                                        # [AI-2026-08-17] A股源 bid 为5档list，IB/FUTU 为标量 → 统一取买一价标量（bid[0]）
                                        if q:
                                            _q_bid = _scalar_level(q.get('bid'))
                                            _q_price = q.get('price')
                                            if _q_bid and _q_bid > 0:
                                                current_etfs[sym_base] = _q_bid
                                            elif _q_price:
                                                current_etfs[sym_base] = _q_price
                                    # [2026-07-30 FIX] 实时估值必须每个"去重基准标的"都有活价：
                                    # 区域后缀(^GLD-EU 等)会折叠到基础代码(GL D)取价，current_etfs 的 key 数恒等于去重基准数，
                                    # 故按"去重基准数"而非组合长度判定；否则含区域后缀的基金会因 key 数永远少于 portfolio 长度
                                    # 而误判缺价、永不显示实时估值。任一去重基准缺活价 → 视为无实时行情，保持 rt_val=None。
                                    if required_bases and len(current_etfs) < len(required_bases):
                                        _basket_missing_etf = True
                                        logger.debug(f"[{code}] 篮子组件缺活价({len(current_etfs)}/{len(required_bases)})，跳过实时估值，避免显示陈旧基准价")
                                
                                # 计算实时估值：仅当全部组件都有活价（_basket_missing_etf 未置位）才计算，
                                # 否则保持 rt_val=None → 前端显示 '-'，与实时沙盘页面一致，不把基准价当实时
                                if not _basket_missing_etf:
                                    res = calculator.calculate(fund_cfg, current_fx, current_etfs)
                                    val_res = res.get('rt_val') if res else None
                                    if val_res and val_res > 0:
                                        metrics['rt_val'] = round(val_res, 4)
                                        # 重新计算溢价率
                                        if metrics.get('price', 0) > 0:
                                            metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)

                            # [AI-2026-07-23] QDII日本基金：用 NK 期货 + 在岸价 做实时估值（Woody 公式）
                            if not metrics.get('rt_val') and category == 'QDII日本':
                                try:
                                    # 获取 NK 期货实时价（hf_NK）
                                    nk_quote = self.market_data_service.get_realtime_quote('NK') if self.market_data_service else None
                                    nk_price = nk_quote.get('bid') or nk_quote.get('price') if nk_quote else 0
                                    # 获取在岸价
                                    jpy_spot = _daily_snapshot.get('jpy_cny_spot') or 0
                                    # [AI-2026-07-27] 复用统一估值核心：取 T-1 基准(NAV+日元中间价)与 NK 结算价(基准)，NK期货价作单组件
                                    t1_row = conn.execute("""
                                        SELECT h.date, h.nav, COALESCE(r.jpy_cny_spot, r.jpy_cny_mid) AS fx_base
                                        FROM unified_fund_history h
                                        LEFT JOIN exchange_rate r ON h.date = r.date
                                        WHERE h.fund_code = ? AND h.nav > 0 AND (r.jpy_cny_spot > 0 OR r.jpy_cny_mid > 0)
                                        ORDER BY h.date DESC LIMIT 1
                                    """, (code,)).fetchone()
                                    nk_base_row = conn.execute(
                                        "SELECT settle_price FROM futures_daily WHERE symbol='NK' AND settle_price > 0 ORDER BY date DESC LIMIT 1"
                                    ).fetchone()
                                    if nk_price > 0 and jpy_spot > 0 and t1_row and nk_base_row:
                                        nav_base = float(t1_row[1])
                                        fx_base = float(t1_row[2])
                                        nk_base = float(nk_base_row[0])
                                        pos = float(fund.get('pos_ratio', 0.95))
                                        rt_val = basket_valuation(
                                            nav_base, pos,
                                            [{'symbol': 'NKY', 'current_price': nk_price,
                                              'base_price': nk_base, 'weight': 1.0}],
                                            fx_base, jpy_spot, hedge=None,
                                        )
                                        if rt_val is not None:
                                            metrics['rt_val'] = round(rt_val, 4)
                                            if metrics.get('price', 0) > 0:
                                                metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                                            logger.debug(f"[{code}] NK实时估值(备用源): nk={nk_price}, jpy={jpy_spot}, rt_val={rt_val:.4f}")
                                except Exception as e:
                                    logger.warning(f"[{code}] NK实时估值失败: {e}")

                            # 尝试用 trade_etf 备用源 [V10.8]
                            # basket为空时（如162411的XOP），直接用 trade_etf 获取实时ETF价格做 hedge 估值
                            # 放在 current_fx 条件外，让无basket基金也能走魔法公式
                            if not metrics.get('rt_val'):
                                trade_etf = fund_cfg.get('trade_etf', '')
                                if trade_etf and trade_etf != '-' and self.market_data_service:
                                    # [V10.9] 跳过指数类符号（HSI/HSTECH等），指数走 get_index_change_percent 路径
                                    from arbcore.config.source_routing import get_symbol_source
                                    # [AI-2026-08-05] HSCHK25 等未在 symbol_sources 声明的符号会抛 KeyError
                                    # 非兜底——确实无数据源，跳过实时ETF估值，前端显示 --
                                    try:
                                        _sym_src = get_symbol_source(trade_etf)
                                    except KeyError:
                                        _sym_src = None
                                    if _sym_src in ('SINA', None):
                                        pass  # 指数/无数据源符号不加入实时行情查询
                                    else:
                                        # [AI-2026-07-20] 实时估值用买一价 bid，无 bid 时降级用成交价 price
                                        try:
                                            q = self.market_data_service.get_realtime_quote(trade_etf)
                                            etf_price = 0
                                            # [AI-2026-08-17] 同 1847 模式：A股源 bid 为5档list，必须降标量为买一价，否则 q['bid']>0 抛 list>int
                                            if q:
                                                _trade_bid = _scalar_level(q.get('bid'))
                                                if _trade_bid and _trade_bid > 0:
                                                    etf_price = _trade_bid
                                                elif q.get('price') and q['price'] > 0:
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
                                                        spot_fx = _daily_snapshot.get('usd_cny_spot') or 0
                                                        fx = spot_fx if spot_fx > 0 else 0
                                                    else:
                                                        # current_fx 可能为空，从 base_data 补充(mid真值)
                                                        fx = current_fx if (current_fx and current_fx > 0) else float(base_data.get('exchange_rate', 0) or 0)
                                                    if b_nav > 0 and b_hedge > 0 and fx > 0:
                                                        # val = nav * (1 - pos) + (etf_price * fx) / hedge
                                                        val_res = b_nav * (1.0 - b_position) + (etf_price * fx) / b_hedge
                                                        if val_res > 0:
                                                            metrics['rt_val'] = round(val_res, 4)
                                                            if metrics.get('price', 0) > 0:
                                                                metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)
                                        except Exception as e:
                                            logger.warning(f"{code} trade_etf({trade_etf}) 实时行情获取失败: {e}")
                except Exception as e:
                    import traceback
                    logger.error(f"实时计算 {code} 估值失败: {e}\n{traceback.format_exc()}")

                # [V6.1] 备用源：如果实时计算失败（例如未连行情源，或美股休市无最新价），从采样表获取最近一次的记录
                if not metrics.get('rt_val') or metrics['rt_val'] <= 0:
                    # [AI-2026-07-06] 篮子基金ETF行情缺失时跳过stale兜底（INDA等低流动性场景）
                    if _basket_missing_etf:
                        # 篮子组件缺活价：实时估值无效，保持空（前端显示 '-'），不显示陈旧基准价
                        metrics['rt_val'] = None
                        metrics['rt_premium'] = None
                    else:
                        try:
                            sample_query = "SELECT date, rt_val, premium FROM fund_intraday_quotes WHERE fund_code=? ORDER BY date DESC, time DESC LIMIT 1"
                            sample_df = pd.read_sql(sample_query, conn, params=(code,))
                            if not sample_df.empty:
                                sample_date = str(sample_df.iloc[0]['date'])
                                today_str = datetime.now().strftime('%Y-%m-%d')
                                # [2026-07-30 FIX] 仅接受"当日"采样作实时备用源，防止展示陈旧历史快照
                                # （库里曾残留 6 周前的采样，会当成"实时估值"误导用户）
                                if sample_date != today_str:
                                    logger.debug(f"[{code}] 采样表最新记录({sample_date})非当日，跳过实时备用源")
                                    metrics['rt_val'] = None
                                    metrics['rt_premium'] = None
                                else:
                                    rv = sample_df.iloc[0]['rt_val']
                                    if rv is not None and float(rv) > 0:
                                        metrics['rt_val'] = float(rv)
                                        pm = sample_df.iloc[0]['premium']
                                        metrics['rt_premium'] = float(pm) if pm is not None else 0
                                    else:
                                        metrics['rt_val'] = None
                                        metrics['rt_premium'] = None
                            else:
                                metrics['rt_val'] = None
                                metrics['rt_premium'] = None
                        except Exception as e:
                            logger.error(f"从采样表获取 {code} 历史记录失败: {e}")
                            metrics['rt_val'] = None
                            metrics['rt_premium'] = None

                # 3. [V4.0] 灵魂逻辑重算 (确保静态溢价率和涨跌幅不为 0)
                cp = float(metrics.get('price') or 0)
                sv = float(metrics.get('static_val') or 0)
                _pc_raw = metrics.get('prev_close')
                pc = float(_pc_raw) if _pc_raw else None

                # [AI-2026-08-07] 缺失昨收(prev_close)时 price_change 显 None → 前端显 --，禁止用 0 掩盖
                if cp > 0 and pc is not None and pc > 0:
                    metrics['price_change'] = (cp / pc - 1) * 100
                else:
                    metrics['price_change'] = None

                # [AI-2026-08-21 FIX] static_premium 用 DB 官方收盘价(cp) 作分子，
                #   与 rt_premium(用 realtime_price) 区分，避免分母错位：
                #   - static_premium = cp / static_val - 1（官方收盘 vs 官方估值）✅
                #   - rt_premium = rt_p / rt_val - 1（实时价 vs 实时估值）✅
                #   原错误写法用 realtime_price 作 static_premium 分子，导致盘中错乱、盘后为 None。
                rt_p = metrics.get('realtime_price')
                if cp > 0 and sv > 0:
                    metrics['static_premium'] = (cp / sv - 1) * 100
                if rt_p and rt_p > 0 and metrics.get('rt_val') and metrics['rt_val'] > 0:
                    metrics['rt_premium'] = round((rt_p / metrics['rt_val'] - 1) * 100, 3)
                if rt_p and rt_p > 0 and metrics.get('si_val') and metrics['si_val'] > 0:
                    metrics['si_premium'] = round((rt_p / metrics['si_val'] - 1) * 100, 3)

                # 4. [V4.0] 精度规范：现价3位、溢价率3位、涨跌幅2位
                # 先创建 fund_dict 用于存储基金数据
                fund_dict = fund.to_dict()
                fund_dict.update(metrics)

                # [AI-2026-08-17] rt_val 为空且基金实时估值依赖 FUTU 行情源、而本地 FUTU 未连接 →
                #   标记 rt_unavailable='FUTU'，前端主看板据此显示「缺FUTU」(而非笼统 '-')，明确是源未连而非无数据。
                #   仅 futu_reader.disabled 才标记：若 FUTU 已连(如接 OpenD)但盘后无行情，rt_val=None 属正常，仍显示 '-'。
                if metrics.get('rt_val') is None and _fund_requires_futu(code, basket_symbols_by_fund, fund):
                    _fr = getattr(self.market_data_service, 'futu_reader', None)
                    if _fr is not None and getattr(_fr, 'disabled', False):
                        fund_dict['rt_unavailable'] = 'FUTU'

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

                _vf_ms = int((time.perf_counter() - _vf_start) * 1000)  # [埋点A] 逐基金耗时
                if _vf_ms >= 500:
                    logger.warning("[VAL-PER-FUND] code=%s cat=%s took=%dms", code, category, _vf_ms)
                else:
                    logger.debug("[VAL-PER-FUND] code=%s cat=%s took=%dms", code, category, _vf_ms)

                result.append(fund_dict)

            # [2026-07-31] ① 盘中持续缓存最后有效估值 → ② 收盘后冻结/回退覆盖 live 值并标记 rt_frozen
            # [AI-2026-08-25] 盘后兜底：若今天官方收盘价未入库（price=NULL），先补齐再冻结/缓存，
            # 防止前端用昨天收盘当"现价"。幂等——已写则 _step4_fetch_prices 内部跳过。
            try:
                self._ensure_today_close_price()
            except Exception as e:
                logger.warning(f"[盘后兜底] 获取今天收盘价失败(不影响其他): {e}")
            try:
                update_rt_cache(result)
            except Exception as e:
                logger.warning(f"[FREEZE] 更新估值缓存失败: {e}")
            try:
                apply_freeze_to_dashboard(result)
            except Exception as e:
                logger.error(f"[FREEZE] 应用冻结值失败: {e}")

            logger.debug(f"Dashboard数据生成完成，共 {len(result)} 只基金")
            _prof['valuation_done'] = _t.perf_counter()  # [埋点A] 估值循环段结束
            _elapsed = lambda a, b: int((_prof[b] - _prof[a]) * 1000)
            logger.info(
                "[DASHBOARD-PROFILE] cat=%s codes=%d total=%dms | "
                "db_read=%dms prefetch_index=%dms realtime_quotes=%dms valuation_loop=%dms",
                category or 'watchlist', len(codes),
                _elapsed('start', 'valuation_done'),
                _elapsed('start', 'db_read'),
                _elapsed('db_read', 'prefetch_index'),
                _elapsed('prefetch_index', 'realtime_quotes'),
                _elapsed('realtime_quotes', 'valuation_done'),
            )
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

    def _ensure_today_close_price(self) -> None:
        """[AI-2026-08-20] 盘后兜底：时间 ≥15:00 且今天 price 仍为 NULL 时，
        调 daily_updater 立刻写今天收盘价。
        解决主看板盘后显示"昨天收盘"的问题。

        [AI-2026-08-26] 防子进程风暴：dashboard 分分类串行计算时，每个分类都会调用本方法，
        只要今天仍有 price IS NULL 的行就会 spawn 一个 _step4_fetch_prices 子进程，
        多个分类并发 = 多个子进程同时抢 SQLite 写锁（WAL 排队），全部变慢/超时后下一轮又起新的，
        曾实测 8 进程并发拖垮 1 核机器（2026-08-26 22:33）。加非阻塞锁：已有兜底在跑则跳过本轮。
        """
        if datetime.now().hour < 15:
            return
        # [AI-2026-08-26] 非阻塞锁：已有兜底子进程在跑（含 120s 窗口）则本轮跳过
        if not self._ensure_close_lock.acquire(blocking=False):
            logger.debug("[盘后兜底] 已有兜底子进程在跑，跳过本轮")
            return
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            conn = self.db._get_conn()
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM unified_fund_history WHERE date=? AND price IS NULL",
                    (today,)
                ).fetchone()[0]
                if count == 0:
                    return
            finally:
                try:
                    conn.close()
                except:
                    pass
            # [AI-2026-08-20] 调 daily_updater 写今天收盘价（幂等，已写则跳过）
            import subprocess, os
            scripts_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scheduler')
            script_path = os.path.join(scripts_dir, 'daily_updater.py')
            python_exe = sys.executable
            # 用 -c 调用，只跑 _step4_fetch_prices
            code = f"""
import sys
sys.path.insert(0, r'{scripts_dir}')
from daily_updater import DailyUpdater
DailyUpdater()._step4_fetch_prices()
"""
            subprocess.run([python_exe, '-c', code], capture_output=True, timeout=120)
            logger.info(f"✅ [盘后兜底] 今日收盘价写入完成，共 {count} 只基金")
        except Exception as e:
            logger.warning(f"⚠️ [盘后兜底] 写入今天收盘价失败: {e}")
        finally:
            self._ensure_close_lock.release()

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
                   h.index_close, h.index_pct, h.shares, h.shares_added, h.trade_volume, h.turnover_rate, h.volume,
                   h.valuation_error,
                    r.usd_cny_mid, r.hkd_cny_mid, r.jpy_cny_mid,
                    f.hedge, f.position
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

            # [AI-2026-08-06] 修复：新增份额须基于【相邻交易日】差值；
            # 中间日缺失(如 VPS 漏采)时显式留空，禁止跨日兜底造出假差值。
            # df 按 date DESC，改为升序后用 shift(1) 取严格前一日，仅当前一日有值且间隔<=4天才算。
            if 'shares' in df.columns:
                _asc = df.sort_values('date')
                _prev = _asc['shares'].shift(1)
                _gap = (pd.to_datetime(_asc['date']) - pd.to_datetime(_asc['date'].shift(1))).dt.days
                _calc = (_asc['shares'] - _prev).where(_prev.notna() & (_gap <= 4))
                _asc['shares_added'] = _calc
                df['shares_added'] = _asc['shares_added']

            # [2026-07-30] 换手率（与 woody 网页对齐，彻底修正此前用成交额错算）
            #   成交量(份) = trade_volume(手) × 100，份额(份) = shares(万) × 10000
            #   换手率% = 成交量(份)/份额(份) × 100 = trade_volume(手) / shares(万)
            #   新增换手% = trade_volume(手) / shares_added(万)（仅当场内新增>0 才有意义，否则 woody 留空）
            if 'trade_volume' in df.columns and 'shares' in df.columns:
                tv = pd.to_numeric(df['trade_volume'], errors='coerce')
                sh = pd.to_numeric(df['shares'], errors='coerce')
                rate = tv / sh
                df['turnover_rate'] = rate.where((tv > 0) & (sh > 0))

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

            # [AI-2026-08-21] 白银基金：获取 AG0 结算价历史，供历史弹窗"结算价"列
            # 结算价是白银估值分母，来自 futures_daily.symbol='AG0'（DB 权威，不回填不兜底）
            ag0_settle_map = {}
            try:
                _cat_row = conn.execute("SELECT category FROM unified_fund_list WHERE fund_code=?", (fund_code,)).fetchone()
                _cat = _cat_row[0] if _cat_row else ''
                if _cat == '白银':
                    _ag0_rows = conn.execute(
                        "SELECT date, settle_price FROM futures_daily WHERE symbol='AG0' AND settle_price IS NOT NULL AND settle_price>0 ORDER BY date DESC"
                    ).fetchall()
                    _prices = {r[0]: r[1] for r in _ag0_rows}
                    _ds = sorted(_prices.keys(), reverse=True)
                    for i in range(len(_ds) - 1):
                        _dc, _dp = _ds[i], _ds[i + 1]
                        if _prices[_dp] and _prices[_dp] > 0 and _prices[_dc] and _prices[_dc] > 0:
                            ag0_settle_map[_dc] = {'settle': _prices[_dc], 'chg': round((_prices[_dc] / _prices[_dp] - 1) * 100, 4)}
                    if _ds:
                        ag0_settle_map[_ds[-1]] = {'settle': _prices[_ds[-1]], 'chg': None}
            except Exception as e:
                logger.warning(f"[FundHistory] 获取AG0结算价失败 {fund_code}: {e}")

            # [AI-2026-07-21] 获取该基金跟踪的ETF历史价格
            # 单主ETF基金（如162411→XOP）显示净值（netvalue），列名"XOP净值"
            # 多篮子基金（如161116→GLD+^GLD-EU）显示价格（price），列名"GLD价格/^GLD-EU价格"
            yaml_trade_etf = _YAML_TRADE_ETF.get(fund_code, '')
            etf_price_map = {}  # {symbol: {date: {price, chg}}}
            is_single_etf = False  # 异常保护，避免 UnboundLocalError
            col_name = 'price'
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

                # 判断：单主ETF（有yaml_trade_etf且仅此一个symbol）且【无篮子权重表】→ 显示净值；否则显示价格
                # [AI-2026-07-29] 修复164701误判：164701篮子仅GLD=100%(SLV权重0未入库)，且 related_index/trade_etf 恰为GLD，
                #   导致 etf_symbols=['GLD'] 被当成单ETF→显示"GLD净值"。但164701本质是有篮子表的基金，应按多篮子显示"GLD价格"。
                #   故加 has_basket 约束：凡 fund_basket_weights 有记录者一律视为多篮子→取价格（与 dynamic_valuation 口径一致）。
                has_basket = conn.execute("SELECT COUNT(*) FROM fund_basket_weights WHERE fund_code=?", (fund_code,)).fetchone()[0] > 0
                is_single_etf = (not has_basket) and bool(yaml_trade_etf) and len(etf_symbols) == 1 and etf_symbols[0] == yaml_trade_etf
                col_name = 'netvalue' if is_single_etf else 'price'

                # 3) 逐个查询
                for sym in etf_symbols:
                    etf_rows = conn.execute(
                        f"SELECT date, {col_name} FROM usa_etf_daily_prices WHERE symbol=? AND {col_name} IS NOT NULL AND {col_name} > 0 ORDER BY date DESC",
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

            # [2026-07-30] 构建 per-symbol 的 date->weight 映射，供历史行附加 {sym}_weight 列（权重以百分比存储）
            # 部分日期可能缺失篮子权重行（同步间隙），lookup_weight 回退到"该标的最近一个 <= 该日期"的权重
            weight_by_sym = {}
            try:
                wrows = conn.execute(
                    "SELECT date, underlying_symbol, weight FROM fund_basket_weights WHERE fund_code=?",
                    (fund_code,)
                ).fetchall()
                for wd, wsym, wval in wrows:
                    if wval is not None:
                        weight_by_sym.setdefault(wsym, {})[str(wd)[:10]] = float(wval)
            except Exception as e:
                logger.warning(f"[FundHistory] 读取篮子权重失败 {fund_code}: {e}")

            def lookup_weight(row_date: str, sym: str):
                dmap = weight_by_sym.get(sym)
                if not dmap:
                    return None
                if row_date in dmap:
                    return dmap[row_date]
                cand = [d for d in dmap if d <= row_date]
                if cand:
                    return dmap[max(cand)]
                return None

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
                            # [2026-07-30] 附加该底层标的当日权重（百分比），供历史页 "标的权重" 列显示（缺失日回退最近权重）
                            w = lookup_weight(row_date, etf_sym)
                            if w is not None:
                                item[f'{etf_sym}_weight'] = round(w, 4)

                # [AI-2026-08-21] 白银：附加 AG0 结算价（历史弹窗"结算价"列）
                if ag0_settle_map:
                    row_date = str(item.get('date', ''))[:10]
                    _ag0 = ag0_settle_map.get(row_date)
                    if _ag0:
                        item['ag0_settle'] = _ag0['settle']
                        item['ag0_settle_chg'] = _ag0['chg']

                item['is_single_etf'] = is_single_etf
                data_list.append(item)

            # [AI-2026-08-21] 历史对账页不展示"今天"这一行：
            # 今天行 nav/price 多数为 NULL（盘中未收盘），且白银今天行 AG0 结算价实为昨结算，显示会误导。
            # 东哥明确：历史记录页不需要今天行（其他基金今天行全空、视觉上本就无此行）。
            # 顶部全局汇率走 get_market_overview，不依赖本接口 today 行，故过滤安全。
            data_list = [x for x in data_list if str(x.get('date', ''))[:10] != today]

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

    def get_fund_intraday(self, fund_code: str, date: str = None, days: int = 1) -> List[Dict[str, Any]]:
        """获取基金分时数据（支持多日）
        - date: 基准日期（默认今天），days: 向前回溯天数
        - 返回按时间排序的多日数据，X轴使用连续时间戳
        - 包含 open_premium/close_premium（真实盘口计算）
        """
        if not date: date = pd.Timestamp.now().strftime('%Y-%m-%d')
        conn = self.db._get_conn()
        try:
            # 计算起始日期
            start_date = (pd.Timestamp(date) - pd.Timedelta(days=days-1)).strftime('%Y-%m-%d')
            query = """SELECT date, time, price, rt_val, premium, open_premium, close_premium,
                              lof_bid1, lof_ask1, etf_bid1, etf_ask1
                       FROM fund_intraday_quotes
                       WHERE fund_code = ? AND date >= ?
                       ORDER BY date ASC, time ASC"""
            df = pd.read_sql(query, conn, params=(fund_code, start_date))
            if df.empty:
                return []
            # 转换为时间戳X轴格式：MM-DD HH:MM
            df['display_time'] = df['date'] + ' ' + df['time']
            return df[['display_time', 'price', 'rt_val', 'premium', 'open_premium', 'close_premium',
                      'lof_bid1', 'lof_ask1', 'etf_bid1', 'etf_ask1']].to_dict(orient='records')
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
            # 名字推断仅作补充（原油→CL / 金→GC / 白银→AG0）。
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
            # [AI-2026-07-29] valuation_method 改从主 YAML(lof_config.yaml) 读取（单一真相源），
            # 空串经 resolve_method 按 category 补充；前端 isQDIIJapan 已改为读 category，不再依赖此值
            _yaml_fund_cfg = self.config_service.get_fund_config(code) or {} if self.config_service else {}
            _raw_method = _yaml_fund_cfg.get('valuation_method') or ''
            _method = _raw_method if _raw_method else resolve_method('', f_row[3] if len(f_row) > 3 else '')
            fund_cfg = {
                "code": code,
                "trade_etf": _YAML_TRADE_ETF.get(code) or _normalize_empty_symbol(f_row[1]),
                "position": float(f_row[2] or 0.95) * 100,
                "trade_future": trade_future,
                "valuation_method": _method,
                "category": f_row[3] if len(f_row) > 3 else ''
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

            # [AI-2026-07-23] 根据基金类别选择汇率字段
            meta_cat_df = pd.read_sql("SELECT category FROM unified_fund_list WHERE fund_code=?", conn, params=(code,))
            meta_category = str(meta_cat_df.iloc[0]['category']).strip() if not meta_cat_df.empty else ''
            if meta_category == 'QDII日本':
                fx_df = pd.read_sql("SELECT jpy_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
                latest_fx = float(fx_df.iloc[0]['jpy_cny_mid']) if not fx_df.empty else 4.16
            else:
                fx_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
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

            # [V10.8] basket为空时用 trade_etf 备用源获取行情（如162411→XOP）
            if not etf_symbols:
                trade_etf = fund_cfg.get('trade_etf', '')
                if trade_etf and trade_etf != '-':
                    # [V10.9] 跳过指数类符号（HSI/HSTECH/399300等），指数无可用的实时行情
                    from arbcore.config.source_routing import get_symbol_source
                    # [AI-2026-08-05] HSCHK25 等未声明数据源的符号抛 KeyError → 跳过（非兜底）
                    try:
                        _sym_src = get_symbol_source(trade_etf)
                    except KeyError:
                        _sym_src = None
                    if _sym_src in ('SINA', None):
                        pass  # 指数/无数据源符号不加入实时行情查询
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
                            # [AI-2026-08-17] realtime_quotes 透传：A股源 bid/ask 为5档list，估值路径统一取买一/卖一标量
                            'bid': _scalar_level(q.get('bid')),
                            'ask': _scalar_level(q.get('ask')),
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

                    # 如果没有独立校准值，查找全局期货校准值补充
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
                    # [AI-2026-08-17] 防御: base_data 偶发含 numpy array / pandas Series
                    # (如 164824 某些字段)，pd.isna(array) 会返回布尔数组，直接 if 判断即抛
                    # "truth value of an array is ambiguous"。先降维为标量或 list 再格式化，
                    # 避免整个 valuation_meta 崩溃导致该基金盘口全显示"等待行情"。
                    # [AI-2026-08-17] 普通 list/tuple（如 _basket 篮子权威注入）直接保留，
                    # 不进 pd.isna 判真值（这正是 164824 报错根因：`pd.isna(list)` 返回数组）；
                    # list 本身 JSON 可序列化，原样传给前端即可。
                    if isinstance(v, (list, tuple)):
                        formatted_base_data[k] = list(v)
                        continue
                    if isinstance(v, (np.ndarray, pd.Series)):
                        try:
                            if getattr(v, 'size', 0) == 1:
                                v = v.item()
                            else:
                                formatted_base_data[k] = [
                                    None if pd.isna(x) else (float(x) if isinstance(x, (np.integer, np.floating, float, int)) else str(x))
                                    for x in v
                                ]
                                continue
                        except Exception:
                            v = str(v)
                    if pd.isna(v):
                        formatted_base_data[k] = None
                    elif isinstance(v, (np.integer, int)):
                        formatted_base_data[k] = int(v)
                    elif isinstance(v, (np.floating, float)):
                        formatted_base_data[k] = float(v)
                    else:
                        formatted_base_data[k] = str(v)

            # [AI-2026-07-23] QDII日本基金：添加 NK 结算价（用于纯期货估值）
            # 注意：bd.calibration 是对冲值（~137081），不是 NK 结算价！
            if meta_category == 'QDII日本':
                try:
                    nk_settle_row = conn.execute(
                        "SELECT settle_price FROM futures_daily WHERE symbol='NK' AND settle_price > 0 ORDER BY date DESC LIMIT 1"
                    ).fetchone()
                    if nk_settle_row:
                        formatted_base_data['nk_settle_price'] = float(nk_settle_row[0])
                except Exception:
                    pass

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
        # [AI-2026-07-25] 容错：fund_watchlist 表不存在（旧库/全新环境未建表）或查询异常时，
        #                  降级返回全部基金，杜绝其他用户运行时的 no such table 报错。
        except Exception as e:
            logger.warning(f"[Snapshot] fund_watchlist 查询失败({e})，降级采样所有基金")
            try:
                cur = conn.execute("SELECT fund_code FROM unified_fund_list ORDER BY fund_code")
                return [row[0] for row in cur.fetchall()]
            except Exception:
                return []
        finally:
            conn.close()
