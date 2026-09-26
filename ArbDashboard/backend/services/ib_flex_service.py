# -*- coding: utf-8 -*-
"""IB Flex Web Service 拉取 + 解析 + 落库 + 对账（盘后对账 IB 路官方数据源）。

设计边界（东哥 2026-09-25 拍板）：
  - 纯 HTTP 直连 Flex Web Service，**不依赖 IB Gateway/TWS 是否在线**，与 ib_reader.py 解耦。
  - 零第三方依赖：仅用标准库（urllib / xml.etree / sqlite3），本机无 pandas 也能跑。
  - 落库到本地 arb_tran.db（与 arbitrage_pairs 同库，database/ 下，物理隔离不进 git）。
  - **不直接回填 arbitrage_pairs**（V7 为唯一真源）；只作为"IB 路官方结算口径"独立真相源，
    提供 reconcile_flex_vs_book() 自动差异核对（Flex 官方成交/FX/费用 vs V7 记的 IB 对冲腿）。
  - 安全：Token/QueryID 只从 .env（项目根，仓库外）或环境变量读，绝不硬编码、绝不打印。

Flex Web Service 两步走（v=3）：
  SendRequest -> 拿 ReferenceCode
  GetStatement -> 用 ReferenceCode 拉 XML 报表（属性型标签）
限频 1 req/s、每 token 每分钟 ≤10；错误码 1012=token过期 1018=限频 1019=报表生成中(轮询)。
"""
import os
import sys
import re
import time
import json
import sqlite3
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

FLEX_SEND_URL = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/SendRequest"
FLEX_GET_URL = "https://gdcdyn.interactivebrokers.com/AccountManagement/FlexWebService/GetStatement"
FLEX_VERSION = "3"

# 错误码 -> 含义
FLEX_ERRORS = {
    "1001": "Invalid token",
    "1002": "Invalid query ID",
    "1003": "Token does not match query",
    "1004": "Too many requests",
    "1005": "Service unavailable",
    "1006": "Invalid date range",
    "1007": "Statement too large",
    "1012": "Token expired",
    "1018": "Rate limit exceeded (per minute)",
    "1019": "Statement still being generated (retry)",
    "1020": "Invalid request or unable to validate request (token/queryId 不匹配或参数非法)",
}


class FlexError(Exception):
    """Flex Web Service 返回的业务错误。"""

    def __init__(self, code, message, retryable=False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"Flex error {code}: {message}")


# ================================================================
# 路径解析（复用 db_manager 的"向上找 database/ 目录"逻辑，避免导入 arbcore 重依赖）
# ================================================================
def _resolve_project_root():
    """向上找含 database/ 的祖先目录（且该目录不含 db_manager.py，即非代码目录），返回项目根。"""
    here = os.path.abspath(os.path.dirname(__file__))
    cur = here
    while True:
        candidate = os.path.join(cur, "database")
        if os.path.isdir(candidate) and not os.path.exists(os.path.join(candidate, "db_manager.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 兜底：退回本文件三层上的 database
    base = os.path.abspath(os.path.join(here, "..", "..", ".."))
    return base


def _resolve_db_path(explicit=None):
    if explicit:
        return explicit
    env = os.environ.get("ARB_TRAN_DB")
    if env:
        return env
    root = _resolve_project_root()
    return os.path.join(root, "database", "arb_tran.db")


def _load_env(extra_path=None):
    """从 项目根/.env 读 KEY=VALUE（不覆盖已存在的 os.environ）。返回 dict（含从 os.environ 取的）。

    安全：只读，不打印值；调用方切勿 log 出 token。
    """
    env = {}
    # 1) 环境变量优先（如东哥在 shell 里 set 过）
    for k in ("IB_FLEX_TOKEN", "IB_FLEX_QUERY_ID", "IB_FLEX_ACCOUNT"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    # 2) 项目根/.env（仓库外，天然不进 git）
    candidates = []
    if extra_path:
        candidates.append(extra_path)
    root = _resolve_project_root()
    candidates.append(os.path.join(root, ".env"))
    for p in candidates:
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in env:  # 环境变量优先
                            env[k] = v
            except Exception as e:
                logger.warning(f"[IBFlex] 读取 .env 失败 {p}: {e}")
            break
    return env


def _mask(token):
    if not token:
        return "<empty>"
    return token[:4] + "****" + token[-2:] if len(token) > 6 else "****"


# ================================================================
# HTTP 客户端（限频 + 错误码解析 + 1019 轮询）
# ================================================================
class _RateLimiter:
    """1 req/s + 每 token 每分钟 ≤10。手动运行足够，非高并发。"""

    def __init__(self, per_sec=1.1, per_min=10):
        self.per_sec = per_sec
        self.per_min = per_min
        self._last = 0.0
        self._minute_ts = 0.0
        self._minute_count = 0

    def wait(self):
        now = time.time()
        # 1 req/s
        gap = self.per_sec - (now - self._last)
        if gap > 0:
            time.sleep(gap)
        # 每分钟 ≤10
        if now - self._minute_ts >= 60:
            self._minute_ts = now
            self._minute_count = 0
        if self._minute_count >= self.per_min:
            sleep_to = 60 - (now - self._minute_ts)
            if sleep_to > 0:
                time.sleep(sleep_to)
            self._minute_ts = time.time()
            self._minute_count = 0
        self._last = time.time()
        self._minute_count += 1


class IBFlexClient:
    def __init__(self, token, query_id, account=None, timeout=30):
        self.token = token
        self.query_id = query_id
        self.account = account
        self.timeout = timeout
        self._rl = _RateLimiter()

    def _http_get(self, url):
        self._rl.wait()
        # IB 硬性要求：编程访问必须带 User-Agent，且格式为 技术/版本（如 Python/3.13），
        # 不能用浏览器 UA，否则 SendRequest 直接 1020 Invalid request。
        req = urllib.request.Request(url, headers={"User-Agent": f"Python/{sys.version_info.major}.{sys.version_info.minor}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise FlexError("HTTP", f"HTTP {e.code}: {body[:300]}")

    @staticmethod
    def _parse_error(body):
        """识别 IB Flex 两种错误结构，返回 (code, msg) 或 None。

        结构A（GetStatement）：<FlexQueryResponse><Response errorCode="1019" errorMessage="..."/>
        结构B（SendRequest）： <FlexStatementResponse><Status>Fail</Status>
                                <ErrorCode>1020</ErrorCode><ErrorMessage>Invalid request...</ErrorMessage>
        纯文本 ref（SendRequest 成功）/ 合法报表 XML（GetStatement 成功）返回 None。
        """
        if "<" not in body:
            return None
        # 结构B：SendRequest 错误（元素式 ErrorCode/ErrorMessage）
        m = re.search(r"<ErrorCode>\s*(\d+)\s*</ErrorCode>", body)
        if m:
            code = m.group(1)
            mm = re.search(r"<ErrorMessage>\s*(.*?)\s*</ErrorMessage>", body, re.S)
            return code, (mm.group(1) if mm else "")
        # 结构A + 裸 <Response .../>（属性式 errorCode）
        try:
            root = ET.fromstring(body)
            for el in root.iter():
                if el.tag.endswith("Response") and el.get("errorCode"):
                    return el.get("errorCode"), el.get("errorMessage") or ""
        except ET.ParseError:
            m2 = re.search(r'errorCode=["\']?(\d+)', body)
            if m2:
                code = m2.group(1)
                mm = re.search(r'errorMessage=["\']?([^"\']+)', body)
                return code, (mm.group(1) if mm else "")
        return None

    def send_request(self, days=None, since=None, to=None):
        """触发报表生成，返回 ReferenceCode。days 与 since/to 二选一。"""
        q = urllib.parse.urlencode({
            "t": self.token, "q": self.query_id, "v": FLEX_VERSION
        })
        if days is not None:
            q += f"&p={int(days)}"
        elif since and to:
            q += f"&fd={since}&td={to}"
        elif since:
            q += f"&fd={since}"
        url = f"{FLEX_SEND_URL}?{q}"
        logger.info(f"[IBFlex] SendRequest (token={_mask(self.token)}, q={self.query_id[:4]}****)")
        body = self._http_get(url)
        err = self._parse_error(body)
        if err:
            code, msg = err
            # SendRequest 偶发 1019（大报表生成中）也应轮询，但 SendRequest 一般即时返回 ref
            raise FlexError(code, msg, retryable=(code == "1019"))
        # SendRequest v3 成功返回 **XML**（不是纯文本！）：
        #   <FlexStatementResponse timestamp='...'><Status>Success</Status>
        #     <ReferenceCode>9741919645</ReferenceCode>
        #     <Url>.../FlexWebService/GetStatement</Url></FlexStatementResponse>
        # 兼容旧版/纯文本 ref。
        b = body.strip()
        ref = None
        if b.startswith("<"):
            try:
                root = ET.fromstring(b)
                for el in root.iter():
                    if el.tag.split("}")[-1] == "ReferenceCode" and el.text:
                        ref = el.text.strip()
                        break
            except ET.ParseError:
                ref = None
        else:
            ref = b or None
        if not ref:
            raise FlexError("NO_REF", "SendRequest 响应无 ReferenceCode，真实响应：\n" + b[:300])
        logger.info("[IBFlex] SendRequest 成功 ref=%s", ref)
        return ref

    def get_statement(self, ref_code, max_poll=12, poll_wait=3):
        """拉报表 XML。1019 轮询等待；其它错误直接抛。"""
        q = urllib.parse.urlencode({"t": self.token, "q": ref_code, "v": FLEX_VERSION})
        url = f"{FLEX_GET_URL}?{q}"
        last_err = None
        for attempt in range(max_poll):
            logger.info(f"[IBFlex] GetStatement 第 {attempt+1}/{max_poll} 次 (ref={ref_code[:8]}...)")
            body = self._http_get(url)
            err = self._parse_error(body)
            if err:
                code, msg = err
                last_err = FlexError(code, msg, retryable=(code == "1019"))
                if code == "1019":
                    time.sleep(poll_wait)
                    continue
                raise last_err
            # 成功：合法 XML
            return body
        raise last_err or FlexError("TIMEOUT", f"GetStatement 轮询 {max_poll} 次仍未就绪")

    def fetch(self, days=None, since=None, to=None, max_poll=12):
        """一步：SendRequest -> GetStatement（1019 轮询）。返回 (ref_code, xml_string)。"""
        ref = self.send_request(days=days, since=since, to=to)
        xml = self.get_statement(ref, max_poll=max_poll)
        return ref, xml


# ================================================================
# XML 解析（属性型标签，容错命名空间）
# ================================================================
def _local(tag):
    """去掉 XML 命名空间前缀，取本地名。IB XML 可能带默认 ns。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _trade_date(date_time):
    """IB dateTime 形如 '20260921;202600' 或 '2026-09-21, 20:26:00' -> YYYY-MM-DD。失败返回 None。"""
    if not date_time:
        return None
    s = re.sub(r"[;,]", " ", str(date_time)).split()[0] if date_time.strip() else ""
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def parse_flex_xml(xml_string):
    """解析 Flex 报表 XML -> {trades, fx, cash, errors}。

    容错：用 iter 找本地名为 Trade / CashTransaction / FxTransaction 的元素，收集全部属性。
    未知字段存 raw(JSON) 备查，不丢数据。
    """
    out = {"trades": [], "fx": [], "cash": [], "errors": []}
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError as e:
        out["errors"].append(f"XML 解析失败: {e}")
        return out

    for el in root.iter():
        name = _local(el.tag)
        attrs = dict(el.attrib)
        if name == "Trade":
            out["trades"].append(_norm_trade(attrs))
        elif name == "CashTransaction":
            out["cash"].append(_norm_cash(attrs))
        elif name == "FxTransaction":
            out["fx"].append(_norm_fx(attrs))
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _norm_trade(a):
    """Trade 属性 -> 规整行。buySell 保留原始（BUY/SELL/SELLSHORT/BUYTOCOVER）。

    实测 IB Flex（2026-09 dongge 账户）结论：
      - ibCommission 为「带符号费用」：负=付出成本（绝大多数），偶有正=返费。
        统一取 abs 作成本 magnitude 存 commission；ib_commission 列保留原始带符号值备查。
      - 订单号字段名为 ibOrderID（非 orderID）。
      - 官方交易日用 tradeDate 属性（与 dateTime 可能因跨时区执行差 1 天），
        date_time 仍存完整 dateTime 时间戳。
      - openCloseIndicator (O=建仓/做空开, C=平仓/买平) 是比 buySell 更干净的对冲腿分类信号。
    """
    dt = a.get("dateTime") or a.get("tradeDate") or a.get("date")
    # 优先用官方 tradeDate 作为交易日
    trade_date = _trade_date(a.get("tradeDate") or dt)
    ib_comm = _f(a.get("ibCommission"))
    comm = abs(ib_comm) if ib_comm is not None else _f(a.get("commission"))
    return {
        "exec_id": a.get("transactionID") or a.get("execId") or a.get("tradeID"),
        "account": a.get("accountId") or a.get("account"),
        "symbol": (a.get("symbol") or "").upper() or None,
        "asset_category": a.get("assetCategory"),
        "buy_sell": a.get("buySell") or a.get("side"),
        "open_close": a.get("openCloseIndicator"),
        "quantity": _f(a.get("quantity") or a.get("shares")),
        "trade_price": _f(a.get("tradePrice") or a.get("price")),
        "commission": comm,
        "ib_commission": ib_comm,
        "currency": a.get("currency"),
        "date_time": dt,
        "trade_date": trade_date,
        "conid": a.get("conid"),
        "description": a.get("description"),
        "order_id": a.get("ibOrderID") or a.get("orderID") or a.get("orderId"),
        "multiplier": a.get("multiplier"),
        "raw": json.dumps(a, ensure_ascii=False),
    }


def _norm_cash(a):
    dt = a.get("dateTime") or a.get("date")
    return {
        "tx_id": a.get("transactionID") or a.get("txId"),
        "account": a.get("accountId") or a.get("account"),
        "type": a.get("type"),
        "amount": _f(a.get("amount")),
        "currency": a.get("currency"),
        "date_time": dt,
        "trade_date": _trade_date(dt),
        "description": a.get("description"),
        "raw": json.dumps(a, ensure_ascii=False),
    }


def _norm_fx(a):
    dt = a.get("dateTime") or a.get("date")
    return {
        "tx_id": a.get("transactionID") or a.get("txId"),
        "account": a.get("accountId") or a.get("account"),
        "currency_pair": a.get("currencyPair") or a.get("currency"),
        "fx_rate": _f(a.get("fxRate") or a.get("rate")),
        "from_amount": _f(a.get("fromAmount")),
        "to_amount": _f(a.get("toAmount")),
        "proceeds": _f(a.get("proceeds")),
        "date_time": dt,
        "trade_date": _trade_date(dt),
        "raw": json.dumps(a, ensure_ascii=False),
    }


# ================================================================
# 落库（arb_tran.db，幂等 upsert）
# ================================================================
class IBFlexStore:
    def __init__(self, db_path=None):
        self.db_path = _resolve_db_path(db_path)

    def _conn(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def ensure_tables(self):
        conn = self._conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ib_flex_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_code TEXT,
                    req_mode TEXT,
                    from_date TEXT,
                    to_date TEXT,
                    req_at TEXT,
                    status TEXT,
                    err_code TEXT,
                    err_msg TEXT,
                    n_trades INTEGER,
                    n_fx INTEGER,
                    n_cash INTEGER,
                    raw_xml TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS ib_flex_trades (
                    exec_id TEXT PRIMARY KEY,
                    run_id INTEGER,
                    account TEXT,
                    symbol TEXT,
                    asset_category TEXT,
                    buy_sell TEXT,
                    open_close_indicator TEXT,
                    quantity REAL,
                    trade_price REAL,
                    commission REAL,
                    ib_commission REAL,
                    currency TEXT,
                    date_time TEXT,
                    trade_date TEXT,
                    conid TEXT,
                    description TEXT,
                    order_id TEXT,
                    multiplier TEXT,
                    raw TEXT
                );
                CREATE TABLE IF NOT EXISTS ib_flex_fx (
                    tx_id TEXT PRIMARY KEY,
                    run_id INTEGER,
                    account TEXT,
                    currency_pair TEXT,
                    fx_rate REAL,
                    from_amount REAL,
                    to_amount REAL,
                    proceeds REAL,
                    date_time TEXT,
                    trade_date TEXT,
                    raw TEXT
                );
                CREATE TABLE IF NOT EXISTS ib_flex_cash (
                    tx_id TEXT PRIMARY KEY,
                    run_id INTEGER,
                    account TEXT,
                    type TEXT,
                    amount REAL,
                    currency TEXT,
                    date_time TEXT,
                    trade_date TEXT,
                    description TEXT,
                    raw TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_flex_trades_symbol ON ib_flex_trades(symbol);
                CREATE INDEX IF NOT EXISTS idx_flex_trades_date ON ib_flex_trades(trade_date);
                CREATE INDEX IF NOT EXISTS idx_flex_fx_date ON ib_flex_fx(trade_date);
                CREATE INDEX IF NOT EXISTS idx_flex_cash_date ON ib_flex_cash(trade_date);
            """)
            conn.commit()
            # 增量加列（兼容已存在的旧库：CREATE TABLE IF NOT EXISTS 不会改已有表）
            try:
                conn.execute("ALTER TABLE ib_flex_trades ADD COLUMN open_close_indicator TEXT")
            except sqlite3.OperationalError:
                pass
        finally:
            conn.close()

    def save_run(self, ref_code, req_mode, from_date, to_date, status,
                 n_trades=0, n_fx=0, n_cash=0, err_code=None, err_msg=None,
                 raw_xml=None, run_id=None):
        conn = self._conn()
        try:
            if run_id:
                conn.execute(
                    """UPDATE ib_flex_runs SET ref_code=?,status=?,err_code=?,err_msg=?,
                       n_trades=?,n_fx=?,n_cash=?,raw_xml=?,created_at=? WHERE id=?""",
                    (ref_code, status, err_code, err_msg, n_trades, n_fx, n_cash,
                     raw_xml, datetime.now(timezone.utc).isoformat(), run_id))
                conn.commit()
                return run_id
            cur = conn.execute(
                """INSERT INTO ib_flex_runs
                   (ref_code,req_mode,from_date,to_date,req_at,status,err_code,err_msg,
                    n_trades,n_fx,n_cash,raw_xml,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ref_code, req_mode, from_date, to_date, datetime.now(timezone.utc).isoformat(),
                 status, err_code, err_msg, n_trades, n_fx, n_cash, raw_xml,
                 datetime.now(timezone.utc).isoformat()))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def upsert_trades(self, rows, run_id):
        conn = self._conn()
        try:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO ib_flex_trades
                       (exec_id,run_id,account,symbol,asset_category,buy_sell,open_close_indicator,quantity,trade_price,
                        commission,ib_commission,currency,date_time,trade_date,conid,description,order_id,multiplier,raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("exec_id"), run_id, r.get("account"), r.get("symbol"),
                     r.get("asset_category"), r.get("buy_sell"), r.get("open_close"), r.get("quantity"),
                     r.get("trade_price"), r.get("commission"), r.get("ib_commission"),
                     r.get("currency"), r.get("date_time"), r.get("trade_date"), r.get("conid"),
                     r.get("description"), r.get("order_id"), r.get("multiplier"), r.get("raw")))
            conn.commit()
        finally:
            conn.close()

    def upsert_fx(self, rows, run_id):
        conn = self._conn()
        try:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO ib_flex_fx
                       (tx_id,run_id,account,currency_pair,fx_rate,from_amount,to_amount,proceeds,date_time,trade_date,raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("tx_id"), run_id, r.get("account"), r.get("currency_pair"),
                     r.get("fx_rate"), r.get("from_amount"), r.get("to_amount"), r.get("proceeds"),
                     r.get("date_time"), r.get("trade_date"), r.get("raw")))
            conn.commit()
        finally:
            conn.close()

    def upsert_cash(self, rows, run_id):
        conn = self._conn()
        try:
            for r in rows:
                conn.execute(
                    """INSERT OR REPLACE INTO ib_flex_cash
                       (tx_id,run_id,account,type,amount,currency,date_time,trade_date,description,raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (r.get("tx_id"), run_id, r.get("account"), r.get("type"), r.get("amount"),
                     r.get("currency"), r.get("date_time"), r.get("trade_date"), r.get("description"),
                     r.get("raw")))
            conn.commit()
        finally:
            conn.close()

    # ---- 读取（对账用） ----
    def get_trades(self):
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT exec_id,account,symbol,buy_sell,open_close_indicator,quantity,trade_price,commission,currency,trade_date FROM ib_flex_trades"
            )]
        finally:
            conn.close()

    def get_fx(self):
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT tx_id,account,currency_pair,fx_rate,from_amount,to_amount,proceeds,trade_date FROM ib_flex_fx"
            )]
        finally:
            conn.close()

    def get_cash(self):
        conn = self._conn()
        try:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT tx_id,account,type,amount,currency,trade_date,description FROM ib_flex_cash"
            )]
        finally:
            conn.close()


# ================================================================
# 自动对账：Flex 官方 vs V7 账本（arbitrage_pairs 的 IB 对冲腿）
# ================================================================
def _date_close(a, b, tol_days=1):
    """两个 YYYY-MM-DD 是否相差 ≤ tol_days（None 不参与匹配）。"""
    if not a or not b:
        return True  # 缺日期不卡死
    try:
        da = datetime.strptime(a, "%Y-%m-%d").date()
        db = datetime.strptime(b, "%Y-%m-%d").date()
        return abs((da - db).days) <= tol_days
    except Exception:
        return True


def reconcile_flex_vs_book(db_path=None, tol_days=1, price_tol=0.01):
    """比对 Flex 官方成交/FX/费用 与 arbitrage_pairs 里记的 IB 对冲腿。

    匹配键：(symbol, abs(quantity), round(trade_price,2)) 且日期相差 ≤ tol_days。
    返回结构化报告 dict（也打印可读摘要）。
    """
    store = IBFlexStore(db_path)
    flex_trades = store.get_trades()
    flex_fx = store.get_fx()
    flex_cash = store.get_cash()

    conn = store._conn()
    try:
        conn.row_factory = sqlite3.Row
        pairs = [dict(r) for r in conn.execute(
            "SELECT serial_no,fund_code,hedge_symbol,short_date,short_price,short_volume,"
            "cover_date,cover_price,cover_volume,us_commission,status FROM arbitrage_pairs "
            "WHERE hedge_symbol IS NOT NULL AND hedge_symbol!=''"
        )]
    finally:
        conn.close()

    # 账本 IB 腿 -> (symbol, date, qty, price, side)
    book_legs = []  # {serial, symbol, date, qty, price, side}
    for p in pairs:
        sym = (p.get("hedge_symbol") or "").upper()
        if not sym:
            continue
        sv = p.get("short_volume")
        sp = p.get("short_price")
        if sv and sp:  # 做空腿（V7 记负）
            book_legs.append({"serial": p.get("serial_no"), "symbol": sym,
                              "date": p.get("short_date"), "qty": abs(float(sv)),
                              "price": round(float(sp), 2), "side": "SHORT"})
        cv = p.get("cover_volume")
        cp = p.get("cover_price")
        if cv and cp:  # 买平腿（V7 记正）
            book_legs.append({"serial": p.get("serial_no"), "symbol": sym,
                              "date": p.get("cover_date"), "qty": abs(float(cv)),
                              "price": round(float(cp), 2), "side": "COVER"})

    # Flex 成交 -> 匹配账本腿
    flex_matched = []
    flex_unmatched = []
    for t in flex_trades:
        sym = (t.get("symbol") or "").upper()
        qty = abs(t.get("quantity") or 0)
        price = round(t.get("trade_price") or 0, 2)
        hit = None
        for bl in book_legs:
            if (bl["symbol"] == sym and abs(bl["qty"] - qty) < 1e-6
                    and abs(bl["price"] - price) <= price_tol
                    and _date_close(bl["date"], t.get("trade_date"), tol_days)):
                hit = bl
                break
        if hit:
            flex_matched.append({"flex": t, "book_serial": hit["serial"], "book_side": hit["side"]})
        else:
            flex_unmatched.append(t)

    # 账本腿 -> 反向找未被匹配者
    matched_book_serials = {m["book_serial"] for m in flex_matched}
    book_unmatched = [bl for bl in book_legs if bl["serial"] not in matched_book_serials]

    # 手续费比对：Flex 对冲标的成交 commission 合计 vs 账本 us_commission 合计
    # 注：V7 us_commission 与 IB ibCommission 同为「带符号费用」（负=成本），比对取绝对值。
    flex_comm = sum((t.get("commission") or 0) for t in flex_trades
                    if (t.get("symbol") or "").upper() in {bl["symbol"] for bl in book_legs})
    book_comm = sum(abs(p.get("us_commission") or 0) for p in pairs)

    # FX 汇总（GLD 对冲 USD 换汇）
    fx_summary = {}
    for f in flex_fx:
        cp = f.get("currency_pair") or "?"
        d = fx_summary.setdefault(cp, {"count": 0, "from_sum": 0.0, "to_sum": 0.0})
        d["count"] += 1
        d["from_sum"] += abs(f.get("from_amount") or 0)
        d["to_sum"] += abs(f.get("to_amount") or 0)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "flex_trades_total": len(flex_trades),
        "flex_matched": len(flex_matched),
        "flex_unmatched": len(flex_unmatched),
        "book_legs_total": len(book_legs),
        "book_unmatched": len(book_unmatched),
        "commission": {
            "flex_hedge_total": round(flex_comm, 2),
            "book_us_commission_total": round(book_comm, 2),
            "diff": round(flex_comm - book_comm, 2),
        },
        "fx_summary": fx_summary,
        "flex_unmatched_detail": flex_unmatched,
        "book_unmatched_detail": book_unmatched,
    }
    _print_reconcile(report)
    return report


def _print_reconcile(r):
    print("=" * 60)
    print("IB Flex 官方 vs V7 账本 对账报告")
    print(f"  Flex 成交总数: {r['flex_trades_total']}  | 匹配: {r['flex_matched']}  | 未匹配: {r['flex_unmatched']}")
    print(f"  账本 IB 腿:    {r['book_legs_total']}  | 未匹配: {r['book_unmatched']}")
    c = r["commission"]
    print(f"  手续费: Flex对冲侧={c['flex_hedge_total']} 账本us_commission={c['book_us_commission_total']} 差={c['diff']}")
    print(f"  FX 换汇汇总: {r['fx_summary']}")
    if r["flex_unmatched_detail"]:
        print(f"\n  ⚠️ Flex有但账本无 ({len(r['flex_unmatched_detail'])} 笔) — 可能 V7 漏记 IB 对冲腿:")
        for t in r["flex_unmatched_detail"][:20]:
            print(f"    {t.get('trade_date')} {t.get('symbol')} {t.get('buy_sell')} "
                  f"qty={t.get('quantity')} @ {t.get('trade_price')} comm={t.get('commission')} {t.get('currency')}")
    if r["book_unmatched_detail"]:
        print(f"\n  ⚠️ 账本有但 Flex无 ({len(r['book_unmatched_detail'])} 腿) — 可能未结算/日期偏差/标的不符:")
        for bl in r["book_unmatched_detail"][:20]:
            print(f"    serial={bl['serial']} {bl['symbol']} {bl['side']} "
                  f"qty={bl['qty']} @ {bl['price']} date={bl['date']}")
    print("=" * 60)


# ================================================================
# 端到端：拉取 -> 解析 -> 落库 -> 对账
# ================================================================
def run_pull(days=None, since=None, to=None, dry_run=False, reconcile=True,
             env_path=None, db_path=None, max_poll=12, csv_path=None):
    """拉取并落库。dry_run=True 时只解析打印不写库。返回 report dict 或 None。"""
    env = _load_env(env_path)
    token = env.get("IB_FLEX_TOKEN")
    query_id = env.get("IB_FLEX_QUERY_ID")
    account = env.get("IB_FLEX_ACCOUNT")
    if not token or not query_id:
        raise FlexError("CONFIG", "缺少 IB_FLEX_TOKEN / IB_FLEX_QUERY_ID（检查 .env 或环境变量）")

    client = IBFlexClient(token, query_id, account=account)
    req_mode = f"days={days}" if days else f"since={since} to={to}"
    ref, xml = client.fetch(days=days, since=since, to=to, max_poll=max_poll)
    parsed = parse_flex_xml(xml)
    if parsed["errors"]:
        print("⚠️ 解析告警:", parsed["errors"])
    if csv_path:
        export_trades_csv(parsed["trades"], csv_path)

    print(f"✔ 拉取成功 ref={ref[:8]}...  trades={len(parsed['trades'])} "
          f"fx={len(parsed['fx'])} cash={len(parsed['cash'])}")

    if dry_run:
        print("[dry-run] 未写库。样本 Trades:")
        for t in parsed["trades"][:5]:
            print("   ", {k: t[k] for k in ("exec_id", "symbol", "buy_sell", "quantity", "trade_price", "commission", "trade_date")})
        if csv_path:
            export_trades_csv(parsed["trades"], csv_path)
        return {"dry_run": True, "parsed": {k: len(v) for k, v in parsed.items() if isinstance(v, list)}}

    store = IBFlexStore(db_path)
    store.ensure_tables()
    run_id = store.save_run(ref, req_mode, since or "", to or "", "ok",
                            n_trades=len(parsed["trades"]), n_fx=len(parsed["fx"]),
                            n_cash=len(parsed["cash"]), raw_xml=xml)
    store.upsert_trades(parsed["trades"], run_id)
    store.upsert_fx(parsed["fx"], run_id)
    store.upsert_cash(parsed["cash"], run_id)
    print(f"✔ 已落库 run_id={run_id}")

    if reconcile:
        return reconcile_flex_vs_book(db_path=store.db_path)
    return None


def export_trades_csv(trades, csv_path):
    """逐笔原始版（不聚合）：每行一笔 IB 成交，qty 带符号（开空为负）。

    纯导出，不写库、不碰 arbitrage_pairs / V7。东哥核对后手动誊抄进 V7。
    列：trade_date / symbol / buy_sell / qty(带符号) / trade_price /
        ib_commission(IB 原始手续费，带符号，负=成本) / currency
    """
    import csv

    def _fmt_qty(q):
        if q is None:
            return q
        return int(q) if float(q).is_integer() else q

    rows = []
    for t in trades:
        rows.append({
            "trade_date": t.get("trade_date"),
            "symbol": t.get("symbol"),
            "buy_sell": t.get("buy_sell"),
            "qty": _fmt_qty(t.get("quantity")),
            "trade_price": t.get("trade_price"),
            "ib_commission": round((t.get("ib_commission") or 0.0), 2),  # IB 原始手续费，带符号
            "currency": t.get("currency"),
        })
    rows.sort(key=lambda r: (r["trade_date"] or "", r["symbol"] or "", str(r["qty"])))
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["trade_date", "symbol", "buy_sell", "qty",
                                          "trade_price", "ib_commission", "currency"])
        w.writeheader()
        w.writerows(rows)
    print(f"✔ 已导出逐笔原始 CSV: {csv_path}  ({len(rows)} 行)")
    return rows


def parse_file(path, reconcile=True, db_path=None, csv_path=None):
    """离线解析本地 XML 文件（验证用，不联网不读 token）。可选落库+对账。"""
    with open(path, "r", encoding="utf-8") as f:
        xml = f.read()
    parsed = parse_flex_xml(xml)
    print(f"✔ 解析 {path}: trades={len(parsed['trades'])} fx={len(parsed['fx'])} cash={len(parsed['cash'])}")
    if parsed["errors"]:
        print("⚠️ 解析告警:", parsed["errors"])
    print("样本 Trades:")
    for t in parsed["trades"][:5]:
        print("   ", {k: t[k] for k in ("exec_id", "symbol", "buy_sell", "quantity", "trade_price", "commission", "trade_date")})
    print("样本 Fx:")
    for fx in parsed["fx"][:3]:
        print("   ", {k: fx[k] for k in ("tx_id", "currency_pair", "fx_rate", "from_amount", "to_amount")})
    print("样本 Cash:")
    for c in parsed["cash"][:3]:
        print("   ", {k: c[k] for k in ("tx_id", "type", "amount", "currency")})
    if csv_path:
        export_trades_csv(parsed["trades"], csv_path)
    return parsed


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "--parse-file" and len(sys.argv) > 2:
        parse_file(sys.argv[2])
    else:
        print("用法: python ib_flex_service.py --parse-file <xml路径>   # 离线解析验证")
        print("      python -m services.ib_flex_service  (需配合 scripts/ib_flex_pull.py CLI)")
