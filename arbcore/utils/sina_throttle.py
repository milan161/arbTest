# -*- coding: utf-8 -*-
"""
[AI-2026-08-21] 新浪请求节流工具

所有调用 hq.sinajs.cn 的模块应使用此工具的 throttle_request() 函数，
确保距上次新浪请求至少间隔 15 秒，避免被反爬封IP。

使用方式：
    from arbcore.utils.sina_throttle import throttle_sina_request
    throttle_sina_request()
    # 然后发起 requests.get(...)
"""
import time
import logging
import threading

logger = logging.getLogger(__name__)

_SINA_THROTTLE_INTERVAL = 15.0
_last_request_time = 0.0
_request_lock = threading.Lock()


def throttle_sina_request():
    """等待直到距上次新浪请求超过15秒，然后更新最后请求时间"""
    global _last_request_time
    with _request_lock:
        elapsed = time.time() - _last_request_time
        if elapsed < _SINA_THROTTLE_INTERVAL:
            wait_time = _SINA_THROTTLE_INTERVAL - elapsed
            logger.debug(f"[SINA-THROTTLE] 等待 {wait_time:.1f}s 以遵守15秒间隔限制")
            time.sleep(wait_time)
            _last_request_time = time.time()
        else:
            _last_request_time = time.time()
