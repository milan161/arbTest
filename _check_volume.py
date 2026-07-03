import sqlite3
conn = sqlite3.connect('database/arb_master.db')

# Check 7/3 AG0
cur = conn.execute("SELECT date, close_price, settle_price, volume FROM futures_daily WHERE symbol='AG0' AND date='2026-07-03'")
r = cur.fetchone()
print(f"AG0 2026-07-03: {r}")

# Check last 5 AG0 records
cur = conn.execute("SELECT date, close_price, settle_price, volume FROM futures_daily WHERE symbol='AG0' ORDER BY date DESC LIMIT 5")
for r in cur:
    print(f"  {r}")

# Check the silver ratio API data source - what does the backend query?
conn.close()
