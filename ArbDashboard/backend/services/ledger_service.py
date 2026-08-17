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

    def _get_rates_map(self, conn) -> dict:
        """一次性加载 exchange_rate 全表 -> {date: usd_cny_mid}（升序），供按日取汇率"""
        try:
            m = self._attach_master(conn)
            rows = conn.execute(
                f"SELECT date, usd_cny_mid FROM {m}.exchange_rate WHERE usd_cny_mid IS NOT NULL ORDER BY date"
            ).fetchall()
            return {r[0]: float(r[1]) for r in rows}
        except Exception:
            return {}

    @staticmethod
    def _rate_on(rates: dict, date_str) -> float:
        """取指定日期（或之前最近一天）的美元中间价；无数据回退 7.2"""
        if not rates:
            return 7.2
        if date_str and date_str in rates:
            return rates[date_str]
        if date_str:
            prior = [k for k in rates if k <= date_str]
            if prior:
                return rates[max(prior)]
        return list(rates.values())[-1]

    def get_all_pairs(self, status: str = None) -> List[Dict[str, Any]]:
        """获取套利对列表"""
        conn = self.db._get_conn()
        try:
            if status:
                df = pd.read_sql_query(
                    "SELECT * FROM arbitrage_pairs WHERE status = ? ORDER BY buy_date DESC",
                    conn, params=(status,)
                )
            else:
                df = pd.read_sql_query(
                    "SELECT * FROM arbitrage_pairs ORDER BY buy_date DESC",
                    conn
                )
            pairs = df.to_dict(orient='records')
            # [AI-2026-08-16] pandas 把 SQL NULL 读成 NaN，NaN 无法 JSON 序列化（会 500），转回 None
            for p in pairs:
                for k, v in list(p.items()):
                    if isinstance(v, float) and (v != v or v in (float('inf'), float('-inf'))):
                        p[k] = None
            rates = self._get_rates_map(conn)
            for p in pairs:
                # 计算各子项盈亏
                buy_amt = p.get('buy_amount') or 0
                sell_amt = p.get('sell_amount') or 0
                redeem_fee = p.get('redemption_fee') or 0
                short_amt = p.get('short_amount') or 0
                cover_amt = p.get('cover_amount') or 0
                us_comm = p.get('us_commission') or 0
                # 汇率：用该笔平仓日（无则开仓日）当天的库里人民币中间价，而非通用汇率
                rate = self._rate_on(rates, p.get('sell_date') or p.get('buy_date'))

                # A股盈亏：优先从 v7 真相源反算（pnl_rmb=M列, pnl_usd=R列）
                # 不用 sell-buy-fee 重算——迁移时 buy/sell 金额可能有错位导致巨偏差
                if p.get('pnl_usd') is not None and p.get('pnl_rmb') is not None:
                    p['a_share_pnl'] = round(p['pnl_rmb'] - p['pnl_usd'] * rate, 2)
                    p['us_pnl'] = round(p['pnl_usd'], 2)
                else:
                    p['a_share_pnl'] = round(sell_amt - buy_amt - redeem_fee, 2) if (sell_amt or buy_amt) else None
                    p['us_pnl'] = round((cover_amt - short_amt) - us_comm, 2) if (cover_amt or short_amt) else None
                    if p['a_share_pnl'] is not None and p['us_pnl'] is not None:
                        p['pnl_rmb'] = round(p['a_share_pnl'] + p['us_pnl'] * rate, 2)
                        p['pnl_usd'] = round(p['us_pnl'], 2)
            return pairs
        finally:
            conn.close()

    def add_pair(self, data: Dict[str, Any]) -> int:
        """新增套利对"""
        conn = self.db._get_conn()
        try:
            self._ensure_open_type(conn)
            buy_vol = data.get('buy_volume') or 0
            buy_price = data.get('buy_price') or 0
            buy_amount = data.get('buy_amount') or (buy_vol * buy_price)
            short_vol = data.get('short_volume') or 0
            short_price = data.get('short_price') or 0
            short_amount = data.get('short_amount') or (short_vol * short_price)

            rates = self._get_rates_map(conn)
            rate = self._rate_on(rates, data.get('sell_date') or data.get('buy_date'))
            sell_amt = data.get('sell_amount') or 0
            redeem_fee = data.get('redemption_fee') or 0
            cover_amt = data.get('cover_amount') or 0
            us_comm = data.get('us_commission') or 0

            a_pnl = sell_amt - buy_amount - redeem_fee
            u_pnl = (cover_amt - short_amount) - us_comm
            pnl_rmb = round(a_pnl + u_pnl * rate, 2)
            pnl_usd = round(u_pnl, 2)

            conn.execute('''
                INSERT INTO arbitrage_pairs
                (fund_code, fund_name, buy_date, buy_price, buy_volume, buy_amount, buy_account,
                 sell_date, sell_price, sell_volume, sell_amount, redemption_fee,
                 hedge_symbol, short_date, short_price, short_volume, short_amount,
                 cover_date, cover_price, cover_volume, cover_amount, us_commission,
                 pnl_rmb, pnl_usd, status, buy_notes, sell_notes, notes,
                 broker_name, open_type, close_type)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
?            ''', (
                data['fund_code'], data.get('fund_name', ''),
                data.get('buy_date'), buy_price, buy_vol, buy_amount, data.get('buy_account'),
                data.get('sell_date'), data.get('sell_price'), data.get('sell_volume'), sell_amt, redeem_fee,
                data.get('hedge_symbol'), data.get('short_date'), short_price, short_vol, short_amount,
                data.get('cover_date'), data.get('cover_price'), data.get('cover_volume'), cover_amt, us_comm,
                pnl_rmb, pnl_usd, data.get('status', 'ACTIVE'),
                data.get('buy_notes'), data.get('sell_notes'), data.get('notes'),
                data.get('broker_name', ''), data.get('open_type', 'BUY'), data.get('close_type', 'REDEEM')
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
                        'broker_name','open_type','close_type']:
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

                rates = self._get_rates_map(conn)
                rate = self._rate_on(rates, data.get('sell_date') or data.get('buy_date'))
                a_pnl = sell_amt - buy_amt - redeem_fee
                u_pnl = (cover_amt - short_amt) - us_comm
                pnl_rmb = round(a_pnl + u_pnl * rate, 2)
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

    def _ensure_open_type(self, conn):
        """确保 arbitrage_pairs.open_type 列存在（记录 A股开仓真实类型 BUY/SUBSCRIBE），幂等。"""
        try:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(arbitrage_pairs)").fetchall()]
            if "open_type" not in cols:
                conn.execute("ALTER TABLE arbitrage_pairs ADD COLUMN open_type TEXT DEFAULT 'BUY'")
                conn.commit()
        except Exception:
            pass


    # ================================================================
    # [AI-2026-08-16] 赎回告警：OPEN 笔推算可优惠赎回日 + unfinished 待净值
    # ================================================================
    def _discount_redeem_date(self, buy_date_str: str):
        """按买入星期推算可优惠赎回日：周一/二买+3天、周三/四/五买+5天，跳过周末。"""
        try:
            buy = datetime.strptime(buy_date_str, '%Y-%m-%d').date()
        except Exception:
            return None
        wd = buy.weekday()  # Mon=0..Sun=6
        if wd in (0, 1):
            days = 3
        elif wd in (2, 3, 4):
            days = 5
        else:  # 周六/周日（A股不会出现，兜底+7）
            days = 7
        d = buy + timedelta(days=days)
        while d.weekday() >= 5:  # 跳过周末
            d += timedelta(days=1)
        return d

    # [AI-2026-08-16] 导入 v7 Excel 套利账本：解析 -> upsert 到 arbitrage_pairs
    _HEDGE_MAP = {'162411': 'XOP', '164701': 'GLD', '161116': 'GLD', '164824': 'INDA'}
    _STATUS_MAP = {'closed': 'Closed', 'final': 'Closed', 'open': 'OPEN', 'unfinished': 'unfinished'}

    def _parse_v7_groups(self, file_path: str) -> List[Dict[str, Any]]:
        """解析 v7 Excel，返回 [{summary, details}] 列表。每组配对由连续的明细行 + 一个汇总行组成。"""
        import openpyxl
        STATUS_WORDS = {'closed', 'final', 'open', 'unfinished'}
        wb = openpyxl.load_workbook(file_path, data_only=True)
        ws = wb.active

        def _num(v):
            if v is None:
                return None
            s = str(v).strip()
            neg = s.startswith('-') or s.startswith('(')
            s2 = s.replace('¥', '').replace('$', '').replace(',', '').replace('(', '').replace(')', '')
            try:
                n = float(s2)
                return -n if neg else n
            except Exception:
                return None

        def _date(v):
            if v is None:
                return None
            if hasattr(v, 'year'):
                return v.strftime('%Y-%m-%d')
            s = str(v).strip()
            m = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', s)
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            return None

        groups = []
        cur = None
        for r in range(2, ws.max_row + 1):
            A = ws.cell(r, 1).value
            D = ws.cell(r, 4).value
            E = ws.cell(r, 5).value
            N = ws.cell(r, 14).value
            O = ws.cell(r, 15).value
            R = ws.cell(r, 18).value
            if A is None and D is None and E is None and N is None:
                if cur:
                    groups.append(cur)
                    cur = None
                continue
            E = str(E).strip() if E else ''
            D = str(D).strip() if D else ''
            A_str = str(A).strip() if A else ''
            if E == '汇总':
                if cur is None:
                    cur = {'details': [], 'fund': D}
                cur['fund'] = D or cur.get('fund')
                a_is_date = hasattr(A, 'year') or (A_str and A_str.lower() not in STATUS_WORDS)
                summary = {
                    'status': self._STATUS_MAP.get(A_str.lower(), 'Final' if a_is_date else A_str),
                    'fund': D,
                    'pnl_rmb': _num(ws.cell(r, 13).value),
                    'pnl_usd': _num(R),
                    'buy_date': _date(A) if a_is_date else None,
                    'sell_date': _date(A) if a_is_date else None,
                }
                cur['summary'] = summary
                groups.append(cur)
                cur = None
                continue
            has_us = (N is not None) or (O is not None) or (R is not None)
            if D or has_us:
                if cur is None:
                    cur = {'details': [], 'fund': D}
                if D:
                    cur['fund'] = D
                cur['details'].append({
                    'action': E or '美股明细',
                    'date': _date(A),
                    'volume': _num(ws.cell(r, 9).value),
                    'short_vol': _num(N),
                })
        if cur:
            groups.append(cur)
        return groups

    def import_v7(self, file_path: str) -> Dict[str, Any]:
        """解析 v7 Excel 并 upsert 到 arbitrage_pairs。
        匹配键：fund_code + abs(pnl_rmb)≈。已存在的行更新（保留DB独有日期若v7无），不存在则插入。不删除DB独有行。
        返回 {inserted, updated, skipped, errors}。
        """
        groups = self._parse_v7_groups(file_path)
        conn = self.db._get_conn()
        try:
            inserted = 0
            updated = 0
            skipped = 0
            errors = []
            for g in groups:
                s = g.get('summary')
                if not s:
                    skipped += 1
                    continue
                fund = (s.get('fund') or '').strip()
                if not fund:
                    errors.append(f"组缺少基金代码 (pnl_rmb={s.get('pnl_rmb')})")
                    skipped += 1
                    continue
                pnl_rmb = s.get('pnl_rmb')
                pnl_usd = s.get('pnl_usd')
                buys = [d for d in g['details'] if d['action'] in ('买入', '开仓续')]
                sells = [d for d in g['details'] if d['action'] in ('卖出', '赎回')]
                buy_date = s.get('buy_date') or (buys[0]['date'] if buys else None)
                sell_date = s.get('sell_date') or (sells[-1]['date'] if sells else None)
                buy_volume = sum(d['volume'] or 0 for d in buys) or None
                sell_volume = sum(abs(d['volume'] or 0) for d in sells) or None
                short_volume = sum(abs(d['short_vol'] or 0) for d in g['details'] if (d['short_vol'] or 0) < 0)
                if not short_volume:
                    short_volume = max([abs(d['short_vol'] or 0) for d in g['details']] or [0]) or None
                status = s.get('status') or 'Closed'
                hedge = self._HEDGE_MAP.get(fund, '')
                broker = '华宝' if fund == '162411' else '银河'

                existing = conn.execute(
                    """SELECT id FROM arbitrage_pairs
                       WHERE fund_code=? AND (ABS(pnl_rmb - ?) < 0.01
                           OR ABS(ABS(pnl_rmb) - ABS(?)) < 0.01)""",
                    (fund, pnl_rmb or 0, pnl_rmb or 0)
                ).fetchone()
                if existing:
                    pid = existing[0]
                    conn.execute(
                        """UPDATE arbitrage_pairs SET
                            buy_date=COALESCE(?, buy_date), sell_date=COALESCE(?, sell_date),
                            buy_volume=COALESCE(?, buy_volume), sell_volume=COALESCE(?, sell_volume),
                            short_volume=COALESCE(?, short_volume), pnl_rmb=?, pnl_usd=?,
                            status=?, hedge_symbol=?, broker_name=?
                            WHERE id=?""",
                        (buy_date, sell_date, buy_volume, sell_volume, short_volume,
                         pnl_rmb, pnl_usd, status, hedge, broker, pid)
                    )
                    updated += 1
                else:
                    conn.execute(
                        """INSERT INTO arbitrage_pairs
                            (fund_code, buy_date, sell_date, buy_volume, sell_volume, short_volume,
                             pnl_rmb, pnl_usd, status, hedge_symbol, broker_name)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                        (fund, buy_date, sell_date, buy_volume, sell_volume, short_volume,
                         pnl_rmb, pnl_usd, status, hedge, broker)
                    )
                    inserted += 1
            conn.commit()
            return {'inserted': inserted, 'updated': updated, 'skipped': skipped, 'errors': errors}
        except Exception as e:
            logger.error(f"导入 v7 失败: {e}")
            raise
        finally:
            conn.close()

    def get_ledger_alerts(self) -> Dict[str, Any]:
        """赎回提醒：OPEN 笔推算可优惠赎回日/倒计时/告警级别；unfinished 提示待净值。"""
        pairs = self.get_all_pairs()
        today = datetime.now().date()
        _wd_cn = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        open_alerts = []
        unfinished_alerts = []
        for p in pairs:
            status = (p.get('status') or '').strip()
            if status == 'OPEN':
                buy_date = p.get('buy_date')
                if not buy_date:
                    continue
                redeem_d = self._discount_redeem_date(buy_date)
                if redeem_d is None:
                    continue
                days_left = (redeem_d - today).days
                wd_cn = _wd_cn[redeem_d.weekday()]
                if days_left <= 0:
                    level, msg = 'critical', f"已到可优惠赎回日（{redeem_d.isoformat()} {wd_cn}），请赎回"
                elif days_left == 1:
                    level, msg = 'warning', f"明天（{redeem_d.isoformat()} {wd_cn}）即可优惠赎回"
                elif days_left <= 3:
                    level, msg = 'notice', f"还有 {days_left} 天到可优惠赎回日（{redeem_d.isoformat()} {wd_cn}）"
                else:
                    level, msg = 'info', f"还有 {days_left} 天到可优惠赎回日（{redeem_d.isoformat()} {wd_cn}）"
                open_alerts.append({
                    'id': p.get('id'), 'fund_code': p.get('fund_code'), 'fund_name': p.get('fund_name'),
                    'buy_date': buy_date, 'redeem_date': redeem_d.isoformat(), 'redeem_weekday': wd_cn,
                    'days_left': days_left, 'level': level, 'message': msg,
                    'short_volume': p.get('short_volume'), 'short_price': p.get('short_price'),
                    'buy_volume': p.get('buy_volume'),
                    'pnl_rmb': p.get('pnl_rmb'), 'pnl_usd': p.get('pnl_usd'),
                })
            elif status == 'unfinished':
                unfinished_alerts.append({
                    'id': p.get('id'), 'fund_code': p.get('fund_code'), 'fund_name': p.get('fund_name'),
                    'buy_date': p.get('buy_date'), 'sell_date': p.get('sell_date'),
                    'level': 'warning', 'message': '已赎回，但基金净值尚未公布，待净值出炉后可结算',
                })
        open_alerts.sort(key=lambda x: (x['days_left'] if x['days_left'] is not None else 999))
        return {
            'today': today.isoformat(),
            'open_count': len(open_alerts),
            'unfinished_count': len(unfinished_alerts),
            'open_alerts': open_alerts,
            'unfinished_alerts': unfinished_alerts,
        }

