import urllib.request, json, sqlite3

# 直接爬新浪期货历史日线（InnerFuturesNewService.getDailyKLine, JSONP）
symbol = "AG0"
trade_date = "20210817"
url = (f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}{trade_date}"
       f"=/InnerFuturesNewService.getDailyKLine?symbol={symbol}&_={trade_date}")
req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0","Referer":"https://finance.sina.com.cn/"})
text = urllib.request.urlopen(req, timeout=30).read().decode('utf-8')
s = text.find("["); e = text.rfind("]")
arr = json.loads(text[s:e+1])
print("Sina 返回 AG0 条数:", len(arr))

db = r'D:\Study\arbTest\database\arb_master.db'
c = sqlite3.connect(db)
c.execute("PRAGMA foreign_keys=OFF")
n = 0
for r in arr:
    d = r.get('d'); c_ = r.get('c'); s_ = r.get('s'); v = r.get('v')
    if not d: continue
    c.execute("INSERT OR IGNORE INTO futures_daily (date, symbol) VALUES (?, 'AG0')", (d,))
    if c_:
        c.execute("UPDATE futures_daily SET close_price=? WHERE date=? AND symbol='AG0'", (float(c_), d))
    if s_:
        c.execute("UPDATE futures_daily SET settle_price=? WHERE date=? AND symbol='AG0'", (float(s_), d))
    if v:
        c.execute("UPDATE futures_daily SET volume=? WHERE date=? AND symbol='AG0'", (int(float(v)), d))
    n += 1
c.commit()
print("upserted:", n)

print("=== 验证 AG0 2026-07-01..07-08 ===")
for row in c.execute("SELECT date,close_price,settle_price,volume FROM futures_daily WHERE symbol='AG0' AND date>='2026-07-01' ORDER BY date"):
    print(row)
c.close()
print("DONE")
