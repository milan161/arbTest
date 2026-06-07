import sqlite3
import pandas as pd
conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
print("=== unified_fund_history schema ===")
print(pd.read_sql_query("PRAGMA table_info(unified_fund_history)", conn))
print("\n=== sample data ===")
print(pd.read_sql_query("SELECT fund_code, date, volume FROM unified_fund_history ORDER BY date DESC LIMIT 5", conn))
