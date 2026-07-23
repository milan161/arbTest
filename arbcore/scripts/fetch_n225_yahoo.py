# -*- coding: utf-8 -*-
# [AI-2026-07-23] 新增：从 Yahoo Finance 直接爬取日经225指数(N225)收盘价
"""
从 Yahoo Finance 直接爬取日经225指数(N225)收盘价

背景：
    VPS 定时脚本 (US_etf_nav_N225.py) 每天 08:30 北京时间运行，通过 Yahoo Finance ^N225
    获取日经指数收盘价。但 JPX 东京交易所于北京时间 08:00 开盘（东京 09:00），
    VPS 运行时 JPX 正在交易中，Yahoo range=1d 返回的是当天盘中价而非前一日收盘价，
    导致入库数据错误。

本脚本修复方案：
    - 使用 Yahoo range=5d 获取多日数据
    - 只取日期 < 今天的已完成交易日 bar（排除当天不完整盘中数据）
    - 写入 index_history 表，source='yahoo_direct'

用法：
    python arbcore/scripts/fetch_n225_yahoo.py              # 每日增量更新
    python arbcore/scripts/fetch_n225_yahoo.py --range=1mo  # 批量回填历史
"""

import ssl
import json
import urllib.request
import sqlite3
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

# ── 数据库路径 ──────────────────────────────────────────────
JST = timezone(timedelta(hours=9), 'JST')       # 东京时区
YAHOO_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Origin': 'https://finance.yahoo.com',
    'Referer': 'https://finance.yahoo.com/',
}

# 项目根目录 → database/arb_master.db
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'database', 'arb_master.db')
DATA_SOURCE = 'yahoo_direct'  # 数据来源标识


def get_today_jst() -> str:
    """返回东京时间今天的日期字符串 YYYY-MM-DD"""
    return datetime.now(JST).strftime('%Y-%m-%d')


def fetch_n225_from_yahoo(range_str: str = '5d') -> list[dict]:
    """
    从 Yahoo Finance v7 API 获取 ^N225 日线数据

    Args:
        range_str: Yahoo range 参数，如 '5d', '1mo', '3mo', '1y'

    Returns:
        [{'date': '2026-07-22', 'close': 66115.60, 'is_completed': True}, ...]
        is_completed=False 表示该 bar 可能是当天的盘中数据（不完整）
    """
    url = (f"https://query1.finance.yahoo.com/v7/finance/chart/"
           f"%5EN225?range={range_str}&interval=1d&indicators=quote"
           f"&includeTimestamps=true")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, headers=YAHOO_HEADERS)
    today_jst = get_today_jst()

    with urllib.request.urlopen(req, context=ctx, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))

    result = data.get('chart', {}).get('result', [])
    if not result:
        print("[ERROR] Yahoo API 返回为空")
        return []

    r = result[0]
    timestamps = r.get('timestamp', [])
    quotes = r.get('indicators', {}).get('quote', [{}])[0]
    closes = quotes.get('close', [])

    records = []
    for i in range(len(timestamps)):
        if closes[i] is None:
            continue
        ts = timestamps[i]
        bar_date = datetime.fromtimestamp(ts, tz=JST).strftime('%Y-%m-%d')
        close_price = round(float(closes[i]), 2)
        is_completed = bar_date < today_jst  # 日期小于今天 = 已完成交易日
        records.append({
            'date': bar_date,
            'close': close_price,
            'is_completed': is_completed,
        })

    print(f"[INFO] Yahoo 返回 {len(records)} 条 N225 日线数据 ({range_str})")
    return records


def write_to_index_history(records: list[dict], dry_run: bool = False):
    """
    将 N225 数据写入 index_history 表 (INSERT OR REPLACE)

    Args:
        records: fetch_n225_from_yahoo() 返回的记录列表
        dry_run: True 时只打印不写入
    """
    today_jst = get_today_jst()
    conn = sqlite3.connect(DB_PATH)

    written = 0
    skipped_incomplete = 0
    skipped_today = 0

    for rec in records:
        bar_date = rec['date']
        close_price = rec['close']

        # 跳过当天的不完整 bar（JPX 交易时段）
        if not rec.get('is_completed', True):
            print(f"  [SKIP] {bar_date} close={close_price} (当天不完整数据)")
            skipped_incomplete += 1
            continue

        if dry_run:
            print(f"  [DRY-RUN] 将写入 {bar_date} close={close_price}")
            written += 1
        else:
            conn.execute(
                "INSERT OR REPLACE INTO index_history "
                "(symbol, date, close, source) VALUES (?, ?, ?, ?)",
                ('N225', bar_date, close_price, DATA_SOURCE)
            )
            print(f"  [OK] 写入 {bar_date} close={close_price}")
            written += 1

    if not dry_run:
        conn.commit()
        print(f"[OK] 提交 {written} 条数据到 index_history")
    else:
        print(f"[DRY-RUN] 共 {written} 条数据待写入")

    conn.close()
    return written


def print_comparison(records: list[dict], db_records: list[tuple]):
    """对比 Yahoo 新数据与数据库现有数据"""
    db_map = {r[0]: r[1] for r in db_records}

    print(f"\n{'Date':<12} {'Yahoo新值':<14} {'DB当前值':<14} {'Diff':<12} {'结果'}")
    print("-" * 64)
    for rec in records:
        d = rec['date']
        yahoo_val = rec['close']
        db_val = db_map.get(d)
        if db_val is not None:
            diff = yahoo_val - db_val
            if abs(diff) < 1:
                status = "OK"
            elif abs(diff) < 10:
                status = "NEAR"
            else:
                status = "MISMATCH"
        else:
            diff = 0
            status = "NEW"
        print(f"{d:<12} {yahoo_val:<14} {str(db_val or 'N/A'):<14} "
              f"{diff:+.2f}    {status}")


def main():
    parser = argparse.ArgumentParser(description='从 Yahoo Finance 爬取日经225(N225)收盘价')
    parser.add_argument('--range', default='5d',
                        help='Yahoo range 参数: 5d(默认), 1mo, 3mo, 1y, 2y, 5y, max')
    parser.add_argument('--dry-run', action='store_true',
                        help='仅预览不写入数据库')
    args = parser.parse_args()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始抓取 N225 数据")
    print(f"  东京今天: {get_today_jst()}")
    print(f"  range={args.range}")
    if args.dry_run:
        print("  [DRY-RUN 模式] 不会写入数据库")

    # 1. 从 Yahoo 拉数据
    records = fetch_n225_from_yahoo(args.range)
    if not records:
        print("[ERROR] 未获取到数据")
        return

    # 2. 显示哪些会写、哪些跳过
    completed = [r for r in records if r['is_completed']]
    incomplete = [r for r in records if not r['is_completed']]
    print(f"\n  已完成交易日: {len(completed)} 条")
    print(f"  跳过(当天盘中): {len(incomplete)} 条")

    # 3. 对比数据库现有值
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT date, close FROM index_history WHERE symbol='N225' ORDER BY date"
    )
    db_records = cursor.fetchall()
    conn.close()

    print("\n── Yahoo 新数据 vs 数据库现有 ──")
    print_comparison(records, db_records)

    # 4. 写入
    print(f"\n── 写入数据库 (source='{DATA_SOURCE}') ──")
    write_to_index_history(records, dry_run=args.dry_run)

    print(f"\n[完成] 操作结束")
    print(f"提示: 如果要验证 N225 数据是否正确，请运行:")
    print(f"  SELECT date, close, source FROM index_history WHERE symbol='N225' ORDER BY date DESC LIMIT 10;")


if __name__ == '__main__':
    main()
