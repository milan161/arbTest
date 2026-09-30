#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UBS CMCI Oil SF USD (OILUSA) 每日收盘价采样器。
每天纽约时间 16:30 触发（美股收盘后），抓取最新收盘价，落库并推 Telegram 通知。

数据源：Yahoo Finance API (OILUSA.SW)
注意：OILUSA 在瑞士 SIX 交易所交易，Yahoo timestamp 有偏移，需特殊处理。

关键发现：
- bar 的 NY_local 时间 + 1天 = 实际交易日期
- 例如 bar[3] NY_local=2026-09-24 03:00，推断交易日期=2026-09-25（错误！）
- 实际上 bar[3] 对应的是 9-24 的交易数据（O=73.24 H=75.12 L=73.24 C=75.12）
- bar[4] NY_local=2026-09-25 03:00，对应的是 9-25 的交易数据（但 close=None）
- regularMarketPrice=73.91 是 9-25 的收盘价（市场已收盘后）

正确逻辑：
- 当 market 已收盘且 regularMarketPrice 可用时，用它作为收盘价
- OHLC 从对应的 bar 获取（bar 的 NY_local = trade_date）
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ---------- 配置 ----------
DEFAULT_DB = "/home/ubuntu/arbtest/database/arb_master.db"
LOG_DIR = "/home/ubuntu/arbtest/logs"
LOG_FILE = os.path.join(LOG_DIR, "oil_eod.log")
SYMBOL = "OILUSA"
SRC = "yahoo"
# 凭据一律走环境变量，绝不硬编码（本文件会进公开仓库）
# ARM 运行时由 systemd unit 的 Environment= 提供；缺失时静默跳过通知，不影响落库
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------- 时区 ----------
try:
    from zoneinfo import ZoneInfo
    NY_TZ = ZoneInfo("America/New_York")
except Exception:
    NY_TZ = None

def ny_now():
    """返回当前纽约时间。"""
    if NY_TZ is not None:
        return datetime.now(NY_TZ)
    # 回退：EDT = UTC-4
    return datetime.now(timezone(timedelta(hours=-4)))

# ---------- 数据库 ----------
CREATE_EOD_SQL = """
    CREATE TABLE IF NOT EXISTS futures_eod_prices (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_date  TEXT NOT NULL,
        symbol      TEXT NOT NULL,
        open        REAL,
        high        REAL,
        low         REAL,
        close       REAL,
        volume      INTEGER,
        src         TEXT NOT NULL DEFAULT 'yahoo',
        fetched_at  TEXT NOT NULL,
        UNIQUE(trade_date, symbol)
    )
"""

def write_eod(db_path: str, trade_date: str, row: dict) -> int:
    """写入 EOD 价格。返回行数。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(CREATE_EOD_SQL)
        conn.execute(
            """
            INSERT INTO futures_eod_prices
                (trade_date, symbol, open, high, low, close, volume, src, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(trade_date, symbol) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close, volume=excluded.volume, src=excluded.src, fetched_at=excluded.fetched_at
            """,
            (
                trade_date, SYMBOL,
                row.get("open"), row.get("high"), row.get("low"), row.get("close"),
                row.get("volume"), SRC, row["fetched_at"],
            ),
        )
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0]
    finally:
        conn.close()

def _num_or_none(v):
    """Yahoo 未完成/停牌 bar 的字段可能为 None；统一转 float|None，杜绝 float(None) 崩溃。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def fetch_oilusa() -> dict | None:
    """从 Yahoo Finance API 获取 OILUSA 最新收盘价。
    
    关键逻辑：
    1. bar 的 NY_local = trade_date（直接用，不+1天）
    2. 当 market 已收盘，使用 regularMarketPrice 作为收盘价
    3. OHLC 从对应的 bar 获取
    """
    try:
        req = urllib.request.Request(
            "https://query2.finance.yahoo.com/v8/finance/chart/OILUSA.SW?interval=1d&range=5d",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        result = data["chart"]["result"][0]
        meta = result["meta"]
        ts = result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
        opens = result["indicators"]["quote"][0]["open"]
        highs = result["indicators"]["quote"][0]["high"]
        lows = result["indicators"]["quote"][0]["low"]
        volumes = result["indicators"]["quote"][0]["volume"]

        now_ny = ny_now()
        
        # Meta 数据
        prev_close = float(meta.get("chartPreviousClose", 0))
        current_price = float(meta.get("regularMarketPrice", 0))
        market_time_unix = meta.get("regularMarketTime", 0)
        market_time_ny = datetime.fromtimestamp(market_time_unix, NY_TZ) if market_time_unix and NY_TZ else None
        
        # 判断市场是否已收盘
        market_closed = (market_time_ny and market_time_ny.hour >= 16) or now_ny.hour >= 16
        
        # 确定交易日期
        if market_closed:
            trade_date = now_ny.strftime("%Y-%m-%d")
            close_price = current_price if current_price > 0 else prev_close
        else:
            trade_date = (now_ny - timedelta(days=1)).strftime("%Y-%m-%d")
            close_price = prev_close
        
        # 找到 trade_date 对应的 bar
        # bar 的 NY_local = trade_date（直接用）
        target_bar_idx = None
        for i, t in enumerate(ts):
            dt_ny = datetime.fromtimestamp(t, NY_TZ) if NY_TZ else None
            if dt_ny and dt_ny.strftime("%Y-%m-%d") == trade_date:
                target_bar_idx = i
                break
        
        # 如果没找到，尝试用 chartPreviousClose 的日期
        if target_bar_idx is None:
            for i, t in enumerate(ts):
                dt_ny = datetime.fromtimestamp(t, NY_TZ) if NY_TZ else None
                if dt_ny:
                    # 找最后一个有收盘价的 bar
                    if closes[i] is not None:
                        target_bar_idx = i
        
        # 获取 OHLC
        if target_bar_idx is not None:
            # [2026-09-30 修复] Yahoo 对"未完成/停牌 bar"会返回 None，原写法 float(None) 直接崩溃
            # （9-30 15:19 手动触发复现: float() argument must be ... not 'NoneType'）。
            # 缺失字段先记 None，待 close_price 定案后统一回退，保证落库不中断。
            open_price = _num_or_none(opens[target_bar_idx])
            high_price = _num_or_none(highs[target_bar_idx])
            low_price = _num_or_none(lows[target_bar_idx])
            volume = _num_or_none(volumes[target_bar_idx])
            
            # 如果 bar 有收盘价，优先使用
            if closes[target_bar_idx] is not None:
                bar_close = float(closes[target_bar_idx])
                # 如果 market 已收盘且 regularMarketPrice 不同，用 regularMarketPrice
                if market_closed and current_price > 0 and abs(bar_close - current_price) > 0.01:
                    close_price = current_price
                else:
                    close_price = bar_close
            
            # [2026-09-30] None 字段回退到 close_price / 0（与 target_bar_idx 缺失时的兜底同语义）
            if open_price is None:
                open_price = close_price
            if high_price is None:
                high_price = close_price
            if low_price is None:
                low_price = close_price
            volume = 0 if volume is None else int(volume)

            # 修正 OHLC 确保逻辑正确
            if close_price > high_price:
                high_price = close_price
            if close_price < low_price:
                low_price = close_price
            if open_price > high_price:
                high_price = open_price
            if open_price < low_price:
                low_price = open_price
        else:
            open_price = high_price = low_price = close_price
            volume = 0
        
        return {
            "trade_date": trade_date,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    except Exception as e:
        log.error("抓取 OILUSA 失败: %s", e)
    return None

# ---------- Telegram 通知 ----------
def notify_telegram(msg: str) -> None:
    """发送 Telegram 通知。失败不影响主流程。"""
    import subprocess
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    cmd = [
        "curl", "-s", "-X", "POST",
        url,
        "--data-urlencode", f"chat_id={TELEGRAM_CHAT_ID}",
        "--data-urlencode", "parse_mode=Markdown",
        "--data-urlencode", f"text={msg}",
    ]
    attempts = 3
    for i in range(attempts):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            resp = json.loads(r.stdout) if r.stdout else {}
            if resp.get("ok"):
                log.info("Telegram 通知已发送")
                return
            desc = resp.get("description", r.stdout)
            log.warning("Telegram 通知失败(第%d/3次) ok=%s desc=%s", i+1, resp.get("ok"), desc[:200])
        except Exception as e:
            log.warning("Telegram 通知异常(第%d/3次): %s", i+1, e)
        if i < 2:
            time.sleep(5)
    log.error("Telegram 通知最终失败(已重试3次，不影响采样)")

# ---------- 主流程 ----------
def main() -> int:
    ap = argparse.ArgumentParser(description="UBS CMCI Oil SF USD (OILUSA) 每日收盘价采样")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--no-notify", action="store_true", help="落库后不发送 Telegram 通知")
    args = ap.parse_args()

    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_FILE)],
    )
    global log
    log = logging.getLogger("oil_eod")

    now = ny_now()
    # 确定交易日期
    hhmm = now.hour * 60 + now.minute
    if hhmm < 9 * 60 + 30:  # 早于 09:30 NY
        trade_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        trade_date = now.strftime("%Y-%m-%d")

    log.info("开始采样 trade_date=%s (NY time=%s)", trade_date, now.strftime("%Y-%m-%d %H:%M %Z"))
    row = fetch_oilusa()
    if row is None:
        log.error("未能获取 OILUSA 收盘价，跳过")
        return 1

    row["trade_date"] = trade_date
    try:
        n = write_eod(args.db, trade_date, row)
        log.info("落库成功 (%d 行)", n)
    except Exception as e:
        log.error("写库失败: %s", e)
        return 1

    if not args.no_notify:
        bj = datetime.now(timezone(timedelta(hours=8))).strftime("%H:%M:%S")
        msg = (
            f"【OILUSA 收盘价】{trade_date}\n"
            f"北京时间 {bj}\n"
            f"开盘: {row['open']:.2f}\n"
            f"最高: {row['high']:.2f}\n"
            f"最低: {row['low']:.2f}\n"
            f"收盘: {row['close']:.2f}\n"
            f"成交量: {row['volume']:,}\n"
            f"来源: Yahoo Finance ✅"
        )
        notify_telegram(msg)

    return 0

if __name__ == "__main__":
    sys.exit(main())
