import os
import sys

# Setup paths as in main.py
backend_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(backend_dir, "..", ".."))
sys.path.insert(0, project_root)
sys.path.append(os.path.join(backend_dir, "core"))

try:
    from arbcore.database.db_manager import DatabaseManager
    from arbcore.fetchers.realtime import RealtimeMarketManager
    print("✅ Successfully imported arbcore modules from root.")
    
    db_path = os.path.join(project_root, "database", "arb_master.db")
    db = DatabaseManager(db_path=db_path)
    print(f"✅ Database initialized at {db_path}")
    
    config = db.get_data_source_config("realtime_market")
    print(f"✅ Found {len(config)} data source configs.")
    for c in config:
        print(f"   - {c['source_name']}: priority {c['priority']}")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
