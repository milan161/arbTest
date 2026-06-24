# -*- coding: utf-8 -*-
import requests

headers = {
    'Referer': 'https://quote.eastmoney.com/',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
}

# QDII亚洲 所有 related_index
tests = [
    ('HSCI', '116.HSCI'),
    ('HSMI', '124.HSMI'),
    ('HSSI', '124.HSSI'),
    ('HSCCI', '116.HSCCI'),
    ('HSSCNE', '124.HSSCNE'),
    ('930914', '2.930914'),
    ('930917', '2.930917'),
    ('.SPHCMSHP', '116..SPHCMSHP'),  # 尝试
    ('.SPACEVCP', '116..SPACEVCP'),   # 尝试
]

for symbol, secid in tests:
    try:
        url = 'https://push2.eastmoney.com/api/qt/stock/get'
        params = {
            'secid': secid,
            'fields': 'f43,f58,f170',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'fltt': '1',
        }
        r = requests.get(url, params=params, headers=headers, timeout=5)
        data = r.json()
        if data.get('rc') == 0 and data.get('data'):
            d = data['data']
            print(f"✅ {symbol} ({secid}): price={d.get('f43')} pct={d.get('f170')} name={d.get('f58')}")
        else:
            print(f"❌ {symbol} ({secid}): rc={data.get('rc')} data={data.get('data')}")
    except Exception as e:
        print(f"❌ {symbol} ({secid}): {e}")
