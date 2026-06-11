import sqlite3
import pandas as pd

conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
cursor = conn.cursor()

# 检查字段名
cursor.execute('PRAGMA table_info(exchange_rate)')
print('exchange_rate 表字段名:')
for row in cursor.fetchall():
    print(f'  {row[1]} ({row[2]})')

# 检查最新数据
cursor.execute('SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 1')
result = cursor.fetchone()
print(f'\n最新数据: {result}')

# 使用 pandas 查询（模拟 fund_service.py 的逻辑）
fx_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
print(f'\npandas 查询结果:')
print(f'  df.empty: {fx_df.empty}')
print(f'  df.columns: {fx_df.columns.tolist()}')
print(f'  df.iloc[0]: {fx_df.iloc[0]}')
print(f'  usd_cny_mid 值: {fx_df.iloc[0]["usd_cny_mid"]}')
print(f'  usd_cny_mid 类型: {type(fx_df.iloc[0]["usd_cny_mid"])}')
print(f'  usd_cny_mid > 0: {fx_df.iloc[0]["usd_cny_mid"] > 0}')

conn.close()
