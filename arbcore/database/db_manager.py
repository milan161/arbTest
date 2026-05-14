import os
import time
import sqlite3
import threading
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path=None):
        """
        初始化数据库管理器
        :param db_path: SQLite数据库文件的路径，默认放置在项目根目录的 database/arb_master.db
        """
        if db_path is None:
            # 自动定位到项目根目录 D:\Study\arbTest\database\arb_master.db
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
            db_path = os.path.join(base_dir, 'database', 'arb_master.db')
            
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        self.db_path = db_path
        self.lock = threading.Lock() # 即使开启了WAL，多线程并发写入时使用Lock可以避免 database is locked 异常
        self.init_db()
        
    def _get_conn(self):
        try:
            logger.info(f"Attempting to connect to database: {self.db_path}")
            logger.info(f"Database directory exists: {os.path.exists(os.path.dirname(self.db_path))}")
            if os.path.exists(self.db_path):
                logger.info(f"Database file size: {os.path.getsize(self.db_path)} bytes")
            
            conn = sqlite3.connect(self.db_path, timeout=15.0)
            
            try:
                conn.execute('PRAGMA journal_mode=WAL;')
                logger.info("WAL mode enabled successfully")
            except Exception as wal_error:
                logger.warning(f"Failed to enable WAL mode: {wal_error}. Falling back to default journal mode.")
            
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            logger.error(f"Database path: {self.db_path}")
            raise
    
    def init_db(self):
        with self.lock:
            conn = self._get_conn()
            conn.execute('CREATE TABLE IF NOT EXISTS fund_data (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, fund_code TEXT, price REAL, nav REAL, premium REAL, static_val REAL, val_error REAL, created_at TEXT, UNIQUE(date, fund_code))')
            
            # 热更新：为已存在的 fund_data 表无损添加两个新字段 (防止直接运行报错)
            try:
                conn.execute('ALTER TABLE fund_data ADD COLUMN static_val REAL')
                conn.execute('ALTER TABLE fund_data ADD COLUMN val_error REAL')
            except sqlite3.OperationalError:
                pass  # 如果字段已存在会抛出此异常，直接忽略即可
            
            # 彻底废弃旧的秒级期货表和独立的校准表
            conn.execute('DROP TABLE IF EXISTS futures_data')
            conn.execute('DROP TABLE IF EXISTS future_calibration')
            conn.execute('DROP TABLE IF EXISTS macro_data')
            conn.execute('DROP TABLE IF EXISTS api_sync_status')
            
            # 系统健康状态监控表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS system_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    status TEXT,
                    message TEXT,
                    timestamp DATETIME DEFAULT (datetime('now', 'localtime'))
                )
            ''')

            # 新增：独立的人民币汇率表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS exchange_rate (
                    date TEXT PRIMARY KEY,
                    usd_cny_mid REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
                )
            ''')

            # 新增：底层 ETF/指数 每日收盘价格表 (取代 basic.csv 里的各类 ETF 列)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS usa_etf_daily_prices (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL,
                    netvalue REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, symbol)
                )
            ''')
            
            # 热更新：为已存在的 usa_etf_daily_prices 表添加 netvalue 字段
            try:
                conn.execute('ALTER TABLE usa_etf_daily_prices ADD COLUMN netvalue REAL')
            except sqlite3.OperationalError:
                pass  # 如果字段已存在会抛出此异常，直接忽略即可
            
            # 新增：纯净指数每日价格表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS index_daily (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    price REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, symbol)
                )
            ''')
            
            # 新增：合并后的每日期货历史数据表 (结算价 + 校准值)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS futures_daily (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    settle_price REAL,
                    calibration REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, symbol)
                )
            ''')
            
            # 新增：基金底层篮子权重表 (解决黄金、原油等持仓多个区域变种 ETF 的 1对N 关系)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS fund_basket_weights (
                    date TEXT NOT NULL,
                    fund_code TEXT NOT NULL,
                    underlying_symbol TEXT NOT NULL,
                    weight REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, fund_code, underlying_symbol)
                )
            ''')
            
            # 新增：基金每日因子表 (规范化提取后的常量，供前端极速读取)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS fund_daily_factors (
                    date TEXT NOT NULL,
                    fund_code TEXT NOT NULL,
                    calibration REAL,
                    hedge REAL,
                    position REAL,
                    nav REAL,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, fund_code)
                )
            ''')
            
            # 热更新：为已存在的 fund_daily_factors 表无损添加 nav 字段
            try:
                conn.execute('ALTER TABLE fund_daily_factors ADD COLUMN nav REAL')
            except sqlite3.OperationalError:
                pass
            
            # 新增：原始 API 数据表 (直接存原汁原味的 JSON，废弃 basic.csv)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS raw_api_data (
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    raw_content TEXT,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, source)
                )
            ''')
            
            # 修改：通用每日访问状态控制表 (防止封禁或超限，适用外汇/东财/新浪等)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS access_sync_status (
                    sync_date TEXT NOT NULL,
                    access_source TEXT NOT NULL,
                    sync_time TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (sync_date, access_source)
                )
            ''')
            
            # 建立核心索引
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fund_code_date ON fund_daily_factors (fund_code, date DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_health_component ON system_health(component)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_etf_prices_date ON usa_etf_daily_prices(date DESC)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_fund_basket ON fund_basket_weights(fund_code, date DESC)')
            
            # 新增：ETF轮动班级专属的原始 API 数据表 (物理隔离保密)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS etf_raw_api_data (
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    raw_content TEXT,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (date, source)
                )
            ''')
            
            # 新增：ETF 轮动套利监控配置池表 (彻底替代 ETFList.csv)
            # 修复：主键必须是 (lof_code, etf_code) 的复合键，防止一对多关系保存时引发约束报错
            conn.execute('''
                CREATE TABLE IF NOT EXISTS etf_rotation_list (
                    group_id INTEGER,
                    lof_code TEXT,
                    lof_name TEXT,
                    etf_code TEXT,
                    etf_name TEXT,
                    track_index TEXT,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                    PRIMARY KEY (lof_code, etf_code)
                )
            ''')
            
            # 新增：JSL 模块专属 - 基金监控配置池 (隔离原 LOF/ETF 业务)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jsl_fund_list (
                    category TEXT,
                    fund_code TEXT PRIMARY KEY,
                    fund_name TEXT,
                    related_index TEXT
                )
            ''')

            # 新增：JSL 模块专属 - AKShare 全市场基金申赎状态缓存表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS fund_purchase_status (
                    fund_code TEXT PRIMARY KEY,
                    purchase_status TEXT,
                    redemption_status TEXT,
                    purchase_fee TEXT,
                    redemption_fee TEXT,
                    updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
                )
            ''')
            
            conn.commit()
            conn.close()
        
    def save_fund_data(self, date, fund_code, price, nav, premium):
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT OR REPLACE INTO fund_data (date, fund_code, price, nav, premium, created_at) VALUES (?, ?, ?, ?, ?, ?)', 
                         (date, fund_code, price, nav, premium, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
            
    def update_fund_valuation(self, date: str, fund_code: str, static_val: float, val_error: float):
        """将012计算出的静态估值与误差更新到 fund_data 全局表中"""
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                UPDATE fund_data 
                SET static_val = ?, val_error = ?
                WHERE date = ? AND fund_code = ?
            ''', (static_val, val_error, date, fund_code))
            conn.commit()
            conn.close()
        
    # ================= 规范化基础数据写入 (Macro & ETF) =================
    def upsert_exchange_rate(self, date: str, usd_cny_mid: float):
        """插入或覆盖人民币中间价"""
        with self.lock:
            conn = self._get_conn()
            query = "INSERT OR REPLACE INTO exchange_rate (date, usd_cny_mid, updated_at) VALUES (?, ?, (datetime('now', 'localtime')))"
            conn.execute(query, (date, usd_cny_mid))
            conn.commit()
            conn.close()
            
    def upsert_futures_daily(self, date: str, symbol: str, settle_price: float = None, calibration: float = None):
        """插入或更新大宗商品每日历史结算价及校准值"""
        with self.lock:
            conn = self._get_conn()
            conn.execute("INSERT OR IGNORE INTO futures_daily (date, symbol) VALUES (?, ?)", (date, symbol))
            if settle_price is not None:
                conn.execute("UPDATE futures_daily SET settle_price = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (settle_price, date, symbol))
            if calibration is not None:
                conn.execute("UPDATE futures_daily SET calibration = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (calibration, date, symbol))
            conn.commit()
            conn.close()
            
    def upsert_usa_etf_price(self, date: str, symbol: str, price: float, netvalue: float = None):
        """插入或覆盖特定底层 ETF 在某日的基准价格（如 GLD, ^GLD-EU, XOP）
        注意：只更新 price 字段，保留已有的 netvalue 不被覆盖
        """
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            # 优先 UPDATE，只覆盖 price，保留 netvalue（如果新值不为空则更新）
            cursor.execute("UPDATE usa_etf_daily_prices SET price = ?, netvalue = COALESCE(?, netvalue), updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (price, netvalue, date, symbol))
            if cursor.rowcount == 0:
                # 没有更新到任何行，则 INSERT（此时 netvalue 来自外部导入，不覆盖）
                query = "INSERT INTO usa_etf_daily_prices (date, symbol, price, netvalue) VALUES (?, ?, ?, ?)"
                cursor.execute(query, (date, symbol, price, netvalue))
            conn.commit()
            conn.close()
            
    def upsert_index_price(self, date: str, symbol: str, price: float):
        """插入或覆盖特定指数在某日的基准价格（如 .INX, .NDX）"""
        with self.lock:
            conn = self._get_conn()
            query = "INSERT OR REPLACE INTO index_daily (date, symbol, price, updated_at) VALUES (?, ?, ?, (datetime('now', 'localtime')))"
            conn.execute(query, (date, symbol, price))
            conn.commit()
            conn.close()
            
    # ================= 基金每日因子专用方法 =================
    def upsert_fund_factor(self, date: str, fund_code: str, calibration: float, hedge: float, position: float, nav: float = None):
        """插入或覆盖特定基金的校准对冲因子"""
        with self.lock:
            conn = self._get_conn()
            query = """
            INSERT OR REPLACE INTO fund_daily_factors (date, fund_code, calibration, hedge, position, nav, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, (datetime('now', 'localtime')))
            """
            conn.execute(query, (date, fund_code, calibration, hedge, position, nav))
            conn.commit()
            conn.close()
            
    def upsert_fund_basket_weight(self, date: str, fund_code: str, underlying_symbol: str, weight: float):
        """插入或覆盖特定基金在某日的底层篮子权重 (支持1对N)"""
        with self.lock:
            conn = self._get_conn()
            query = """
            INSERT OR REPLACE INTO fund_basket_weights (date, fund_code, underlying_symbol, weight, updated_at)
            VALUES (?, ?, ?, ?, (datetime('now', 'localtime')))
            """
            conn.execute(query, (date, fund_code, underlying_symbol, weight))
            conn.commit()
            conn.close()

    def get_latest_fund_factor(self, fund_code: str):
        """前端和实时估值专用：极速获取最新一天的常量折叠参数"""
        conn = self._get_conn()
        query = """
        SELECT date, calibration, hedge, position
        FROM fund_daily_factors 
        WHERE fund_code = ? 
        ORDER BY date DESC LIMIT 1
        """
        cursor = conn.execute(query, (fund_code,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "date": result[0], "calibration": result[1], 
                "hedge": result[2], "position": result[3]
            }
        return None

    def get_fund_basket(self, date: str, fund_code: str):
        """获取基金某天的底层成分篮子及权重"""
        conn = self._get_conn()
        query = "SELECT underlying_symbol, weight FROM fund_basket_weights WHERE date = ? AND fund_code = ?"
        cursor = conn.execute(query, (date, fund_code))
        results = cursor.fetchall()
        conn.close()
        return [{"symbol": row[0], "weight": row[1]} for row in results]
        
    # ================= 原始数据湖(Data Lake)专用方法 =================
    def save_raw_api_data(self, date: str, source: str, raw_content: str):
        """保存原汁原味的 API 返回字符串 (如 JSON)"""
        with self.lock:
            conn = self._get_conn()
            query = """
            INSERT OR REPLACE INTO raw_api_data (date, source, raw_content, updated_at)
            VALUES (?, ?, ?, (datetime('now', 'localtime')))
            """
            conn.execute(query, (date, source, raw_content))
            conn.commit()
            conn.close()

    def get_raw_api_data(self, date: str, source: str):
        """读取某天原汁原味的 API 数据"""
        conn = self._get_conn()
        query = "SELECT raw_content FROM raw_api_data WHERE date = ? AND source = ?"
        cursor = conn.execute(query, (date, source))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    # ================= ETF 轮动班级专属的 API 存取方法 =================
    def save_etf_raw_api_data(self, date: str, source: str, raw_content: str):
        """保存原汁原味的 API 返回字符串 (专属 etf_raw_api_data)"""
        with self.lock:
            conn = self._get_conn()
            query = """
            INSERT OR REPLACE INTO etf_raw_api_data (date, source, raw_content, updated_at)
            VALUES (?, ?, ?, (datetime('now', 'localtime')))
            """
            conn.execute(query, (date, source, raw_content))
            conn.commit()
            conn.close()
            
    def get_etf_raw_api_data(self, date: str, source: str):
        conn = self._get_conn()
        query = "SELECT raw_content FROM etf_raw_api_data WHERE date = ? AND source = ?"
        cursor = conn.execute(query, (date, source))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    # ================= 访问频率及防封号控制 =================
    def mark_access_synced(self, sync_date: str, source: str):
        """标记当前自然日已经访问过某个数据源，防止重复调用封号/IP限制"""
        with self.lock:
            conn = self._get_conn()
            query = "INSERT OR REPLACE INTO access_sync_status (sync_date, access_source, sync_time) VALUES (?, ?, (datetime('now', 'localtime')))"
            conn.execute(query, (sync_date, source))
            conn.commit()
            conn.close()
            
    def is_access_synced_today(self, sync_date: str, source: str) -> bool:
        """检查当前自然日是否已经成功访问过指定的数据源"""
        conn = self._get_conn()
        query = "SELECT 1 FROM access_sync_status WHERE sync_date = ? AND access_source = ?"
        cursor = conn.execute(query, (sync_date, source))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def remove_access_sync_status(self, sync_date: str, source: str):
        """移除指定日期和来源的访问同步状态，强制允许重新抓取"""
        with self.lock:
            conn = self._get_conn()
            query = "DELETE FROM access_sync_status WHERE sync_date = ? AND access_source = ?"
            conn.execute(query, (sync_date, source))
            conn.commit()
            conn.close()


    # 兼容过渡期旧代码 (防止系统中其他旧代码报错)
    def mark_api_synced(self, sync_date: str, source: str):
        self.mark_access_synced(sync_date, source)

    def is_api_synced_today(self, sync_date: str, source: str) -> bool:
        return self.is_access_synced_today(sync_date, source)

    # ================= 轮动套利 (ETFRotate) 专用方法 =================
    def sync_etf_rotation_list(self, df):
        """将 ETFList.csv 的配置同步到数据库中"""
        with self.lock:
            try:
                conn = self._get_conn()
                # 修复：直接销毁旧表并用正确的复合主键重建，彻底清除可能残留的错误约束
                conn.execute('DROP TABLE IF EXISTS etf_rotation_list')
                conn.execute('''
                    CREATE TABLE etf_rotation_list (
                        group_id INTEGER,
                        lof_code TEXT,
                        lof_name TEXT,
                        etf_code TEXT,
                        etf_name TEXT,
                        track_index TEXT,
                        updated_at TIMESTAMP DEFAULT (datetime('now', 'localtime')),
                        PRIMARY KEY (lof_code, etf_code)
                    )
                ''')
                
                for _, row in df.iterrows():
                    conn.execute('''
                        INSERT INTO etf_rotation_list 
                        (group_id, lof_code, lof_name, etf_code, etf_name, track_index)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        int(row['组别']), 
                        str(row['LOF基金代码']).split('.')[0].zfill(6), 
                        str(row['LOF基金名称']),
                        str(row['ETF基金代码']).split('.')[0].zfill(6),
                        str(row['ETF基金名称']),
                        str(row['跟踪指数'])
                    ))
                conn.commit()
                logger.info(f"已成功将 {len(df)} 条轮动配置同步至数据库 etf_rotation_list 表。")
            except Exception as e:
                logger.error(f"同步轮动配置池失败: {e}")
            finally:
                conn.close()

    # ================= JSL 监控模块 (集思录) 专用方法 =================
    def sync_jsl_fund_list(self, fund_list: List[Dict[str, str]]):
        """将 JSL 的基金配置清单同步到数据库中，彻底替代 fund_list.csv"""
        with self.lock:
            try:
                conn = self._get_conn()
                for item in fund_list:
                    conn.execute('''
                        INSERT OR REPLACE INTO jsl_fund_list 
                        (category, fund_code, fund_name, related_index)
                        VALUES (?, ?, ?, ?)
                    ''', (item['category'], item['code'], item['name'], item.get('related_index', '-')))
                conn.commit()
                logger.info(f"已成功将 {len(fund_list)} 条 JSL 配置同步至数据库。")
            except Exception as e:
                logger.error(f"同步 JSL 基金清单失败: {e}")
            finally:
                conn.close()

    def get_jsl_fund_list(self) -> List[Dict[str, str]]:
        """获取 JSL 监控配置池"""
        conn = self._get_conn()
        cursor = conn.execute("SELECT category, fund_code, fund_name, related_index FROM jsl_fund_list")
        results = [{"category": r[0], "code": r[1], "name": r[2], "related_index": r[3]} for r in cursor.fetchall()]
        conn.close()
        return results

    def batch_save_fund_purchase_status(self, df):
        """批量保存 AKShare 获取的申赎状态数据到本地库"""
        with self.lock:
            try:
                conn = self._get_conn()
                records = df.to_records(index=False)
                conn.executemany('''
                    INSERT OR REPLACE INTO fund_purchase_status 
                    (fund_code, purchase_status, redemption_status, purchase_fee, redemption_fee, updated_at)
                    VALUES (?, ?, ?, ?, ?, (datetime('now', 'localtime')))
                ''', records)
                conn.commit()
                logger.info(f"成功将 {len(df)} 条全市场申赎状态缓存入库！")
            except Exception as e:
                logger.error(f"批量保存 AKShare 申赎状态失败: {e}")
            finally:
                conn.close()

    def get_fund_purchase_status(self, fund_code: str) -> Dict[str, str]:
        """极速获取单只基金的申赎费率，如果没找到则返回兜底数据"""
        conn = self._get_conn()
        cursor = conn.execute('''
            SELECT purchase_status, redemption_status, purchase_fee, redemption_fee 
            FROM fund_purchase_status WHERE fund_code = ?
        ''', (fund_code,))
        r = cursor.fetchone()
        conn.close()
        if r:
            return {
                'purchase_status': r[0], 'redemption_status': r[1],
                'purchase_fee': r[2], 'redemption_fee': r[3]
            }
        return {
            'purchase_status': '未知', 'redemption_status': '未知',
            'purchase_fee': '0%', 'redemption_fee': '0.50%'
        }

    # ================= 系统运行维护方法 =================
    def get_latest_futures_price(self, symbol: str) -> Optional[float]:
        """获取最新的期货历史结算价"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT settle_price FROM futures_daily 
                WHERE symbol = ? 
                ORDER BY date DESC LIMIT 1
            ''', (symbol,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result and result[0] is not None else None
        except Exception as e:
            logger.error(f"获取期货价格失败: {e}")
            return None

    def get_latest_fund_price(self, code: str) -> Optional[Dict[str, Any]]:
        """获取最新的 fund 数据记录"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT fund_code, price, nav, premium, created_at, date 
                FROM fund_data 
                WHERE fund_code = ? 
                ORDER BY date DESC LIMIT 1
            ''', (code,))
            result = cursor.fetchone()
            conn.close()
            if result:
                return {
                    'code': result[0],
                    'price': result[1],
                    'nav': result[2],
                    'premium': result[3],
                    'timestamp': result[4],
                    'date': result[5]
                }
            return None
        except Exception as e:
            logger.error(f"获取LOF价格失败: {e}")
            return None

    def get_health_status(self, component: str = None) -> List[Dict[str, Any]]:
        """获取系统健康日志"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            if component:
                cursor.execute('SELECT component, status, message, timestamp FROM system_health WHERE component = ? ORDER BY timestamp DESC LIMIT 10', (component,))
            else:
                cursor.execute('SELECT component, status, message, timestamp FROM system_health ORDER BY timestamp DESC LIMIT 50')
            results = cursor.fetchall()
            conn.close()
            return [
                {'component': row[0], 'status': row[1], 'message': row[2], 'timestamp': row[3]}
                for row in results
            ]
        except Exception as e:
            logger.error(f"获取健康状态失败: {e}")
            return []
            
    def save_health_status(self, component: str, status: str, message: str = ""):
        with self.lock:
            try:
                conn = self._get_conn()
                conn.execute('''
                    INSERT INTO system_health (component, status, message, timestamp)
                    VALUES (?, ?, ?, (datetime('now', 'localtime')))
                ''', (component, status, message, datetime.now()))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"保存健康状态失败: {e}")

    def batch_save_futures_data(self, data_list: List[Dict[str, Any]]):
        """批量保存期货数据 (适配新表结构)"""
        try:
            for data in data_list:
                date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
                sym = data.get('symbol')
                price = data.get('price', data.get('settle_price'))
                self.upsert_futures_daily(date=date_str, symbol=sym, settle_price=price)
            logger.info(f"批量保存期货数据: {len(data_list)}条")
        except Exception as e:
            logger.error(f"批量保存期货数据失败: {e}")
            
    def batch_save_fund_prices(self, data_list: List[Dict[str, Any]]):
        """批量保存 fund 价格 (适配新表结构)"""
        try:
            for data in data_list:
                date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
                self.save_fund_data(
                    date=date_str, 
                    fund_code=data.get('code'), 
                    price=data.get('price'), 
                    nav=data.get('nav'), 
                    premium=data.get('premium')
                )
            logger.info(f"批量保存fund价格: {len(data_list)}条")
        except Exception as e:
            logger.error(f"批量保存fund价格失败: {e}")

    def cleanup_old_data(self, days: int = 30):
        """清理 30 天前的常规行情数据，防止数据库无限膨胀"""
        with self.lock:
            try:
                conn = self._get_conn()
                cutoff_date = (datetime.now() - pd.Timedelta(days=days)).strftime('%Y-%m-%d')
                
                conn.execute('DELETE FROM futures_daily WHERE date < ?', (cutoff_date,))
                conn.execute('DELETE FROM usa_etf_daily_prices WHERE date < ?', (cutoff_date,))
                conn.execute('DELETE FROM fund_data WHERE date < ?', (cutoff_date,))
                conn.execute('DELETE FROM system_health WHERE timestamp < ?', (cutoff_date,))
                
                conn.commit()
                conn.close()
                logger.info(f"清理旧数据完成，保留最近 {days} 天")
            except Exception as e:
                logger.error(f"清理旧数据失败: {e}")
                
    def vacuum_database(self):
        """优化 SQLite 数据库空间"""
        try:
            conn = self._get_conn()
            conn.execute('VACUUM')
            conn.commit()
            conn.close()
            logger.info("数据库 VACUUM 优化完成")
        except Exception as e:
            logger.error(f"数据库优化失败: {e}")