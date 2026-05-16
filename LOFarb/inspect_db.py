import sqlite3
import os

# 修正后的路径
db_path = 'D:/Study/arbTest/database/arb_master.db'
if not os.path.exists(db_path):
    print(f"Error: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
c = conn.cursor()

def print_table_info(table_name):
    print(f"\n--- {table_name} schema ---")
    c.execute(f"PRAGMA table_info({table_name})")
    for col in c.fetchall():
        print(f"  Column: {col[1]} ({col[2]})")

# 1. 检查 fund_data
print_table_info('fund_data')

# 2. 列出所有表
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("\n--- All tables in DB ---")
print(", ".join(tables))

# 3. 检查一个历史表
sample_hist = [t for t in tables if t.startswith('fund_history_')]
if sample_hist:
    print_table_info(sample_hist[0])
else:
    print("\nNo fund_history_ tables found.")

conn.close()
