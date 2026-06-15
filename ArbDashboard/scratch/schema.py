import sqlite3
conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
print(conn.execute("PRAGMA table_info(futures_daily);").fetchall())
