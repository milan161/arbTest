from .base import BaseManager
import sqlite3
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class SystemManager(BaseManager):
    def save_raw_api_data(self, date: str, source: str, raw_content: str):
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
        conn = self._get_conn()
        query = "SELECT raw_content FROM raw_api_data WHERE date = ? AND source = ?"
        cursor = conn.execute(query, (date, source))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None

    def mark_access_synced(self, sync_date: str, source: str):
        with self.lock:
            conn = self._get_conn()
            query = "INSERT OR REPLACE INTO access_sync_status (sync_date, access_source, sync_time) VALUES (?, ?, (datetime('now', 'localtime')))"
            conn.execute(query, (sync_date, source))
            conn.commit()
            conn.close()
            
    def is_access_synced_today(self, sync_date: str, source: str) -> bool:
        conn = self._get_conn()
        query = "SELECT 1 FROM access_sync_status WHERE sync_date = ? AND access_source = ?"
        cursor = conn.execute(query, (sync_date, source))
        result = cursor.fetchone()
        conn.close()
        return result is not None

    def save_health_status(self, component: str, status: str, message: str = ""):
        with self.lock:
            try:
                conn = self._get_conn()
                conn.execute('''
                    INSERT INTO system_health (component, status, message, timestamp)
                    VALUES (?, ?, ?, (datetime('now', 'localtime')))
                ''', (component, status, message))
                conn.commit()
                conn.close()
            except Exception as e:
                logger.error(f"Failed to save health status: {e}")

    def get_health_status(self, component: str = None) -> List[Dict[str, Any]]:
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
            logger.error(f"Failed to get health status: {e}")
            return []

    def remove_access_sync_status(self, sync_date: str, source: str):
        with self.lock:
            conn = self._get_conn()
            query = "DELETE FROM access_sync_status WHERE sync_date = ? AND access_source = ?"
            conn.execute(query, (sync_date, source))
            conn.commit()
            conn.close()

    def cleanup_old_data(self, days: int = 30):
        with self.lock:
            try:
                conn = self._get_conn()
                from datetime import timedelta
                cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                
                conn.execute('DELETE FROM futures_daily WHERE date < ?', (cutoff_date,))
                conn.execute('DELETE FROM usa_etf_daily_prices WHERE date < ?', (cutoff_date,))
                conn.execute('DELETE FROM system_health WHERE timestamp < ?', (cutoff_date,))
                
                sync_cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                conn.execute('DELETE FROM access_sync_status WHERE sync_date < ?', (sync_cutoff,))
                
                conn.commit()
                conn.close()
                logger.info(f"Cleaned up old data, kept last {days} days")
            except Exception as e:
                logger.error(f"Failed to cleanup old data: {e}")

    def drop_deprecated_tables(self):
        with self.lock:
            try:
                conn = self._get_conn()
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fund_history_%'")
                old_tables = [row[0] for row in cursor.fetchall()]
                if old_tables:
                    logger.info(f"🧹 Found {len(old_tables)} old tables, dropping...")
                    for table in old_tables:
                        cursor.execute(f"DROP TABLE IF EXISTS {table}")
                    conn.commit()
                    logger.info("✅ Old tables dropped.")
                conn.close()
            except Exception as e:
                logger.error(f"Failed to drop old tables: {e}")

    def vacuum_database(self):
        try:
            conn = self._get_conn()
            conn.execute('VACUUM')
            conn.commit()
            conn.close()
            logger.info("Database VACUUM completed")
        except Exception as e:
            logger.error(f"Failed to vacuum database: {e}")

    def get_data_source_config(self, module: str) -> List[Dict[str, Any]]:
        """获取指定模块的数据源配置，按优先级排序"""
        try:
            conn = self._get_conn()
            cursor = conn.cursor()
            query = """
                SELECT source_name, priority, is_active, config_json 
                FROM data_source_config 
                WHERE module = ? AND is_active = 1
                ORDER BY priority ASC
            """
            cursor.execute(query, (module,))
            results = cursor.fetchall()
            conn.close()
            return [
                {
                    'source_name': row[0],
                    'priority': row[1],
                    'is_active': row[2],
                    'config_json': row[3]
                }
                for row in results
            ]
        except Exception as e:
            logger.error(f"Failed to get data source config for {module}: {e}")
            return []

    def update_data_source_config(self, module: str, source_name: str, priority: int = None, is_active: int = None, config_json: str = None):
        """更新数据源配置"""
        with self.lock:
            try:
                conn = self._get_conn()
                updates = []
                params = []
                if priority is not None:
                    updates.append("priority = ?")
                    params.append(priority)
                if is_active is not None:
                    updates.append("is_active = ?")
                    params.append(is_active)
                if config_json is not None:
                    updates.append("config_json = ?")
                    params.append(config_json)
                
                if not updates: return
                
                params.extend([module, source_name])
                query = f"UPDATE data_source_config SET {', '.join(updates)}, updated_at = (datetime('now', 'localtime')) WHERE module = ? AND source_name = ?"
                conn.execute(query, params)
                conn.commit()
                conn.close()
                logger.info(f"Updated data source config: {module} -> {source_name}")
            except Exception as e:
                logger.error(f"Failed to update data source config: {e}")
