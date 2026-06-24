from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(r"D:\Study\codexTest\CodexLOFarb")
PROC_DIR = ROOT / r"data\analysis_outputs_20260329\procedure fiels"
MAIN_DIR = ROOT / r"data\analysis_outputs_20260329"

METHOD_PATH = PROC_DIR / "method_compare_160719.csv"
FORWARD_PATH = PROC_DIR / "pure_futures_forward_160719.csv"
OUT_CSV = MAIN_DIR / "160719_纯GC估值样板.csv"
OUT_MD = MAIN_DIR / "160719_纯GC估值骨架说明.md"


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


def main() -> None:
    method_rows = read_csv(METHOD_PATH)
    forward_rows = read_csv(FORWARD_PATH)

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
                "交易日期": trade_date,
                "净值实际归属日": base_date,
                "已知净值锚点": to_num(known_nav, 4),
                "T日真实净值_次日公布": to_num(target_nav, 4),
                "价格": to_num(price, 3),
                "使用仓位": to_num(position, 4),
                "GC当日收盘价": to_num(future_close, 1),
                "GC锚点收盘价": to_num(base_future, 1),
                "人民币中间价": to_num(rmb_mid, 4),
                "锚点人民币中间价": to_num(base_rmb, 4),
                "GCx人民币变化倍数": to_num(gc_cny_ratio, 6),
                "GCx人民币涨跌幅": to_percent(gc_cny_return),
                "现金腿锚点": to_num(cash_anchor, 4),
                "风险腿锚点": to_num(risk_anchor, 4),
                "纯GC未调仓风险腿估值": to_num(pure_gc_new_leg, 4),
                "纯GC静态Beta": to_num(static_beta, 4),
                "纯GC滚动Beta": to_num(rolling_beta, 4),
                "纯GC静态估值": to_num(static_est, 4),
                "纯GC滚动估值": to_num(rolling_est, 4),
                "纯GC静态误差_次日验证": to_percent(static_err),
                "纯GC滚动误差_次日验证": to_percent(rolling_err),
                "纯GC静态溢价": to_percent(static_premium),
                "纯GC滚动溢价": to_percent(rolling_premium),
                "woody官方估值": row.get("official_est", ""),
                "期货校准ETF估值": row.get("calibrated_est", ""),
                "旧版直接期货估值": row.get("direct_est", ""),
            }
        )

    fieldnames = list(out_rows[0].keys())
    write_csv(OUT_CSV, out_rows, fieldnames)

    examples: list[dict[str, str]] = []
    wanted_dates = {"2026-03-23", "2026-03-24", "2026-03-26"}
    for row in out_rows:
        if row["交易日期"] in wanted_dates:
            examples.append(row)

    md_lines = [
        "# 160719 纯GC估值骨架说明",
        "",
        "这份说明对应样板文件：",
        f"- `{OUT_CSV}`",
        "",
        "## 公式骨架",
        "",
        "从 woody 代码抽象出来，160719 的纯 GC 版本可以写成：",
        "",
        "```text",
        "GC人民币变化倍数 = (GC_t × RMB_t) / (GC_0 × RMB_0)",
        "GC人民币涨跌幅 = GC人民币变化倍数 - 1",
        "现金腿锚点 = NAV0 × (1 - 仓位)",
        "风险腿锚点 = NAV0 × 仓位",
        "纯GC估值 = 现金腿锚点 + 风险腿锚点 × (1 + Beta × GC人民币涨跌幅)",
        "```",
        "",
        "当 `Beta = 1` 时，这就是最接近 woody `FundAdjustPosition` 骨架的纯期货版本。",
        "",
        "## 和 woody 代码的对应关系",
        "",
        "- `FundAdjustPosition(r, new, old) = r × new + (1-r) × old`",
        "- 这里的 `old` 就是锚点净值 `NAV0`",
        "- `new` 对应“如果基金风险资产完全跟着 GC×人民币变化后，理论上会到哪里”",
        "- `r` 就是基金仓位",
        "",
        "也就是说，纯 GC 版并不是去预测未来，而是围绕最近一次可信净值锚点做实时展开。",
        "",
        "## 样例",
        "",
    ]

    for row in examples:
        md_lines.extend(
            [
                f"### {row['交易日期']}",
                f"- 锚点净值：{row['已知净值锚点']}",
                f"- 仓位：{row['使用仓位']}",
                f"- GC×人民币涨跌幅：{row['GCx人民币涨跌幅']}",
                f"- 纯GC静态估值：{row['纯GC静态估值']}",
                f"- T日真实净值_次日公布：{row['T日真实净值_次日公布']}",
                f"- 纯GC静态误差：{row['纯GC静态误差_次日验证']}",
                f"- woody官方估值：{row['woody官方估值']}",
                f"- 期货校准ETF估值：{row['期货校准ETF估值']}",
                f"- 旧版直接期货估值：{row['旧版直接期货估值']}",
                "",
            ]
        )

    OUT_MD.write_text("\n".join(md_lines), encoding="utf-8-sig")

    print(f"Wrote {OUT_CSV}")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
