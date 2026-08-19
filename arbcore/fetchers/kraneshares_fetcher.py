# -*- coding: utf-8 -*-
"""
KraneShares ETF 净值获取器

通过 KraneShares 官方 premium-discount API 获取每日溢价率，
结合 Yahoo 收盘价反推真实净值：
    nav = close_price / (1 + premium_ratio)

数据来源：https://kraneshares.com/product-json/

覆盖符号：KWEB (pid=7615), KSTR (pid=8340)
参考：woody/php/stock/kraneshares.php

[AI-2026-08-18] 新增，解决 164906 详情页 base_price=None 问题
"""

import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# KWEB pid=7615, KSTR pid=8340（来自 woody/php/stock/kraneshares.php）
_KRANE_PID = {
    'KWEB': 7615,
    'KSTR': 8340,
}

_KRANE_URL = 'https://kraneshares.com/product-json/'
_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Referer': 'https://kraneshares.com/',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
}


def fetch_krane_premium(symbol: str, date: str) -> Optional[float]:
    """
    从 KraneShares API 获取指定日期的溢价率（小数，如 -0.0027 表示 -0.27%）。

    Args:
        symbol: ETF 符号（KWEB / KSTR）
        date: 日期字符串 YYYY-MM-DD

    Returns:
        溢价率（float），失败返回 None
    """
    pid = _KRANE_PID.get(symbol.upper())
    if not pid:
        logger.warning(f"[KraneShares] 未知符号: {symbol}")
        return None

    url = f"{_KRANE_URL}?pid={pid}&type=premium-discount&start={date}&end={date}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"[KraneShares] 获取 {symbol}@{date} 失败: {e}")
        return None

    if not data or not isinstance(data, list) or len(data) == 0:
        logger.warning(f"[KraneShares] {symbol}@{date} 无数据")
        return None

    # 格式: [[timestamp_ms, premium_ratio], ...]
    ts_ms, premium = data[0]
    # 验证日期匹配（防止跨时区偏移）
    dt = datetime.fromtimestamp(ts_ms / 1000).strftime('%Y-%m-%d')
    if dt != date:
        logger.warning(
            f"[KraneShares] {symbol}@{date} 日期不匹配: API返回 {dt}"
        )
        return None

    return float(premium)


def fetch_kraneshares_nav(
    symbol: str,
    close_price: float,
    date: str,
) -> Optional[float]:
    """
    根据收盘价和溢价率反推净值。

    nav = close_price / (1 + premium_ratio)

    Args:
        symbol: ETF 符号
        close_price: 当日收盘价（来自 Yahoo/新浪）
        date: 日期字符串 YYYY-MM-DD

    Returns:
        净值（float），失败返回 None
    """
    if close_price <= 0:
        logger.warning(f"[KraneShares] {symbol}@{date} close_price={close_price} 无效")
        return None

    premium = fetch_krane_premium(symbol, date)
    if premium is None:
        return None

    nav = close_price / (1.0 + premium)
    logger.info(
        f"[KraneShares] {symbol}@{date}: close={close_price}, "
        f"premium={premium*100:+.4f}%, nav={nav:.4f}"
    )
    return nav


def fetch_kraneshares_nav_range(
    symbol: str,
    close_prices: dict,
    start_date: str,
    end_date: str,
) -> list:
    """
    批量获取指定日期范围内的净值。

    Args:
        symbol: ETF 符号
        close_prices: {date_str: close_price} 从 Yahoo/新浪已采集的数据
        start_date: 起始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD

    Returns:
        [{date, symbol, netvalue}, ...] 成功记录的列表
    """
    results = []
    d = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    while d <= end:
        date_str = d.strftime('%Y-%m-%d')
        close = close_prices.get(date_str)
        if close and close > 0:
            nav = fetch_kraneshares_nav(symbol, close, date_str)
            if nav is not None and nav > 0:
                results.append({
                    'date': date_str,
                    'symbol': symbol,
                    'netvalue': nav,
                })
        d += timedelta(days=1)

    return results
