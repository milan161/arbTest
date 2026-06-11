from .base import BaseManager
import sqlite3
import pandas as pd
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class FundManager(BaseManager):
    def save_fund_data(self, date, fund_code, price, nav, premium):
        with self.lock:
            conn = self._get_conn()
            conn.execute('INSERT OR REPLACE INTO fund_data (date, fund_code, price, nav, premium, created_at) VALUES (?, ?, ?, ?, ?, ?)', 
                         (date, fund_code, price, nav, premium, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
            conn.commit()
            conn.close()
            
    def update_fund_valuation(self, date: str, fund_code: str, static_val: float, val_error: float):
        with self.lock:
            conn = self._get_conn()
            conn.execute('''
                UPDATE fund_data 
                SET static_val = ?, val_error = ?
                WHERE date = ? AND fund_code = ?
            ''', (static_val, val_error, date, fund_code))
            conn.commit()
            conn.close()

    def upsert_fund_factor(self, date: str, fund_code: str, calibration: float, hedge: float, position: float, nav: float = None):
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
        conn = self._get_conn()
        query = "SELECT underlying_symbol, weight FROM fund_basket_weights WHERE date = ? AND fund_code = ?"
        cursor = conn.execute(query, (date, fund_code))
        results = cursor.fetchall()
        conn.close()
        return [{"symbol": row[0], "weight": row[1]} for row in results]

    def get_latest_fund_price(self, code: str) -> Optional[Dict[str, Any]]:
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
            logger.error(f"Failed to get fund price: {e}")
            return None

    def batch_save_fund_prices(self, data_list: List[Dict[str, Any]]):
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
            logger.info(f"Batch saved fund prices: {len(data_list)} items")
        except Exception as e:
            logger.error(f"Failed to batch save fund prices: {e}")
            
    def sync_jsl_fund_list(self, fund_list: List[Dict[str, str]]):
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
                logger.info(f"Successfully synced {len(fund_list)} JSL items to database.")
            except Exception as e:
                logger.error(f"Failed to sync JSL fund list: {e}")
            finally:
                conn.close()

    def get_jsl_fund_list(self) -> List[Dict[str, str]]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT category, fund_code, fund_name, related_index FROM jsl_fund_list")
        results = [{"category": r[0], "code": r[1], "name": r[2], "related_index": r[3]} for r in cursor.fetchall()]
        conn.close()
        return results

    def batch_save_fund_purchase_status(self, df):
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
                logger.info(f"Successfully cached {len(df)} fund purchase status items!")
            except Exception as e:
                logger.error(f"Failed to batch save fund purchase status: {e}")
            finally:
                conn.close()

    def get_fund_purchase_status(self, fund_code: str) -> Dict[str, str]:
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

    def sync_unified_fund_list(self, fund_list: List[Dict[str, Any]]):
        with self.lock:
            try:
                conn = self._get_conn()
                for item in fund_list:
                    conn.execute('''
                        INSERT OR REPLACE INTO unified_fund_list
                        (category, fund_code, fund_name, related_index, pos_ratio, target_type)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (item['category'], item['code'], item['name'], item.get('related_index', '-'), item.get('pos_ratio', 0.95), item.get('target_type', 'ETF')))
                conn.commit()
                logger.info(f"Successfully synced {len(fund_list)} unified items to database.")
            except Exception as e:
                logger.error(f"Failed to sync unified fund list: {e}")
            finally:
                conn.close()

    def get_unified_fund_list(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.execute("SELECT category, fund_code, fund_name, related_index, pos_ratio, target_type FROM unified_fund_list")
        results = [{"category": r[0], "code": r[1], "name": r[2], "related_index": r[3], "pos_ratio": r[4], "target_type": r[5]} for r in cursor.fetchall()]
        conn.close()
        return results

    def save_unified_history(self, date_str, fund_code, **kwargs):
        """
        [V3.0] 极简通用型历史数据保存器
        支持动态列更新，自动处理 NULL 覆盖问题。
        """
        with self.lock:
            conn = self._get_conn()
            try:
                # 过滤掉 None 值，避免覆盖已有数据
                valid_data = {k: v for k, v in kwargs.items() if v is not None}
                if not valid_data: return

                cols = ['date', 'fund_code'] + list(valid_data.keys())
                placeholders = ['?'] * len(cols)
                vals = [date_str, fund_code] + list(valid_data.values())

                update_clause = ", ".join([f"{k} = excluded.{k}" for k in valid_data.keys()])

                query = f"""
                    INSERT INTO unified_fund_history ({", ".join(cols)})
                    VALUES ({", ".join(placeholders)})
                    ON CONFLICT(date, fund_code) DO UPDATE SET
                    {update_clause}
                """
                conn.execute(query, vals)
                conn.commit()
            except Exception as e:
                logger.error(f"Failed to save unified history for {fund_code}: {e}")
            finally:
                conn.close()

