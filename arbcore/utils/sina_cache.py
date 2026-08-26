"""
新浪行情合并抓取器（Plan C — 根治首屏几十秒）
================================================

问题根因（见 docs/002_3 事件循环阻塞陷阱专项 第九节）：
    原代码在估值循环 / 指数抓取 / 期货盘口等处，对每只标的单独调用
    `_throttle_sina_request()`（进程级全局 3 秒节流锁）+ 单独 GET。
    新浪节流锁是全局串行的，N 次调用被堆叠成 N×3 秒，叠加 7 条快照循环
    并发 → 首屏实测 30~315 秒。

方案（合并批量 + 缓存）：
    - 进程级 TTL 缓存（3s，与节流窗口一致）：symbol -> (ts, raw)
    - 跨调用合并(coalesce)：同一节流窗口(3s)内的多次 get_sina_quotes 调用，
      合并为「一次批量 GET（list=A,B,C）」，所有调用方只读缓存。
    - 负缓存：本次批量请求但未返回（无行情）的 symbol，TTL 内不再重抓，
      避免对恒为空标的（如 hf_MGC）反复打新浪。
    - 强制 IPv4（根治 IPv6 半通挂死，见 docs/002_3 第九节 B3）。
    - 单一全局节流（复用 arbcore.utils.sina_throttle，与历史调用同源）。
    - 返回 {symbol: raw_content}，调用方按原有格式自行解析。

效果：首屏从几十秒压到约 1~2 个节流窗口（3~6 秒）。
"""
import time
import re
import threading
import logging
import requests

from arbcore.utils.sina_throttle import throttle_sina_request as _throttle

logger = logging.getLogger(__name__)

_TTL = 3.0                         # 缓存有效期，与节流窗口一致
_CACHE: dict = {}                 # symbol -> (ts, raw_content)
_PENDING: set = set()             # 跨调用合并的待抓取 symbol
_LOCK = threading.Lock()
_FETCHING = False
_LAST_FETCH_TS = 0.0
_FETCH_EVENT = threading.Event()


class _ForceIPv4Adapter(requests.adapters.HTTPAdapter):
    """临时覆盖 getaddrinfo 强制 IPv4（保留 SNI/Host 头），根治 IPv6 半通挂死。"""
    def send(self, request, **kwargs):
        import socket as _socket
        _orig = _socket.getaddrinfo

        def _ipv4_only(*a, **kw):
            return [r for r in _orig(*a, **kw) if r[0] == _socket.AF_INET]

        _socket.getaddrinfo = _ipv4_only
        try:
            return super().send(request, **kwargs)
        finally:
            _socket.getaddrinfo = _orig


_session = requests.Session()
_session.mount("http://", _ForceIPv4Adapter())
_session.mount("https://", _ForceIPv4Adapter())
_session.proxies.update({"http": None, "https": None})
_HEADERS = {'Referer': 'https://finance.sina.com.cn/'}


def get_sina_quotes(symbols, timeout=5.0) -> dict:
    """批量取新浪行情，进程级合并 + TTL 缓存。

    Args:
        symbols: 新浪 symbol 列表，如
                 ['s_sh000001', 's_sz399001', 'rt_hkHSI', 'int_nikkei',
                  'hf_GC', 'hf_NK', 'nf_AG0', 'fx_susdcny']
    Returns:
        {symbol: raw_content}；未取到（无行情 / 超时 / 网络错）的 symbol 不在返回中。
        raw_content 为 hq.sinajs.cn 响应里引号内的逗号串（与历史解析格式一致）。
    """
    global _FETCHING
    if not symbols:
        return {}
    wanted = list(dict.fromkeys(symbols))  # 去重保序
    deadline = time.time() + 2 * _TTL + 1.0  # 总时限 ~7s：最多多等/补抓一个窗口
    result = {}

    while True:
        now = time.time()
        missing = []
        with _LOCK:
            for s in wanted:
                e = _CACHE.get(s)
                if e and now - e[0] < _TTL:
                    result[s] = e[1]
                else:
                    missing.append(s)
                    _PENDING.add(s)
        if not missing:
            return result
        if time.time() > deadline:
            return result  # 尽力而为：命中的照常返回，未命中交由调用方兜底

        # 决策：本窗口是否立即抓取（仅一个线程执行实际网络请求）
        do_fetch = False
        with _LOCK:
            if not _FETCHING and (time.time() - _LAST_FETCH_TS) >= _TTL:
                do_fetch = True
                _FETCHING = True
        if do_fetch:
            try:
                _fetch_now(timeout)
            finally:
                with _LOCK:
                    _FETCHING = False
            # 回到循环顶部重读缓存；仍缺的（如本线程抓取期间才加入的"后来者"）
            # 会在窗口过期后由本函数自行补抓，不再像旧版那样直接返回空导致间歇丢数据
        else:
            # 等待当前抓取者完成；醒来后回到循环顶部重新决策：
            # 若仍缺且节流窗口已过 → 自己发起补抓（修复竞态饿死）
            _FETCH_EVENT.wait(timeout=_TTL + 2.0)


def _fetch_now(timeout):
    global _LAST_FETCH_TS
    with _LOCK:
        batch = list(_PENDING)
        _PENDING.clear()
    if not batch:
        return
    _FETCH_EVENT.clear()
    _throttle()  # 全局 3 秒节流（仅此处真正打新浪）
    url = "http://hq.sinajs.cn/list=" + ",".join(batch)
    found = set()
    try:
        r = _session.get(url, headers=_HEADERS, timeout=timeout)
        r.encoding = 'gbk'
        if r.status_code == 200:
            for m in re.finditer(r'var hq_str_(\w+)="([^"]*)"', r.text):
                sym, raw = m.group(1), m.group(2)
                found.add(sym)
                with _LOCK:
                    _CACHE[sym] = (time.time(), raw)
    except Exception as e:
        logger.warning(f"[SINA-CACHE] 批量请求失败: {e}")
    finally:
        ts = time.time()
        # 负缓存：本次请求但未返回（无行情）的 symbol，TTL 内不再重抓
        with _LOCK:
            for s in batch:
                if s not in found:
                    _CACHE[s] = (ts, '')
        _LAST_FETCH_TS = ts
        _FETCH_EVENT.set()
