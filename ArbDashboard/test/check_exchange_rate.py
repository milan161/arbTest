# -*- coding: utf-8 -*-
"""快速检查汇率数据"""
import sqlite3

db_path = r'D:\Study\arbTest\database\arb_master.db'
conn = sqlite3.connect(db_path)

print("=" * 60)
print("汇率数据检查")
print("=" * 60)

# 1. 检查表结构
print("\n[1] exchange_rate 表结构:")
cursor = conn.execute('PRAGMA table_info(exchange_rate)')
for row in cursor.fetchall():
    print(f"  {row}")

# 2. 检查最新数据
print("\n[2] 最新 3 天汇率数据:")
cursor = conn.execute('SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 3')
rows = cursor.fetchall()
for row in rows:
    print(f"  日期: {row[0]}")
    print(f"  USD/CNY: {row[1]}")
    if len(row) > 2:
        print(f"  更新时间: {row[2]}")
    if len(row) > 3:
        print(f"  HKD/CNY: {row[3]}")
    print()

# 3. 检查数据完整性
print("\n[3] 数据完整性检查:")
cursor = conn.execute('SELECT COUNT(*) FROM exchange_rate')
count = cursor.fetchone()[0]
print(f"  总记录数: {count}")

cursor = conn.execute('SELECT COUNT(*) FROM exchange_rate WHERE usd_cny_mid IS NOT NULL')
usd_count = cursor.fetchone()[0]
print(f"  有 USD 数据: {usd_count}")

cursor = conn.execute('SELECT COUNT(*) FROM exchange_rate WHERE hkd_cny_mid IS NOT NULL')
hkd_count = cursor.fetchone()[0]
print(f"  有 HKD 数据: {hkd_count}")

# 4. 检查今日数据
from datetime import datetime
today = datetime.now().strftime('%Y-%m-%d')
cursor = conn.execute('SELECT * FROM exchange_rate WHERE date = ?', (today,))
today_data = cursor.fetchone()
print(f"\n[4] 今日 ({today}) 数据:")
if today_data:
    print(f"  [OK] 存在")
    print(f"  USD/CNY: {today_data[1]}")
    if len(today_data) > 3:
        print(f"  HKD/CNY: {today_data[3]}")
else:
    print(f"  [X] 不存在（需要手动更新或等待 011 程序运行）")

conn.close()
print("\n" + "=" * 60)
