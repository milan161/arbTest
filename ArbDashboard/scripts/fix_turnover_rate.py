# -*- coding: utf-8 -*-
"""
修复换手率公式 v2 - 处理 volume 单位不一致问题
- tqcenter: volume in 股 (shares)
- 腾讯 API: volume in 万元 (10k yuan)

正确公式: 换手率 = 成交额(万元) / (收盘价 × 场内份额(万份)) × 100
判断: volume < shares → 万元, volume >= shares → 股
"""
import sqlite3
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = r'D:\Study\arbTest\database\arb_master.db'


def calc_turnover(price, volume, shares):
    if not price or not volume or not shares or shares <= 0:
        return None
    if volume < shares:
        return volume / (price * shares) * 100
    else:
        return volume / shares / 100


def fix_turnover_rate():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout = 30000")
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM unified_fund_history WHERE volume IS NOT NULL AND shares IS NOT NULL AND shares > 0 AND price IS NOT NULL")
    total = cursor.fetchone()[0]
    print(f"共 {total} 条记录需要修复")
    
    print("\n=== 修复前 (168204) ===")
    cursor.execute("SELECT date, price, volume, shares, turnover_rate FROM unified_fund_history WHERE fund_code = '168204' AND volume IS NOT NULL AND shares IS NOT NULL ORDER BY date DESC LIMIT 10")
    for r in cursor.fetchall():
        date, price, vol, shares, tr = r
        new_tr = calc_turnover(price, vol, shares)
        unit = '万元' if vol < shares else '股'
        print(f"  {date}: vol={vol:.0f}({unit}) shares={shares:.1f} old={tr} new={new_tr:.4f}%")
    
    print(f"\n开始修复...")
    cursor.execute("SELECT date, fund_code, price, volume, shares FROM unified_fund_history WHERE volume IS NOT NULL AND shares IS NOT NULL AND shares > 0 AND price IS NOT NULL")
    rows = cursor.fetchall()
    
    updated = 0
    for date, fc, price, vol, shares in rows:
        new_tr = calc_turnover(price, vol, shares)
        if new_tr is not None:
            cursor.execute("UPDATE unified_fund_history SET turnover_rate = ? WHERE date = ? AND fund_code = ?", (new_tr, date, fc))
            updated += 1
    
    conn.commit()
    print(f"已修复 {updated} 条记录")
    
    print("\n=== 修复后 (168204) ===")
    cursor.execute("SELECT date, price, volume, shares, turnover_rate FROM unified_fund_history WHERE fund_code = '168204' AND volume IS NOT NULL AND shares IS NOT NULL ORDER BY date DESC LIMIT 10")
    for r in cursor.fetchall():
        date, price, vol, shares, tr = r
        unit = '万元' if vol < shares else '股'
        print(f"  {date}: vol={vol:.0f}({unit}) shares={shares:.1f} turnover={tr}%")
    
    conn.close()
    print("\n完成!")


if __name__ == '__main__':
    fix_turnover_rate()
