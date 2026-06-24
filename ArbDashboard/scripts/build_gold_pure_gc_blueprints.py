from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(r"D:\Study\codexTest\CodexLOFarb")
PROC_DIR = ROOT / r"data\analysis_outputs_20260329\procedure fiels"
MAIN_DIR = ROOT / r"data\analysis_outputs_20260329"

GOLD_FUNDS = {
    "160719": "\u5609\u5b9e\u9ec4\u91d1",
    "161116": "\u6613\u65b9\u8fbe\u9ec4\u91d1\u4e3b\u9898",
    "164701": "\u6c47\u6dfb\u5bcc\u8d35\u91d1\u5c5e",
    "165513": "\u4e2d\u4fe1\u4fdd\u8bda\u5546\u54c1\u4e3b\u9898",
}

FORWARD_SUMMARY_PATH = PROC_DIR / "pure_futures_forward_summary.csv"
OUT_SUMMARY_CSV = MAIN_DIR / "\u0030\u0030_\u9ec4\u91d1\u7ec4\u7eafGC\u524d\u5411\u56de\u6d4b\u603b\u8868.csv"
OUT_SUMMARY_MD = MAIN_DIR / "\u9ec4\u91d1\u7ec4_\u7eafGC\u4f30\u503c\u9aa8\u67b6\u8bf4\u660e.md"


def cn(text: str) -> str:
    return text.encode("utf-8").decode("unicode_escape")


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_percent(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.2%}"


def to_num(value: float | None, digits: int = 4) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> bool:
    try:
        write_csv(path, rows, fieldnames)
        return True
    except PermissionError:
        return False


def build_per_fund_file(fund_code: str, fund_name: str) -> dict[str, str]:
    method_path = PROC_DIR / f"method_compare_{fund_code}.csv"
    forward_path = PROC_DIR / f"pure_futures_forward_{fund_code}.csv"
    sample_label = cn(r"\u7eafGC\u4f30\u503c\u6837\u677f")
    out_csv = MAIN_DIR / f"{fund_code}_{sample_label}.csv"

    method_rows = read_csv(method_path)
    forward_rows = read_csv(forward_path)
    method_map = {row["date"]: row for row in method_rows}
    forward_map = {row["trade_date"]: row for row in forward_rows}

    out_rows: list[dict[str, str]] = []

    for trade_date in sorted(method_map.keys(), reverse=True):
        row = method_map[trade_date]
        forward = forward_map.get(trade_date, {})
        base_date = row.get("nav_asof_date", "")
        base_row = method_map.get(base_date, {})

        known_nav = to_float(row.get("nav"))
        position = to_float(row.get("position_used"))
        future_close = to_float(row.get("future_close"))
        rmb_mid = to_float(row.get("rmb_mid"))
        base_future = to_float(base_row.get("future_close"))
        base_rmb = to_float(base_row.get("rmb_mid"))
        static_beta = to_float(forward.get("static_beta"))
        rolling_beta = to_float(forward.get("rolling_beta"))
        target_nav = to_float(forward.get("target_nav_trade_date"))
        price = to_float(row.get("price"))

        gc_cny_ratio = None
        gc_cny_return = None
        cash_anchor = None
        risk_anchor = None
        pure_gc_new_leg = None
        static_est = None
        rolling_est = None
        static_err = None
        rolling_err = None
        static_premium = None
        rolling_premium = None

        if (
            known_nav is not None
            and position is not None
            and future_close is not None
            and rmb_mid is not None
            and base_future is not None
            and base_rmb is not None
            and base_future > 0
            and base_rmb > 0
        ):
            gc_cny_ratio = (future_close * rmb_mid) / (base_future * base_rmb)
            gc_cny_return = gc_cny_ratio - 1.0
            cash_anchor = known_nav * (1.0 - position)
            risk_anchor = known_nav * position
            pure_gc_new_leg = known_nav * gc_cny_ratio

            if static_beta is not None:
                static_est = cash_anchor + risk_anchor * (1.0 + static_beta * gc_cny_return)
            if rolling_beta is not None:
                rolling_est = cash_anchor + risk_anchor * (1.0 + rolling_beta * gc_cny_return)

        if target_nav and target_nav > 0:
            if static_est is not None:
                static_err = (static_est - target_nav) / target_nav
            if rolling_est is not None:
                rolling_err = (rolling_est - target_nav) / target_nav

        if price and price > 0:
            if static_est and static_est > 0:
                static_premium = (price - static_est) / static_est
            if rolling_est and rolling_est > 0:
                rolling_premium = (price - rolling_est) / rolling_est

        out_rows.append(
            {
                cn(r"\u57fa\u91d1\u4ee3\u7801"): fund_code,
                cn(r"\u57fa\u91d1\u540d\u79f0"): fund_name,
                cn(r"\u4ea4\u6613\u65e5\u671f"): trade_date,
                cn(r"\u51c0\u503c\u5b9e\u9645\u5f52\u5c5e\u65e5"): base_date,
                cn(r"\u5df2\u77e5\u51c0\u503c\u951a\u70b9"): to_num(known_nav, 4),
                cn(r"T\u65e5\u771f\u5b9e\u51c0\u503c_\u6b21\u65e5\u516c\u5e03"): to_num(target_nav, 4),
                cn(r"\u4ef7\u683c"): to_num(price, 3),
                cn(r"\u4f7f\u7528\u4ed3\u4f4d"): to_num(position, 4),
                cn(r"GC\u5f53\u65e5\u6536\u76d8\u4ef7"): to_num(future_close, 1),
                cn(r"GC\u951a\u70b9\u6536\u76d8\u4ef7"): to_num(base_future, 1),
                cn(r"\u4eba\u6c11\u5e01\u4e2d\u95f4\u4ef7"): to_num(rmb_mid, 4),
                cn(r"\u951a\u70b9\u4eba\u6c11\u5e01\u4e2d\u95f4\u4ef7"): to_num(base_rmb, 4),
                cn(r"GCx\u4eba\u6c11\u5e01\u53d8\u5316\u500d\u6570"): to_num(gc_cny_ratio, 6),
                cn(r"GCx\u4eba\u6c11\u5e01\u6da8\u8dcc\u5e45"): to_percent(gc_cny_return),
                cn(r"\u73b0\u91d1\u817f\u951a\u70b9"): to_num(cash_anchor, 4),
                cn(r"\u98ce\u9669\u817f\u951a\u70b9"): to_num(risk_anchor, 4),
                cn(r"\u7eafGC\u672a\u8c03\u4ed3\u98ce\u9669\u817f\u4f30\u503c"): to_num(pure_gc_new_leg, 4),
                cn(r"\u7eafGC\u9759\u6001Beta"): to_num(static_beta, 4),
                cn(r"\u7eafGC\u6eda\u52a8Beta"): to_num(rolling_beta, 4),
                cn(r"\u7eafGC\u9759\u6001\u4f30\u503c"): to_num(static_est, 4),
                cn(r"\u7eafGC\u6eda\u52a8\u4f30\u503c"): to_num(rolling_est, 4),
                cn(r"\u7eafGC\u9759\u6001\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"): to_percent(static_err),
                cn(r"\u7eafGC\u6eda\u52a8\u8bef\u5dee_\u6b21\u65e5\u9a8c\u8bc1"): to_percent(rolling_err),
                cn(r"\u7eafGC\u9759\u6001\u6ea2\u4ef7"): to_percent(static_premium),
                cn(r"\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"): to_percent(rolling_premium),
                cn(r"woody\u5b98\u65b9\u4f30\u503c"): row.get("official_est", ""),
                cn(r"\u671f\u8d27\u6821\u51c6ETF\u4f30\u503c"): row.get("calibrated_est", ""),
                cn(r"\u65e7\u7248\u76f4\u63a5\u671f\u8d27\u4f30\u503c"): row.get("direct_est", ""),
            }
        )

    wrote_ok = safe_write_csv(out_csv, out_rows, list(out_rows[0].keys()))
    latest = out_rows[0]
    return {
        "fund_code": fund_code,
        "fund_name": fund_name,
        "latest_trade_date": latest[cn(r"\u4ea4\u6613\u65e5\u671f")],
        "latest_nav_anchor": latest[cn(r"\u5df2\u77e5\u51c0\u503c\u951a\u70b9")],
        "latest_price": latest[cn(r"\u4ef7\u683c")],
        "latest_position": latest[cn(r"\u4f7f\u7528\u4ed3\u4f4d")],
        "latest_static_est": latest[cn(r"\u7eafGC\u9759\u6001\u4f30\u503c")],
        "latest_rolling_est": latest[cn(r"\u7eafGC\u6eda\u52a8\u4f30\u503c")],
        "latest_static_premium": latest[cn(r"\u7eafGC\u9759\u6001\u6ea2\u4ef7")],
        "latest_rolling_premium": latest[cn(r"\u7eafGC\u6eda\u52a8\u6ea2\u4ef7")],
        "sample_file": str(out_csv),
        "write_status": cn(r"\u662f") if wrote_ok else cn(r"\u5426(\u6587\u4ef6\u5360\u7528\uff0c\u4fdd\u7559\u539f\u6587\u4ef6)"),
    }


def main() -> None:
    forward_summary_rows = read_csv(FORWARD_SUMMARY_PATH)
    metrics_map: dict[tuple[str, str], dict[str, str]] = {}
    for row in forward_summary_rows:
        metrics_map[(row["fund_code"], row["method"])] = row

    latest_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []

    for fund_code, fund_name in GOLD_FUNDS.items():
        latest_info = build_per_fund_file(fund_code, fund_name)
        latest_rows.append(latest_info)

        static_row = metrics_map[(fund_code, "static_beta_forward")]
        rolling_row = metrics_map[(fund_code, "rolling_beta_forward")]

        summary_rows.append(
            {
                cn(r"\u57fa\u91d1\u4ee3\u7801"): fund_code,
                cn(r"\u57fa\u91d1\u540d\u79f0"): fund_name,
                cn(r"\u6837\u672c\u6570"): static_row["sample_count"],
                cn(r"\u9759\u6001Beta_MAE"): static_row["mae_abs_error_pct"],
                cn(r"\u6eda\u52a8Beta_MAE"): rolling_row["mae_abs_error_pct"],
                cn(r"\u9759\u6001Beta_RMSE"): static_row["rmse_error_pct"],
                cn(r"\u6eda\u52a8Beta_RMSE"): rolling_row["rmse_error_pct"],
                cn(r"\u9759\u6001Beta_\u4f30\u503c\u6298\u4ef7\u4fe1\u53f7\u5929\u6570"): static_row["est_discount_signals"],
                cn(r"\u6eda\u52a8Beta_\u4f30\u503c\u6298\u4ef7\u4fe1\u53f7\u5929\u6570"): rolling_row["est_discount_signals"],
                cn(r"\u5b9e\u9645\u6298\u4ef7\u5929\u6570"): static_row["actual_discount_days"],
                cn(r"\u9759\u6001Beta_\u67e5\u51c6\u7387"): static_row["precision"],
                cn(r"\u6eda\u52a8Beta_\u67e5\u51c6\u7387"): rolling_row["precision"],
                cn(r"\u9759\u6001Beta_\u67e5\u5168\u7387"): static_row["recall"],
                cn(r"\u6eda\u52a8Beta_\u67e5\u5168\u7387"): rolling_row["recall"],
                cn(r"\u6700\u65b0\u4ea4\u6613\u65e5\u671f"): latest_info["latest_trade_date"],
                cn(r"\u6700\u65b0\u7eafGC\u9759\u6001\u4f30\u503c"): latest_info["latest_static_est"],
                cn(r"\u6700\u65b0\u7eafGC\u6eda\u52a8\u4f30\u503c"): latest_info["latest_rolling_est"],
                cn(r"\u6700\u65b0\u7eafGC\u9759\u6001\u6ea2\u4ef7"): latest_info["latest_static_premium"],
                cn(r"\u6700\u65b0\u7eafGC\u6eda\u52a8\u6ea2\u4ef7"): latest_info["latest_rolling_premium"],
                cn(r"\u6837\u677f\u6587\u4ef6\u5199\u5165\u6210\u529f"): latest_info["write_status"],
                cn(r"\u6837\u677f\u6587\u4ef6"): latest_info["sample_file"],
            }
        )

    write_csv(OUT_SUMMARY_CSV, summary_rows, list(summary_rows[0].keys()))

    rolling_mae_key = cn(r"\u6eda\u52a8Beta_MAE")
    fund_code_key = cn(r"\u57fa\u91d1\u4ee3\u7801")
    fund_name_key = cn(r"\u57fa\u91d1\u540d\u79f0")
    best_intro = cn(r"\u6eda\u52a8Beta\u91cc\u5f53\u524d\u8bef\u5dee\u6700\u5c0f\u7684\u662f")
    mae_intro = cn(r"\uff0cMAE =")

    best_mae_row = min(summary_rows, key=lambda row: float(row[rolling_mae_key].strip("%")))

    lines = [
        cn(r"# \u9ec4\u91d1\u7ec4\u7eafGC\u4f30\u503c\u9aa8\u67b6\u8bf4\u660e"),
        "",
        cn(r"\u8fd9\u4efd\u603b\u8868\u5bf9\u5e94\u6587\u4ef6\uff1a"),
        f"- `{OUT_SUMMARY_CSV}`",
        "",
        cn(r"\u5355\u57fa\u91d1\u6837\u677f\u6587\u4ef6\uff1a"),
    ]
    for row in latest_rows:
        lines.append(f"- `{row['sample_file']}`")

    lines.extend(
        [
            "",
            cn(r"## \u901a\u7528\u9aa8\u67b6"),
            "",
            cn(r"\u56db\u53ea\u9ec4\u91d1\u57fa\u91d1\u76ee\u524d\u7edf\u4e00\u6309\u4e0b\u9762\u8fd9\u6761\u9aa8\u67b6\u5c55\u5f00\uff1a"),
            "",
            "```text",
            "GC\u4eba\u6c11\u5e01\u53d8\u5316\u500d\u6570 = (GC_t x RMB_t) / (GC_0 x RMB_0)",
            "\u7eafGC\u4f30\u503c = NAV0 x (1 - \u4ed3\u4f4d) + NAV0 x \u4ed3\u4f4d x (1 + Beta x (GC\u4eba\u6c11\u5e01\u53d8\u5316\u500d\u6570 - 1))",
            "```",
            "",
            cn(r"\u8fd9\u6761\u516c\u5f0f\u4fdd\u7559\u4e86 woody \u7684\u4e09\u4e2a\u6838\u5fc3\u601d\u60f3\uff1a"),
            cn(r"- \u4ee5\u6700\u8fd1\u53ef\u4fe1\u51c0\u503c\u4e3a\u951a\u70b9"),
            cn(r"- \u4fdd\u7559\u73b0\u91d1\u4ed3\u4f4d\uff0c\u4e0d\u628a\u57fa\u91d1\u5f53\u6210 100% \u6ee1\u4ed3"),
            cn(r"- \u98ce\u9669\u817f\u53ea\u8ba9 GC\u00d7\u4eba\u6c11\u5e01 \u8fd9\u4e00\u4e2a\u56e0\u5b50\u53bb\u9a71\u52a8"),
            "",
            cn(r"## \u5f53\u524d\u7ed3\u8bba"),
            "",
            f"- {best_intro} {best_mae_row[fund_code_key]} {best_mae_row[fund_name_key]}{mae_intro} {best_mae_row[rolling_mae_key]}",
            cn(r"- \u5bf9\u9ec4\u91d1\u7ec4\u6765\u8bf4\uff0c\u7eafGC\u9aa8\u67b6\u6574\u4f53\u662f\u80fd\u5de5\u4f5c\u7684\uff0c\u8bef\u5dee\u663e\u8457\u4f4e\u4e8e\u539f\u6cb9\u7ec4"),
            cn(r"- \u9759\u6001Beta\u548c\u6eda\u52a8Beta\u5dee\u8ddd\u4e0d\u5927\uff0c\u8bf4\u660e\u9ec4\u91d1\u7ec4\u5f53\u524d\u66f4\u50cf\u201c\u7a33\u5b9a\u5355\u56e0\u5b50\u201d\u800c\u4e0d\u662f\u9891\u7e41\u6f02\u79fb\u7684\u591a\u56e0\u5b50"),
            "",
            cn(r"## \u4e0b\u4e00\u6b65\u5efa\u8bae"),
            "",
            cn(r"- \u5982\u679c\u4f60\u662f\u4e3a\u4e86\u5b9e\u76d8\u76d1\u63a7\uff0c\u9ec4\u91d1\u7ec4\u5df2\u7ecf\u53ef\u4ee5\u4f18\u5148\u8bd5\u8fd9\u5957\u7eafGC\u9aa8\u67b6"),
            cn(r"- \u5982\u679c\u4f60\u8981\u518d\u7ee7\u7eed\u63d0\u5347\uff0c\u4e0b\u4e00\u6b65\u6700\u503c\u5f97\u52a0\u7684\u662f\u201c\u5f02\u5e38\u65e5\u8fc7\u6ee4\u201d\uff0c\u4f8b\u5982\u6362\u6708/\u57fa\u5dee\u7a81\u53d8\u65f6\u964d\u6743"),
        ]
    )

    OUT_SUMMARY_MD.write_text("\n".join(lines), encoding="utf-8-sig")

    print(f"Wrote {OUT_SUMMARY_CSV}")
    print(f"Wrote {OUT_SUMMARY_MD}")
    for row in latest_rows:
        print(f"{row['write_status']} {row['sample_file']}")


if __name__ == "__main__":
    main()
