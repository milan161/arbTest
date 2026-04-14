import sqlite3
import os
import threading
import time
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str = 'data/lof_arb.db'):
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_database()
    
    def _init_database(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS futures_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    price REAL,
                    source TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS lof_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL,
                    price REAL,
                    nav REAL,
                    premium REAL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_health (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    status TEXT,
                    message TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_futures_symbol ON futures_data(symbol)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_lof_code ON lof_prices(code)
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_health_component ON system_health(component)
            ''')
            
            conn.commit()
            logger.info(f"数据库初始化完成: {self.db_path}")
    
    def save_futures_data(self, symbol: str, price: float, source: str):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO futures_data (symbol, price, source, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (symbol, price, source, datetime.now()))
                    conn.commit()
            except Exception as e:
                logger.error(f"保存期货数据失败: {e}")
    
    def save_lof_price(self, code: str, price: float, nav: float, premium: float):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO lof_prices (code, price, nav, premium, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (code, price, nav, premium, datetime.now()))
                    conn.commit()
            except Exception as e:
                logger.error(f"保存LOF价格失败: {e}")
    
    def batch_save_futures_data(self, data_list: List[Dict[str, Any]]):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    for data in data_list:
                        cursor.execute('''
                            INSERT INTO futures_data (symbol, price, source, timestamp)
                            VALUES (?, ?, ?, ?)
                        ''', (data['symbol'], data['price'], data['source'], datetime.now()))
                    conn.commit()
                    logger.info(f"批量保存期货数据: {len(data_list)}条")
            except Exception as e:
                logger.error(f"批量保存期货数据失败: {e}")
    
    def batch_save_lof_prices(self, data_list: List[Dict[str, Any]]):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    for data in data_list:
                        cursor.execute('''
                            INSERT INTO lof_prices (code, price, nav, premium, timestamp)
                            VALUES (?, ?, ?, ?, ?)
                        ''', (data['code'], data['price'], data['nav'], data['premium'], datetime.now()))
                    conn.commit()
                    logger.info(f"批量保存LOF价格: {len(data_list)}条")
            except Exception as e:
                logger.error(f"批量保存LOF价格失败: {e}")
    
    def save_health_status(self, component: str, status: str, message: str = ""):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO system_health (component, status, message, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (component, status, message, datetime.now()))
                    conn.commit()
            except Exception as e:
                logger.error(f"保存健康状态失败: {e}")
    
    def get_latest_futures_price(self, symbol: str) -> Optional[float]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT price FROM futures_data 
                    WHERE symbol = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                ''', (symbol,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"获取期货价格失败: {e}")
            return None
    
    def get_latest_lof_price(self, code: str) -> Optional[Dict[str, Any]]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT code, price, nav, premium, timestamp FROM lof_prices 
                    WHERE code = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                ''', (code,))
                result = cursor.fetchone()
                if result:
                    return {
                        'code': result[0],
                        'price': result[1],
                        'nav': result[2],
                        'premium': result[3],
                        'timestamp': result[4]
                    }
                return None
        except Exception as e:
            logger.error(f"获取LOF价格失败: {e}")
            return None
    
    def get_health_status(self, component: str = None) -> List[Dict[str, Any]]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if component:
                    cursor.execute('''
                        SELECT component, status, message, timestamp FROM system_health 
                        WHERE component = ? 
                        ORDER BY timestamp DESC 
                        LIMIT 10
                    ''', (component,))
                else:
                    cursor.execute('''
                        SELECT component, status, message, timestamp FROM system_health 
                        ORDER BY timestamp DESC 
                        LIMIT 50
                    ''')
                results = cursor.fetchall()
                return [
                    {
                        'component': row[0],
                        'status': row[1],
                        'message': row[2],
                        'timestamp': row[3]
                    }
                    for row in results
                ]
        except Exception as e:
            logger.error(f"获取健康状态失败: {e}")
            return []
    
    def cleanup_old_data(self, days: int = 30):
        with self.lock:
            try:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cutoff_date = datetime.now() - timedelta(days=days)
                    
                    cursor.execute('''
                        DELETE FROM futures_data 
                        WHERE timestamp < ?
                    ''', (cutoff_date,))
                    
                    cursor.execute('''
                        DELETE FROM lof_prices 
                        WHERE timestamp < ?
                    ''', (cutoff_date,))
                    
                    cursor.execute('''
                        DELETE FROM system_health 
                        WHERE timestamp < ?
                    ''', (cutoff_date,))
                    
                    conn.commit()
                    logger.info(f"清理旧数据完成，保留最近{days}天")
            except Exception as e:
                logger.error(f"清理旧数据失败: {e}")
    
    def vacuum_database(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('VACUUM')
                conn.commit()
                logger.info("数据库优化完成")
        except Exception as e:
            logger.error(f"数据库优化失败: {e}")
