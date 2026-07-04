#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recalc_static_val_with_hedge.py - 使用 Hedge 重新计算静态估值

用途：针对 QDII欧美 TAB 的 single-ETF 基金（魔法公式），
      从 2026-04-08 起重新计算 static_val，强制使用 magic formula (含 hedge)。

公式：static_val = T-1_nav * (1 - position) + (current_price * current_fx) / hedge

用法：
  python recalc_static_val_with_hedge.py           # 正常执行
  python recalc_static_val_with_hedge.py --dry-run # 仅打印 diff 不写入
"""
import sys, io, sqlite3, os, yaml
from datetime import datetime
from typing import Optional, Dict, List, Any
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = r'D:\Study\arbTest\database\arb_master.db'
YAML_PATH = r'D:\Study\arbTest\arbcore\config\lof_config.yaml'
START_DATE = '2026-04-08'
GAP_DAYS_LIMIT = 5


def load_target_funds() -> List[Dict[str, str]]:
    """筛选 QDII欧美 single-ETF 且有 hedge 的基金"""
    conn = sqlite3.connect(DB_PATH)
    try:
        with open(YAML_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        fund_map = {f['code']: f for f in cfg.get('funds', [])}
        rows = conn.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE category='QDII欧美'").fetchall()
        result = []
        for code, name in rows:
            fd = fund_map.get(code)
            if not fd:
                continue
            port = fd.get('valuation_portfolio', [])
            if not port or len(port) != 1:
                continue
            if conn.execute("SELECT 1 FROM fund_daily_factors WHERE fund_code=? AND hedge>0 LIMIT 1", (code,)).fetchone():
                sym = port[0].get('symbol', '').replace('^', '').split('-')[0]
                result.append({'code': code, 'name': name or '?', 'symbol': sym})
        return result
    finally:
        conn.close()


def process_fund(conn, fund: Dict[str, str], dry_run: bool = False) -> dict:
    code, name, symbol = fund['code'], fund['name'], fund['symbol']
    print(f'\n[{code}] {name} -> {symbol}')

    import pandas as pd
    # Load ETF prices
    etf_rows = conn.execute("SELECT date, COALESCE(NULLIF(netvalue,0),price) FROM usa_etf_daily_prices WHERE symbol=?", (symbol,)).fetchall()
    etf_prices = {r[0]: r[1] for r in etf_rows if r[1] and r[1] > 0}
    if not etf_prices:
        print(f'  [SKIP] {symbol} 无历史价格')
        return {'code': code, 'updated': 0, 'skipped': 0}

    # Load fund history
    df = pd.read_sql("""
        SELECT a.date, a.price as close, a.nav, c.usd_cny_mid as exchange_rate,
               b.position, b.hedge
        FROM unified_fund_history a
        LEFT JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
        LEFT JOIN exchange_rate c ON a.date = c.date
        WHERE a.fund_code = ? AND a.date >= ?
        ORDER BY a.date DESC
    """, conn, params=(code, START_DATE))
    if df.empty:
        print(f'  [SKIP] 无历史数据')
        return {'code': code, 'updated': 0, 'skipped': 0}

    # Merge ETF prices
    df = df.sort_values('date', ascending=False).reset_index(drop=True)
    df = pd.merge(df, pd.DataFrame(list(etf_prices.items()), columns=['date', symbol]), on='date', how='left')

    updates, updated, skipped = [], 0, 0
    for i, row in df.iterrows():
        c_price = row.get(symbol)
        if pd.isna(c_price) or not c_price or c_price <= 0:
            continue
        if pd.isna(row['exchange_rate']) or not row['exchange_rate'] or row['exchange_rate'] <= 0:
            continue

        # Find base T-1 row
        base = None
        for j in range(i + 1, min(i + 15, len(df))):
            c = df.iloc[j]
            if pd.notna(c['nav']) and c['nav'] > 0 and pd.notna(c['exchange_rate']):
                base = c
                break
        if base is None or pd.isna(base['hedge']) or not base['hedge'] or base['hedge'] <= 0:
            continue

        try:
            bdt = datetime.strptime(str(base['date']), '%Y-%m-%d')
            cdt = datetime.strptime(str(row['date']), '%Y-%m-%d')
            if abs((cdt - bdt).days) > GAP_DAYS_LIMIT:
                continue
        except:
            pass

        val = round(base['nav'] * (1.0 - base['position']) + (c_price * row['exchange_rate']) / base['hedge'], 4)
        updates.append((row['date'], val, base['hedge']))

    updates.sort(key=lambda x: x[0])
    cursor = conn.cursor()
    for date, new_val, hedge_val in updates:
        old = conn.execute("SELECT static_val FROM unified_fund_history WHERE fund_code=? AND date=?", (code, date)).fetchone()
        if old and old[0] and old[0] > 0 and abs(new_val - old[0]) < 0.0001:
            skipped += 1
            continue
        nav = conn.execute("SELECT nav FROM unified_fund_history WHERE fund_code=? AND date=?", (code, date)).fetchone()
        daily_nav = nav[0] if nav else None
        val_err = round(new_val - daily_nav, 6) if daily_nav and daily_nav > 0 else None
        if dry_run:
            print(f'  [DRY] {date}: {old[0] if old else "None":>8} -> {new_val:.4f}')
        else:
            cursor.execute("UPDATE unified_fund_history SET static_val=?, valuation_error=?, calibration=? WHERE fund_code=? AND date=?", (new_val, val_err, hedge_val, code, date))
            updated += 1
    if not dry_run:
        conn.commit()
    print(f'  [DONE] updated={updated}, skipped={skipped}')
    return {'code': code, 'updated': updated, 'skipped': skipped}


def main():
    dry_run = '--dry-run' in sys.argv
    print(f'{"="*50}\n recalc_static_val_with_hedge.py\n 模式: {"DRY RUN" if dry_run else "正常执行"}\n{"="*50}')
    funds = load_target_funds()
    print(f'基金: {len(funds)} 只')
    for f in funds:
        print(f'  {f["code"]} {f["name"]} -> {f["symbol"]}')
    conn = sqlite3.connect(DB_PATH)
    tu, ts = 0, 0
    for fund in funds:
        r = process_fund(conn, fund, dry_run=dry_run)
        tu += r['updated']; ts += r['skipped']
    conn.close()
    print(f'\n{"="*50}\n 完成: updated={tu}, skipped={ts}\n{"="*50}')


if __name__ == '__main__':
    main()
