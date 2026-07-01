import yaml
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
from database.db_manager import DatabaseManager

YAML_PATH = os.path.join(ROOT, 'arbcore', 'config', 'lof_config.yaml')
DB_PATH = os.path.join(ROOT, 'database', 'arb_master.db')

with open(YAML_PATH, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

funds = config.get('funds', [])
fund_list = []
for f in funds:
    fund_obj = {
        'category': f.get('category', '未知'),
        'code': str(f.get('code')),
        'name': f.get('name'),
        'related_index': f.get('related_index', f.get('trade_etf', '-')),
        'idx_code': f.get('idx_code', f.get('related_index', f.get('trade_etf', '-'))),
        'idx_name': f.get('idx_name', '-'),
        'pos_ratio': f.get('pos_ratio', 0.95),
        'purchase_fee': f.get('purchase_fee', '-'),
        'redemption_fee': f.get('redemption_fee', '-'),
    }
    fund_list.append(fund_obj)

db = DatabaseManager(db_path=DB_PATH)
db.sync_unified_fund_list(fund_list)
print(f"Successfully synced {len(fund_list)} funds from lof_config.yaml to unified_fund_list table.")
