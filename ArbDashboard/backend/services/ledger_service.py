import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class LedgerService:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_all_trades(self, status: str = 'ACTIVE') -> List[Dict[str, Any]]:
        """获取所有实盘记录"""
        conn = self.db._get_conn()
        try:
            query = "SELECT * FROM user_trades WHERE status = ? ORDER BY trade_date DESC"
            df = pd.read_sql_query(query, conn, params=(status,))
            
            # 增强逻辑：计算剩余赎回天数与染色状态
            today = datetime.now().date()
            trades = df.to_dict(orient='records')
            for t in trades:
                if t['remind_date']:
                    remind = datetime.strptime(t['remind_date'], '%Y-%m-%d').date()
                    t['days_left'] = (remind - today).days
                else:
                    t['days_left'] = None
            return trades
        finally:
            conn.close()

    def _get_next_workday(self, current_date: datetime, days: int) -> datetime:
        """计算 N 个交易日后的日期 (跳过周六日)"""
        added_days = 0
        tmp_date = current_date
        while added_days < days:
            tmp_date += timedelta(days=1)
            if tmp_date.weekday() < 5: # 0-4 是周一到周五
                added_days += 1
        return tmp_date

    def add_trade(self, trade_data: Dict[str, Any]):
        """
        新增对账记录
        """
        conn = self.db._get_conn()
        try:
            trade_date_str = trade_data.get('trade_date', datetime.now().strftime('%Y-%m-%d'))
            dt = datetime.strptime(trade_date_str, '%Y-%m-%d')
            
            # [V4.6 核心规则]：自动推演 3 个交易日后的赎回日
            # 如果前端传了手动修改后的 remind_date，优先使用手动值
            manual_remind = trade_data.get('remind_date')
            if manual_remind and manual_remind != '':
                remind_date = manual_remind
            else:
                # 否则执行自动推演逻辑 (T+3 工作日)
                remind_dt = self._get_next_workday(dt, 3)
                remind_date = remind_dt.strftime('%Y-%m-%d')
            
            query = """
                INSERT INTO user_trades 
                (fund_code, fund_name, account_suffix, action, volume, price, amount, 
                 hedge_symbol, hedge_price, hedge_vol, fees, trade_date, remind_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
            """
            conn.execute(query, (
                trade_data['fund_code'],
                trade_data.get('fund_name', ''),
                trade_data.get('account_suffix', ''),
                trade_data['action'],
                trade_data['volume'],
                trade_data['price'],
                float(trade_data['volume']) * float(trade_data['price']),
                trade_data.get('hedge_symbol'),
                trade_data.get('hedge_price'),
                trade_data.get('hedge_vol'),
                trade_data.get('fees', 0),
                trade_date_str,
                remind_date
            ))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"记账失败: {e}")
            return False
        finally:
            conn.close()

    def close_trade(self, trade_id: int):
        conn = self.db._get_conn()
        try:
            conn.execute("UPDATE user_trades SET status = 'CLOSED' WHERE id = ?", (trade_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    # --- 费率管理 ---
    def get_fund_fees(self, fund_code: str) -> Dict[str, Any]:
        conn = self.db._get_conn()
        try:
            df = pd.read_sql_query("SELECT * FROM fund_fees WHERE fund_code = ?", conn, params=(fund_code,))
            if not df.empty:
                return df.iloc[0].to_dict()
            return {"redemption_fee_rate": 0.5, "commission_rate": 0}
        finally:
            conn.close()

    def upsert_fund_fee(self, data: Dict[str, Any]):
        conn = self.db._get_conn()
        try:
            query = "INSERT OR REPLACE INTO fund_fees (fund_code, redemption_fee_rate, commission_rate, updated_at) VALUES (?, ?, ?, datetime('now'))"
            conn.execute(query, (data['fund_code'], data['redemption_fee_rate'], data['commission_rate']))
            conn.commit()
            return True
        finally:
            conn.close()
