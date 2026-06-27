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
            conn.execute('''CREATE TABLE IF NOT EXISTS fund_purchase_status (fund_code TEXT PRIMARY KEY, purchase_status TEXT, redemption_status TEXT, purchase_fee TEXT, redemption_fee TEXT, purchase_limit REAL, updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')))''')
            # 兼容旧表：如果 purchase_limit 列不存在则添加
            try:
                conn.execute("ALTER TABLE fund_purchase_status ADD COLUMN purchase_limit REAL")
            except:
                pass
            
            # 数据源配置中心 (VUE 控制台的核心)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS data_source_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    module TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    config_json TEXT DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(module, source_name)
                )
            ''')
            
            # 种子数据：初始化实时行情的优先级
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM data_source_config WHERE module = 'realtime_market'")
            if cursor.fetchone()[0] == 0:
                initial_sources = [
                    ('realtime_market', 'tdx', 1, 1, '{"desc": "通达信内存直连"}'),
                    ('realtime_market', 'guojin', 2, 1, '{"desc": "国金QMT (xtquant)"}'),
                    ('realtime_market', 'galaxy', 3, 1, '{"desc": "银河QMT (Socket)"}'),
                    ('realtime_market', 'sina', 4, 1, '{"desc": "新浪财经轮询"}')
                ]
                conn.executemany('''
                    INSERT INTO data_source_config (module, source_name, priority, is_active, config_json)
                    VALUES (?, ?, ?, ?, ?)
                ''', initial_sources)
                
                # 种子数据：初始化历史数据的优先级
                historical_sources = [
                    ('historical_nav', 'eastmoney', 1, 1, '{"desc": "东方财富净值"}'),
                    ('historical_price', 'sina', 1, 1, '{"desc": "新浪/腾讯价格"}')
                ]
                conn.executemany('''
                    INSERT INTO data_source_config (module, source_name, priority, is_active, config_json)
                    VALUES (?, ?, ?, ?, ?)
                ''', historical_sources)

            conn.execute('''CREATE TABLE IF NOT EXISTS unified_fund_list (category TEXT, fund_code TEXT PRIMARY KEY, fund_name TEXT, related_index TEXT, pos_ratio REAL DEFAULT 0.95, target_type TEXT DEFAULT 'ETF')''')
            conn.execute('''CREATE TABLE IF NOT EXISTS jsl_fund_list (category TEXT, fund_code TEXT PRIMARY KEY, fund_name TEXT, related_index TEXT, pos_ratio REAL DEFAULT 0.95)''')
            try: conn.execute('ALTER TABLE unified_fund_list ADD COLUMN target_type TEXT DEFAULT \'ETF\'')
            except sqlite3.OperationalError: pass
            try: conn.execute('ALTER TABLE jsl_fund_list ADD COLUMN target_type TEXT DEFAULT \'ETF\'')
            except sqlite3.OperationalError: pass
            # [V11.0] 补齐 idx_code / idx_name 列（兼容旧版分享数据库）
            try: conn.execute('ALTER TABLE unified_fund_list ADD COLUMN idx_code TEXT DEFAULT \'-\''')
            except sqlite3.OperationalError: pass
            try: conn.execute('ALTER TABLE unified_fund_list ADD COLUMN idx_name TEXT DEFAULT \'-\''')
            except sqlite3.OperationalError: pass

            # JSL Index history and realtime tables
            conn.execute('''CREATE TABLE IF NOT EXISTS index_history (symbol TEXT NOT NULL, date TEXT NOT NULL, close REAL, source TEXT, PRIMARY KEY (symbol, date))''')
            conn.execute('''CREATE TABLE IF NOT EXISTS index_realtime_quotes (symbol TEXT PRIMARY KEY, name TEXT, last_price REAL, prev_close REAL, pct_change REAL, quote_time TEXT, source TEXT, updated_at TEXT)''')

            # Create unified_fund_history if it doesn't exist
            conn.execute('''
                CREATE TABLE IF NOT EXISTS unified_fund_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    fund_code TEXT NOT NULL,
                    price REAL,
                    price_change REAL,
                    nav REAL,
                    nav_date TEXT,
                    volume REAL,
                    shares REAL,
                    shares_added REAL,
                    turnover_rate TEXT,
                    static_val REAL,
                    rt_val REAL,
                    premium REAL,
                    rt_premium REAL,
                    index_close REAL,
                    index_pct REAL,
                    calibration REAL,
                    purchase_status TEXT,
                    redemption_status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, fund_code)
                )
            ''')

            # [V3.8] 新增分时采样表，用于展示深度分析的分时曲线
            conn.execute('''
                CREATE TABLE IF NOT EXISTS fund_intraday_quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fund_code TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    price REAL,
                    rt_val REAL,
                    premium REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_intraday_code_date ON fund_intraday_quotes(fund_code, date)')

            # [V4.6] 新增实盘交易对账表 (强化多账号与快速赎回支持)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fund_code TEXT NOT NULL,
                    fund_name TEXT,
                    account_suffix TEXT, -- 账号尾号 (如 1 或 6)
                    action TEXT, -- BUY / SELL / REDEEM
                    volume INTEGER,
                    price REAL,
                    amount REAL,
                    hedge_symbol TEXT,
                    hedge_price REAL,
                    hedge_vol INTEGER,
                    fees REAL DEFAULT 0,
                    trade_date TEXT DEFAULT (date('now', 'localtime')),
                    remind_date TEXT, -- 赎回提醒日
                    status TEXT DEFAULT 'ACTIVE', -- ACTIVE / CLOSED
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # [V4.6] 基金费率与佣金设置表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS fund_fees (
                    fund_code TEXT PRIMARY KEY,
                    redemption_fee_rate REAL DEFAULT 0.5, -- 正常赎回费率 (%)
                    commission_rate REAL DEFAULT 0, -- 券商返佣或折扣 (%)
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 券商赎回费表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS broker_redemption_fees (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT,
                    fund_code TEXT,
                    broker_name TEXT,
                    fee_rate TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(fund_code, broker_name)
                )
            ''')

            # [V9.2] 套利对账本（匹配Excel格式：A股买卖+美股空平+盈亏汇总）
            conn.execute('''
                CREATE TABLE IF NOT EXISTS arbitrage_pairs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fund_code TEXT,
                    fund_name TEXT,
                    -- A股买入
                    buy_date TEXT,
                    buy_price REAL,
                    buy_volume INTEGER,
                    buy_amount REAL,
                    buy_account TEXT,
                    -- A股卖出/赎回
                    sell_date TEXT,
                    sell_price REAL,
                    sell_amount REAL,
                    redemption_fee REAL DEFAULT 0,
                    -- 美股做空
                    hedge_symbol TEXT,
                    short_date TEXT,
                    short_price REAL,
                    short_volume INTEGER,
                    short_amount REAL,
                    -- 美股买平
                    cover_date TEXT,
                    cover_price REAL,
                    cover_amount REAL,
                    us_commission REAL DEFAULT 0,
                    -- 汇总
                    pnl_rmb REAL,
                    pnl_usd REAL,
                    status TEXT DEFAULT 'ACTIVE',
                    buy_notes TEXT,
                    sell_notes TEXT,
                    notes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            conn.close()

    # Delegate methods
    def save_fund_data(self, *args, **kwargs): return self.funds.save_fund_data(*args, **kwargs)
    def update_fund_valuation(self, *args, **kwargs): return self.funds.update_fund_valuation(*args, **kwargs)
    def upsert_fund_factor(self, *args, **kwargs): return self.funds.upsert_fund_factor(*args, **kwargs)
    def update_fund_pos_ratio(self, *args, **kwargs): return self.funds.update_fund_pos_ratio(*args, **kwargs)
    def upsert_fund_basket_weight(self, *args, **kwargs): return self.funds.upsert_fund_basket_weight(*args, **kwargs)
    def get_latest_fund_factor(self, *args, **kwargs): return self.funds.get_latest_fund_factor(*args, **kwargs)
    def get_fund_basket(self, *args, **kwargs): return self.funds.get_fund_basket(*args, **kwargs)
    def get_latest_fund_price(self, *args, **kwargs): return self.funds.get_latest_fund_price(*args, **kwargs)
    def batch_save_fund_prices(self, *args, **kwargs): return self.funds.batch_save_fund_prices(*args, **kwargs)
    def sync_unified_fund_list(self, *args, **kwargs): return self.funds.sync_unified_fund_list(*args, **kwargs)
    def get_unified_fund_list(self, *args, **kwargs): return self.funds.get_unified_fund_list(*args, **kwargs)
    def sync_jsl_fund_list(self, *args, **kwargs): return self.funds.sync_jsl_fund_list(*args, **kwargs)
    def get_jsl_fund_list(self, *args, **kwargs): return self.funds.get_jsl_fund_list(*args, **kwargs)
    def batch_save_fund_purchase_status(self, *args, **kwargs): return self.funds.batch_save_fund_purchase_status(*args, **kwargs)
    def get_fund_purchase_status(self, *args, **kwargs): return self.funds.get_fund_purchase_status(*args, **kwargs)
    def save_unified_history(self, *args, **kwargs): return self.funds.save_unified_history(*args, **kwargs)

    def upsert_exchange_rate(self, *args, **kwargs): return self.market.upsert_exchange_rate(*args, **kwargs)
    def upsert_hkd_exchange_rate(self, *args, **kwargs): return self.market.upsert_hkd_exchange_rate(*args, **kwargs)
    def upsert_futures_daily(self, *args, **kwargs): return self.market.upsert_futures_daily(*args, **kwargs)
    def upsert_usa_etf_price(self, *args, **kwargs): return self.market.upsert_usa_etf_price(*args, **kwargs)

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
    def get_data_source_config(self, *args, **kwargs): return self.system.get_data_source_config(*args, **kwargs)
    def update_data_source_config(self, *args, **kwargs): return self.system.update_data_source_config(*args, **kwargs)

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
