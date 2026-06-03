import os
import sqlite3
import threading
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from .managers.fund_manager import FundManager
from .managers.market_manager import MarketManager
from .managers.system_manager import SystemManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            db_path = os.path.join(base_dir, 'database', 'arb_master.db')
            
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        self.db_path = db_path
        self.lock = threading.Lock()
        
        # Composition: delegate to specialized managers
        self.funds = FundManager(self.db_path, self.lock)
        self.market = MarketManager(self.db_path, self.lock)
        self.system = SystemManager(self.db_path, self.lock)
        
        self.init_db()
        
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.execute('PRAGMA journal_mode=WAL;')
        return conn
    
    def init_db(self):
        with self.lock:
            conn = self._get_conn()
            conn.execute('CREATE TABLE IF NOT EXISTS fund_data (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, fund_code TEXT, price REAL, nav REAL, premium REAL, static_val REAL, val_error REAL, created_at TEXT, UNIQUE(date, fund_code))')
            try:
                conn.execute('ALTER TABLE fund_data ADD COLUMN static_val REAL')
                conn.execute('ALTER TABLE fund_data ADD COLUMN val_error REAL')
            except sqlite3.OperationalError: pass

            conn.execute('DROP TABLE IF EXISTS futures_data')
            conn.execute('DROP TABLE IF EXISTS future_calibration')
            conn.execute('DROP TABLE IF EXISTS macro_data')
            conn.execute('DROP TABLE IF EXISTS api_sync_status')

            conn.execute('''CREATE TABLE IF NOT EXISTS system_health (id INTEGER PRIMARY KEY AUTOINCREMENT, component TEXT NOT NULL, status TEXT, message TEXT, timestamp DATETIME DEFAULT (datetime('now', 'localtime')))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS exchange_rate (date TEXT PRIMARY KEY, usd_cny_mid REAL, hkd_cny_mid REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')))''')
            try: conn.execute('ALTER TABLE exchange_rate ADD COLUMN hkd_cny_mid REAL')
            except sqlite3.OperationalError: pass

            conn.execute('''CREATE TABLE IF NOT EXISTS usa_etf_daily_prices (date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL, netvalue REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, symbol))''')
            try: conn.execute('ALTER TABLE usa_etf_daily_prices ADD COLUMN netvalue REAL')
            except sqlite3.OperationalError: pass

            conn.execute('''CREATE TABLE IF NOT EXISTS index_daily (date TEXT NOT NULL, symbol TEXT NOT NULL, price REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, symbol))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS futures_daily (date TEXT NOT NULL, symbol TEXT NOT NULL, settle_price REAL, calibration REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, symbol))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fund_basket_weights (date TEXT NOT NULL, fund_code TEXT NOT NULL, underlying_symbol TEXT NOT NULL, weight REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, fund_code, underlying_symbol))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fund_daily_factors (date TEXT NOT NULL, fund_code TEXT NOT NULL, calibration REAL, hedge REAL, position REAL, nav REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, fund_code))''')
            try: conn.execute('ALTER TABLE fund_daily_factors ADD COLUMN nav REAL')
            except sqlite3.OperationalError: pass

            conn.execute('''CREATE TABLE IF NOT EXISTS raw_api_data (date TEXT NOT NULL, source TEXT NOT NULL, raw_content TEXT, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, source))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS access_sync_status (sync_date TEXT NOT NULL, access_source TEXT NOT NULL, sync_time TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (sync_date, access_source))''')

            conn.execute('CREATE INDEX IF NOT EXISTS idx_fund_code_date ON fund_daily_factors (fund_code, date DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_health_component ON system_health(component)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_etf_prices_date ON usa_etf_daily_prices(date DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fund_basket ON fund_basket_weights(fund_code, date DESC)')

            conn.execute('''CREATE TABLE IF NOT EXISTS etf_raw_api_data (date TEXT NOT NULL, source TEXT NOT NULL, raw_content TEXT, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (date, source))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS etf_rotation_list (group_id INTEGER, lof_code TEXT, lof_name TEXT, etf_code TEXT, etf_name TEXT, track_index TEXT, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (lof_code, etf_code))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS fund_purchase_status (fund_code TEXT PRIMARY KEY, purchase_status TEXT, redemption_status TEXT, purchase_fee TEXT, redemption_fee TEXT, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS jsl_fund_list (category TEXT, fund_code TEXT PRIMARY KEY, fund_name TEXT, related_index TEXT)''')

            conn.commit()
            conn.close()

    # Delegate methods
    def save_fund_data(self, *args, **kwargs): return self.funds.save_fund_data(*args, **kwargs)
    def update_fund_valuation(self, *args, **kwargs): return self.funds.update_fund_valuation(*args, **kwargs)
    def upsert_fund_factor(self, *args, **kwargs): return self.funds.upsert_fund_factor(*args, **kwargs)
    def upsert_fund_basket_weight(self, *args, **kwargs): return self.funds.upsert_fund_basket_weight(*args, **kwargs)
    def get_latest_fund_factor(self, *args, **kwargs): return self.funds.get_latest_fund_factor(*args, **kwargs)
    def get_fund_basket(self, *args, **kwargs): return self.funds.get_fund_basket(*args, **kwargs)
    def get_latest_fund_price(self, *args, **kwargs): return self.funds.get_latest_fund_price(*args, **kwargs)
    def batch_save_fund_prices(self, *args, **kwargs): return self.funds.batch_save_fund_prices(*args, **kwargs)
    def sync_jsl_fund_list(self, *args, **kwargs): return self.funds.sync_jsl_fund_list(*args, **kwargs)
    def get_jsl_fund_list(self, *args, **kwargs): return self.funds.get_jsl_fund_list(*args, **kwargs)
    def batch_save_fund_purchase_status(self, *args, **kwargs): return self.funds.batch_save_fund_purchase_status(*args, **kwargs)
    def get_fund_purchase_status(self, *args, **kwargs): return self.funds.get_fund_purchase_status(*args, **kwargs)

    def upsert_exchange_rate(self, *args, **kwargs): return self.market.upsert_exchange_rate(*args, **kwargs)
    def upsert_hkd_exchange_rate(self, *args, **kwargs): return self.market.upsert_hkd_exchange_rate(*args, **kwargs)
    def upsert_futures_daily(self, *args, **kwargs): return self.market.upsert_futures_daily(*args, **kwargs)
    def upsert_usa_etf_price(self, *args, **kwargs): return self.market.upsert_usa_etf_price(*args, **kwargs)
    def upsert_index_price(self, *args, **kwargs): return self.market.upsert_index_price(*args, **kwargs)
    def get_latest_usa_etf_date(self, *args, **kwargs): return self.market.get_latest_usa_etf_date(*args, **kwargs)
    def get_latest_futures_price(self, *args, **kwargs): return self.market.get_latest_futures_price(*args, **kwargs)
    def batch_save_futures_data(self, *args, **kwargs): return self.market.batch_save_futures_data(*args, **kwargs)

    def save_raw_api_data(self, *args, **kwargs): return self.system.save_raw_api_data(*args, **kwargs)
    def get_raw_api_data(self, *args, **kwargs): return self.system.get_raw_api_data(*args, **kwargs)
    def mark_access_synced(self, *args, **kwargs): return self.system.mark_access_synced(*args, **kwargs)
    def is_access_synced_today(self, *args, **kwargs): return self.system.is_access_synced_today(*args, **kwargs)
    def remove_access_sync_status(self, *args, **kwargs): return self.system.remove_access_sync_status(*args, **kwargs)
    def save_health_status(self, *args, **kwargs): return self.system.save_health_status(*args, **kwargs)
    def get_health_status(self, *args, **kwargs): return self.system.get_health_status(*args, **kwargs)
    def cleanup_old_data(self, *args, **kwargs): return self.system.cleanup_old_data(*args, **kwargs)
    def drop_deprecated_tables(self, *args, **kwargs): return self.system.drop_deprecated_tables(*args, **kwargs)
    def vacuum_database(self, *args, **kwargs): return self.system.vacuum_database(*args, **kwargs)

    # Compatibility methods
    def mark_api_synced(self, *args, **kwargs): return self.mark_access_synced(*args, **kwargs)
    def is_api_synced_today(self, *args, **kwargs): return self.is_access_synced_today(*args, **kwargs)

    def sync_etf_rotation_list(self, df):
        with self.lock:
            try:
                conn = self._get_conn()
                conn.execute('DROP TABLE IF EXISTS etf_rotation_list')
                conn.execute('''CREATE TABLE etf_rotation_list (group_id INTEGER, lof_code TEXT, lof_name TEXT, etf_code TEXT, etf_name TEXT, track_index TEXT, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')), PRIMARY KEY (lof_code, etf_code))''')
                for _, row in df.iterrows():
                    conn.execute('INSERT INTO etf_rotation_list (group_id, lof_code, lof_name, etf_code, etf_name, track_index) VALUES (?, ?, ?, ?, ?, ?)', (int(row['组别']), str(row['LOF基金代码']).split('.')[0].zfill(6), str(row['LOF基金名称']), str(row['ETF基金代码']).split('.')[0].zfill(6), str(row['ETF基金名称']), str(row['跟踪指数'])))
                conn.commit()
                logger.info(f"Successfully synced {len(df)} rotation config items.")
            except Exception as e: logger.error(f"Failed to sync rotation config: {e}")
            finally: conn.close()