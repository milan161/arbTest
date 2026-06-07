import sys
import os
import pandas as pd

backend_dir = r'D:\Study\arbTest\ArbDashboard_Next\backend'
sys.path.append(os.path.join(backend_dir, 'core'))
sys.path.append(backend_dir)
sys.path.append(r'D:\Study\arbTest')

from services.fund_service import FundService
from arbcore.database.db_manager import DatabaseManager

db = DatabaseManager(db_path=r'D:\Study\arbTest\database\arb_master.db')
service = FundService(db)
data = service.get_unified_dashboard_data()

print("--- DEBUG START ---")
for item in data:
    if item['fund_code'] in ('160719', '162411'):
        print(f"Code: {item['fund_code']}, Name: {item['fund_name']}")
        print(f"  - Price: {item.get('price')}")
        print(f"  - Volume (Amount/Wan): {item.get('volume')}")
        print(f"  - Shares (Total/Wan): {item.get('shares')}")
        print(f"  - Turnover Rate (%): {item.get('turnover_rate')}")
print("--- DEBUG END ---")
