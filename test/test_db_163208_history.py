import sqlite3
import pandas as pd

db_path = r"D:\Study\arbTest\database\arb_master.db"
conn = sqlite3.connect(db_path)

print("--- fund_info 记录 for 163208 ---")
df_info = pd.read_sql("SELECT * FROM fund_info WHERE fund_code='163208'", conn)
print(df_info)

print("\n--- unified_fund_history 最新 5 条记录 for 163208 ---")
df_hist = pd.read_sql("SELECT * FROM unified_fund_history WHERE fund_code='163208' ORDER BY date DESC LIMIT 5", conn)
print(df_hist)

print("\n--- 检查 unified_fund_history 表的行数 for 163208 ---")
count = pd.read_sql("SELECT COUNT(*) as count FROM unified_fund_history WHERE fund_code='163208'", conn)
print(count)

conn.close()
