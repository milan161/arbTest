import sqlite3
import pandas as pd
conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
print("unified_fund_history:")
print(pd.read_sql("SELECT date, nav, static_val, calibration FROM unified_fund_history WHERE fund_code='160719' ORDER BY date DESC LIMIT 5", conn))
print("\nfutures_daily:")
print(pd.read_sql("SELECT * FROM futures_daily WHERE symbol='MGC' ORDER BY date DESC LIMIT 5", conn))
