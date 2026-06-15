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
            return {"redemption_fee_rate": 0.5, "broker_name": ""}
        finally:
            conn.close()

    def upsert_fund_fee(self, data: Dict[str, Any]):
        conn = self.db._get_conn()
        try:
            query = "INSERT OR REPLACE INTO fund_fees (fund_code, redemption_fee_rate, broker_name, updated_at) VALUES (?, ?, ?, datetime('now'))"
            conn.execute(query, (data['fund_code'], data['redemption_fee_rate'], data.get('broker_name', '')))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"upsert_fund_fee failed: {e}")
            return False
        finally:
            conn.close()

    def get_broker_redemption_fees(self):
        conn = self.db._get_conn()
        try:
            df = pd.read_sql_query("SELECT * FROM broker_redemption_fees", conn)
            return df.to_dict('records')
        finally:
            conn.close()

    def upsert_broker_redemption_fee(self, data: Dict[str, Any]):
        conn = self.db._get_conn()
        try:
            query = "INSERT OR REPLACE INTO broker_redemption_fees (category, fund_code, broker_name, fee_rate, updated_at) VALUES (?, ?, ?, ?, datetime('now', 'localtime'))"
            conn.execute(query, (data.get('category', ''), data['fund_code'], data['broker_name'], data['fee_rate']))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"upsert_broker_redemption_fee failed: {e}")
            return False
        finally:
            conn.close()

    def delete_broker_redemption_fee(self, fee_id: int):
        conn = self.db._get_conn()
        try:
            conn.execute("DELETE FROM broker_redemption_fees WHERE id = ?", (fee_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"delete_broker_redemption_fee failed: {e}")
            return False
        finally:
            conn.close()

    # ================================================================
    # 辅助方法（默认价格、费率等）
    # ================================================================

    def get_prev_close(self, fund_code: str) -> float:
        """获取最新收盘价"""
        try:
            conn = self.db._get_conn()
            try:
                cur = conn.execute(
                    "SELECT price FROM fund_data WHERE fund_code=? AND price IS NOT NULL ORDER BY date DESC LIMIT 1",
                    (fund_code,)
                )
                row = cur.fetchone()
                return float(row[0]) if row else 0
            finally:
                conn.close()
        except:
            return 0

    def get_fee_rate(self, fund_code: str, broker: str = '') -> float:
        """获取指定基金+券商的赎回费率"""
        try:
            conn = self.db._get_conn()
            try:
                if broker:
                    cur = conn.execute(
                        "SELECT fee_rate FROM broker_redemption_fees WHERE fund_code=? AND broker_name=? LIMIT 1",
                        (fund_code, broker)
                    )
                else:
                    cur = conn.execute(
                        "SELECT fee_rate FROM broker_redemption_fees WHERE fund_code=? LIMIT 1",
                        (fund_code,)
                    )
                row = cur.fetchone()
                return float(row[0]) if row else 0
            finally:
                conn.close()
        except:
            return 0

    # ================================================================
    # 套利对账本（arbitrage_pairs）- 匹配Excel格式
    # ================================================================

    def _get_usd_rate(self) -> float:
        """获取最新美元汇率"""
        try:
            conn = self.db._get_conn()
            try:
                cur = conn.execute(
                    "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1"
                )
                row = cur.fetchone()
                return float(row[0]) if row else 7.2
            finally:
                conn.close()
        except:
            return 7.2

    def get_all_pairs(self, status: str = None) -> List[Dict[str, Any]]:
        """获取套利对列表"""
        conn = self.db._get_conn()
        try:
            if status:
                df = pd.read_sql_query(
                    "SELECT * FROM arbitrage_pairs WHERE status = ? ORDER BY COALESCE(sell_date, buy_date) DESC",
                    conn, params=(status,)
                )
            else:
                df = pd.read_sql_query(
                    "SELECT * FROM arbitrage_pairs ORDER BY COALESCE(sell_date, buy_date) DESC",
                    conn
                )
            pairs = df.to_dict(orient='records')
            usd_rate = self._get_usd_rate()
            for p in pairs:
                # 计算各子项盈亏
                buy_amt = p.get('buy_amount') or 0
                sell_amt = p.get('sell_amount') or 0
                redeem_fee = p.get('redemption_fee') or 0
                short_amt = p.get('short_amount') or 0
                cover_amt = p.get('cover_amount') or 0
                us_comm = p.get('us_commission') or 0

                p['a_share_pnl'] = round(sell_amt - buy_amt - redeem_fee, 2) if (sell_amt or buy_amt) else None
                p['us_pnl'] = round((cover_amt - short_amt) - us_comm, 2) if (cover_amt or short_amt) else None
                if p.get('pnl_usd') is not None and p.get('pnl_rmb') is not None:
                    pass  # 数据库已有值
                else:
                    # 自动估算
                    if p['a_share_pnl'] is not None and p['us_pnl'] is not None:
                        p['pnl_rmb'] = round(p['a_share_pnl'] + p['us_pnl'] * usd_rate, 2)
                        p['pnl_usd'] = round(p['us_pnl'], 2)
            return pairs
        finally:
            conn.close()

    def add_pair(self, data: Dict[str, Any]) -> int:
        """新增套利对"""
        conn = self.db._get_conn()
        try:
            buy_vol = data.get('buy_volume') or 0
            buy_price = data.get('buy_price') or 0
            buy_amount = data.get('buy_amount') or (buy_vol * buy_price)
            short_vol = data.get('short_volume') or 0
            short_price = data.get('short_price') or 0
            short_amount = data.get('short_amount') or (short_vol * short_price)

            usd_rate = self._get_usd_rate()
            sell_amt = data.get('sell_amount') or 0
            redeem_fee = data.get('redemption_fee') or 0
            cover_amt = data.get('cover_amount') or 0
            us_comm = data.get('us_commission') or 0

            a_pnl = sell_amt - buy_amount - redeem_fee
            u_pnl = (cover_amt - short_amount) - us_comm
            pnl_rmb = round(a_pnl + u_pnl * usd_rate, 2)
            pnl_usd = round(u_pnl, 2)

            conn.execute('''
                INSERT INTO arbitrage_pairs
                (fund_code, fund_name, buy_date, buy_price, buy_volume, buy_amount, buy_account,
                 sell_date, sell_price, sell_amount, redemption_fee,
                 hedge_symbol, short_date, short_price, short_volume, short_amount,
                 cover_date, cover_price, cover_amount, us_commission,
                 pnl_rmb, pnl_usd, status, buy_notes, sell_notes, notes,
                 broker_name, close_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                data['fund_code'], data.get('fund_name', ''),
                data.get('buy_date'), buy_price, buy_vol, buy_amount, data.get('buy_account'),
                data.get('sell_date'), data.get('sell_price'), sell_amt, redeem_fee,
                data.get('hedge_symbol'), data.get('short_date'), short_price, short_vol, short_amount,
                data.get('cover_date'), data.get('cover_price'), cover_amt, us_comm,
                pnl_rmb, pnl_usd, data.get('status', 'ACTIVE'),
                data.get('buy_notes'), data.get('sell_notes'), data.get('notes'),
                data.get('broker_name', ''), data.get('close_type', 'REDEEM')
            ))
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as e:
            logger.error(f"新增套利对失败: {e}")
            raise
        finally:
            conn.close()

    def update_pair(self, pair_id: int, data: Dict[str, Any]) -> bool:
        """更新套利对"""
        conn = self.db._get_conn()
        try:
            fields = []
            values = []
            for key in ['fund_code','fund_name','buy_date','buy_price','buy_volume','buy_amount',
                        'buy_account','sell_date','sell_price','sell_amount','redemption_fee',
                        'hedge_symbol','short_date','short_price','short_volume','short_amount',
                        'cover_date','cover_price','cover_amount','us_commission',
                        'status','buy_notes','sell_notes','notes',
                        'broker_name','close_type']:
                if key in data:
                    fields.append(f"{key} = ?")
                    values.append(data[key])

            if not fields:
                return False

            # 如果有金额变化，重算盈亏
            if any(k in data for k in ['buy_amount','sell_amount','redemption_fee',
                                       'short_amount','cover_amount','us_commission']):
                buy_amt = data.get('buy_amount') or 0
                sell_amt = data.get('sell_amount') or 0
                redeem_fee = data.get('redemption_fee') or 0
                short_amt = data.get('short_amount') or 0
                cover_amt = data.get('cover_amount') or 0
                us_comm = data.get('us_commission') or 0

                if not all([buy_amt, sell_amt]):
                    df = pd.read_sql_query("SELECT * FROM arbitrage_pairs WHERE id = ?", conn, params=(pair_id,))
                    if not df.empty:
                        row = df.iloc[0]
                        buy_amt = buy_amt or (row.get('buy_amount') or 0)
                        sell_amt = sell_amt or (row.get('sell_amount') or 0)
                        redeem_fee = redeem_fee or (row.get('redemption_fee') or 0)
                        short_amt = short_amt or (row.get('short_amount') or 0)
                        cover_amt = cover_amt or (row.get('cover_amount') or 0)
                        us_comm = us_comm or (row.get('us_commission') or 0)

                usd_rate = self._get_usd_rate()
                a_pnl = sell_amt - buy_amt - redeem_fee
                u_pnl = (cover_amt - short_amt) - us_comm
                pnl_rmb = round(a_pnl + u_pnl * usd_rate, 2)
                pnl_usd = round(u_pnl, 2)
                fields.append("pnl_rmb = ?")
                fields.append("pnl_usd = ?")
                values.extend([pnl_rmb, pnl_usd])

            fields.append("updated_at = datetime('now', 'localtime')")
            values.append(pair_id)
            conn.execute(f"UPDATE arbitrage_pairs SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"更新套利对失败: {e}")
            return False
        finally:
            conn.close()

    def delete_pair(self, pair_id: int) -> bool:
        """删除套利对"""
        conn = self.db._get_conn()
        try:
            conn.execute("DELETE FROM arbitrage_pairs WHERE id = ?", (pair_id,))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"删除套利对失败: {e}")
            return False
        finally:
            conn.close()

    def auto_record_trade(self, data: Dict[str, Any]) -> int:
        """自动记录一笔成交（从QMT交易回调）"""
        conn = self.db._get_conn()
        try:
            action = data.get('action', 'BUY')
            fund_code = data.get('fund_code', '')
            price = data.get('price', 0)
            volume = int(data.get('volume', 0))
            amount = data.get('amount', 0) or (price * volume)

            if action == 'BUY':
                # A股买入 → 新建一个套利对
                pair_id = self.add_pair({
                    'fund_code': fund_code.split('.')[0],
                    'fund_name': data.get('fund_name', ''),
                    'buy_date': data.get('trade_date', datetime.now().strftime('%Y-%m-%d')),
                    'buy_price': price,
                    'buy_volume': volume,
                    'buy_amount': amount,
                    'buy_account': data.get('account_suffix', ''),
                    'buy_notes': data.get('notes', '自动记录'),
                    'status': 'ACTIVE'
                })
                return pair_id
            elif action == 'SELL':
                # 美股做空 → 找到该基金最新没有美股侧的ACTIVE对，附加上去
                df = pd.read_sql_query(
                    "SELECT id FROM arbitrage_pairs WHERE status='ACTIVE' AND (short_amount IS NULL OR short_amount=0) AND fund_code=? ORDER BY id DESC LIMIT 1",
                    conn, params=(fund_code.split('.')[0],)
                )
                if not df.empty:
                    pair_id = int(df.iloc[0]['id'])
                    self.update_pair(pair_id, {
                        'hedge_symbol': data.get('hedge_symbol', ''),
                        'short_date': data.get('trade_date'),
                        'short_price': price,
                        'short_volume': volume,
                        'short_amount': amount
                    })
                    return pair_id
            return 0
        except Exception as e:
            logger.error(f"自动记录交易失败: {e}")
            return 0
        finally:
            conn.close()
