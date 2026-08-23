# -*- coding: utf-8 -*-
"""
RuleEngine — 自动化分档位规则引擎（DB 驱动版）
=================================================
- 规则全部存储在 DB `auto_trade_rules` 表
- 支持多基金并行评估（按 fund_code 分组）
- hedge_symbol 从 unified_fund_list.trade_etf 自动映射
- 参数（阈值、仓位、现金约束）全部可配
- CRUD API 通过 main.py 暴露
"""
import threading
import time
import logging
import sqlite3
import os
from collections import deque, defaultdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger("RuleEngine")

# ---------- 内置日志 ----------
class _LogHandler(logging.Handler):
    def __init__(self, capacity=200):
        super().__init__()
        self.logs = deque(maxlen=capacity)
    def emit(self, record):
        self.logs.appendleft({
            "time": datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
            "level": record.levelname,
            "message": record.getMessage()
        })

_log_handler = _LogHandler()
if not any(isinstance(h, _LogHandler) for h in logger.handlers):
    logger.addHandler(_log_handler)
logger.setLevel(logging.INFO)


# ====================================================================
# 默认种子规则（首次创建表时自动写入）
# ====================================================================
# [AI-2026-08-22] 简化版种子规则：只保留溢价率阈值，去掉仓位/现金约束
# 每笔开仓约5万元（LOF数量=100的倍数）
PER_TRIGGER_MAX_YUAN = 50000

# [AI-2026-08-22] 券商路由：TDX（华宝通达信） vs QMT
TDX_FUNDS = {"162411"}  # 162411 赎回时佣金便宜，走华宝通达信

# [AI-2026-08-23] 默认每笔交易数量（可被用户自定义覆盖）
DEFAULT_TRIGGER_QTY = {
    "lof_qty": 10000,  # 默认1万LOF股（约5万元）
    "etf_qty": 60,     # 默认60ETF股
}

# [AI-2026-08-23] 允许用户自定义（从数据库 fund_trade_config 表读取，不存在则用 DEFAULT）

SEED_RULES = [
    # ── 164701 + GLD 开仓（折价够深 → 买入） ──
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "open",  "condition": "lt",  "threshold": -0.70, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L1 溢价<-0.70% 开仓"},
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "open",  "condition": "lt",  "threshold": -0.85, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L2 溢价<-0.85% 开仓"},
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "open",  "condition": "lt",  "threshold": -1.00, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L3 溢价<-1.00% 开仓"},
    # ── 164701 + GLD 平仓（折价收敛 → 卖出） ──
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "close", "condition": "gt",  "threshold": -0.20, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L1 溢价>-0.20% 平仓"},
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "close", "condition": "gt",  "threshold": -0.50, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L2 溢价>-0.50% 平仓"},
    {"fund_code": "164701", "hedge_symbol": "GLD", "direction": "close", "condition": "gt",  "threshold": -0.70, "pos_constraint": None, "pos_value": None, "cash_constraint": None, "cash_value": None, "enabled": True,  "note": "L3 溢价>-0.70% 平仓"},
]


# ====================================================================
# 规则引擎
# ====================================================================
class RuleEngine:

    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._db_path: Optional[str] = None
        self._master_db_path: Optional[str] = None  # [AI-2026-08-16] master 库路径，_lookup_hedge 跨库读 unified_fund_list

        # 依赖注入
        self.fund_service = None
        self.lazy_trader = None
        self.trading_service = None  # [AI-2026-07-02] TDX下单用

        # ISG 防重入
        self._last_fired: dict[str, float] = {}
        self.COOLDOWN_SECONDS = 60

        # 缓存每基金的实时数据，避免重复获取
        self._market_cache: dict[str, dict] = {}

    # ── 依赖注入 ──
    # [AI-2026-07-02] 增加 trading_service 用于TDX下单
    def inject(self, fund_service=None, lazy_trader=None, trading_service=None, db_path=None, master_db_path=None):
        if fund_service:
            self.fund_service = fund_service
        if lazy_trader:
            self.lazy_trader = lazy_trader
        if trading_service:
            self.trading_service = trading_service
        if db_path:
            self._db_path = db_path
            self._init_db()
        if master_db_path:
            self._master_db_path = master_db_path

    # ── 数据库初始化 ──
    def _get_conn(self):
        if not self._db_path:
            # 备用源路径
            # [AI-2026-08-16] 活库移出仓库根到 D:\Study\arbTest\database（物理隔离防泄漏）；root再上两层到项目根父目录
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self._db_path = os.path.join(os.path.dirname(root), '..', '..', 'database', 'arb_master.db')
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auto_trade_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fund_code TEXT NOT NULL,
                    hedge_symbol TEXT NOT NULL DEFAULT '',
                    direction TEXT NOT NULL CHECK(direction IN ('open','close')),
                    condition TEXT NOT NULL CHECK(condition IN ('gt','lt')),
                    threshold REAL NOT NULL,
                    pos_constraint TEXT,
                    pos_value REAL,
                    cash_constraint TEXT,
                    cash_value REAL,
                    enabled INTEGER DEFAULT 1,
                    note TEXT DEFAULT '',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            # 表为空时写入种子规则
            count = conn.execute("SELECT COUNT(*) FROM auto_trade_rules").fetchone()[0]
            if count == 0:
                for r in SEED_RULES:
                    conn.execute(
                        "INSERT INTO auto_trade_rules (fund_code, hedge_symbol, direction, condition, threshold, pos_constraint, pos_value, cash_constraint, cash_value, enabled, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (r["fund_code"], r["hedge_symbol"], r["direction"], r["condition"], r["threshold"], r["pos_constraint"], r["pos_value"], r["cash_constraint"], r["cash_value"], 1 if r["enabled"] else 0, r["note"])
                    )
                conn.commit()
                logger.info(f"[RuleEngine] 已写入 {len(SEED_RULES)} 条种子规则")
        finally:
            conn.close()

    # ── 规则 CRUD ──
    def get_all_rules(self) -> list:
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT * FROM auto_trade_rules ORDER BY fund_code, direction, threshold").fetchall()
            rules = [dict(r) for r in rows]
            # 附加当前评估状态
            for r in rules:
                st = self._evaluate_rule(r)
                r.update(st)
            return rules
        finally:
            conn.close()

    def add_rule(self, rule: dict) -> dict:
        conn = self._get_conn()
        try:
            cur = conn.execute(
                "INSERT INTO auto_trade_rules (fund_code, hedge_symbol, direction, condition, threshold, pos_constraint, pos_value, cash_constraint, cash_value, enabled, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (rule.get("fund_code",""), rule.get("hedge_symbol",""), rule.get("direction","open"), rule.get("condition","gt"), rule.get("threshold",0.5), rule.get("pos_constraint"), rule.get("pos_value"), rule.get("cash_constraint"), rule.get("cash_value"), 1 if rule.get("enabled",True) else 0, rule.get("note",""))
            )
            conn.commit()
            rule_id = cur.lastrowid
            logger.info(f"[RuleEngine] 新增规则 id={rule_id} {rule.get('fund_code')} {rule.get('note')}")
            return {"id": rule_id, "status": "ok"}
        finally:
            conn.close()

    def update_rule(self, rule_id: int, rule: dict) -> bool:
        conn = self._get_conn()
        try:
            fields = []
            params = []
            for key in ["fund_code","hedge_symbol","direction","condition","threshold","pos_constraint","pos_value","cash_constraint","cash_value","enabled","note"]:
                if key in rule:
                    fields.append(f"{key}=?")
                    v = rule[key]
                    if key == "enabled":
                        v = 1 if v else 0
                    params.append(v)
            if not fields:
                return False
            params.append(rule_id)
            conn.execute(f"UPDATE auto_trade_rules SET {','.join(fields)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", params)
            conn.commit()
            logger.info(f"[RuleEngine] 更新规则 id={rule_id}")
            return True
        finally:
            conn.close()

    def delete_rule(self, rule_id: int) -> bool:
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM auto_trade_rules WHERE id=?", (rule_id,))
            conn.commit()
            logger.info(f"[RuleEngine] 删除规则 id={rule_id}")
            return True
        finally:
            conn.close()

    # ── 交易数量配置（fund_code → {lof_qty, etf_qty}）──
    def get_trade_config(self, fund_code: str) -> dict:
        """获取指定基金的交易数量配置，不存在则返回默认值"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT lof_qty, etf_qty FROM fund_trade_config WHERE fund_code=?",
                (fund_code,)
            ).fetchone()
            if row:
                return {"lof_qty": row[0], "etf_qty": row[1]}
            return DEFAULT_TRIGGER_QTY
        finally:
            conn.close()

    def save_trade_config(self, fund_code: str, lof_qty: int, etf_qty: int) -> bool:
        """保存/更新基金的交易数量配置"""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO fund_trade_config (fund_code, lof_qty, etf_qty)
                VALUES (?, ?, ?)
                ON CONFLICT(fund_code) DO UPDATE SET lof_qty=excluded.lof_qty, etf_qty=excluded.etf_qty
            """, (fund_code, lof_qty, etf_qty))
            conn.commit()
            logger.info(f"[RuleEngine] 保存交易配置 {fund_code}: LOF {lof_qty}股, ETF {etf_qty}股")
            return True
        except Exception as e:
            logger.error(f"[RuleEngine] 保存交易配置失败: {e}")
            return False
        finally:
            conn.close()

    def get_all_trade_configs(self) -> dict:
        """获取所有基金的交易数量配置（供前端展示）"""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT fund_code, lof_qty, etf_qty FROM fund_trade_config").fetchall()
            result = {}
            for r in rows:
                result[r[0]] = {"lof_qty": r[1], "etf_qty": r[2]}
            return result
        finally:
            conn.close()

    # ── 查询 hedge（从 unified_fund_list 自动映射） ──
    def _lookup_hedge(self, fund_code: str) -> str:
        conn = self._get_conn()
        try:
            tbl = 'unified_fund_list'
            if self._master_db_path:
                try:
                    conn.execute("ATTACH DATABASE ? AS master", (self._master_db_path,))
                    tbl = 'master.unified_fund_list'
                except Exception:
                    tbl = 'unified_fund_list'
            row = conn.execute(f"SELECT trade_etf FROM {tbl} WHERE fund_code=?", (fund_code,)).fetchone()
            if row and row[0] and row[0] != '-':
                return row[0]
        except Exception:
            pass
        finally:
            conn.close()
        # [AI-2026-07-02] 备用源映射；161125→SPY（用户指定，不是INDA）
        FALLBACK = {"164701": "GLD", "162411": "XOP", "164824": "INDA", "161125": "SPY", "161130": "QQQ"}
        return FALLBACK.get(fund_code, "GLD")

    # ── 启动/停止 ──
    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("[RuleEngine] 规则引擎已启动（每 5 秒扫描一轮）")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)
        logger.info("[RuleEngine] 规则引擎已停止")

    def get_recent_logs(self):
        return list(_log_handler.logs)

    # ── 核心循环 ──
    def _loop(self):
        while self.running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"[RuleEngine] 异常: {e}")
            time.sleep(5)

    def _tick(self):
        """从 DB 加载所有规则，按 fund_code 分组评估"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM auto_trade_rules WHERE enabled=1 ORDER BY fund_code, direction, threshold"
            ).fetchall()
            rules = [dict(r) for r in rows]
        finally:
            conn.close()

        if not rules:
            return

        # 按 fund_code 分组
        groups = defaultdict(list)
        for r in rules:
            groups[r["fund_code"]].append(r)

        # 分别获取每组行情
        for fund_code, group_rules in groups.items():
            self._refresh_market_for(fund_code)
            for rule in group_rules:
                self._evaluate_and_fire(rule)

    # [AI-2026-07-02] 从 get_valuation_meta 的 realtime_quotes 中提取 LOF bid1 和 ETF bid1
    def _refresh_market_for(self, fund_code: str):
        """
        获取某基金实时数据
        
        直接使用 rt_premium 的真实正负值：
        - rt_premium > 0 → 溢价（LOF贵了）
        - rt_premium < 0 → 折价（LOF便宜了，套利机会）
        - 规则中的 threshold 也是真实溢价率（带符号）：
          - 开仓: signal < threshold（如 signal=-0.72 < -0.69 → 开仓）
          - 平仓: signal > threshold（如 signal=-0.15 > -0.21 → 平仓）
        """
        entry = {
            "signal": 0.0,       # 溢价率真实值（可正可负）
            "position": 0.0,      # 持仓市值
            "cash": 500000,       # 可用现金
            "lof_bid1": 0.0,      # LOF 买一价
            "etf_bid1": 0.0,      # ETF 买一价（卖空成交价）
            "hedge_symbol": "",    # 对冲标的代码
        }
        if self.fund_service:
            try:
                meta = self.fund_service.get_valuation_meta(fund_code)
                if meta and isinstance(meta, dict):
                    premium = meta.get("rt_premium", 0)
                    entry["signal"] = float(premium) if premium else 0.0
                    # [AI-2026-07-02] 从 realtime_quotes 提取 LOF bid1
                    quotes = meta.get("realtime_quotes", {})
                    lof_q = quotes.get(fund_code)
                    if lof_q:
                        entry["lof_bid1"] = float(lof_q.get("bid", 0) or 0)
                    # 尝试取 ETF bid1（用 fund_cfg 的 trade_etf）
                    hedge_sym = meta.get("fund_config", {}).get("trade_etf", "")
                    if hedge_sym and hedge_sym in quotes:
                        hq = quotes[hedge_sym]
                        if hq:
                            entry["etf_bid1"] = float(hq.get("bid", 0) or 0)
                            entry["hedge_symbol"] = hedge_sym
            except Exception as e:
                logger.debug(f"行情获取失败 {fund_code}: {e}")
        self._market_cache[fund_code] = entry

    def _get_market(self, fund_code: str) -> dict:
        return self._market_cache.get(fund_code, {"signal": 0.0, "position": 0.0, "cash": 500000})

    # ── 单条评估 ──
    def _evaluate_rule(self, rule: dict) -> dict:
        fund_code = rule["fund_code"]
        market = self._get_market(fund_code)
        signal = market["signal"]
        pos = market["position"]
        cash = market["cash"]
        threshold = rule["threshold"]
        direction = rule["direction"]
        condition = rule["condition"]

        reason_parts = []

        # 折价条件
        if condition == "gt":
            cond_ok = signal > threshold
            op = ">"
        else:
            cond_ok = signal < threshold
            op = "<"
        reason_parts.append(f"signal={signal:.3f} {'✓' if cond_ok else '不满足'} {op} {threshold:.3f}")

        if not cond_ok:
            return {"current_signal": round(signal,3), "current_position": pos, "current_cash": cash, "condition_met": False, "reason": " ".join(reason_parts), "last_triggered_at": self._last_fired.get(rule.get("id"))}

        # [AI-2026-07-02] 仓位/现金约束暂时跳过（用户测试阶段，每天只做1-2单，仓位和现金无风险）
        # 字段保留在DB和UI中，但评估逻辑不以此否决触发
        # 仓位约束
        pc = rule.get("pos_constraint")
        pv = rule.get("pos_value")
        if pc and pv is not None:
            if pc == "lte" and pos > pv:
                reason_parts.append(f"仓位={pos:.0f} > {pv:.0f} (跳过)")
            elif pc == "gte" and pos < pv:
                reason_parts.append(f"仓位={pos:.0f} < {pv:.0f} (跳过)")
            else:
                reason_parts.append(f"仓位={pos:.0f} ✓")
        # 现金约束
        cc = rule.get("cash_constraint")
        cv = rule.get("cash_value")
        if cc and cv is not None:
            if cc == "gte" and cash < cv:
                reason_parts.append(f"现金={cash:.0f} < {cv:.0f} (跳过)")
            elif cc == "lt" and cash >= cv:
                reason_parts.append(f"现金={cash:.0f} >= {cv:.0f} (跳过)")
            else:
                reason_parts.append(f"现金={cash:.0f} ✓")

        return {"current_signal": round(signal,3), "current_position": pos, "current_cash": cash, "condition_met": True, "reason": " ".join(reason_parts), "last_triggered_at": self._last_fired.get(rule.get("id"))}

    def _evaluate_and_fire(self, rule: dict):
        rule_id = rule.get("id")
        now = time.time()
        last = self._last_fired.get(rule_id, 0)
        if now - last < self.COOLDOWN_SECONDS:
            return

        status = self._evaluate_rule(rule)
        if not status["condition_met"]:
            return

        self._last_fired[rule_id] = now
        logger.info(f">> 触发 [{rule_id}] {rule.get('note','')}")

        if rule["direction"] == "open":
            self._execute_open(rule)
        else:
            self._execute_close(rule)

    # [AI-2026-07-02] 重写：固定数量 + 真实买一价 + 券商路由（162411→TDX, 其他→QMT）
    def _execute_open(self, rule: dict):
        fund_code = rule["fund_code"]
        symbol = rule.get("hedge_symbol") or self._lookup_hedge(fund_code)
        market = self._get_market(fund_code)
        lof_price = market.get("lof_bid1", 0)
        etf_bid1 = market.get("etf_bid1", 0)

        if lof_price <= 0 or etf_bid1 <= 0:
            logger.warning(f"[RuleEngine] {fund_code} 价格数据不完整（lof_bid1={lof_price}, etf_bid1={etf_bid1}），跳过开仓")
            return

        # [AI-2026-08-23] 从数据库获取交易数量配置（不存在则用默认值）
        qty = self.get_trade_config(fund_code)
        lof_qty = qty["lof_qty"]
        etf_qty = qty["etf_qty"]

        logger.info(f"[RuleEngine] 开仓 {fund_code} x{lof_qty} @ {lof_price:.3f}, 对冲 {symbol} x{etf_qty} @ {etf_bid1:.3f}")
        results = []

        # 1. IB 卖空 ETF（吃买一价即时成交）
        ib_ok = False
        if self.lazy_trader and hasattr(self.lazy_trader, 'ib_reader') and self.lazy_trader.ib_reader:
            try:
                if self.lazy_trader.ib_reader.isConnected():
                    success, msg = self.lazy_trader.ib_reader.place_us_order(
                        symbol=symbol, action="SELL",
                        quantity=etf_qty, price=etf_bid1,
                    )
                    ib_ok = success
                    results.append({"driver": "IB", "action": "SELL", "symbol": f"{symbol}x{etf_qty}", "success": success, "msg": msg})
                    logger.info(f"[RuleEngine] IB short {symbol}x{etf_qty}: {msg}")
                else:
                    results.append({"driver": "IB", "action": "SELL", "symbol": symbol, "success": False, "msg": "IB not connected"})
            except Exception as e:
                logger.error(f"[RuleEngine] IB short 异常: {e}")
                results.append({"driver": "IB", "action": "SELL", "symbol": symbol, "success": False, "msg": str(e)})
        else:
            results.append({"driver": "IB", "action": "SELL", "symbol": symbol, "success": False, "msg": "IB reader not available"})

        # 2. LOF 买入：162411→TDX（华宝通达信），其他→QMT
        if fund_code in TDX_FUNDS:
            if self.trading_service:
                try:
                    r = self.trading_service.execute_order(
                        action="BUY", code=fund_code,
                        volume=lof_qty, price=lof_price,
                        broker='tdx'
                    )
                    tdx_ok = r.get("status") == "ok"
                    results.append({"driver": "TDX", "action": "BUY", "symbol": f"{fund_code}x{lof_qty}", "success": tdx_ok, "msg": r.get("message", "")})
                    logger.info(f"[RuleEngine] TDX buy {fund_code}x{lof_qty}: {r}")
                except Exception as e:
                    logger.error(f"[RuleEngine] TDX buy 异常: {e}")
                    results.append({"driver": "TDX", "action": "BUY", "symbol": fund_code, "success": False, "msg": str(e)})
            else:
                logger.warning(f"[RuleEngine] trading_service 未注入，无法TDX下单 {fund_code}")
                results.append({"driver": "TDX", "action": "BUY", "symbol": fund_code, "success": False, "msg": "trading_service not injected"})
        else:
            # QMT 买入（银河/国金自动切换）
            if self.lazy_trader:
                try:
                    qmt_results = self.lazy_trader._qmt_buy(fund_code, lof_price, lof_qty)
                    results.extend(qmt_results)
                except Exception as e:
                    logger.error(f"[RuleEngine] QMT buy 异常: {e}")
                    results.append({"driver": "QMT", "action": "BUY", "symbol": fund_code, "success": False, "msg": str(e)})
            else:
                results.append({"driver": "QMT", "action": "BUY", "symbol": fund_code, "success": False, "msg": "lazy_trader not injected"})

        any_ok = any(r.get("success") for r in results)
        logger.info(f"[RuleEngine] 开仓 {'✅成功' if any_ok else '❌失败'} {results}")

    # [AI-2026-07-02] 平仓只发日志通知，不下单（用户手动操作）
    def _execute_close(self, rule: dict):
        fund_code = rule["fund_code"]
        symbol = rule.get("hedge_symbol") or self._lookup_hedge(fund_code)
        note = rule.get("note", "")
        logger.warning(
            f"[RuleEngine] ⚠️ 平仓信号触发，请手动操作！ "
            f"{fund_code} 对冲{symbol} | {note}"
        )


# ── 全局单例 ──
rule_engine = RuleEngine()
