from .base import BaseManager
import sqlite3
import pandas as pd
from datetime import datetime
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class MarketManager(BaseManager):
    # [AI-2026-07-08] 新增 usd_cny_spot 在岸价支持
    def upsert_exchange_rate(self, date: str, usd_cny_mid: float = None, hkd_cny_mid: float = None, usd_cnh: float = None, usd_cny_spot: float = None):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            # [AI-2026-07-03] 新增 usd_cnh 列支持
            # [AI-2026-07-08] 新增 usd_cny_spot 列支持
            cursor.execute("SELECT usd_cny_mid, hkd_cny_mid, usd_cnh, usd_cny_spot FROM exchange_rate WHERE date = ?", (date,))
            row = cursor.fetchone()
            
            exist_usd = row[0] if row else None
            exist_hkd = row[1] if row else None
            exist_cnh = row[2] if row else None
            exist_spot = row[3] if row else None
            
            new_usd = usd_cny_mid if usd_cny_mid is not None else exist_usd
            new_hkd = hkd_cny_mid if hkd_cny_mid is not None else exist_hkd
            new_cnh = usd_cnh if usd_cnh is not None else exist_cnh
            new_spot = usd_cny_spot if usd_cny_spot is not None else exist_spot
            
            query = "INSERT OR REPLACE INTO exchange_rate (date, usd_cny_mid, hkd_cny_mid, usd_cnh, usd_cny_spot, updated_at) VALUES (?, ?, ?, ?, ?, (datetime('now', 'localtime')))"
            conn.execute(query, (date, new_usd, new_hkd, new_cnh, new_spot))
            conn.commit()
            conn.close()

    def upsert_futures_daily(self, date: str, symbol: str, settle_price: float = None, calibration: float = None, close_price: float = None, volume: int = None):
        with self.lock:
            conn = self._get_conn()
            conn.execute("INSERT OR IGNORE INTO futures_daily (date, symbol) VALUES (?, ?)", (date, symbol))
            if settle_price is not None:
                conn.execute("UPDATE futures_daily SET settle_price = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (settle_price, date, symbol))
            if calibration is not None:
                conn.execute("UPDATE futures_daily SET calibration = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (calibration, date, symbol))
            if close_price is not None:
                conn.execute("UPDATE futures_daily SET close_price = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (close_price, date, symbol))
            if volume is not None:
                conn.execute("UPDATE futures_daily SET volume = ?, updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (volume, date, symbol))
            conn.commit()
            conn.close()
            
    def upsert_usa_etf_price(self, date: str, symbol: str, price: float, netvalue: float = None):
        with self.lock:
            conn = self._get_conn()
            cursor = conn.cursor()
            cursor.execute("UPDATE usa_etf_daily_prices SET price = ?, netvalue = COALESCE(?, netvalue), updated_at = (datetime('now', 'localtime')) WHERE date = ? AND symbol = ?", (price, netvalue, date, symbol))
            if cursor.rowcount == 0:
                query = "INSERT INTO usa_etf_daily_prices (date, symbol, price, netvalue) VALUES (?, ?, ?, ?)"
                cursor.execute(query, (date, symbol, price, netvalue))
            conn.commit()
            conn.close()

    def get_latest_usa_etf_date(self, symbol: str) -> str:
        conn = self._get_conn()
        query = "SELECT MAX(date) FROM usa_etf_daily_prices WHERE symbol = ?"
        cursor = conn.execute(query, (symbol,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result and result[0] else None

    def upsert_hkd_exchange_rate(self, date: str, hkd_cny_mid: float):
        self.upsert_exchange_rate(date, hkd_cny_mid=hkd_cny_mid)

    def get_latest_futures_price(self, symbol: str) -> Optional[float]:
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
            logger.error(f"Failed to get futures price: {e}")
            return None

    def batch_save_futures_data(self, data_list: List[Dict[str, Any]]):
        try:
            for data in data_list:
                date_str = data.get('date', datetime.now().strftime('%Y-%m-%d'))
                sym = data.get('symbol')
                price = data.get('price', data.get('settle_price'))
                self.upsert_futures_daily(date=date_str, symbol=sym, settle_price=price)
            logger.info(f"Batch saved futures data: {len(data_list)} items")
        except Exception as e:
            logger.error(f"Failed to batch save futures data: {e}")
