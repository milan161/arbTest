#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股/伦敦/港股 ETF 日 K 采样器（ARM 部署）。

功能：
- 每日收盘后增量抓取指定标的日 K 收盘价，写入 ARM 数据库
  `usa_etf_daily_prices(date, symbol, price, updated_at)`。
- 美股走新浪 US_MinKService.getDailyK；伦敦 ETC/港股走腾讯日 K。
- 瑞士 OILUSA（SIX 官方 CSV: CH0109967858USD4）/ 日股 1671·1699（雅虎日本: 1671.T / 1699.T）
  自 2026-09-26 起自动化抓取，替代原先手动补数；HoldingAnalysis 手喂表单保留为可选覆盖。

部署：
- systemd timer 每日北京时间 06:00 运行（美股收盘后、A股开盘前）。
- 日志：/home/ubuntu/arbtest/logs/usa_etf_history_sampler.log

手动测试：
    python3 usa_etf_history_sampler.py --dry-run
    python3 usa_etf_history_sampler.py --symbol USO --days 5
"""

import argparse
import csv
import io
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta

# ---------- 配置 ----------
DEFAULT_DB = "/home/ubuntu/arbtest/database/arb_master.db"
LOG_DIR = "/home/ubuntu/arbtest/logs"
LOG_FILE = os.path.join(LOG_DIR, "usa_etf_history_sampler.log")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 标的配置：symbol -> (source, remote_code)
# source: "sina"=新浪美股日K, "tx"=腾讯日K
SOURCES = {
    # 原油 LOF 直接持仓
    "CRUD": ("tx", "ukCRUD"),
    "BRNT": ("tx", "ukBRNT"),
    "USO": ("sina", "USO"),
    "OILK": ("sina", "OILK"),
    "BNO": ("sina", "BNO"),
    "DBO": ("sina", "DBO"),
    "03175": ("tx", "hk03175"),
    # 常用 QDII / 对冲标的
    "XOP": ("sina", "XOP"),
    "GLD": ("sina", "GLD"),
    "SLV": ("sina", "SLV"),
    "INDA": ("sina", "INDA"),
    "QQQ": ("sina", "QQQ"),
    "SPY": ("sina", "SPY"),
    "XBI": ("sina", "XBI"),
    "VGT": ("sina", "VGT"),
    "XLE": ("sina", "XLE"),
    "XLY": ("sina", "XLY"),
    "KWEB": ("sina", "KWEB"),
    # 瑞士/日本上市（SIX 官方 CSV / 雅虎日本，2026-09-26 接入，替代手动补）
    "OILUSA": ("six", "CH0109967858USD4"),
    "1671": ("jp", "1671.T"),
    "1699": ("jp", "1699.T"),
}

# 无稳定自动化源的标的（日志提示用）。OILUSA/1671/1699 自 2026-09-26 已由 SIX/雅虎日本自动抓取，移出。
UNSUPPORTED = set()

N_DAYS_DEFAULT = 800


# ---------- 日志 ----------
def _setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("usa_etf_sampler")


# ---------- 网络 ----------
def _http_get(url, enc="utf-8", referer=None, timeout=25, retry=3):
    last = None
    for i in range(retry):
        try:
            h = {"User-Agent": UA}
            if referer:
                h["Referer"] = referer
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode(enc, "ignore")
        except Exception as e:
            last = e
            if i < retry - 1:
                time.sleep(1.5 * (i + 1))
    raise last


# ---------- SIX / 雅虎日本 新增源（2026-09-26 接入，替代手动补 OILUSA/1671/1699） ----------

def _to_num(s):
    """'6,050' / '73.91' / '-' -> float|None。"""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).replace(",", "").replace("+", "").strip()
    if not t or t in {"-", "--", "－"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _http_get_bytes(url, timeout=25, retry=3):
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < retry - 1:
                time.sleep(1.5 * (i + 1))
    raise last


def fetch_six(sid, n=N_DAYS_DEFAULT):
    """SIX 瑞士交易所官方 CSV（OILUSA = CH0109967858USD4）。

    零依赖、免 UA/Cookie/代理；裸请求即 200。CSV 四坑：
    UTF-8-BOM / 分号分隔 / 前两行元数据 / 日期 dd.mm.yyyy 且倒序。
    返回 {YYYY-MM-DD: close}。
    """
    url = "https://www.six-group.com/sheldon/market_data/v1/%s/historic.csv" % sid
    raw = _http_get_bytes(url)
    text = raw.decode("utf-8-sig")
    lines = text.splitlines()
    hdr = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("date;")), None)
    if hdr is None:
        raise ValueError("SIX CSV 未找到表头行: %r" % text[:200])
    header = [h.strip().lower() for h in lines[hdr].split(";")]
    price_col = header.index("price") if "price" in header else 1
    out = {}
    for parts in csv.reader(io.StringIO("\n".join(lines[hdr + 1:])), delimiter=";"):
        if len(parts) < 2 or not parts[0].strip():
            continue
        try:
            d = datetime.strptime(parts[0].strip(), "%d.%m.%Y").strftime("%Y-%m-%d")
        except ValueError:
            continue
        p = _to_num(parts[price_col]) if price_col < len(parts) else None
        if p is not None:
            out[d] = p
    return out


def _rsc_payload(html):
    """把 Next.js 的 RSC 分片（JS 字符串字面量）拼回完整载荷。"""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    return "".join(json.loads(c) for c in chunks if c)


def _extract_balanced(text, key, open_ch="{"):
    """抠出 "key":{...} / "key":[...] 完整结构（括号配平，跳过字符串内括号）。"""
    close_ch = "}" if open_ch == "{" else "]"
    idx = text.find('"%s":' % key)
    if idx < 0:
        return None
    start = text.find(open_ch, idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == open_ch:
                depth += 1
            elif ch == close_ch:
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def fetch_yahoo_jp(code, n=N_DAYS_DEFAULT):
    """雅虎日本历史页（Next.js RSC 载荷）。返回 {YYYY-MM-DD: close}。

    国内网络 finance.yahoo.co.jp 可达；values 顺序：开/高/低/收/量/调整后收。
    """
    url = "https://finance.yahoo.co.jp/quote/%s/history" % code
    html = _http_get(url, referer="https://finance.yahoo.co.jp/")
    payload = _rsc_payload(html)
    if not payload:
        raise ValueError("雅虎日本页面无 RSC 载荷（结构可能变化）")
    arr_txt = _extract_balanced(payload, "histories", "[")
    if not arr_txt:
        raise ValueError("载荷中未找到 histories 数组")
    arr = json.loads(arr_txt.replace("$undefined", "null"))
    out = {}
    for item in arr:
        d = item.get("date")
        vals = [_to_num(v.get("value")) for v in item.get("values", [])]
        if d and len(vals) >= 4 and vals[3] is not None:
            out[d] = vals[3]
    return out


# ---------- 行情源 ----------
def fetch_tx(code, kind="us", n=N_DAYS_DEFAULT):
    """腾讯日K。伦敦 ukXXX、港股 hkXXXX 可用；美股 usXXX 只给最近1天，不要用它取历史。"""
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/%sfqkline/get"
        "?param=%s,day,,,%d,qfq" % (kind, code, n)
    )
    j = json.loads(_http_get(url, referer="https://gu.qq.com/"))
    data = j.get("data", {}).get(code)
    if not data:
        return {}
    k = data.get("qfqday") or data.get("day")
    if not k:
        return {}
    return {x[0]: float(x[2]) for x in k}  # [date, open, close, high, low, ...]


def fetch_sina(sym, n=N_DAYS_DEFAULT):
    """新浪美股日K。当前唯一能拿到美股长历史的免费源。"""
    url = (
        "https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_/"
        "US_MinKService.getDailyK?symbol=" + sym + "&___qn=3"
    )
    t = _http_get(url, referer="https://finance.sina.com.cn")
    i = t.find("(")
    if i < 0:
        raise ValueError("新浪返回格式异常")
    arr = json.loads(t[i + 1 : t.rfind(")")])
    out = {x["d"]: float(x["c"]) for x in arr}
    return {k: out[k] for k in sorted(out)[-n:]}


def fetch_symbol(symbol, n=N_DAYS_DEFAULT):
    src, code = SOURCES[symbol]
    if src == "tx":
        # 腾讯接口：美股/伦敦统一走 usfqkline，港股单独走 hkfqkline
        kind = "hk" if code.startswith("hk") else "us"
        return fetch_tx(code, kind=kind, n=n)
    if src == "sina":
        return fetch_sina(code, n=n)
    if src == "six":
        return fetch_six(code, n=n)
    if src == "jp":
        return fetch_yahoo_jp(code, n=n)
    raise ValueError(f"未知 source: {src}")


# ---------- 数据库 ----------
def ensure_table(conn):
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


def get_last_date(conn, symbol):
    row = conn.execute(
        "SELECT MAX(date) FROM usa_etf_daily_prices WHERE symbol=?", (symbol,)
    ).fetchone()
    return row[0] if row and row[0] else None


def write_symbol(conn, symbol, prices):
    """写入某 symbol 的价格序列；用 INSERT OR REPLACE 覆盖同日主键。"""
    if not prices:
        return 0
    ensure_table(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    n = 0
    for dt in sorted(prices):
        conn.execute(
            "INSERT OR REPLACE INTO usa_etf_daily_prices (date, symbol, price, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (dt, symbol, prices[dt], now),
        )
        n += 1
    return n


# ---------- 交易日推断 ----------
def yesterday_beijing():
    """北京时间昨日（UTC+8）。美股收盘对应北京时间次日 04:00-05:00，所以取昨天稳妥。"""
    return (datetime.utcnow() + timedelta(hours=8) - timedelta(days=1)).strftime("%Y-%m-%d")


# ---------- 主流程 ----------
def run(db_path, symbols=None, days=None, dry_run=False, force_start=None, force_end=None):
    log = _setup_logging()
    symbols = list(symbols or SOURCES.keys())
    log.info("开始抓取: symbols=%s db=%s dry_run=%s", symbols, db_path, dry_run)

    conn = sqlite3.connect(db_path)
    try:
        ensure_table(conn)
        stats = []
        overall_new = 0
        end_date = force_end or yesterday_beijing()
        n_days = days or N_DAYS_DEFAULT

        for symbol in symbols:
            if symbol not in SOURCES:
                if symbol in UNSUPPORTED:
                    log.info("跳过无自动化源: %s", symbol)
                else:
                    log.warning("未知 symbol: %s", symbol)
                stats.append({"symbol": symbol, "status": "skipped", "reason": "unsupported/unknown"})
                continue

            try:
                last = get_last_date(conn, symbol)
                # 起点：
                # - 如果库里有数据，从 last_date 往前多抓几天覆盖可能的修正，同时往后抓到 end_date
                # - 如果库里没有，抓最近 n_days 天
                # 简化：全量抓最近 n_days，然后按 date <= end_date 写入；避免日期边界复杂判断
                prices = fetch_symbol(symbol, n=n_days)
                # 过滤掉未来日期和超过 end_date 的盘中数据
                prices = {d: p for d, p in prices.items() if d <= end_date}

                if dry_run:
                    ks = sorted(prices)
                    stats.append({
                        "symbol": symbol,
                        "status": "dry_run",
                        "count": len(prices),
                        "first": ks[0] if ks else None,
                        "last": ks[-1] if ks else None,
                        "last_price": prices[ks[-1]] if ks else None,
                        "local_last": last,
                    })
                    log.info("[dry-run] %s: 远程 %d 条 (%s ~ %s), 本地末条 %s",
                             symbol, len(prices),
                             ks[0] if ks else "-", ks[-1] if ks else "-", last or "无")
                    continue

                if prices:
                    # 为防残留，删除 [min_date, max_date] 区间旧值后再写入
                    ks = sorted(prices)
                    conn.execute(
                        "DELETE FROM usa_etf_daily_prices WHERE symbol=? AND date>=? AND date<=?",
                        (symbol, ks[0], ks[-1]),
                    )
                    n = write_symbol(conn, symbol, prices)
                    conn.commit()
                    overall_new += n
                    stats.append({
                        "symbol": symbol,
                        "status": "ok",
                        "count": n,
                        "first": ks[0],
                        "last": ks[-1],
                        "last_price": prices[ks[-1]],
                        "local_last": last,
                    })
                    log.info("%s: 写入 %d 条 (%s ~ %s), 本地末条 %s",
                             symbol, n, ks[0], ks[-1], last or "无")
                else:
                    stats.append({
                        "symbol": symbol,
                        "status": "empty",
                        "count": 0,
                        "local_last": last,
                    })
                    log.warning("%s: 未获取到价格", symbol)
            except Exception as e:
                log.error("%s: 抓取失败 %s", symbol, str(e)[:200])
                stats.append({"symbol": symbol, "status": "error", "message": str(e)[:200]})

        summary = {
            "status": "ok",
            "db": db_path,
            "end_date": end_date,
            "dry_run": dry_run,
            "overall_new": overall_new,
            "symbols": stats,
        }
        log.info("完成: %s", json.dumps(summary, ensure_ascii=False))
        return summary
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="美股/伦敦/港股 ETF 日 K 采样器（ARM）")
    ap.add_argument("--db", default=DEFAULT_DB, help="目标 sqlite 路径")
    ap.add_argument("--symbol", action="append", help="只抓取指定 symbol（可多次）")
    ap.add_argument("--days", type=int, default=N_DAYS_DEFAULT, help="抓取最近 N 天")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    ap.add_argument("--end-date", help="截止日期 yyyy-mm-dd（默认昨日北京时间）")
    args = ap.parse_args()

    result = run(
        args.db,
        symbols=args.symbol,
        days=args.days,
        dry_run=args.dry_run,
        force_end=args.end_date,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
