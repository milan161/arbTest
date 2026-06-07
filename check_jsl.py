import sqlite3
import pandas as pd
import json

conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
query = "SELECT * FROM raw_api_data WHERE source='jsl_fund_list' ORDER BY date DESC LIMIT 1"
df = pd.read_sql_query(query, conn)

if not df.empty:
    content = df.iloc[0]['raw_content']
    data = json.loads(content)
    # Find 160723
    for item in data.get('rows', []):
        cell = item.get('cell', {})
        if cell.get('fund_id') == '160723':
            print('JSL 160723 data:', cell)
        if cell.get('fund_id') == '161129':
            print('JSL 161129 data:', cell)
else:
    print('No JSL data found')
