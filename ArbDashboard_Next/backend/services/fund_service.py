import os
import sys
import pandas as pd
from typing import List, Dict, Any

class FundService:
    def __init__(self, db):
        self.db = db

    def get_unified_dashboard_data(self) -> List[Dict[str, Any]]:
        """
        Merges unified fund list with latest price and factor data.
        This provides a single source for the main dashboard table.
        """
        # 1. Get base fund list from unified table
        conn = self.db._get_conn()
        query = """
        SELECT j.fund_code, j.fund_name, j.category, j.related_index,
               f.price, f.nav, f.premium, f.date as price_date,
               df.calibration, df.hedge, df.position, df.date as factor_date,
               ps.purchase_status, ps.redemption_status
        FROM unified_fund_list j
        LEFT JOIN (
            SELECT fund_code, price, nav, premium, date
            FROM fund_data
            WHERE date = (SELECT MAX(date) FROM fund_data)
        ) f ON j.fund_code = f.fund_code
        LEFT JOIN (
            SELECT fund_code, calibration, hedge, position, date
            FROM fund_daily_factors
            WHERE date = (SELECT MAX(date) FROM fund_daily_factors)
        ) df ON j.fund_code = df.fund_code
        LEFT JOIN fund_purchase_status ps ON j.fund_code = ps.fund_code
        """
        # Ensure the connection uses utf-8 if possible (sqlite default)
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Fill NaN with 0 or empty strings for JSON compatibility
        df['price'] = pd.to_numeric(df['price'], errors='coerce').fillna(0)
        df['nav'] = pd.to_numeric(df['nav'], errors='coerce').fillna(0)
        df['premium'] = pd.to_numeric(df['premium'], errors='coerce').fillna(0)
        df['calibration'] = pd.to_numeric(df['calibration'], errors='coerce').fillna(0)
        df['hedge'] = pd.to_numeric(df['hedge'], errors='coerce').fillna(0)
        df['position'] = pd.to_numeric(df['position'], errors='coerce').fillna(0)
        
        df['purchase_status'] = df['purchase_status'].fillna('未知')
        df['redemption_status'] = df['redemption_status'].fillna('未知')
        
        return df.to_dict(orient='records')

    def get_market_overview(self) -> Dict[str, Any]:
        """
        Returns latest exchange rates and system stats with robust error handling.
        """
        conn = self.db._get_conn()
        res = {
            "rates": {},
            "usd_change": 0,
            "stats": {"fund_count": 0, "system_health": 0}
        }
        
        try:
            # 1. Exchange Rates
            rates_df = pd.read_sql_query("SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 2", conn)
            if not rates_df.empty:
                latest_rate = rates_df.iloc[0].to_dict()
                # Ensure values are JSON serializable
                for k, v in latest_rate.items():
                    if pd.isna(v): latest_rate[k] = None
                res["rates"] = latest_rate
                
                if len(rates_df) > 1:
                    prev_rate = rates_df.iloc[1]
                    if prev_rate.get('usd_cny_mid', 0) > 0:
                        res["usd_change"] = float((latest_rate['usd_cny_mid'] - prev_rate['usd_cny_mid']) / prev_rate['usd_cny_mid'])

            # 2. Fund Count
            count_df = pd.read_sql_query("SELECT count(*) as count FROM unified_fund_list", conn)
            if not count_df.empty:
                res["stats"]["fund_count"] = int(count_df.iloc[0]['count'])

            # 3. System Health
            health_df = pd.read_sql_query("SELECT * FROM system_health ORDER BY timestamp DESC LIMIT 1", conn)
            if not health_df.empty:
                status = str(health_df.iloc[0]['status']).upper()
                res["stats"]["system_health"] = 100 if status == 'OK' else 85
            else:
                res["stats"]["system_health"] = 90 # Default if no health data
                
        except Exception as e:
            print(f"ERROR in get_market_overview: {e}")
            # Fallback to defaults already in 'res'
        finally:
            conn.close()

        return res

    def get_fund_history(self, fund_code: str) -> List[Dict[str, Any]]:
        """
        Returns historical premium data for a specific fund (last 30 days).
        """
        conn = self.db._get_conn()
        query = """
        SELECT date, price, nav, premium
        FROM fund_data
        WHERE fund_code = ?
        ORDER BY date ASC
        LIMIT 100
        """
        df = pd.read_sql_query(query, conn, params=(fund_code,))
        conn.close()
        
        # Format for ECharts
        return df.to_dict(orient='records')

    def get_fund_basket(self, fund_code: str) -> List[Dict[str, Any]]:
        """
        Returns latest basket weights for a specific fund.
        """
        conn = self.db._get_conn()
        query = """
        SELECT underlying_symbol, weight, date
        FROM fund_basket_weights
        WHERE fund_code = ? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code = ?)
        """
        df = pd.read_sql_query(query, conn, params=(fund_code, fund_code))
        conn.close()
        return df.to_dict(orient='records')
