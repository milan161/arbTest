#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""调试162411实时估值计算"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"D:\Study\arbTest")

from datetime import datetime
import pandas as pd

print(f"[调试] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. 连接数据库
from arbcore.database.db_manager import DatabaseManager
db_manager = DatabaseManager(db_path=r'D:\Study\arbTest\database\arb_master.db')
conn = db_manager._get_conn()

# 2. 检查162411的配置
print("\n[1] 检查162411在unified_fund_list中的数据:")
row = conn.execute("SELECT fund_code, fund_name, related_index, pos_ratio, category FROM unified_fund_list WHERE fund_code='162411'").fetchone()
if row:
    print(f"  fund_code: {row[0]}")
    print(f"  fund_name: {row[1]}")
    print(f"  related_index: {row[2]}")
    print(f"  pos_ratio: {row[3]}")
    print(f"  category: {row[4]}")
else:
    print("  未找到162411")

# 3. 检查basket数据
print("\n[2] 检查162411的basket数据:")
basket_rows = conn.execute("SELECT * FROM fund_basket_weights WHERE fund_code='162411' ORDER BY date DESC LIMIT 5").fetchall()
if basket_rows:
    for r in basket_rows:
        print(f"  {r}")
else:
    print("  basket为空")

# 4. 检查基准数据
print("\n[3] 检查162411的基准数据(fund_base_data):")
base_rows = conn.execute("SELECT * FROM fund_base_data WHERE fund_code='162411' ORDER BY date DESC LIMIT 1").fetchall()
if base_rows:
    for col in base_rows[0].keys():
        print(f"  {col}: {base_rows[0][col]}")
else:
    print("  未找到基准数据")

# 5. 获取实时行情
print("\n[4] 获取XOP实时价格:")
from services.market_data_service import MarketDataService
market_data = MarketDataService(db_manager)

# 测试多种符号格式
symbols_to_test = ['XOP', '^XOP', 'XOP-US']
for sym in symbols_to_test:
    q = market_data.get_realtime_quote(sym)
    if q and q.get('price'):
        print(f"  {sym}: {q['price']} (source: {q.get('source', '')})")
    else:
        print(f"  {sym}: 无数据")

# 6. 获取汇率
print("\n[5] 获取汇率:")
fx_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
if not fx_df.empty:
    print(f"  usd_cny_mid: {fx_df.iloc[0]['usd_cny_mid']}")

# 7. 检查指数数据
print("\n[6] 检查指数数据:")
idx_rows = conn.execute("SELECT * FROM index_history WHERE code='XOP' ORDER BY date DESC LIMIT 1").fetchall()
if idx_rows:
    print(f"  {idx_rows[0]}")
else:
    print("  XOP指数数据为空")

conn.close()
print("\n" + "=" * 80)
