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
import sqlite3
from typing import Dict, Any, List, Optional


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
            if nav is not None:
                realtime_nav = nav * (1.0 + total_contribution)

            return {
                "fund_code": fund_code,
                "report_period": report_period,
                "report_date": report_date,
                "report_nav": nav,
                "realtime_nav": realtime_nav,
                "total_change_pct": total_contribution,
                "valid_weight_sum": valid_weight_sum,
                "components": components,
            }
        finally:
            conn.close()
