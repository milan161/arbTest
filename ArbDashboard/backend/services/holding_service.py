"""
基金季报持仓分析服务（160723 MVP）。

提供：
- 报告期列表
- 某报告期持仓明细、地区分布、与上期变动
- 季报持仓法实时估值（报告期净值 × Σ权重 × 标的涨跌幅）

数据依赖：
- fund_report_holdings：季报解析后的持仓
- unified_fund_history：报告日基金净值
- usa_etf_daily_prices：底层标的报告日收盘价
- market_data_service.get_realtime_quote：底层标的实时行情
"""
import re
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional


# ---------------------------------------------------------------------------
# 季报持仓法静态估值（Model A）配置
# ---------------------------------------------------------------------------
# 权重唯一权威 = DB fund_report_holdings.weight（小数存储，×100 才是百分比）。
# 这里只保留"代码取代不了 DB"的两项元数据：

# 1) 季报持仓 symbol -> 估值篮子 symbol 的等价合并。
#    同一底层资产在不同币种/交易所发行的份额（WisdomTree Brent ETC 的
#    USD(BRNT)/GBP(BRNG)/EUR(BNQA) 份额）净值走势一致、差异仅为汇率，
#    统一用主份额 BRNT 的 USD 价格序列代表，避免"有权重却没有独立价格源"。
SYMBOL_ALIAS: Dict[str, str] = {
    "BRNG": "BRNT",
    "BNQA": "BRNT",
}

# 2) 单个标的可用性：该标的在报告期适用区间内的价格点数 / 该区间净值天数。
#    低于此值说明它只有报告日当天的快照（如 1671 只有 2 个点），
#    硬算会退化成"前填一个僵死价格"参与加权，必须从篮子剔除。
MIN_SYMBOL_DAYS_RATIO = 0.70

# 3) 覆盖率门控：篮子可算权重 / 该报告期全部基金持仓权重。
#    低于此值说明该期缺失标的过多，复算结果不可信，仅返回不落库。
MIN_COVERAGE = 0.90

# 汇率口径：按币种取对应 cny_mid（USD->usd_cny_mid / JPY->jpy_cny_mid / HKD->hkd_cny_mid）。
# 逐标的 (1+本地涨跌)×(1+该币种汇率涨跌)-1 加权，才是 NAV(CNY) 的真实构成。
# 纯 USD 篮子（160723/161129 五只）与旧"全 usd_only"数值完全一致；
# 含 JPY/HKD 篮子（501018 的 1699/1671、161129 的 03175）必须用对应汇率，否则误差系统性偏大。
FX_MODE = "by_currency"

# 币种 -> exchange_rate 列名（GBP/EUR 暂无列，缺则退化为 USD 并告警）
CURRENCY_FX_COL: Dict[str, str] = {
    "USD": "usd_cny_mid",
    "JPY": "jpy_cny_mid",
    "HKD": "hkd_cny_mid",
}

# 4) 前填标注：区分"真实休市前填 ✅"与"非假期数据缺失前填 ⚠️"。
#    东哥 2026-09-12 立规：前填只可用于真实交易假期（美/港/日/欧/英假期不同），
#    绝不可以把"数据源没爬到行情"偷偷当前填掩盖；缺价必须明显标注供人工核实。
#    标的 -> 上市市场（用于查该市场当日是否真休市）。BRNG/BNQA 已 alias 成 BRNT(UK)。
SYMBOL_MARKET: Dict[str, str] = {
    # 美股（NYSE/Nasdaq）
    "OILK": "US", "BNO": "US", "USO": "US", "DBO": "US",
    "XLE": "US", "XOP": "US", "OILUSA": "CH",
    # 伦敦（LSE）ETC/ETF
    "CRUD": "UK", "BRNT": "UK",
    # 港股
    "03175": "HK",
    # 日股
    "1699": "JP", "1671": "JP",
}

# 各市场 2026 休市日（只列确定的主要假期；宁可少列——漏列会触发"⚠️非假期缺价"
# 提示交由人工核实，绝不掩盖成正常前填）。
MARKET_HOLIDAYS: Dict[str, set] = {
    "US": {
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
        "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
        "2026-11-26", "2026-12-25",
    },
    "UK": {
        "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04",
        "2026-05-25", "2026-08-31", "2026-12-25", "2026-12-28",
    },
    "HK": {
        "2026-01-01", "2026-02-17", "2026-02-18", "2026-02-19",
        "2026-04-03", "2026-04-06", "2026-04-07", "2026-05-01",
        "2026-06-19", "2026-07-01", "2026-09-25", "2026-10-01",
        "2026-10-26", "2026-12-25", "2026-12-26", "2026-12-28",
    },
    "JP": {
        "2026-01-01", "2026-01-12", "2026-02-11", "2026-03-20",
        "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05",
        "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22",
        "2026-10-12", "2026-11-03", "2026-11-23",
    },
    "CH": {
        "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-01",
        "2026-08-01", "2026-12-25", "2026-12-26",
    },
}

_MISSING_MARKET_DEFAULT = "US"  # 未知标的默认按美股判断（美股休市最多，避免误判为"非假期"漏标）


def _market_of(symbol: str) -> str:
    return SYMBOL_MARKET.get(symbol, _MISSING_MARKET_DEFAULT)


def is_market_holiday(symbol: str, dt: str) -> bool:
    """该标的对应市场在某日是否真实休市（用于区分合法前填与数据漏抓）。
    周末（周六/周日）所有市场均不开市，统一视为非交易日——缺价属合法前填，
    绝不标红成\"⚠️非假期缺价\"（避免把周末误判成数据缺失）。"""
    try:
        wd = __import__("datetime").date.fromisoformat(dt).weekday()  # 0=Mon..6=Sun
    except Exception:
        wd = -1
    if wd >= 5:  # 周六/周日
        return True
    return dt in MARKET_HOLIDAYS.get(_market_of(symbol), set())


# ---------------------------------------------------------------------------
# 同步兜底补抓（东哥 2026-09-15 提议，配合 sync_usa_etf_from_arm）
# 背景：ARM sampler 每日 06:00 抓取，新浪美股日K部分标的更新延迟（9-14 实证：
# 多数标的当时停在 9-11，北京时间 19:39 才补齐），ARM 缺 → 同步后本地同缺。
# 兜底：同步完成后，对本地缺"最新已收盘交易日"收盘价的标的，本地直连源补抓
# 一次；仍缺则在返回里列出供前端报警。ARM 缺 + 本地也缺的概率大幅降低。
# 源与 sampler 一致：美股→新浪 US_MinKService；伦敦→腾讯 ukXXX；港股→腾讯 hkXXXX；
# 日股(JP)/瑞股(CH) 无自动化源，跳过（维持人工补 + ⚠️标红口径，见 013_2 §9.1）。

_SINA_US_DAILY_URL = ("https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_/"
                      "US_MinKService.getDailyK?symbol={sym}&___qn=3")
_TENCENT_KLINE_URL = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
                      "param={code},day,,,10,qfq")


def _http_get_text(url: str, timeout: int = 15) -> str:
    import ssl
    import urllib.request
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://finance.sina.com.cn" if "sina" in url else "https://gu.qq.com",
    })
    return urllib.request.urlopen(req, timeout=timeout, context=ctx).read().decode("gbk", "ignore")


def _sina_us_daily_closes(symbol: str) -> Dict[str, float]:
    """新浪美股日K最近收盘（{date: close}）。jsonp 用 find('(')~rfind(')') 截取。"""
    import json
    raw = _http_get_text(_SINA_US_DAILY_URL.format(sym=symbol))
    i, j = raw.find("("), raw.rfind(")")
    if i < 0 or j <= i:
        return {}
    arr = json.loads(raw[i + 1:j])
    return {x["d"]: float(x["c"]) for x in arr if x.get("d") and x.get("c")}


def _tencent_daily_closes(code: str) -> Dict[str, float]:
    """腾讯日K最近收盘（{date: close}）。
    code 形如 ukCRUD / hk03175。伦敦 ukXXX 必须走 usfqkline 端点（裸 fqkline
    对 uk 只回当天盘中 1 行；ukfqkline 返回空）——与 fetch_oil_etf_history.py
    tx_kline 默认 kind='us' 的既有用法一致。港股走裸 fqkline。"""
    import json
    path = "usfqkline" if code.startswith("uk") else "fqkline"
    raw = _http_get_text(
        f"https://web.ifzq.gtimg.cn/appstock/app/{path}/get?param={code},day,,,10,qfq")
    obj = json.loads(raw)
    node = (obj.get("data") or {}).get(code) or {}
    days = node.get("day") or node.get("qfqday") or []
    out: Dict[str, float] = {}
    for d in days:
        if isinstance(d, (list, tuple)) and len(d) >= 3 and d[0]:
            try:
                out[str(d[0])] = float(d[2])
            except (TypeError, ValueError):
                continue
    return out


# ---------------------------------------------------------------------------
# 持仓实时估值（Model B）配置
# ---------------------------------------------------------------------------
# 分母 = CL(WTI) 合约月三时点冻结价（来自 ARM futures_freeze_prices，每天上午盘前拉一次）。
# 自 2026-09-15 起改为"有效近月 ±1"三合约：近月=当月+1（USO 持次月合约）。
# 例: 9 月 → [2610,2611,2612]；10 月自动滚动为 [2611,2612,2701]。
FREEZE_POINTS = ["1130", "1430", "1600"]


def get_active_cl_contracts(as_of_date=None):
    """返回当前活跃的三个 CL 合约 YYMM 列表 [近月, +1月, +2月]。
    规则：有效近月 = 当月 + 1（USO 持次月合约）。
    """
    from datetime import date as _date
    if as_of_date is None:
        as_of_date = _date.today()
    y, m = as_of_date.year, as_of_date.month
    front_m = m + 1
    front_y = y
    if front_m > 12:
        front_m -= 12
        front_y += 1

    def _yymm(year, month):
        return f"{year % 100:02d}{month:02d}"

    contracts = []
    for i in range(3):
        cm = front_m + i
        cy = front_y
        if cm > 12:
            cm -= 12
            cy += 1
        contracts.append(_yymm(cy, cm))
    return contracts


CL_CONTRACTS = get_active_cl_contracts()  # 模块加载时算一次（当天不变）
# 篮子标的 -> 其确定自身净值的 NY 时点（与 Model A 口径一致）：
#   CRUD = CME WTI 14:30 EDT；BRNT = ICE Brent 11:30 EDT（本期用 CL 带残差）；
#   其余美股/港股原油 ETF 净值按 NY 收盘近似 -> 16:00。
POINT_BY_SYMBOL: Dict[str, str] = {
    "CRUD": "1430",
    "BRNT": "1130",
}


class HoldingService:
    def __init__(self, db, market_data_service=None):
        self.db = db
        self.market_data_service = market_data_service

    def _get_conn(self):
        from arbcore.database.managers.base import ensure_wal_once
        ensure_wal_once(self.db.db_path)
        return sqlite3.connect(self.db.db_path, timeout=15.0)

    def get_periods(self, fund_code: str) -> List[Dict[str, str]]:
        """返回该基金可用的报告期列表（按报告日倒序，仅保留季度 Q1~Q4，过滤 H1/H2 等半年报）。"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """
                SELECT report_period, MIN(report_date) AS report_date,
                       COUNT(DISTINCT symbol) AS holding_count
                FROM fund_report_holdings
                WHERE fund_code = ? AND report_period GLOB '[0-9]*Q[1-4]'
                GROUP BY report_period
                ORDER BY report_date DESC
                """,
                (fund_code,),
            )
            rows = cur.fetchall()
            return [
                {"period": r[0], "date": r[1], "holding_count": r[2]}
                for r in rows
            ]
        finally:
            conn.close()

    def get_holdings(self, fund_code: str, report_period: str) -> Dict[str, Any]:
        """返回某报告期的持仓明细、地区分布、与上期变动。"""
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """
                SELECT id, fund_code, report_period, report_date, symbol, name, name_en,
                       region, currency, type, operation_mode, manager, weight,
                       market_value, is_stock, sort_order
                FROM fund_report_holdings
                WHERE fund_code = ? AND report_period = ?
                ORDER BY is_stock, sort_order
                """,
                (fund_code, report_period),
            )
            rows = cur.fetchall()
            holdings = [
                {
                    "id": r[0],
                    "fund_code": r[1],
                    "report_period": r[2],
                    "report_date": r[3],
                    "symbol": r[4],
                    "name": r[5],
                    "name_en": r[6],
                    "region": r[7],
                    "currency": r[8],
                    "type": r[9],
                    "operation_mode": r[10],
                    "manager": r[11],
                    "weight": r[12],
                    "market_value": r[13],
                    "is_stock": bool(r[14]),
                    "sort_order": r[15],
                }
                for r in rows
            ]

            # Top10 持仓：按权重降序取前10（包含股票和基金，按 sort_order 分组后按权重排序）
            holdings_sorted = sorted(holdings, key=lambda x: -(x["weight"] or 0.0))
            top10 = holdings_sorted[:10]
            # 重新编号 sort_order
            for i, h in enumerate(top10):
                h["display_order"] = i + 1

            # 地区分布：按 region 聚合 weight（仅基金持仓，不含股票；股票单独列）
            region_map: Dict[str, float] = {}
            for h in holdings:
                if h["is_stock"]:
                    continue
                region = h["region"] or "其他"
                region_map[region] = region_map.get(region, 0.0) + (h["weight"] or 0.0)
            region_distribution = [
                {"region": k, "weight": v, "pct": round(v * 100, 2)}
                for k, v in sorted(region_map.items(), key=lambda x: -x[1])
            ]

            # 与上期变动：先算出上期Top10，再用上期Top10构建prev_symbols（只比较有资格进前十的）
            prev_period, prev_date = self._get_previous_period(conn, fund_code, report_period)
            prev_symbols = {}
            if prev_period:
                cur2 = conn.execute(
                    "SELECT symbol, name, weight FROM fund_report_holdings WHERE fund_code=? AND report_period=? ORDER BY weight DESC",
                    (fund_code, prev_period),
                )
                # 只取上期按权重前10的持仓（含股票），作为"上期有资格进前十"的基准
                for i, (sym, name, weight) in enumerate(cur2.fetchall()):
                    if i >= 10:
                        break
                    key = sym or name
                    prev_symbols[key] = {"symbol": sym, "name": name, "weight": weight}

            # 给 top10 注入 prev_weight
            for h in top10:
                key = h["symbol"] or h["name"]
                h["prev_weight"] = prev_symbols.get(key, {}).get("weight")

            exited = []
            for key, p in prev_symbols.items():
                if key not in {h["symbol"] or h["name"] for h in top10}:
                    exited.append(p)
            new_in = []
            for key, c in {h["symbol"] or h["name"]: h for h in top10}.items():
                if key not in prev_symbols:
                    new_in.append({
                        "symbol": c["symbol"],
                        "name": c["name"],
                        "weight": c["weight"],
                    })
            changed = []
            for h in top10:
                key = h["symbol"] or h["name"]
                if key in prev_symbols:
                    delta = (h["weight"] or 0.0) - (prev_symbols[key]["weight"] or 0.0)
                    if abs(delta) >= 0.0001:
                        changed.append({
                            "symbol": h["symbol"],
                            "name": h["name"],
                            "current_weight": h["weight"],
                            "prev_weight": prev_symbols[key]["weight"],
                            "delta": delta,
                            "delta_pct": round(delta * 100, 2),
                        })

            return {
                "fund_code": fund_code,
                "report_period": report_period,
                "report_date": holdings[0]["report_date"] if holdings else None,
                "holdings": top10,
                "region_distribution": region_distribution,
                "prev_period": prev_period,
                "prev_date": prev_date,
                "exited": exited,
                "new_in": new_in,
                "changed": sorted(changed, key=lambda x: -abs(x["delta"])),
            }
        finally:
            conn.close()

    def _get_previous_period(self, conn, fund_code: str, report_period: str):
        """按报告日找上一个有数据的报告期。"""
        cur = conn.execute(
            "SELECT report_date FROM fund_report_holdings WHERE fund_code=? AND report_period=? LIMIT 1",
            (fund_code, report_period),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        report_date = row[0]
        cur2 = conn.execute(
            """
            SELECT report_period, report_date
            FROM fund_report_holdings
            WHERE fund_code = ? AND report_date < ?
            GROUP BY report_period, report_date
            ORDER BY report_date DESC
            LIMIT 1
            """,
            (fund_code, report_date),
        )
        row2 = cur2.fetchone()
        return row2 if row2 else (None, None)

    def get_valuation(self, fund_code: str, report_period: str) -> Dict[str, Any]:
        """季报持仓法实时估值。

        公式（简化版）：
            realtime_nav = report_nav * (1 + Σ(weight_i * (current_price_i / base_price_i - 1)))

        说明：
        - 报告期净值来自 unified_fund_history.nav
        - 底层标的报告日价格优先取 usa_etf_daily_prices.price
        - 当前价格来自 market_data_service.get_realtime_quote
        - MVP 暂不做汇率调整（底层标的价格波动远大于汇率波动）
        """
        conn = self._get_conn()
        try:
            holdings_info = self.get_holdings(fund_code, report_period)
            report_date = holdings_info["report_date"]
            holdings = [h for h in holdings_info["holdings"] if not h["is_stock"]]

            # 取报告期基金净值
            nav = None
            cur = conn.execute(
                "SELECT nav FROM unified_fund_history WHERE fund_code=? AND date=? AND nav IS NOT NULL AND nav>0",
                (fund_code, report_date),
            )
            row = cur.fetchone()
            if row:
                nav = float(row[0])

            # 逐标估值
            components = []
            total_contribution = 0.0
            valid_weight_sum = 0.0
            for h in holdings:
                symbol = h["symbol"]
                weight = h["weight"] or 0.0
                if not symbol:
                    components.append({
                        **h,
                        "base_price": None,
                        "current_price": None,
                        "change_pct": None,
                        "contribution": None,
                        "status": "missing_symbol",
                    })
                    continue

                # 报告日价格
                base_price = None
                cur2 = conn.execute(
                    "SELECT price FROM usa_etf_daily_prices WHERE symbol=? AND date=? AND price IS NOT NULL AND price>0",
                    (symbol, report_date),
                )
                r2 = cur2.fetchone()
                if r2:
                    base_price = float(r2[0])

                # 当前实时价格
                current_price = None
                if self.market_data_service:
                    try:
                        q = self.market_data_service.get_realtime_quote(symbol)
                        if q:
                            current_price = q.get("price") or q.get("bid") or q.get("last")
                            if current_price:
                                current_price = float(current_price)
                    except Exception:
                        pass

                if base_price and current_price and base_price > 0:
                    change_pct = current_price / base_price - 1.0
                    contribution = weight * change_pct
                    total_contribution += contribution
                    valid_weight_sum += weight
                    status = "ok"
                else:
                    change_pct = None
                    contribution = None
                    status = []
                    if base_price is None:
                        status.append("missing_base_price")
                    if current_price is None:
                        status.append("missing_current_price")
                    status = "|".join(status) if status else "unknown"

                components.append({
                    **h,
                    "base_price": base_price,
                    "current_price": current_price,
                    "change_pct": change_pct,
                    "contribution": contribution,
                    "status": status,
                })

            realtime_nav = None
            realtime_available = False
            if nav is not None and valid_weight_sum > 1e-6:
                realtime_nav = nav * (1.0 + total_contribution)
                realtime_available = True

            return {
                "fund_code": fund_code,
                "report_period": report_period,
                "report_date": report_date,
                "report_nav": nav,
                "realtime_nav": realtime_nav,
                "realtime_available": realtime_available,
                "total_change_pct": total_contribution,
                "valid_weight_sum": valid_weight_sum,
                "components": components,
            }
        finally:
            conn.close()

    def _load_period_weights(self, fund_code: str) -> List[Dict[str, Any]]:
        """从 DB 读取各季度报告期的持仓权重，按报告日升序。

        权重唯一权威 = fund_report_holdings.weight（小数存储，×100 得百分比）。
        规则：
        - 仅取季度报告期 Q1~Q4；半年报 H1/H2 与 Q2/Q4 同报告日且重复，已过滤
        - 股票持仓（is_stock=1）不进篮子
        - 按 SYMBOL_ALIAS 合并同一底层资产的多币种份额
        """
        conn = self._get_conn()
        try:
            cur = conn.execute(
                """
                SELECT report_period, report_date, symbol, weight, is_stock, currency
                FROM fund_report_holdings
                WHERE fund_code = ? AND report_period GLOB '[0-9]*Q[1-4]'
                  AND weight IS NOT NULL
                ORDER BY report_date
                """,
                (fund_code,),
            )
            by_date: Dict[str, Dict[str, Any]] = {}
            for period, rdate, sym, w, is_stock, currency in cur.fetchall():
                if is_stock or not sym:
                    continue
                slot = by_date.setdefault(
                    rdate, {"period": period, "weights": {}, "cur": {}, "total": 0.0}
                )
                slot["total"] += w * 100.0
                basket_sym = SYMBOL_ALIAS.get(sym, sym)
                slot["weights"][basket_sym] = (
                    slot["weights"].get(basket_sym, 0.0) + w * 100.0
                )
                # 记录币种（别名合并后同资产同币种，取首个即可）
                if basket_sym not in slot["cur"]:
                    slot["cur"][basket_sym] = (currency or "USD").upper()
            return [
                {
                    "period": v["period"],
                    "report_date": k,
                    "weights": v["weights"],
                    "cur": v["cur"],
                    "total": round(v["total"], 4),
                }
                for k, v in sorted(by_date.items())
            ]
        finally:
            conn.close()

    @staticmethod
    def _pick_period(periods: List[Dict[str, Any]], date: str) -> Optional[Dict[str, Any]]:
        """按期切换：报告日 R 的持仓适用于 R 之后（不含 R）到下一份报告日之间。

        Q1(3-31) -> 4-01~6-30；Q2(6-30) -> 7-01~9-30。periods 必须按报告日升序。
        """
        chosen = None
        for p in periods:
            if p["report_date"] < date:
                chosen = p
            else:
                break
        return chosen

    def get_recalc_history(
        self,
        fund_code: str,
        report_period: str = None,
        start: str = "2026-07-01",
        min_coverage: float = None,
    ) -> Dict[str, Any]:
        """持仓静态估值历史（季报持仓法 Model A，按币种 FX 折算口径）。

        与旧版（160723 硬编码 Q2 五只权重）的区别：
        1. 权重按期切换 —— 报告日 R 的持仓只用于 R 之后到下一份报告日之间，
           绝不用一份权重复算全历史（用错期实测把误差放大 1.8~20 倍）
        2. 权重来源 DB（fund_report_holdings），不再硬编码，因此 161129 等基金通用
        3. 篮子可算权重覆盖率低于 MIN_COVERAGE 的报告期，仅返回不落库

        report_period 参数已废弃（保留仅为兼容前端调用），权重由日期自动路由。
        链式基数 = 官方净值(t-1)，不累积漂移。
        结果落库 unified_fund_history.holding_static_val。
        """
        cov_gate = MIN_COVERAGE if min_coverage is None else min_coverage
        periods = self._load_period_weights(fund_code)
        if not periods:
            return {
                "fund_code": fund_code, "start": start, "count": 0, "rows": [],
                "periods": [], "fx_mode": FX_MODE, "error": "no_report_holdings",
            }

        all_symbols = sorted({s for p in periods for s in p["weights"]})

        conn = self._get_conn()
        try:
            # [AI-2026-09-12] 不再过滤 nav IS NOT NULL：T+1 未公布净值的交易日（如 9-11 周五）
            # 仍应生成静态估值行——它依赖的是上一非空净值(T-1, 已公布)而非当日净值。
            # official_nav 缺失日返回 NULL（前端显示 '-'），但 holding_static_val 照常计算。
            nav_rows = conn.execute(
                "SELECT date, nav FROM unified_fund_history "
                "WHERE fund_code=? AND date>=? ORDER BY date",
                (fund_code, start),
            ).fetchall()
            price_rows = {}
            for s in all_symbols:
                price_rows[s] = {
                    r[0]: r[1] for r in conn.execute(
                        "SELECT date, price FROM usa_etf_daily_prices "
                        "WHERE symbol=? AND date>=? AND price IS NOT NULL AND price>0 ORDER BY date",
                        (s, start),
                    ).fetchall()
                }
            fx_rows: Dict[str, Dict[str, float]] = {}
            for col in CURRENCY_FX_COL.values():
                fx_rows[col] = {
                    r[0]: r[1] for r in conn.execute(
                        f"SELECT date, {col} FROM exchange_rate "
                        f"WHERE {col} IS NOT NULL AND date>=? ORDER BY date",
                        (start,),
                    ).fetchall()
                }
            # [AI-2026-09-15] 美股时钟：参考大盘 ETF(SPY/QQQ) 在库中的最新日
            # = 美股最新"已收盘且已入库"的交易日。篮子含美股标的的 QDII，
            # 目标日 d 超过该时钟（且 d 非美股假期）时，美股部分必为前填凑数
            # ——只剩汇率噪声的假估值（9-15 实测：est=2.3583 纯汇率噪声）。
            # 该行不生成、不落库（宁缺毋假，东哥 2026-09-15 拍板）。
            us_clock_row = conn.execute(
                "SELECT MAX(date) FROM usa_etf_daily_prices "
                "WHERE symbol IN ('SPY','QQQ') AND price IS NOT NULL AND price>0"
            ).fetchone()
            us_clock = us_clock_row[0] if us_clock_row else None
        finally:
            conn.close()

        if not nav_rows:
            return {
                "fund_code": fund_code, "start": start, "count": 0, "rows": [],
                "periods": periods, "fx_mode": FX_MODE, "error": "no_nav",
            }

        # 每个报告期：按各自的适用区间 (本报告日, 下一报告日] 判定标的价格可得性。
        # 只有报告日快照、区间内没有连续序列的标的（1671 / BRNG 之类）必须剔除，
        # 否则前填会让它以"僵死价格"参与加权，等于凭空稀释篮子波动。
        nav_dates = [d for d, _ in nav_rows]
        for idx, p in enumerate(periods):
            lo = p["report_date"]
            hi = periods[idx + 1]["report_date"] if idx + 1 < len(periods) else nav_dates[-1]
            span = [d for d in nav_dates if lo < d <= hi]
            if not span:
                p.update(usable={}, pos=0.0, dropped=sorted(p["weights"]),
                         coverage=0.0, span=[])
                continue
            s0, s1 = span[0], span[-1]
            usable, dropped = {}, []
            for s, w in p["weights"].items():
                pts = sum(1 for d in price_rows.get(s, {}) if s0 <= d <= s1)
                if pts / len(span) >= MIN_SYMBOL_DAYS_RATIO:
                    usable[s] = w
                else:
                    dropped.append(s)
            pos = sum(usable.values())
            p.update(usable=usable, pos=round(pos, 4), dropped=sorted(dropped),
                     coverage=round(pos / p["total"], 4) if p["total"] > 0 else 0.0,
                     span=[s0, s1])

        def _fill(d: dict, dt: str):
            if dt in d:
                return d[dt]
            keys = [k for k in d if k <= dt]
            return d[keys[-1]] if keys else None

        rows = []
        stat: Dict[str, Dict[str, float]] = {}
        prev_nav = None
        for i, (d, nav) in enumerate(nav_rows):
            # 美股时钟拦截：d 尚未收盘/未入库（非假期）→ 整行跳过，不生成不落库。
            # 假期日放行（假期前填合法）；prev_nav 链与其它 skip 分支保持一致。
            if us_clock and d > us_clock and not is_market_holiday("USO", d):
                if nav is not None:
                    prev_nav = nav
                continue
            prev_date = nav_rows[i - 1][0]
            if prev_nav is None:
                # 还没有可用于推算(T-1)的上一个非空净值，跳过当日；
                # 仅当当日自身 nav 非空时才更新 prev_nav。
                if nav is not None:
                    prev_nav = nav
                continue
            per = self._pick_period(periods, d)
            if per is None or not per["usable"]:
                if nav is not None:
                    prev_nav = nav
                continue

            syms = list(per["usable"])
            p0 = {s: _fill(price_rows[s], prev_date) for s in syms}
            p1 = {s: _fill(price_rows[s], d) for s in syms}
            if any(p0[s] is None or p1[s] is None or p0[s] <= 0 for s in syms):
                prev_nav = nav
                continue
            # 逐标的 FX：本地涨跌 × 该币种汇率涨跌，再按权重加权成 r_basket。
            # 纯 USD 篮子（160723/161129 五只）每标的使用 usd_cny_mid，与旧口径数值一致；
            # 含 JPY/HKD 篮子（501018 的 1699/1671、161129 的 03175）按对应币种汇率折算。
            # 缺某标的的相关币种汇率则跳日（不兜底假数据）。
            pos = sum(per["usable"].values())
            r_basket = 0.0
            fx_detail: Dict[str, Dict[str, Any]] = {}
            fx_missing = False
            for s in syms:
                r_local = p1[s] / p0[s] - 1.0
                cur = per["cur"].get(s, "USD")
                col = CURRENCY_FX_COL.get(cur, "usd_cny_mid")
                fxc0 = _fill(fx_rows[col], prev_date)
                fxc1 = _fill(fx_rows[col], d)
                if fxc0 is None or fxc1 is None or fxc0 <= 0:
                    fx_missing = True
                    break
                r_fx = fxc1 / fxc0 - 1.0
                r_i = (1.0 + r_local) * (1.0 + r_fx) - 1.0
                r_basket += (per["usable"][s] / pos) * r_i
                fx_detail[s] = {"cur": cur, "r_fx": round(r_fx, 6)}
            if fx_missing:
                prev_nav = nav
                continue

            est = prev_nav * (1.0 + pos / 100.0 * r_basket)
            # 当日官方净值缺失(T+1未公布)时估值仍可算(依赖上一非空净值)，但误差无法计算
            err = (est / nav - 1.0) if nav is not None else None

            # 前填标注：区分"真实休市前填 ✅"与"非假期数据缺失前填 ⚠️"（东哥 2026-09-12 立规）。
            # 缺价的日期可能是 prev_date(T-1) 或 d(T 日)，分别按该标的市场判断是否真休市。
            note_parts: List[str] = []
            fill_warning = False
            for s in syms:
                miss_dates = [dt for dt in (prev_date, d) if dt not in price_rows[s]]
                for md in miss_dates:
                    if is_market_holiday(s, md):
                        note_parts.append(f"假期前填:{s}({md})")
                    else:
                        note_parts.append(f"⚠️非假期缺价:{s}({md})")
                        fill_warning = True
            usd_ref = _fill(fx_rows["usd_cny_mid"], d)
            rows.append({
                "date": d,
                "report_period": per["period"],
                "coverage": per["coverage"],
                "official_nav": round(nav, 6) if nav is not None else None,
                "holding_static_val": round(est, 6),
                "err_pct": round(err * 100, 4) if err is not None else None,
                "err_bp": round(err * 10000, 2) if err is not None else None,
                "prev_official_nav": round(prev_nav, 6),
                "etf_prices": {s: round(p1[s], 4) for s in syms},
                "etf_prev": {s: round(p0[s], 4) for s in syms},
                "usd_cny": round(usd_ref, 4) if usd_ref is not None else None,
                "fx_detail": fx_detail,
                "note": "; ".join(note_parts) if note_parts else "",
                "fill_warning": fill_warning,
            })

            # 仅当当日官方净值存在(可算误差)才计入误差统计
            if err is not None:
                st = stat.setdefault(per["period"], {"n": 0, "abs_bp": 0.0, "max_abs_bp": 0.0})
                st["n"] += 1
                st["abs_bp"] += abs(err * 10000)
                st["max_abs_bp"] = max(st["max_abs_bp"], abs(err * 10000))

            # prev_nav 仅用非空净值推进；缺失日(如 T+1 未公布的 9-11)保持上一非空值，
            # 使后续可交易日的估值仍能依赖最近一个已公布净值推算。
            if nav is not None:
                prev_nav = nav

        for k, v in stat.items():
            v["mean_abs_bp"] = round(v["abs_bp"] / v["n"], 2) if v["n"] else None
            v["abs_bp"] = round(v["abs_bp"], 2)
            v["max_abs_bp"] = round(v["max_abs_bp"], 2)

        # 落库 holding_static_val（先清零该基金；仅按"覆盖率达标"落库）。
        # [AI-2026-09-12] 去掉 note=="" 限制：个别标的缺价(真实休市前填 / 或非假期数据漏抓)
        # 时由 _fill 前填到最近交易日，估值仍是合理预测(东哥口径"静态估值即预测")，不应因此变 NULL；
        # note 字段透明标注"假期前填:SYM(日期)"或"⚠️非假期缺价:SYM(日期)"，fill_warning 标记
        # 非假期缺价行供前端标红核实。真正的低覆盖/大面积缺口日仍被 cov_gate 挡掉。
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE unified_fund_history SET holding_static_val=NULL WHERE fund_code=?",
                (fund_code,),
            )
            for r in rows:
                if r["coverage"] >= cov_gate:
                    conn.execute(
                        "UPDATE unified_fund_history SET holding_static_val=? "
                        "WHERE fund_code=? AND date=?",
                        (r["holding_static_val"], fund_code, r["date"]),
                    )
            conn.commit()
        finally:
            conn.close()

        return {
            "fund_code": fund_code,
            "start": start,
            "count": len(rows),
            "fx_mode": FX_MODE,
            "min_coverage": cov_gate,
            "periods": [
                {
                    "period": p["period"],
                    "report_date": p["report_date"],
                    "span": p.get("span") or [],  # 该期实际复算区间；空=落在 start 之前，未参与
                    "total_weight": p["total"],
                    "usable_weight": p["pos"],
                    "coverage": p["coverage"],
                    "dropped": p["dropped"],
                    "basket": {s: round(w, 4) for s, w in p["usable"].items()},
                    "stat": stat.get(p["period"]),
                }
                for p in periods
            ],
            "rows": list(reversed(rows)),  # 降序：最新在上
        }

    # ------------------------------------------------------------------
    # 持仓实时估值（Model B）：季报持仓法 + CL 期货实时价
    # ------------------------------------------------------------------
    def get_realtime_valuation(self, fund_code: str) -> Dict[str, Any]:
        """持仓实时估值（Model B）—— 有效近月±1 三合约对比版。

        公式：est_now = base_nav * (1 + Σ (w_i/100) * (CL_now / CL_point_i - 1))
        自 2026-09-15 起同时计算三个合约（近月/+1/+2，如 9 月 → 2610/2611/2612）的估值：
          - 每个合约各自取本地 futures_freeze_prices 的三时点冻结价作分母（symbol='CL{合约}'）；
          - 分子实时抓对应合约新浪 hf_CL{合约}（与冻结采样合约严格一致）；
          - LOF 实时价 / 实时美元人民币为三合约共用输入（与实际基金、汇率相关，与合约无关）。
        返回结构含 contracts:{ '2610':{...}, '2611':{...}, '2612':{...} }，
        前端可任选一个作对冲基准并对比精度。
        selected_contract 默认取 CL_CONTRACTS[0]（当前近月），前端可切换。
        分母（futures_freeze_prices）需先经 sync_futures_freeze_from_arm 从 ARM 拉到本地；
        本方法只读本地缓存，不实时去 ARM（东哥：每天上午取一次即可）。
        某合约三点不齐 → 该合约 status='freeze_incomplete'，其余仍正常；整体 status='partial'。
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # [AI-2026-09-15] 共用输入（与合约无关）提到最前：
        # 即便某合约后续走错误分支（冻结缺失/CL 抓取失败），LOF 现价/汇率也能带出，UI 不空白。
        lof_price, lof_price_source = self._fetch_lof_price(fund_code)
        try:
            fx_now = self._fetch_usdcny_realtime()
        except Exception as e:
            # 汇率失败仍是硬错误（估值无法计算），但带上 LOF 现价便于 UI 显示收盘现价
            return _rt_err(fund_code, "fx_fetch_failed", today=today,
                          lof_price=lof_price, lof_price_source=lof_price_source,
                          message=str(e)[:200])

        periods = self._load_period_weights(fund_code)
        if not periods:
            return _rt_err(fund_code, "no_report_holdings",
                          lof_price=lof_price, lof_price_source=lof_price_source,
                          fx_now=fx_now)

        active = get_active_cl_contracts()  # 每次调用重算（跨月安全）

        conn = self._get_conn()
        self._ensure_freeze_table(conn)
        try:
            # [AI-2026-09-15] 基准日 = CL 采样日（分子分母同日对齐），但必须是「完整采样日」：
            # 近月合约（active[0]）在该日三时点齐全，且该日 holding_static_val 已落库。
            # 否则采样进行中（如 9-15 只来了 1430 一点、静态估值还是 NULL）会被选为基准，
            # base_nav 缺失 → 整体硬报错 → 前端 active_contracts 拿不到、单选组消失（当日实际 bug）。
            # 无完整采样日时 fallback 旧净值日口径，避免全空回归。
            near_sym = f"CL{active[0]}"
            fr = conn.execute(
                "SELECT f.trade_date FROM futures_freeze_prices f "
                "JOIN unified_fund_history u ON u.date = f.trade_date AND u.fund_code = ? "
                "WHERE f.symbol = ? AND f.trade_date <= ? "
                "GROUP BY f.trade_date "
                "HAVING COUNT(DISTINCT f.point) >= ? AND u.holding_static_val IS NOT NULL "
                "ORDER BY f.trade_date DESC LIMIT 1",
                (fund_code, near_sym, today, len(FREEZE_POINTS))).fetchone()
            freeze_base_date = fr[0] if fr else None

            nav_dates = [r[0] for r in conn.execute(
                "SELECT date FROM unified_fund_history "
                "WHERE fund_code=? AND nav IS NOT NULL AND nav>0 ORDER BY date",
                (fund_code,)).fetchall()]
            nav_base_date = max((d for d in nav_dates if d < today), default=None)

            base_date = freeze_base_date or nav_base_date
            if not base_date:
                return _rt_err(fund_code, "no_base_date", today=today,
                              lof_price=lof_price, lof_price_source=lof_price_source,
                              fx_now=fx_now)

            base_nav_row = conn.execute(
                "SELECT holding_static_val FROM unified_fund_history "
                "WHERE fund_code=? AND date=?", (fund_code, base_date)).fetchone()
            if base_nav_row is None or base_nav_row[0] is None:
                nav_row = conn.execute(
                    "SELECT nav FROM unified_fund_history "
                    "WHERE fund_code=? AND date=?", (fund_code, base_date)).fetchone()
                if nav_row is None or nav_row[0] is None:
                    return _rt_err(fund_code, "no_base_nav", base_date=base_date,
                                  lof_price=lof_price, lof_price_source=lof_price_source,
                                  fx_now=fx_now)
                base_nav = float(nav_row[0])
            else:
                base_nav = float(base_nav_row[0])

            per = self._pick_period(periods, base_date)
            if per is None:
                return _rt_err(fund_code, "no_period", base_date=base_date,
                              lof_price=lof_price, lof_price_source=lof_price_source,
                              fx_now=fx_now)
            basket = per["weights"]  # 已合并 BRNG/BNQA->BRNT，已剔除股票，单位 %

            # FX 时点价：base_date 的 usd_cny_mid（静态估值同源，全 USD 简化）。
            # 分母(三时点冻结价)改为按合约在 _value_one_contract 内各自查询。
            fx_row = conn.execute(
                "SELECT usd_cny_mid FROM exchange_rate WHERE date=?",
                (base_date,)).fetchone()
            fx_point = float(fx_row[0]) if (fx_row and fx_row[0] is not None) else None
        finally:
            conn.close()

        # 逐合约计算估值（分母/分子各自合约严格一致）
        contracts: Dict[str, Any] = {}
        for contract in active:
            contracts[contract] = self._value_one_contract(
                fund_code, contract, base_date, base_nav, per, basket,
                fx_point, fx_now, lof_price, lof_price_source, today)

        any_ok = any(c["status"] == "ok" for c in contracts.values())
        all_ok = all(c["status"] == "ok" for c in contracts.values())
        status = "ok" if all_ok else ("partial" if any_ok else "error")
        return {
            "fund_code": fund_code,
            "base_date": base_date,
            "base_nav": round(base_nav, 6),
            "selected_contract": active[0],
            "active_contracts": active,  # 前端渲染选择器用
            "contracts": contracts,
            "status": status,
            "message": None,
        }

    def _value_one_contract(self, fund_code, contract, base_date, base_nav, per, basket,
                           fx_point, fx_now, lof_price, lof_price_source, today) -> Dict[str, Any]:
        """对单个合约（如 '2610' 近月 / '2611' +1 / '2612' +2）计算完整估值。

        分母取本地 futures_freeze_prices 中 symbol='CL{contract}' 的三时点冻结价；
        分子实时抓新浪 hf_CL{contract}。其余（base_nav/篮子/fx_point/lof_price/fx_now）与合约无关，由调用方传入。
        冻结价缺失（三点不齐）返回 status='freeze_incomplete'，不兜底。
        """
        sym = "CL" + contract
        conn = self._get_conn()
        try:
            freeze: Dict[str, Dict[str, Any]] = {}
            for pt in FREEZE_POINTS:
                # [AI-2026-09-15] 分母三点必须严格取基准日当天，杜绝手工测试行 /
                # 跨日残留污染分母（如 9-15 手工 1430 行顶掉 9-14 真实 1430）。
                # 原写法 trade_date<=today 取各点最新一条，会把非基准日价格混入。
                row = conn.execute(
                    "SELECT price, trade_date FROM futures_freeze_prices "
                    "WHERE symbol=? AND point=? AND trade_date=?",
                    (sym, pt, base_date)).fetchone()
                if row and row[0] is not None:
                    freeze[pt] = {"price": float(row[0]), "trade_date": row[1]}
        finally:
            conn.close()

        missing = [pt for pt in FREEZE_POINTS if pt not in freeze]
        if missing:
            # 即便冻结价缺失，也带出共用输入，避免 ETF 现价/汇率在 UI 空白
            return _rt_err(
                fund_code, "freeze_incomplete", base_date=base_date, contract=contract,
                missing_points=missing,
                lof_price=lof_price, lof_price_source=lof_price_source,
                fx_now=fx_now, fx_point=fx_point, fx_status="unknown_pre_freeze",
                message=f"CL{contract} 三时点冻结价缺失，请先调 sync_futures_freeze_from_arm / "
                        f"/api/fund/sync-freeze 从 ARM 拉取",
            )

        # 分子：实时抓该合约 CL（A 股盘中）
        try:
            cl_now, cl_time = self._fetch_cl_realtime(contract)
        except Exception as e:
            return _rt_err(fund_code, "cl_fetch_failed", base_date=base_date, contract=contract,
                          lof_price=lof_price, lof_price_source=lof_price_source,
                          fx_now=fx_now, fx_point=fx_point, fx_status="unknown_pre_cl",
                          message=str(e)[:200])

        # 计算
        components = []
        contrib_sum = 0.0
        valid_weight_pct = 0.0
        for s, w_pct in basket.items():
            pt = POINT_BY_SYMBOL.get(s, "1600")
            fp = freeze[pt]["price"]
            if fp <= 0:
                components.append({"symbol": s, "weight_pct": round(w_pct, 4),
                                   "point": pt, "status": "bad_freeze"})
                continue
            ratio = cl_now / fp - 1.0
            contrib = (w_pct / 100.0) * ratio  # w_pct 是%，/100 -> 小数权重
            contrib_sum += contrib
            valid_weight_pct += w_pct
            components.append({
                "symbol": s, "name": s, "weight_pct": round(w_pct, 4),
                "point": pt, "freeze_price": round(fp, 4),
                "freeze_date": freeze[pt]["trade_date"],
                "cl_now": round(cl_now, 4), "ratio": round(ratio, 6),
                "contrib": round(contrib, 6), "status": "ok",
            })

        # FX 合并（全 USD 简化，与静态估值口径一致：篮子变动与汇率变动合进同一 POS% 杠杆）
        pos_pct = per["total"]
        r_basket_norm = contrib_sum * 100.0 / pos_pct if pos_pct > 0 else 0.0
        if fx_point is None or fx_point <= 0:
            fx_point_used = fx_now          # fx_point 缺失：退化为无 FX 项
            fx_status = "fx_point_missing"
            r_fx_rt = 0.0
        else:
            fx_point_used = fx_point
            fx_status = "ok"
            r_fx_rt = fx_now / fx_point_used - 1.0
        total_change = (pos_pct / 100.0) * ((1.0 + r_basket_norm) * (1.0 + r_fx_rt) - 1.0)
        est = base_nav * (1.0 + total_change)
        return {
            "fund_code": fund_code,
            "base_date": base_date,
            "base_nav": round(base_nav, 6),
            "contract": contract,
            "cl_now": round(cl_now, 4),
            "cl_time": cl_time,
            "cl_symbol": sym,
            "cl_contract_name": f"CL {contract[2:]}月 (hf_CL{contract})",
            "cl_contract_note": f"新浪 hf_CL{contract} 为 WTI {contract[2:]}月合约，与 ARM 三时点冻结采样合约一致",
            "freeze_trade_date": freeze["1600"]["trade_date"],
            "freeze_points": {
                pt: {"price": round(freeze[pt]["price"], 4), "trade_date": freeze[pt]["trade_date"]}
                for pt in FREEZE_POINTS if pt in freeze
            },
            "realtime_nav": round(est, 6),
            "lof_price": round(lof_price, 4) if lof_price is not None else None,
            "lof_price_source": lof_price_source,
            "realtime_premium": round(lof_price / est - 1, 6)
            if (lof_price is not None and est and est > 0) else None,
            "total_change_pct": round(total_change, 6),
            "basket_change_pct": round(r_basket_norm, 6),
            "fx_change_pct": round(r_fx_rt, 6),
            "fx_now": round(fx_now, 4),
            "fx_point": round(fx_point_used, 4),
            "fx_status": fx_status,
            "valid_weight_sum": round(valid_weight_pct / 100.0, 4),
            "coverage": round(valid_weight_pct / per["total"], 4) if per["total"] > 0 else 0.0,
            "components": components,
            "status": "ok",
            "message": None,
        }

    @staticmethod
    def _fetch_cl_realtime(contract: str) -> Any:
        """实时抓指定远月合约 CL(WTI) 价（新浪 hf_CL{contract}，如 hf_CL2611）。与 cl_freeze_sampler.fetch_cl 同源。"""
        import re
        import urllib.request
        code = "hf_CL" + contract
        url = "https://hq.sinajs.cn/list=" + code
        req = urllib.request.Request(
            url, headers={"Referer": "https://finance.sina.com.cn",
                          "User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "ignore")
        m = re.search(r'var hq_str_' + code + r'="(.*?)"', raw)
        if not m:
            raise ValueError(f"新浪未匹配 {code}")
        fields = m.group(1).split(",")
        price = None
        for f in fields:
            f = f.strip()
            try:
                v = float(f)
                if 1.0 < v < 1000.0:  # WTI 合理区间
                    price = v
                    break
            except ValueError:
                continue
        if price is None:
            raise ValueError(f"新浪 {code} 无有效价格")
        t = fields[-1].strip() if fields else ""
        return price, t

    @staticmethod
    def _fetch_usdcny_realtime() -> float:
        """实时美元人民币（腾讯 fxUSDCNY，在岸价）。与静态估值 usd_cny_mid 同源（全 USD 简化）。"""
        import re
        import urllib.request
        url = "http://qt.gtimg.cn/q=fxUSDCNY"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "ignore")
        m = re.search(r'v_fxUSDCNY="(.*?)"', raw)
        if not m:
            raise ValueError("腾讯未匹配 fxUSDCNY")
        fields = m.group(1).split("~")
        if len(fields) < 4:
            raise ValueError("腾讯 fxUSDCNY 字段不足")
        try:
            return float(fields[3])
        except ValueError:
            raise ValueError("腾讯 fxUSDCNY 无有效价格")

    def _fetch_lof_price(self, fund_code: str):
        """LOF 基金实时价（与主看板"现价"同源）。

        - A 股盘中：走 market_data_service.get_realtime_quote（腾讯/新浪，与主看板现价同一入口）；
        - 盘后/休市/非交易日：回退到 unified_fund_history 最近官方收盘价（与主看板收盘口径一致）。
        返回 (price, source)：source ∈ {'realtime:腾讯'/'realtime:新浪'/'close'/None}。取不到返回 (None, None)。
        """
        price = None
        src = None
        if self.market_data_service:
            try:
                q = self.market_data_service.get_realtime_quote(fund_code)
                if q and q.get("price", 0) > 0:
                    price = float(q["price"])
                    src = "realtime:" + str(q.get("source", "mds"))
            except Exception as e:
                logger.debug(f"[{fund_code}] LOF 实时价获取失败(回退收盘): {e}")
        if price is None:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT price FROM unified_fund_history "
                    "WHERE fund_code=? AND price IS NOT NULL AND price>0 "
                    "ORDER BY date DESC LIMIT 1",
                    (fund_code,)).fetchone()
                if row:
                    price = float(row[0])
                    src = "close"
            finally:
                conn.close()
        return price, src

    @staticmethod
    def _ensure_freeze_table(conn) -> None:
        """确保本地 futures_freeze_prices 表存在（与 ARM cl_freeze_sampler 同结构）。"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS futures_freeze_prices (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT NOT NULL,
                point       TEXT NOT NULL,
                symbol      TEXT NOT NULL,
                price       REAL NOT NULL,
                src         TEXT NOT NULL DEFAULT 'sina',
                fetched_at  TEXT NOT NULL,
                UNIQUE(trade_date, point, symbol)
            )
            """
        )

    def _fallback_fill_missing_etf(self, conn) -> Dict[str, Any]:
        """同步后兜底：本地缺"最新已收盘交易日"收盘价的标的，直连源补抓一次。

        参考日 = 新浪 SPY 最新日（即新浪口径的美股最新已收盘交易日，独立于本地库，
        避免整库同步延迟时"库内最新日"自我参照漏判）。逐标的检查：
        - 该标的所在市场当日休市（is_market_holiday）→ 跳过，不算缺；
        - JP/CH 无自动化源 → 跳过（人工维护 + ⚠️标红口径）；
        - 缺价 → 按 _market_of 选源补抓参考日收盘价，成功即 INSERT OR REPLACE 落库。
        返回 {reference_date, filled:{sym:price}, still_missing:[sym]}，绝不抛异常。
        """
        result: Dict[str, Any] = {"reference_date": None, "filled": {}, "still_missing": []}
        try:
            spy = _sina_us_daily_closes("SPY")
            if not spy:
                result["error"] = "新浪SPY参考日获取失败"
                return result
            ref_date = max(spy)
            result["reference_date"] = ref_date
            symbols = [r[0] for r in conn.execute(
                "SELECT DISTINCT symbol FROM usa_etf_daily_prices ORDER BY symbol").fetchall()]
            tried: list = []
            for sym in symbols:
                # BRNG/BNQA 是 BRNT 的 GBP/EUR 份额别名：USD 价一致，按 BRNT(UK) 处理。
                sym_key = SYMBOL_ALIAS.get(sym, sym)
                # 跳过非美股命名的特殊代码（00700/0857.HK/^GLD-JP/sz159560 等）：
                # 美股源必失败，且不属美股日K管辖（HK/JP 已有映射的除外）
                if sym_key not in SYMBOL_MARKET and (
                        re.search(r"[.^]", sym_key) or sym_key.isdigit()
                        or re.match(r"^[a-z]{2}\d+$", sym_key)):
                    continue
                mkt = _market_of(sym_key)
                if mkt in ("JP", "CH"):
                    continue
                if is_market_holiday(sym_key, ref_date):
                    continue
                has = conn.execute(
                    "SELECT 1 FROM usa_etf_daily_prices WHERE symbol=? AND date=?",
                    (sym, ref_date)).fetchone()
                if has:
                    continue
                tried.append(sym)
                try:
                    if mkt == "UK":
                        closes = _tencent_daily_closes("uk" + sym_key)
                    elif mkt == "HK":
                        closes = _tencent_daily_closes("hk" + sym_key)
                    else:
                        closes = _sina_us_daily_closes(sym_key)
                except Exception:
                    closes = {}
                price = closes.get(ref_date)
                if price is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO usa_etf_daily_prices "
                        "(date, symbol, price, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (ref_date, sym, price))
                    result["filled"][sym] = price
            conn.commit()
            result["still_missing"] = [s for s in tried if s not in result["filled"]]
        except Exception as e:
            result["error"] = str(e)[:200]
        return result

    def sync_usa_etf_from_arm(self) -> Dict[str, Any]:
        """从 ARM 拉 usa_etf_daily_prices 全表到本地库（用户手动触发）。

        全表镜像：ARM 上 usa-etf-history.timer 每日增量累积（截至昨日北京时间），
        本地只在用户点按钮时把 ARM 整张表拉回，因此"停用 N 天后点一次"会补齐这 N 天
        （以及此前任何缺失）的全部历史，不存在 90 天窗口漏数据的问题。
        用 INSERT OR REPLACE 按 (date, symbol) 覆盖交集，本地更长历史的行不会被删。
        失败就地返回 dict，绝不抛异常。
        """
        import json
        import os
        import subprocess
        import tempfile

        remote_script = (
            "import sqlite3, json\n"
            "c = sqlite3.connect('/home/ubuntu/arbtest/database/arb_master.db')\n"
            "rows = c.execute(\"\"\"SELECT date, symbol, price, netvalue, updated_at "
            "FROM usa_etf_daily_prices ORDER BY symbol, date\"\"\").fetchall()\n"
            "print(json.dumps(rows))\n"
        )
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                f.write(remote_script)
                tmp = f.name
            cmd = 'ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no -o BatchMode=yes arm "python3 -"'
            proc = subprocess.run(cmd, shell=True, stdin=open(tmp, "r"),
                                  capture_output=True, text=True, timeout=60)
            if proc.returncode != 0:
                return {"status": "error",
                        "message": f"SSH 查询 ARM 失败: {(proc.stderr or proc.stdout).strip()[:300]}"}
            out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            rows = json.loads(out)
            if not rows:
                return {"status": "ok", "updated": 0,
                        "message": "ARM 无 usa_etf_daily_prices 数据"}

            conn = self._get_conn()
            try:
                self._ensure_usa_etf_table(conn)
                n = 0
                for r in rows:
                    date, symbol, price, netvalue, updated_at = r
                    conn.execute(
                        "INSERT OR REPLACE INTO usa_etf_daily_prices "
                        "(date, symbol, price, netvalue, updated_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (date, symbol, price, netvalue, updated_at),
                    )
                    n += 1
                conn.commit()
                # 防御：只保留 2026 年起（东哥 2026-09-12 拍板；ARM 表本就只含 2026+，此句防日后 ARM 出现脏老行回流）
                conn.execute("DELETE FROM usa_etf_daily_prices WHERE date < ?", ("2026-01-01",))
                conn.commit()
                # 兜底补抓：ARM 当天源延迟抓不全时，本地直连新浪/腾讯补一次（东哥 2026-09-15 提议）
                fallback = self._fallback_fill_missing_etf(conn)
                # 统计本地覆盖范围（仅取本地也关心的标的 + 总行数），供前端展示
                cur = conn.execute(
                    "SELECT COUNT(*), MIN(date), MAX(date) FROM usa_etf_daily_prices"
                )
                total, first, last = cur.fetchone()
            finally:
                conn.close()
            message = f"从 ARM 同步 {n} 条；本地现有 {total} 条（{first}~{last}）"
            if fallback.get("filled"):
                message += f"；本地补抓 {len(fallback['filled'])} 只（{fallback['reference_date']}）"
            if fallback.get("still_missing"):
                message += f"；⚠️仍缺 {fallback['reference_date']} 收盘: {','.join(fallback['still_missing'])}"
            if fallback.get("error"):
                message += f"；兜底补抓失败({fallback['error']})"
            return {"status": "ok", "updated": n,
                    "total": total,
                    "first": first,
                    "last": last,
                    "fallback": fallback,
                    "message": message}
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "SSH 超时（arm 不可达）"}
        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

    @staticmethod
    def _ensure_usa_etf_table(conn) -> None:
        """确保本地 usa_etf_daily_prices 表存在（与 ARM 同结构）。"""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usa_etf_daily_prices (
                date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price REAL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                netvalue REAL,
                PRIMARY KEY (date, symbol)
            )
            """
        )

    def sync_futures_freeze_from_arm(self) -> Dict[str, Any]:
        """从 ARM 拉 futures_freeze_prices 到本地库（每天上午盘前调一次即可）。

        复用 main.py 的 ssh arm 查询通道（仅拉此小表，不 scp 全库、不碰 ARM 部署）。
        失败就地返回 dict，绝不抛异常。
        """
        import json
        import os
        import subprocess
        import tempfile
        remote_script = (
            "import sqlite3, json\n"
            "c = sqlite3.connect('/home/ubuntu/arbtest/database/arb_master.db')\n"
            "rows = c.execute(\"SELECT trade_date, point, symbol, price, src, fetched_at "
            "FROM futures_freeze_prices ORDER BY trade_date, point, symbol\").fetchall()\n"
            "print(json.dumps(rows))\n"
        )
        tmp = None
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
                f.write(remote_script)
                tmp = f.name
            cmd = 'ssh -o ConnectTimeout=8 -o StrictHostKeyChecking=no -o BatchMode=yes arm "python3 -"'
            proc = subprocess.run(cmd, shell=True, stdin=open(tmp, "r"),
                                  capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                return {"status": "error",
                        "message": f"SSH 查询 ARM 失败: {(proc.stderr or proc.stdout).strip()[:300]}"}
            out = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
            rows = json.loads(out)
            if not rows:
                return {"status": "ok", "updated": 0,
                        "message": "ARM 无 futures_freeze_prices 数据"}

            conn = self._get_conn()
            try:
                self._ensure_freeze_table(conn)
                # ARM 已只保留最新一个 trade_date；本地同步前清空旧数据，保持一致
                conn.execute("DELETE FROM futures_freeze_prices")
                n = 0
                for r in rows:
                    conn.execute(
                        "INSERT INTO futures_freeze_prices "
                        "(trade_date, point, symbol, price, src, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        tuple(r),
                    )
                    n += 1
                conn.commit()
            finally:
                conn.close()
            return {"status": "ok", "updated": n, "message": f"同步 {n} 条"}
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "SSH 超时（arm 不可达）"}
        except Exception as e:
            return {"status": "error", "message": str(e)[:300]}
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass


def _rt_err(fund_code: str, code: str, **extra: Any) -> Dict[str, Any]:
    """Model B 统一错误返回。"""
    msg_map = {
        "no_report_holdings": "无季报持仓数据",
        "no_base_date": "无可用基准日期（今天之前无净值）",
        "no_base_nav": "基准日无净值",
        "no_period": "基准日无法路由报告期",
        "freeze_incomplete": "CL 三时点冻结价缺失",
        "cl_fetch_failed": "CL 实时价抓取失败",
        "fx_fetch_failed": "美元人民币实时价抓取失败",
    }
    return {
        "fund_code": fund_code,
        "status": "error",
        "code": code,
        "message": msg_map.get(code, code),
        **extra,
    }
