import yaml
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(backend_dir)
sys.path.append(os.path.abspath(os.path.join(backend_dir, '..', '..', 'arbcore')))
from database.db_manager import DatabaseManager

def sync_config_to_jsl_list():
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'arbcore', 'config', 'lof_config.yaml'))
    if not os.path.exists(config_path):
        print(f"Error: Config not found at {config_path}")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    funds = config.get('funds', [])
    fund_list = []
    for f in funds:
        fund_list.append({
            'category': f.get('category', '未知'),
            'code': str(f.get('code')),
            'name': f.get('name'),
            'related_index': f.get('trade_etf', '-')
        })

    # Initialize Database Manager (explicitly pointing to the central root database)
    root_db_path = os.path.abspath(os.path.join(backend_dir, "..", "..", "database", "arb_master.db"))
    db = DatabaseManager(db_path=root_db_path)
    db.sync_unified_fund_list(fund_list)
    print(f"Successfully synced {len(fund_list)} funds from lof_config.yaml to unified_fund_list table.")

if __name__ == "__main__":
    sync_config_to_jsl_list()
