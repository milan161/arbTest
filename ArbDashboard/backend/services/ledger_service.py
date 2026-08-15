import sqlite3
import pandas as pd
from datetime import datetime, timedelta
import logging
import re, os, glob, csv, json
import yaml as _yaml
import shutil
from typing import List, Dict, Any, Set

logger = logging.getLogger(__name__)

# [AI-2026-08-15] 套利基金代码白名单缓存（读 arbcore/config/lof_config.yaml，mtime 感知热加载）
_LOF_CFG_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'arbcore', 'config', 'lof_config.yaml'))
_ARB_CODES_CACHE: Dict[str, Any] = {"codes": None, "mtime": 0}

def _get_arbitrage_codes() -> Set[str]:
    """从 lof_config.yaml 读所有套利基金代码（funds[].code）作为白名单。"""
    try:
        mtime = os.path.getmtime(_LOF_CFG_PATH)
    except OSError:
        return set()
    if _ARB_CODES_CACHE["codes"] is not None and _ARB_CODES_CACHE["mtime"] == mtime:
        return _ARB_CODES_CACHE["codes"]
    try:
        with open(_LOF_CFG_PATH, 'r', encoding='utf-8') as f:
            cfg = _yaml.safe_load(f)
        codes = {str(x.get('code', '')).strip() for x in cfg.get('funds', [])}
        codes.discard('')
        _ARB_CODES_CACHE["codes"] = codes
        _ARB_CODES_CACHE["mtime"] = mtime
        logger.info(f"[TDX-PreFilter] 套利白名单载入: {len(codes)} 只 (lof_config.yaml)")
        return codes
    except Exception as e:
        logger.warning(f"[TDX-PreFilter] 加载 lof_config.yaml 失败: {e}")
        return set()

class LedgerService:
    def __init__(self, db_manager, master_db_path=None):
        self.db = db_manager  # 交易库（arb_tran.db）
        # master 库路径（市场因子：fund_daily_factors.hedge / exchange_rate），对账时 ATTACH 只读
        self.master_db_path = master_db_path
        # [AI-2026-08-15] IB 真实成交流水表：从 IB reqExecutions 同步，替代手动 Excel 记录。
        # 放在 LedgerService 启动时建表，与 user_trades/arbitrage_pairs 同域且保证每次启动建表。
        try:
            conn = self.db._get_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS ib_executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        exec_id TEXT UNIQUE,
                        order_id INTEGER,
                        symbol TEXT,
                        side TEXT,
                        shares REAL,
                        price REAL,
                        commission REAL,
                        currency TEXT,
                        account TEXT,
                        trade_time TEXT,
                        local_date TEXT,
                        source TEXT DEFAULT 'IB',
                        created_at TIMESTAMP DEFAULT (datetime('now','localtime'))
                    )
                """)
                conn.commit()
                # [AI-2026-08-15] 华宝(通达信)历史成交流水表：解析导出的txt入库，替代手动Excel
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tdx_executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source_file TEXT,
                        line_no INTEGER,
                        trade_date TEXT,
                        trade_time TEXT,
                        account TEXT,
                        code TEXT,
                        name TEXT,
                        category TEXT,
                        side TEXT,
                        price REAL,
                        qty REAL,
                        amount REAL,
                        remain REAL,
                        commission REAL,
                        stamp_tax REAL,
                        transfer_fee REAL,
                        deal_fee REAL,
                        total_fee REAL,
                        deal_no TEXT,
                        order_no TEXT,
                        created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                        UNIQUE(source_file, line_no)
                    )
                """)
                conn.commit()
                # [AI-2026-08-15] 银河QMT历史成交流水表：经桥接策略 QUERY_DEALS 实时查询入库
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS qmt_executions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        account TEXT,
                        code TEXT,
                        name TEXT,
                        trade_date TEXT,
                        trade_time TEXT,
                        side TEXT,
                        price REAL,
                        volume REAL,
                        amount REAL,
                        fee REAL,
                        raw TEXT,
                        created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                        UNIQUE(account, code, trade_date, trade_time, volume, price)
                    )
                """)
                conn.commit()
                # [AI-2026-08-15] 配对映射表：记录每个套利对用了哪些腿（tdx/qmt/ib 三源 id 会重复，须带 source）
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS pair_legs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        pair_id INTEGER NOT NULL,
                        leg_source TEXT NOT NULL,
                        leg_id INTEGER NOT NULL,
                        role TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                        UNIQUE(leg_source, leg_id)
                    )
                """)
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"建 ib_executions 表失败: {e}")

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
                    "SELECT price FROM unified_fund_history WHERE fund_code=? AND price IS NOT NULL ORDER BY date DESC LIMIT 1",
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
                m = self._attach_master(conn)
                cur = conn.execute(
                    f"SELECT usd_cny_mid FROM {m}.exchange_rate ORDER BY date DESC LIMIT 1"
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
            # [AI-2026-08-16] pandas 把 SQL NULL 读成 NaN，NaN 无法 JSON 序列化（会 500），转回 None
            for p in pairs:
                for k, v in list(p.items()):
                    if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
                        p[k] = None
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
                 sell_date, sell_price, sell_volume, sell_amount, redemption_fee,
                 hedge_symbol, short_date, short_price, short_volume, short_amount,
                 cover_date, cover_price, cover_volume, cover_amount, us_commission,
                 pnl_rmb, pnl_usd, status, buy_notes, sell_notes, notes,
                 broker_name, close_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
?            ''', (
                data['fund_code'], data.get('fund_name', ''),
                data.get('buy_date'), buy_price, buy_vol, buy_amount, data.get('buy_account'),
                data.get('sell_date'), data.get('sell_price'), data.get('sell_volume'), sell_amt, redeem_fee,
                data.get('hedge_symbol'), data.get('short_date'), short_price, short_vol, short_amount,
                data.get('cover_date'), data.get('cover_price'), data.get('cover_volume'), cover_amt, us_comm,
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

    # ================================================================
    # [AI-2026-08-15] IB 真实成交流水（从 IB reqExecutions 同步）
    # ================================================================

    def _parse_local_date(self, trade_time: str):
        """IB 成交时间 -> 本地日期 YYYY-MM-DD（用于按天过滤）。"""
        if not trade_time:
            return None
        try:
            return datetime.strptime(trade_time, "%Y%m%d %H:%M:%S").strftime("%Y-%m-%d")
        except:
            pass
        try:
            return datetime.fromisoformat(trade_time).strftime("%Y-%m-%d")
        except:
            return None

    def upsert_ib_executions(self, rows: List[Dict]) -> int:
        """批量写入 IB 真实成交流水（exec_id 唯一防重复同步）。返回写入条数。"""
        if not rows:
            return 0
        conn = self.db._get_conn()
        try:
            cnt = 0
            for r in rows:
                tt = r.get('trade_time')
                local_date = self._parse_local_date(tt)
                conn.execute("""
                    INSERT OR REPLACE INTO ib_executions
                    (exec_id, order_id, symbol, side, shares, price, commission, currency, account, trade_time, local_date, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?, 'IB')
                """, (
                    r.get('exec_id'), r.get('order_id'), r.get('symbol'), r.get('side'),
                    r.get('shares'), r.get('price'), r.get('commission'), r.get('currency'),
                    r.get('account'), tt, local_date
                ))
                cnt += 1
            conn.commit()
            return cnt
        except Exception as e:
            logger.error(f"写入 IB 成交流水失败: {e}")
            return 0
        finally:
            conn.close()

    def get_ib_executions(self, days: int = 0) -> List[Dict]:
        """查询 IB 成交流水（days>0 按 local_date 过滤）。"""
        conn = self.db._get_conn()
        try:
            if days and days > 0:
                since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                df = pd.read_sql_query(
                    "SELECT * FROM ib_executions WHERE local_date >= ? ORDER BY trade_time DESC",
                    conn, params=(since,))
            else:
                df = pd.read_sql_query("SELECT * FROM ib_executions ORDER BY trade_time DESC", conn)
            return df.to_dict(orient='records')
        except Exception as e:
            logger.error(f"查询 IB 成交流水失败: {e}")
            return []
        finally:
            conn.close()

    # --- [AI-2026-08-15] IB 网页活动账单 CSV 解析（盈透API无法查历史，改用网页导出CSV） ---
    def parse_ib_statement_csv(self, path: str) -> List[Dict[str, Any]]:
        """解析 IB 活动账单 CSV 的「交易」段，返回成交流水记录。
        盈透 reqExecutions 无法返回历史成交，故改为解析用户在 IB 网页导出的活动账单 CSV。
        跳过「外汇」兑换行；数量/价格含千分位逗号时自动剥离。"""
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                all_rows = list(csv.reader(f))
        except Exception as e:
            logger.error(f"读取 IB 账单 CSV 失败: {e}")
            return rows
        # 账户（账户信息段）
        account = None
        for r in all_rows:
            if len(r) >= 4 and r[0] == '账户信息' and r[2] == '账户':
                account = r[3]
                break
        # 交易段数据行
        data_rows = [r for r in all_rows
                     if len(r) > 2 and r[0] == '交易' and r[1] == 'Data']
        skipped = 0
        for r in data_rows:
            if len(r) < 16:
                skipped += 1
                continue
            if r[3] == '外汇':          # 外汇兑换不是成交，跳过
                continue
            try:
                sym = r[5].strip()
                # 日期时间形如 "2026-06-01, 16:00:00" → 去逗号空格
                dt = r[6].replace(', ', ' ').strip()
                qty = float(r[7].replace(',', ''))
                price = float(r[8].replace(',', ''))
                commission = abs(float(r[11].replace(',', '')))
                currency = r[4].strip()
                asset_class = r[3].strip()
                open_close = r[15].strip() if len(r) > 15 else ''
                side = 'BUY' if qty > 0 else 'SELL'
                local_date = dt[:10] if len(dt) >= 10 else None
                # 合成唯一键（CSV 无 exec_id），保证同文件重复导入幂等
                exec_id = f"{account}_{sym}_{dt}_{int(qty)}_{price}"
                rows.append({
                    "exec_id": exec_id,
                    "order_id": 0,
                    "symbol": sym,
                    "side": side,
                    "shares": abs(qty),
                    "price": price,
                    "commission": commission,
                    "currency": currency,
                    "account": account,
                    "trade_time": dt,
                    "local_date": local_date,
                    "asset_class": asset_class,
                    "open_close": open_close,
                    "source": "IB_CSV",
                })
            except Exception as e:
                skipped += 1
                logger.warning(f"[IB_CSV] 行解析异常跳过: {e} | {r[:6]}")
        if skipped:
            logger.warning(f"[IB_CSV] {os.path.basename(path)} 跳过 {skipped} 行(外汇/格式异常)")
        return rows

    def import_ib_csv_dir(self, dir_path: str, pattern: str = "*.csv") -> Dict[str, Any]:
        """扫描目录最新 csv 并解析入库。返回 {file, count}。"""
        files = glob.glob(os.path.join(dir_path, pattern))
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return {"file": None, "count": 0, "msg": "目录无csv文件"}
        latest = max(files, key=os.path.getmtime)
        rows = self.parse_ib_statement_csv(latest)
        if not rows:
            return {"file": os.path.basename(latest), "count": 0, "msg": "CSV无交易记录"}
        cnt = self.upsert_ib_executions(rows)
        return {"file": os.path.basename(latest), "count": cnt}

    # --- [AI-2026-08-15] 华宝(通达信)历史成交导入（解析导出的txt，替代手动Excel） ---
    _TDX_TITLE = "成交日期"   # 列名行标记

    @staticmethod
    def _tdx_normalize_side(category: str) -> str:
        c = (category or "").strip()
        if "买入" in c: return "BUY"
        if "卖出" in c: return "SELL"
        if "赎回" in c: return "REDEEM"
        if "融券购回" in c or "购回" in c: return "SHORT_COVER"
        if "融券" in c: return "SHORT"
        if "申购" in c or c == "配号": return "ALLOT"
        return "OTHER"

    # [AI-2026-08-15] 通达信导出txt 表头列名 -> 内部字段 映射（华宝/银河同格式族，列布局不同靠表头自适应）
    _TDX_COL_MAP = {
        "成交日期": "trade_date",
        "成交时间": "trade_time",
        "股东代码": "account",
        "证券代码": "code",
        "证券名称": "name",
        "委托类别": "side_raw",   # 华宝(通达信)
        "买卖标志": "side_raw",   # 银河(通达信)
        "成交价格": "price",
        "成交数量": "qty",
        "发生金额": "amount",     # 华宝
        "成交金额": "amount",     # 银河
        "剩余金额": "remain",
        "佣金": "commission",
        "印花税": "stamp_tax",
        "过户费": "transfer_fee",
        "成交费": "deal_fee",
        "成交编号": "deal_no",
        "委托编号": "order_no",   # 华宝
        "协议编号": "order_no",   # 银河
    }

    def parse_tdx_history_file(self, path: str) -> List[Dict[str, Any]]:
        """解析通达信导出的历史成交文本（表头列名自适应：华宝/银河同一套代码）。
        返回记录列表，字段: source_file/line_no/trade_date/trade_time/account/code/name/
        category/side/price/qty/amount/remain/commission/stamp_tax/transfer_fee/
        deal_fee/total_fee/deal_no/order_no。"""
        rows: List[Dict[str, Any]] = []
        skipped = 0
        try:
            with open(path, 'r', encoding='gb18030', errors='ignore') as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"读取通达信成交文件失败: {e}")
            return rows
        source = os.path.basename(path)
        # 1) 定位表头行，建立 列名->列号 映射
        col_index: Dict[str, int] = {}
        header_ncols = 0
        for raw in lines:
            s = raw.strip()
            if not s or set(s) <= set("-"):
                continue
            toks = s.split()
            mapped = [self._TDX_COL_MAP.get(t) for t in toks]
            if "trade_date" in mapped and "code" in mapped:
                header_ncols = len(toks)
                for i, m in enumerate(mapped):
                    if m and m not in col_index:
                        col_index[m] = i
                break
        if not col_index:
            logger.warning(f"[TDX] {source} 未找到表头（成交日期/证券代码），格式不识别")
            return rows
        need = max(col_index.values()) + 1   # 数据行最少需要的 token 数
        for idx, raw in enumerate(lines, start=1):
            s = raw.strip()
            if not s or set(s) <= set("-"):
                continue
            toks = s.split()
            if toks and toks[0] == "成交日期":   # 表头行
                continue
            # 容错：成交编号内含单空格（如"申购失败: B01"），token 数比表头多1时合并到 deal_no 列
            if len(toks) == header_ncols + 1:
                di = col_index.get("deal_no")
                if di is not None and di < len(toks) - 1:
                    toks = toks[:di] + [toks[di] + " " + toks[di + 1]] + toks[di + 2:]
            # 校验：数据行 token 数允许 ==表头列数；末尾空列（如备注）被 strip 掉时可少 1~3 个
            if not (need <= len(toks) <= header_ncols + 1):
                skipped += 1
                logger.warning(f"[TDX] 行{idx} 字段数={len(toks)}（需 {need}~{header_ncols + 1}），跳过: {s[:60]}")
                continue
            try:
                def _g(field):
                    i = col_index.get(field)
                    return toks[i] if i is not None and i < len(toks) else None
                def _f(field):
                    v = _g(field)
                    try:
                        return float(v) if v not in (None, "") else 0.0
                    except (TypeError, ValueError):
                        return 0.0
                trade_date = _g("trade_date") or ""
                if len(trade_date) == 8 and trade_date.isdigit():   # YYYYMMDD -> YYYY-MM-DD
                    trade_date = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
                side_raw = _g("side_raw") or ""
                rec = {
                    "source_file": source,
                    "line_no": idx,
                    "trade_date": trade_date,
                    "trade_time": _g("trade_time") or "",
                    "account": _g("account") or "",
                    "code": _g("code") or "",
                    "name": _g("name") or "",
                    "category": side_raw,
                    "side": self._tdx_normalize_side(side_raw),
                    "price": _f("price"),
                    "qty": _f("qty"),
                    "amount": _f("amount"),
                    "remain": _f("remain"),
                    "commission": _f("commission"),
                    "stamp_tax": _f("stamp_tax"),
                    "transfer_fee": _f("transfer_fee"),
                    "deal_fee": _f("deal_fee"),
                    "deal_no": _g("deal_no") or "",
                    "order_no": _g("order_no") or "",
                }
                rec["total_fee"] = (rec["commission"] + rec["stamp_tax"]
                                    + rec["transfer_fee"] + rec["deal_fee"])
                rows.append(rec)
            except Exception as e:
                skipped += 1
                logger.warning(f"[TDX] 行{idx} 解析异常跳过: {e} | {s[:60]}")
        if skipped:
            logger.warning(f"[TDX] {source} 跳过 {skipped} 行")
        return rows

    def import_tdx_file(self, path: str, code_filter: str = None) -> int:
        """解析并入库单个华宝成交txt（按 source_file 覆盖式导入，幂等）。返回写入条数。
        [AI-2026-08-15] code_filter：源头过滤，只入库该基金代码的行（防无关交易入库/泄密）。"""
        rows = self.parse_tdx_history_file(path)
        if not rows:
            return 0
        if code_filter:
            code_filter = str(code_filter).strip()
            filtered = [r for r in rows if str(r.get("code", "")).strip() == code_filter]
            if len(filtered) != len(rows):
                logger.info(f"[TDX] {os.path.basename(path)} 源头过滤 code={code_filter}: {len(rows)}行 -> {len(filtered)}行")
            rows = filtered
        if not rows:
            logger.warning(f"[TDX] {os.path.basename(path)} 过滤后无 {code_filter} 的成交，跳过入库")
            return 0
        source = os.path.basename(path)
        conn = self.db._get_conn()
        try:
            conn.execute("DELETE FROM tdx_executions WHERE source_file = ?", (source,))
            for r in rows:
                conn.execute("""
                    INSERT OR REPLACE INTO tdx_executions
                    (source_file, line_no, trade_date, trade_time, account, code, name,
                     category, side, price, qty, amount, remain, commission, stamp_tax,
                     transfer_fee, deal_fee, total_fee, deal_no, order_no)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    r["source_file"], r["line_no"], r["trade_date"], r["trade_time"], r["account"],
                    r["code"], r["name"], r["category"], r["side"], r["price"], r["qty"], r["amount"],
                    r["remain"], r["commission"], r["stamp_tax"], r["transfer_fee"], r["deal_fee"],
                    r["total_fee"], r["deal_no"], r["order_no"]
                ))
            conn.commit()
            return len(rows)
        except Exception as e:
            logger.error(f"写入华宝成交流水失败: {e}")
            return 0
        finally:
            conn.close()

    def import_tdx_dir(self, dir_path: str, pattern: str = "*华宝*.txt", code_filter: str = None) -> Dict[str, Any]:
        """扫描目录最新华宝txt，先按套利白名单预处理（写回原文件，删除逆回购/打新股等），
        再解析入库。code_filter 兼容老接口。返回 {file, count, prefilter}。"""
        files = glob.glob(os.path.join(dir_path, pattern))
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return {"file": None, "count": 0, "msg": "目录无华宝txt文件"}
        latest = max(files, key=os.path.getmtime)
        # [AI-2026-08-15] 第一性原理：预处理必须在解析前完成，写回原文件，UI 100% 看不到杂项
        pre = self.prefilter_tdx_file(latest)
        cnt = self.import_tdx_file(latest, code_filter=code_filter)
        return {"file": os.path.basename(latest), "count": cnt, "prefilter": pre}

    def import_galaxy_file(self, path: str) -> int:
        """解析并入库单个"通达信导出的银河账户历史成交txt"（复用表头自适应解析器，与华宝同套代码）。
        写入 qmt_executions 表（account+code+date+time+volume+price 唯一幂等）。
        [AI-2026-08-15] **覆盖式**：先按 account 清空本批账户的旧数据再插入。
        原因：qmt_executions 表无 source_file 字段，UNIQUE 约束只去重相同成交、不删白名单外的旧杂项
        （早期全量导入残留的 131810/204001/920XXX 等会持续显在 UI 里）。返回写入条数。"""
        rows = self.parse_tdx_history_file(path)
        if not rows:
            return 0
        accounts = {r.get("account") for r in rows if r.get("account")}
        conn = self.db._get_conn()
        try:
            # 覆盖式：清掉本批账户的全部旧行（避免白名单外的历史残留）
            if accounts:
                ph = ",".join("?" for _ in accounts)
                conn.execute(f"DELETE FROM qmt_executions WHERE account IN ({ph})", list(accounts))
            cnt = 0
            for r in rows:
                conn.execute("""
                    INSERT OR REPLACE INTO qmt_executions
                    (account, code, name, trade_date, trade_time, side, price, volume, amount, fee, raw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    r.get("account") or "", r.get("code") or "", r.get("name") or "",
                    r.get("trade_date") or "", r.get("trade_time") or "",
                    r.get("side") or "OTHER", r.get("price") or 0.0, r.get("qty") or 0.0,
                    r.get("amount") or 0.0, r.get("total_fee") or 0.0,
                    json.dumps(r, ensure_ascii=False, default=str)
                ))
                cnt += 1
            conn.commit()
            return cnt
        except Exception as e:
            logger.error(f"写入银河成交流水失败: {e}")
            return 0
        finally:
            conn.close()

    def import_galaxy_dir(self, dir_path: str) -> Dict[str, Any]:
        """扫描最新"*银河*.txt"，先预处理（写回原文件），再入库。返回 {file, count, prefilter}。"""
        files = glob.glob(os.path.join(dir_path, "*银河*.txt"))
        files = [f for f in files if os.path.isfile(f)]
        if not files:
            return {"file": None, "count": 0, "msg": "目录无银河成交txt"}
        latest = max(files, key=os.path.getmtime)
        pre = self.prefilter_tdx_file(latest)
        cnt = self.import_galaxy_file(latest)
        return {"file": os.path.basename(latest), "count": cnt, "prefilter": pre}

    def prefilter_tdx_file(self, path: str, target_codes: Set[str] = None) -> Dict[str, Any]:
        """[AI-2026-08-15] 预处理：按套利白名单过滤掉无关行（逆回购/打新股等），**写回原文件**。
        写回前先备份到 <name>.bak 安全网。
        返回 {before, after, removed, backup, msg}。"""
        if target_codes is None:
            target_codes = _get_arbitrage_codes()
        if not target_codes:
            return {"before": 0, "after": 0, "removed": 0, "backup": None, "msg": "套利白名单为空(lof_config.yaml加载失败)"}
        try:
            with open(path, 'r', encoding='gb18030', errors='ignore') as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"[TDX-PreFilter] 读取失败: {e}")
            return {"error": str(e)}
        # 找表头 + 建 col_index（复用 _TDX_COL_MAP）
        col_index: Dict[str, int] = {}
        for raw in lines:
            s = raw.strip()
            if not s or set(s) <= set("-"):
                continue
            toks = s.split()
            mapped = [self._TDX_COL_MAP.get(t) for t in toks]
            if "trade_date" in mapped and "code" in mapped:
                for i, m in enumerate(mapped):
                    if m and m not in col_index:
                        col_index[m] = i
                break
        if "code" not in col_index:
            logger.warning(f"[TDX-PreFilter] {os.path.basename(path)} 表头不识别")
            return {"before": 0, "after": 0, "removed": 0, "msg": "表头不识别"}
        code_idx = col_index["code"]
        # 备份
        backup = path + ".bak"
        try:
            shutil.copy2(path, backup)
        except Exception as e:
            logger.warning(f"[TDX-PreFilter] 备份失败: {e}")
            backup = None
        # 过滤：数据行 code ∉ target_codes → 删除；表头/分隔线/空行原样保留
        out = []
        before = 0
        removed = 0
        for raw in lines:
            s = raw.strip()
            if not s or set(s) <= set("-"):
                out.append(raw); continue
            toks = s.split()
            if toks and toks[0] == "成交日期":   # 表头
                out.append(raw); continue
            before += 1
            if code_idx < len(toks) and toks[code_idx].strip() in target_codes:
                out.append(raw)
            else:
                removed += 1
        try:
            with open(path, 'w', encoding='gb18030', errors='ignore') as f:
                f.writelines(out)
            logger.info(f"[TDX-PreFilter] {os.path.basename(path)}: 数据{before}行 -> 保留{before-removed}, 删除{removed}, 备份={backup}")
        except Exception as e:
            logger.error(f"[TDX-PreFilter] 写回失败: {e}")
            return {"error": str(e)}
        return {"before": before, "after": before - removed, "removed": removed, "backup": backup}

    def get_tdx_executions(self, code: str = None, category: str = None, days: int = 0) -> List[Dict[str, Any]]:
        """查询华宝成交流水。可选 code/category 过滤，days>0 按 trade_date 过滤。"""
        conn = self.db._get_conn()
        try:
            sql = "SELECT * FROM tdx_executions WHERE 1=1"
            params: List[Any] = []
            if code:
                sql += " AND code = ?"; params.append(code)
            if category:
                sql += " AND category = ?"; params.append(category)
            if days and days > 0:
                since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                sql += " AND trade_date >= ?"; params.append(since)
            sql += " ORDER BY trade_date DESC, trade_time DESC"
            df = pd.read_sql_query(sql, conn, params=params)
            return df.to_dict(orient='records')
        except Exception as e:
            logger.error(f"查询华宝成交流水失败: {e}")
            return []
        finally:
            conn.close()

    # --- [AI-2026-08-15] 银河QMT历史成交（经桥接策略 QUERY_DEALS 实时查询入库） ---
    @staticmethod
    def _normalize_qmt_date(d: str) -> str:
        d = (d or "").strip()
        if len(d) == 8 and d.isdigit():           # YYYYMMDD -> YYYY-MM-DD
            return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
        return d

    @staticmethod
    def _extract_qmt_deal(rec: Dict[str, Any]) -> Dict[str, Any]:
        """从 QMT TradeDetail 属性字典提取结构化字段（字段名以首轮 DEAL_ATTRS 联调为准，此处做容错映射）。"""
        account = rec.get('m_strAccountID') or rec.get('m_strAccount') or ''
        code = rec.get('m_strInstrumentID') or rec.get('m_strContractCode') or ''
        name = rec.get('m_strInstrumentName') or ''
        trade_date = LedgerService._normalize_qmt_date(rec.get('m_strTradeDate') or '')
        t = rec.get('m_strTradeTime') or ''
        # m_strTradeTime 可能是 "20260602 09:30:00" 或 "09:30:00"
        if ' ' in t:
            t = t.split(' ', 1)[1]
        try:
            price = float(rec.get('m_dPrice') or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            volume = float(rec.get('m_nVolume') or 0)
        except (TypeError, ValueError):
            volume = 0.0
        try:
            amount = float(rec.get('m_dTradeMoney') or 0)
        except (TypeError, ValueError):
            amount = 0.0
        try:
            fee = float(rec.get('m_dTradeCost') or 0)
        except (TypeError, ValueError):
            fee = 0.0
        # 方向（买/卖）：QMT 字段名待首轮联调确认，此处尽力映射
        direction = rec.get('m_nDirection')
        side = 'OTHER'
        if isinstance(direction, str):
            if '买' in direction: side = 'BUY'
            elif '卖' in direction: side = 'SELL'
        elif isinstance(direction, (int, float)):
            if direction in (48,): side = 'BUY'
            elif direction in (49,): side = 'SELL'
        return {
            "account": account, "code": code, "name": name,
            "trade_date": trade_date, "trade_time": t,
            "side": side, "price": price, "volume": volume,
            "amount": amount, "fee": fee,
            "raw": json.dumps(rec, ensure_ascii=False, default=str),
        }

    def import_qmt_rows(self, rows: List[Dict[str, Any]]) -> int:
        """写入银河QMT历史成交流水（按 account+code+date+time+volume+price 唯一幂等）。返回写入条数。"""
        if not rows:
            return 0
        conn = self.db._get_conn()
        try:
            cnt = 0
            for rec in rows:
                r = self._extract_qmt_deal(rec)
                conn.execute("""
                    INSERT OR REPLACE INTO qmt_executions
                    (account, code, name, trade_date, trade_time, side, price, volume, amount, fee, raw)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    r["account"], r["code"], r["name"], r["trade_date"], r["trade_time"],
                    r["side"], r["price"], r["volume"], r["amount"], r["fee"], r["raw"]
                ))
                cnt += 1
            conn.commit()
            return cnt
        except Exception as e:
            logger.error(f"写入银河QMT成交流水失败: {e}")
            return 0
        finally:
            conn.close()

    def get_qmt_executions(self, code: str = None, days: int = 0) -> List[Dict[str, Any]]:
        """查询银河QMT成交流水。可选 code 过滤，days>0 按 trade_date 过滤。"""
        conn = self.db._get_conn()
        try:
            sql = "SELECT * FROM qmt_executions WHERE 1=1"
            params: List[Any] = []
            if code:
                sql += " AND code = ?"; params.append(code)
            if days and days > 0:
                since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
                sql += " AND trade_date >= ?"; params.append(since)
            sql += " ORDER BY trade_date DESC, trade_time DESC"
            df = pd.read_sql_query(sql, conn, params=params)
            return df.to_dict(orient='records')
        except Exception as e:
            logger.error(f"查询银河QMT成交流水失败: {e}")
            return []
        finally:
            conn.close()

    # ================================================================
    # [AI-2026-08-15] 手动配对对账（扶正假对账）
    # ================================================================

    @staticmethod
    def _normalize_leg_side(source: str, side) -> str:
        """归一化腿方向：BUY/REDEEM(含LOF场内卖出)/SHORT(做空)/COVER(平仓)。"""
        s = (side or "").strip().upper()
        if source in ("tdx", "qmt"):
            if s == "BUY":
                return "BUY"
            if s in ("REDEEM", "SELL"):
                return "REDEEM"
            return s
        else:
            if s == "SELL":
                return "SHORT"
            if s == "BUY":
                return "COVER"
            return s

    def _load_leg(self, conn, source: str, leg_id: int):
        if source == "tdx":
            r = conn.execute("SELECT id, trade_date, trade_time, account, code, name, side, qty, price, amount, total_fee FROM tdx_executions WHERE id=?", (leg_id,)).fetchone()
            if not r:
                return None
            return {"source": "tdx", "leg_id": r[0], "trade_date": r[1], "trade_time": r[2], "account": r[3], "code": r[4], "name": r[5],
                    "side": self._normalize_leg_side("tdx", r[6]), "qty": r[7], "price": r[8], "amount": r[9], "fee": r[10] or 0}
        if source == "qmt":
            r = conn.execute("SELECT id, trade_date, trade_time, account, code, name, side, volume, price, amount, fee FROM qmt_executions WHERE id=?", (leg_id,)).fetchone()
            if not r:
                return None
            return {"source": "qmt", "leg_id": r[0], "trade_date": r[1], "trade_time": r[2], "account": r[3], "code": r[4], "name": r[5],
                    "side": self._normalize_leg_side("qmt", r[6]), "qty": r[7], "price": r[8], "amount": r[9], "fee": r[10] or 0}
        if source == "ib":
            r = conn.execute("SELECT id, local_date, trade_time, account, symbol, side, shares, price, commission FROM ib_executions WHERE id=?", (leg_id,)).fetchone()
            if not r:
                return None
            return {"source": "ib", "leg_id": r[0], "trade_date": r[1], "trade_time": r[2], "account": r[3], "code": r[4], "name": r[4],
                    "side": self._normalize_leg_side("ib", r[5]), "qty": r[6], "price": r[7], "amount": (r[6] or 0) * (r[7] or 0), "fee": r[8] or 0}
        return None

    def _attach_master(self, conn):
        """在交易库(tran)连接上 ATTACH 主库(master)，供跨库读因子。返回别名('master'或'main')。"""
        if not getattr(self, 'master_db_path', None):
            return 'main'
        try:
            conn.execute("ATTACH DATABASE ? AS master", (self.master_db_path,))
        except sqlite3.OperationalError:
            pass  # 已 attach
        return 'master'

    def _get_hedge(self, conn, fund_code: str, date: str):
        m = self._attach_master(conn)
        row = conn.execute(f"SELECT hedge FROM {m}.fund_daily_factors WHERE fund_code=? AND date=? LIMIT 1", (fund_code, date)).fetchone()
        if row and row[0]:
            return float(row[0])
        row = conn.execute(f"SELECT hedge FROM {m}.fund_daily_factors WHERE fund_code=? ORDER BY date DESC LIMIT 1", (fund_code,)).fetchone()
        return float(row[0]) if row and row[0] else None

    def _get_redeem_rate(self, conn, fund_code: str) -> float:
        row = conn.execute("SELECT fee_rate FROM broker_redemption_fees WHERE fund_code=? LIMIT 1", (fund_code,)).fetchone()
        try:
            return float(row[0]) if row and row[0] else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _get_usd_rate_on(self, conn, date: str) -> float:
        m = self._attach_master(conn)
        row = conn.execute(f"SELECT usd_cny_mid FROM {m}.exchange_rate WHERE date=? LIMIT 1", (date,)).fetchone()
        if row and row[0]:
            return float(row[0])
        row = conn.execute(f"SELECT usd_cny_mid FROM {m}.exchange_rate ORDER BY date DESC LIMIT 1").fetchone()
        return float(row[0]) if row and row[0] else 7.2

    def get_unpaired_trades(self) -> List[Dict[str, Any]]:
        """汇总 tdx/qmt/ib 三源所有未配对交易，统一格式，按日期倒序。
        REDEEM 腿的 fee 自动加 redeem_fee 估算（amount × broker_fee_rate / 100），让前端配对前就看到完整费用。"""
        conn = self.db._get_conn()
        try:
            paired = {(r[0], r[1]) for r in conn.execute("SELECT leg_source, leg_id FROM pair_legs").fetchall()}
            fee_rate_map = {r[0]: float(r[1]) for r in conn.execute("SELECT fund_code, fee_rate FROM broker_redemption_fees").fetchall() if r[1]}
            trades: List[Dict[str, Any]] = []
            for r in conn.execute("SELECT id, trade_date, trade_time, account, code, name, side, qty, price, amount, total_fee FROM tdx_executions ORDER BY trade_date DESC, trade_time DESC").fetchall():
                if ("tdx", r[0]) in paired:
                    continue
                fee = r[10] or 0
                side_norm = self._normalize_leg_side("tdx", r[6])
                if side_norm == "REDEEM":
                    fee_rate = fee_rate_map.get(r[4], 0)
                    fee = round(fee + (r[9] or 0) * fee_rate / 100.0, 2)
                trades.append({"key": "tdx:%s" % r[0], "source": "tdx", "leg_id": r[0], "trade_date": r[1], "trade_time": r[2], "account": r[3],
                               "code": r[4], "name": r[5], "side": side_norm,
                               "qty": r[7], "price": r[8], "amount": r[9], "fee": fee})
            for r in conn.execute("SELECT id, trade_date, trade_time, account, code, name, side, volume, price, amount, fee FROM qmt_executions ORDER BY trade_date DESC, trade_time DESC").fetchall():
                if ("qmt", r[0]) in paired:
                    continue
                fee = r[10] or 0
                side_norm = self._normalize_leg_side("qmt", r[6])
                if side_norm == "REDEEM":
                    fee_rate = fee_rate_map.get(r[4], 0)
                    fee = round(fee + (r[9] or 0) * fee_rate / 100.0, 2)
                trades.append({"key": "qmt:%s" % r[0], "source": "qmt", "leg_id": r[0], "trade_date": r[1], "trade_time": r[2], "account": r[3],
                               "code": r[4], "name": r[5], "side": side_norm,
                               "qty": r[7], "price": r[8], "amount": r[9], "fee": fee})
            for r in conn.execute("SELECT id, local_date, trade_time, account, symbol, side, shares, price, commission FROM ib_executions WHERE symbol IN ('XOP','GLD','INDA') ORDER BY local_date DESC, trade_time DESC").fetchall():
                if ("ib", r[0]) in paired:
                    continue
                _tt = (r[2] or "")
                if " " in _tt:
                    _tt = _tt.split(" ")[-1]
                trades.append({"key": "ib:%s" % r[0], "source": "ib", "leg_id": r[0], "trade_date": r[1], "trade_time": _tt, "account": r[3],
                               "code": r[4], "name": r[4], "side": self._normalize_leg_side("ib", r[5]),
                               "qty": r[6], "price": r[7], "amount": (r[6] or 0) * (r[7] or 0), "fee": r[8] or 0})

            def _ts(t):
                tt = (t.get("trade_time") or "")
                if " " in tt:
                    tt = tt.split(" ")[-1]
                return (t.get("trade_date") or "", tt)
            trades.sort(key=_ts, reverse=True)
            return trades
        finally:
            conn.close()

    def match_pair(self, leg_keys: List[str], force: bool = False) -> Dict[str, Any]:
        """手动配对：勾选最多4条腿 -> 归位/校验对冲/算收益 -> 写 arbitrage_pairs + pair_legs。"""
        conn = self.db._get_conn()
        try:
            legs = []
            for key in leg_keys:
                if ":" not in key:
                    return {"ok": False, "error": "腿标识非法: %s" % key}
                source, leg_id = key.split(":", 1)
                leg = self._load_leg(conn, source, int(leg_id))
                if leg is None:
                    return {"ok": False, "error": "腿不存在: %s" % key}
                legs.append(leg)
            if not legs:
                return {"ok": False, "error": "未选择任何腿"}

            buy = sell = short = cover = None
            for lg in legs:
                if lg["side"] == "BUY":
                    buy = lg
                elif lg["side"] == "REDEEM":
                    sell = lg
                elif lg["side"] == "SHORT":
                    short = lg
                elif lg["side"] == "COVER":
                    cover = lg

            if buy and sell and buy["code"] != sell["code"]:
                return {"ok": False, "error": "LOF买入(%s)与赎回(%s)不是同一基金" % (buy["code"], sell["code"])}
            if short and cover and short["code"] != cover["code"]:
                return {"ok": False, "error": "ETF做空(%s)与平仓(%s)不是同一标的" % (short["code"], cover["code"])}

            if buy and short and not force:
                hedge = self._get_hedge(conn, buy["code"], buy["trade_date"])
                if hedge:
                    expected = (buy["qty"] or 0) / hedge
                    actual = short["qty"] or 0
                    if expected > 0:
                        diff = abs(actual - expected) / expected
                        if diff > 0.10:
                            warn = ("对冲数量不匹配：LOF %.0f份 ÷ hedge %.1f ≈ %.0f股，实际做空 %.0f股（差 %.0f%%）"
                                    % (buy["qty"], hedge, expected, actual, diff * 100))
                            return {"ok": False, "warning": warn}

            fund_code = (buy or sell or {}).get("code") or ""
            fund_name = (buy or sell or {}).get("name") or ""
            hedge_symbol = (short or cover or {}).get("code") or ""

            buy_cost = 0.0
            if buy:
                buy_cost = (buy["amount"] or 0) + (buy["fee"] or 0)

            sell_net = 0.0
            redeem_fee = 0.0
            if sell:
                fee_rate = self._get_redeem_rate(conn, sell["code"])
                redeem_fee = round((sell["amount"] or 0) * fee_rate / 100.0, 2)
                sell_net = (sell["amount"] or 0) - (sell["fee"] or 0) - redeem_fee

            a_pnl = round(sell_net - buy_cost, 2) if (buy or sell) else None

            us_pnl = 0.0
            us_comm = 0.0
            if short and cover:
                short_amt = (short["qty"] or 0) * (short["price"] or 0)
                cover_amt = (cover["qty"] or 0) * (cover["price"] or 0)
                us_comm = (short["fee"] or 0) + (cover["fee"] or 0)
                us_pnl = round(short_amt - cover_amt - us_comm, 2)
            elif short or cover:
                us_pnl = None

            usd_rate = self._get_usd_rate_on(conn, (cover or sell or buy or {}).get("trade_date") or "") if (cover or sell or buy) else 7.2

            pnl_rmb = None
            pnl_usd = None
            if a_pnl is not None and us_pnl is not None:
                pnl_rmb = round(a_pnl + us_pnl * usd_rate, 2)
                pnl_usd = round(us_pnl, 2)
            elif a_pnl is not None:
                pnl_rmb = round(a_pnl, 2)
            elif us_pnl is not None:
                pnl_rmb = round(us_pnl * usd_rate, 2)
                pnl_usd = round(us_pnl, 2)

            has_lof_open = buy is not None
            has_lof_close = sell is not None
            has_etf_open = short is not None
            has_etf_close = cover is not None
            if has_lof_open and has_lof_close and has_etf_open and has_etf_close:
                status = "已结"
            elif has_lof_open and not has_lof_close:
                status = "未赎回"
            elif has_lof_open and has_lof_close and not (has_etf_open and has_etf_close):
                status = "未对冲"
            elif has_lof_open != has_etf_open:
                status = "单边"
            else:
                status = "未对冲"

            pair_id = conn.execute(
                """INSERT INTO arbitrage_pairs
                (fund_code, fund_name, buy_date, buy_price, buy_volume, buy_amount, buy_account,
                 sell_date, sell_price, sell_volume, sell_amount, redemption_fee,
                 hedge_symbol, short_date, short_price, short_volume, short_amount,
                 cover_date, cover_price, cover_volume, cover_amount, us_commission,
                 pnl_rmb, pnl_usd, status, broker_name, close_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fund_code, fund_name,
                 (buy or {}).get("trade_date"), (buy or {}).get("price"), (buy or {}).get("qty"),
                 (buy["amount"] if buy else None), (buy or {}).get("account"),
                 (sell or {}).get("trade_date"), (sell or {}).get("price"), (sell or {}).get("qty"), (sell["amount"] if sell else None), (redeem_fee or None),
                 hedge_symbol,
                 (short or {}).get("trade_date"), (short or {}).get("price"), (short or {}).get("qty"), (short["amount"] if short else None),
                 (cover or {}).get("trade_date"), (cover or {}).get("price"), (cover or {}).get("qty"), (cover["amount"] if cover else None), (us_comm or None),
                 pnl_rmb, pnl_usd, status, "", "REDEEM"))
            pair_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for role, lg in (("buy", buy), ("sell", sell), ("short", short), ("cover", cover)):
                if lg:
                    conn.execute("INSERT OR REPLACE INTO pair_legs (pair_id, leg_source, leg_id, role) VALUES (?,?,?,?)",
                                 (pair_id, lg["source"], lg["leg_id"], role))
            conn.commit()
            return {"ok": True, "pair_id": pair_id, "status": status,
                    "pnl_rmb": pnl_rmb, "pnl_usd": pnl_usd, "a_pnl": a_pnl, "us_pnl": us_pnl, "usd_rate": usd_rate}
        except Exception as e:
            logger.error("配对失败: %s" % e)
            return {"ok": False, "error": "配对失败: %s" % e}
        finally:
            conn.close()

    def get_matched_pairs(self) -> List[Dict[str, Any]]:
        """已配对列表（复用 get_all_pairs + 附每条腿 source:id）。"""
        pairs = self.get_all_pairs()
        conn = self.db._get_conn()
        try:
            leg_map = {}
            for r in conn.execute("SELECT pair_id, leg_source, leg_id, role FROM pair_legs").fetchall():
                leg_map.setdefault(r[0], []).append({"source": r[1], "leg_id": r[2], "role": r[3], "key": "%s:%s" % (r[1], r[2])})
            for p in pairs:
                p["legs"] = leg_map.get(p.get("id"), [])
            return pairs
        finally:
            conn.close()

    def unmatch_pair(self, pair_id: int) -> Dict[str, Any]:
        """撤销配对：删除 arbitrage_pairs + pair_legs，释放腿回到待配对区。"""
        conn = self.db._get_conn()
        try:
            conn.execute("DELETE FROM pair_legs WHERE pair_id=?", (pair_id,))
            conn.execute("DELETE FROM arbitrage_pairs WHERE id=?", (pair_id,))
            conn.commit()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            conn.close()
