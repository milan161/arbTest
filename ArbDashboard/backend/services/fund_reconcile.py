# -*- coding: utf-8 -*-
"""[AI-2026-08-04] 单基金「核对静态估值」。

替代 Data.vue 已移除的全局「重算静态估值」：按基金粒度补采历史 + 重算，不全量打补丁。
逻辑：
  1) 补采该 LOF 近 N 个交易日的价格(腾讯日K) + 净值(东财) -> unified_fund_history
  2) 级联补采估值篮子底层 ETF(如 VGT) 日价 -> usa_etf_daily_prices（否则 static_val 算不出）
  3) 重算 static_val 前，先补该基金 related_index 的指数历史 -> index_history（否则缺指数时 static_val 仍算不出，按钮"点了没用"）
  4) 重算 static_val（复用 StaticValuationCalculator.process_fund，天然单基金，固定重算最近40行）
  5) 顺带补溢价率（按 category 分支：QDII欧美/黄金原油=T价/T-1净值，其余=T价/T净值）
"""
import os
from datetime import date, timedelta
import yaml

from arbcore.database.db_manager import DatabaseManager
from arbcore.fetchers.historical import HistoricalDataManager
from arbcore.fetchers.historical.tencent import TencentHistoricalFetcher
from arbcore.calculators.static_valuation import StaticValuationCalculator
from arbcore.utils.market_calendar import is_trading_day

_CFG_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'arbcore', 'config', 'lof_config.yaml'))


def recent_trading_days(n, exchange, end=None):
    """自建：全库无此 helper；基于 is_trading_day 倒序生成近 N 个交易日（升序返回）。"""
    d = end or date.today()
    out = []
    while len(out) < n:
        if is_trading_day(exchange, d):
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def reconcile_fund_static_val(fund_code: str, days: int = 10) -> dict:
    db = DatabaseManager()
    hist = HistoricalDataManager(db_manager=db)

    # 0. 取该基金 YAML 配置（process_fund 需要整个 dict，不是 code）
    with open(_CFG_PATH, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    fund = next((x for x in cfg.get('funds', []) if str(x.get('code')) == fund_code), None)
    if not fund:
        return {"ok": False, "error": f"fund {fund_code} 不在 lof_config.yaml 的 funds 列表"}

    a_days = recent_trading_days(days, 'A_SHARE')
    start_a = a_days[0].strftime('%Y-%m-%d')
    us_start = recent_trading_days(days + 3, 'NYSE')[0].strftime('%Y-%m-%d')  # 多留 buffer 防时差
    stats = {"lof_price": 0, "lof_nav": 0, "etf": {}, "premium_updated": 0}

    # 1. LOF 价格（腾讯日K，带成交量）
    tx = ('sz' if fund_code.startswith(('0', '1', '3')) else 'sh') + fund_code
    try:
        px = TencentHistoricalFetcher().fetch_prices(tx, start_date=start_a)
        for _, r in px.iterrows():
            ds = r['date'].strftime('%Y-%m-%d')
            db.save_unified_history(date_str=ds, fund_code=fund_code,
                                   price=float(r['close']),
                                   trade_volume=float(r.get('volume_hands') or 0))
            stats["lof_price"] += 1
    except Exception as e:
        stats["price_err"] = str(e)

    # 2. LOF 净值（东财）
    try:
        nav_df = hist.get_nav(fund_code, source='eastmoney', start_date=start_a)
        for _, r in nav_df.iterrows():
            ds = r['date'].strftime('%Y-%m-%d')
            db.save_unified_history(date_str=ds, fund_code=fund_code,
                                   nav=float(r['nav']), nav_date=ds)
            stats["lof_nav"] += 1
    except Exception as e:
        stats["nav_err"] = str(e)

    # 3. 级联底层 ETF（VGT 等）日价 -> usa_etf_daily_prices（static_val 依赖它）
    for item in (fund.get('valuation_portfolio') or fund.get('hedging_portfolio') or []):
        sym = str(item.get('symbol')).lstrip('^')
        try:
            edf = hist.get_prices(sym, source='sina', start_date=us_start)
            cnt = 0
            for _, r in edf.iterrows():
                c = r.get('close')
                if c is None or c <= 0:
                    continue
                db.upsert_usa_etf_price(date=r['date'].strftime('%Y-%m-%d'),
                                       symbol=sym, price=float(c))
                cnt += 1
            stats["etf"][sym] = cnt
        except Exception as e:
            stats["etf"][sym] = f"err: {e}"

    # 3.5 [AI-2026-08-05] 单基金指数历史补采（让"核对静态估值"按钮真正能补指数：
    #     此前只补价/净值/ETF，缺指数时 static_val 仍算不出 → 按钮"点了没用"）。
    #     只补该基金 related_index，不进每日流水线（每日自动补采已被东哥否决）。
    try:
        from services.index_repair_service import repair_fund_index_history
        idx_res = repair_fund_index_history(fund_code, days_back=days + 5)
        stats["index_backfill"] = idx_res
    except Exception as e:
        stats["index_backfill_err"] = str(e)

    # 4. 重算 static_val（天然单基金，固定重算最近 40 行，覆盖近 N 日绰绰有余）
    try:
        ok = StaticValuationCalculator(db).process_fund(fund)
        stats["static_val_ok"] = bool(ok)
    except Exception as e:
        stats["static_val_ok"] = False
        stats["static_val_err"] = str(e)

    # 5. [AI-2026-08-05] 顺带补溢价率（东哥铁律口径，曾误用统一 T-1，见 AGENTS.md TOP 2）：
    #    QDII欧美/黄金原油（跟美股，有时差）→ T价 / T-1净值
    #    QDII亚洲/QDII日本/国内LOF（无时差）→ T价 / T净值（同日）；同日净值缺失则退回 T-1
    cat = (fund.get('category') or '').strip()
    use_t1 = cat in ('QDII欧美', '黄金原油')
    try:
        conn = db._get_conn()
        for d in a_days:
            ds = d.strftime('%Y-%m-%d')
            row = conn.execute(
                "SELECT price, nav FROM unified_fund_history WHERE date=? AND fund_code=?",
                (ds, fund_code)).fetchone()
            if not row or row[0] is None:
                continue
            price = float(row[0])
            same_nav = row[1]
            denom = None
            if use_t1:
                t1 = conn.execute(
                    "SELECT nav FROM unified_fund_history WHERE fund_code=? AND date<? AND nav IS NOT NULL ORDER BY date DESC LIMIT 1",
                    (fund_code, ds)).fetchone()
                if t1 and t1[0]:
                    denom = float(t1[0])
            else:
                if same_nav and float(same_nav) > 0:
                    denom = float(same_nav)
                else:
                    t1 = conn.execute(
                        "SELECT nav FROM unified_fund_history WHERE fund_code=? AND date<? AND nav IS NOT NULL ORDER BY date DESC LIMIT 1",
                        (fund_code, ds)).fetchone()
                    if t1 and t1[0]:
                        denom = float(t1[0])
            if denom and denom > 0:
                prem = (price - denom) / denom * 100
                conn.execute(
                    "UPDATE unified_fund_history SET premium=? WHERE date=? AND fund_code=?",
                    (round(prem, 4), ds, fund_code))
                stats["premium_updated"] += 1
        conn.commit()
    except Exception as e:
        stats["premium_err"] = str(e)

    return {"ok": True, "fund_code": fund_code, "days": len(a_days), "stats": stats}
