import sqlite3
import pandas as pd

db_path = r"D:\Study\arbTest\database\arb_master.db"
conn = sqlite3.connect(db_path)

print("--- fund_data 最新 3 条记录 for 163208 ---")
df_fund = pd.read_sql("SELECT * FROM fund_data WHERE fund_code='163208' ORDER BY date DESC LIMIT 3", conn)
print(df_fund)

print("\n--- fund_daily_factors 最新 3 条记录 for 163208 ---")
df_factors = pd.read_sql("SELECT * FROM fund_daily_factors WHERE fund_code='163208' ORDER BY date DESC LIMIT 3", conn)
print(df_factors)

print("\n--- exchange_rate 最新 3 条记录 ---")
df_fx = pd.read_sql("SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 3", conn)
print(df_fx)

print("\n--- 执行联表 JOIN 查询 ---")
query = """
    SELECT 
        a.date, a.nav, a.price as close, 
        c.usd_cny_mid as exchange_rate,
        b.position, b.hedge, b.calibration
    FROM fund_data a
    JOIN fund_daily_factors b ON a.date = b.date AND a.fund_code = b.fund_code
    JOIN exchange_rate c ON a.date = c.date
    WHERE a.fund_code = '163208' AND a.nav IS NOT NULL AND a.nav > 0
    ORDER BY a.date DESC LIMIT 1
"""
df_join = pd.read_sql(query, conn)
print(df_join)

conn.close()
