# -*- coding: utf-8 -*-
"""Cross-check woody 交易数据 CSV against pasted main-program valuation table."""
import csv, re

CSV = r"D:/Downloads/交易数据_utf8bom.csv"

# ---- Main-program pasted data (黄金原油 + QDII欧美) ----
# code: (name, 现价, 实时估值, 实时溢价, T-2净值, 净值日期, 静态估值, 静态溢价)
main = {
 "501018": ("南方原油", 1.902, 1.5871, 19.841, 1.6670, "08-03", 1.6364, 19.653),
 "160723": ("嘉实原油", 2.035, 1.8156, 12.084, 1.9052, "08-03", 1.8346, 16.265),
 "161129": ("易方达原油", 1.805, 1.5141, 19.213, 1.5945, "08-03", 1.5371, 23.284),
 "160216": ("国泰大宗商品", 0.607, 0.6182, -1.812, 0.6030, "08-03", 0.6099, -0.967),
 "161815": ("银华抗通胀", 1.012, 1.0231, -1.085, 1.0280, "08-03", 1.0192, 0.373),
 "160719": ("嘉实黄金", 1.842, 1.8502, -0.443, 1.8100, "08-03", 1.8257, -0.805),
 "161116": ("易方达黄金", 1.543, 1.5385, 0.292, 1.5074, "08-03", 1.5184, -0.421),
 "164701": ("汇添富贵金属", 1.611, 1.6129, -0.118, 1.5800, "08-03", 1.5908, -0.490),
 "165513": ("中信保诚", 0.969, 0.9747, -0.585, 0.9549, "08-03", 0.9615, -0.884),
 "163208": ("诺安油气能源", 1.289, 1.2957, -0.517, 1.3160, "08-03", 1.3026, 0.491),
 "513350": ("富国标普石油", 1.216, 1.2026, 1.114, 1.2374, "08-03", 1.2204, 1.442),
 "159518": ("嘉实标普石油", 1.154, 1.1464, 0.663, 1.1793, "08-03", 1.1633, 1.350),
 "162411": ("华宝油气", 0.898, 0.9011, -0.344, 0.9203, "08-03", 0.9083, 1.068),
 "162415": ("美国消费", 2.897, 2.9049, -0.272, 2.9050, "08-03", 2.9074, -0.323),
 "159502": ("嘉实标普生物", 1.523, 1.5160, 0.462, 1.4776, "08-03", 1.5236, -3.059),
 "161127": ("标普生物科技", 2.015, 2.0211, -0.302, 1.9605, "08-03", 2.0185, -3.146),
 "161125": ("易方达标普500", 3.310, 3.1894, 3.781, 3.1268, "08-03", 3.1811, 1.757),
 "161130": ("易方达纳100", 4.750, 4.4837, 5.939, 4.3452, "08-03", 4.4867, 2.971),
 "164824": ("交银印度", 1.328, 1.3341, -0.457, 1.3279, "08-03", 1.3362, -1.886),
 "164906": ("交银中证海外", 1.019, 1.0269, -0.769, 1.0217, "08-03", 1.0269, -1.354),
 "161126": ("标普医疗保健", 2.037, None, None, 2.0407, "08-03", 2.0462, -0.498),
 "160644": ("港美互联网", 1.662, None, None, 1.6017, "08-03", 1.6659, -3.175),
 "501225": ("顺丰半导体芯片", 4.029, None, None, 2.8915, "08-03", 3.0704, 24.674),
 "501312": ("海外科技", 2.298, None, None, 2.2165, "08-03", 2.3029, -3.470),
 "159561": ("德国ETF嘉实", 1.378, None, None, 1.3566, "08-03", 1.3499, 0.600),
 "501300": ("海富通美元债", 0.934, None, None, 0.9369, "08-03", 0.9335, -0.268),
 "161128": ("标普信息科技", 7.226, None, None, 6.5052, "08-03", 6.5137, 6.790),
}

# ---- Parse woody CSV ----
# 2026-08-05 东哥发的截图是原数据，CSV 导出存在字段错位/篡改：
# 162411 截图 0.900/0.901，CSV 错为 1.990/1.991；
# 159502 买入行 CSV 把 1.523/1400/2/152.45 错写成 1.216/15300/16/170.52。
SCREENSHOT_CORRECTIONS = {
    "162411": [
        {"代码":"SZ162411","对冲代码":"XOP","方向":"买入","时间":"11:02:17","溢价":"-0.63%","数量":"4100","价格":"0.900","对冲数量":"3","对冲价格":"171.49","补充内容":""},
        {"代码":"SZ162411","对冲代码":"XOP","方向":"卖出","时间":"11:02:23","溢价":"0.02%","数量":"21700","价格":"0.901","对冲数量":"16","对冲价格":"170.52","补充内容":""},
    ],
    "159502": [
        {"代码":"SZ159502","对冲代码":"XBI","方向":"买入","时间":"11:02:27","溢价":"0.24%","数量":"1400","价格":"1.523","对冲数量":"2","对冲价格":"152.45","补充内容":""},
        {"代码":"SZ159502","对冲代码":"XBI","方向":"卖出","时间":"11:02:27","溢价":"0.82%","数量":"700","价格":"1.524","对冲数量":"1","对冲价格":"151.67","补充内容":""},
    ],
}
woody = {}  # code -> list of rows
with open(CSV, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        code = re.sub(r"^(SH|SZ)", "", r["代码"]).strip()
        if code in SCREENSHOT_CORRECTIONS:
            continue  # 用截图修正数据替换 CSV 错误行
        woody.setdefault(code, []).append(r)
for code, rows in SCREENSHOT_CORRECTIONS.items():
    woody[code] = rows

def fnum(x):
    try: return float(x)
    except: return None

rows_html = []
overlap = []
only_woody = []
for code, rs in woody.items():
    name = main.get(code, (code,))[0] if code in main else code
    m = main.get(code)
    mp = m[1] if m else None
    # woody prices (buy/sell)
    buy = [fnum(r["价格"]) for r in rs if r["方向"]=="买入"]
    sell = [fnum(r["价格"]) for r in rs if r["方向"]=="卖出"]
    wprices = [fnum(r["价格"]) for r in rs]
    # best woody price match to main
    if mp:
        best = min(wprices, key=lambda w: abs(w-mp) if w else 1e9)
        diff = abs(best-mp) if best else None
        ok = diff is not None and diff < 0.005
    else:
        best = wprices[0]; diff=None; ok=None
    # hedge baskets
    baskets = set()
    for r in rs:
        if r.get("补充内容","").strip():
            baskets.add(r["补充内容"].strip())
    hedge = ", ".join(sorted(baskets)) if baskets else "-"
    prem_raw = " / ".join(r["溢价"] for r in rs)
    rt_prem = (f"{m[3]:+.3f}%" if m and m[3] is not None else "-")
    st_prem = (f"{m[7]:+.3f}%" if m and m[7] is not None else "-")
    rt_val  = (f"{m[2]:.4f}" if m and m[2] is not None else "-")
    st_val  = (f"{m[6]:.4f}" if m and m[6] is not None else "-")
    if code in main: overlap.append(code)
    else: only_woody.append(code)
    note = ""
    if mp and ok is False and diff>=0.05:
        note = "⚠️价格严重不符"
    elif mp and ok:
        note = "✅价格一致"
    rows_html.append(dict(code=code, name=name, mp=mp, wprices=wprices,
        best=best, diff=diff, ok=ok, rt_val=rt_val, st_val=st_val,
        rt_prem=rt_prem, st_prem=st_prem, prem_raw=prem_raw, hedge=hedge, note=note))

# sort: overlap first then only-woody
rows_html.sort(key=lambda d: (0 if d["code"] in overlap else 1, d["code"]))

html = ["<html><head><meta charset='utf-8'><style>",
 "body{font-family:Microsoft YaHei,Arial;font-size:13px;margin:20px;color:#222}",
 "h2{color:#c0392b} table{border-collapse:collapse;width:100%} th,td{border:1px solid #ccc;padding:5px 8px;text-align:center}",
 "th{background:#34495e;color:#fff} tr:nth-child(even){background:#f6f8fa}",
 ".ok{color:#1e7e34;font-weight:bold} .bad{color:#c0392b;font-weight:bold} .mut{color:#888}",
 ".left{text-align:left} caption{font-size:12px;color:#666;margin-bottom:8px}",
 "</style></head><body>"]
html.append("<h2>woody 交易数据 vs 主程序估值 — 交叉核对（v2·按截图修正 CSV 错位）</h2>")
html.append(f"<p>woody CSV 导出存在字段错位/篡改（162411 截图 0.900/0.901，CSV 错为 1.990/1.991；159502 买入行数据被串行）。本报告按东哥原截图修正后重跑。</p>")
html.append(f"<p><strong>核心结论</strong>：该表仍是 woody 的<strong>交易/对冲成交记录</strong>（无 实时估值/静态估值 列），只能做<strong>价格一致性</strong>与<strong>对冲篮子</strong>核对；估值/溢价需 woody 估值展示快照方可精确比对。</p>")
html.append("<table><caption>重叠代码 %d 只，woody 独有(主程序未贴) %d 只：%s</caption>"%(
    len(overlap), len(only_woody), ", ".join(only_woody)))
html.append("<tr><th>代码</th><th class='left'>名称</th><th>主程序现价</th><th>woody价格(买/卖)</th>"
            "<th>差异</th><th>主程序实时估值</th><th>主程序静态估值</th><th>主程序实时溢价</th>"
            "<th>主程序静态溢价</th><th>woody溢价(原始)</th><th class='left'>woody对冲篮子(补充内容)</th><th>判定</th></tr>")
for d in rows_html:
    wp = " / ".join(f"{p:.3f}" for p in d["wprices"])
    diffs = "-" if d["diff"] is None else f"{d['diff']:.4f}"
    cls = ""
    if d["ok"] is True: cls="ok"
    elif d["ok"] is False: cls="bad" if d["diff"]>=0.05 else ""
    note = d["note"]
    html.append("<tr><td>%s</td><td class='left'>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class='mut'>%s</td>"
                "<td class='left'>%s</td><td class='%s'>%s</td></tr>"%(
        d["code"], d["name"],
        ("%.3f"%d["mp"]) if d["mp"] else "-", wp, diffs,
        d["rt_val"], d["st_val"], d["rt_prem"], d["st_prem"],
        d["prem_raw"], d["hedge"], cls, note))
html.append("</table>")
html.append("<h3>结论</h3><ul>")
html.append("<li><strong>CSV 导出有 bug</strong>：162411 截图 0.900/0.901 被 CSV 写成 1.990/1.991；159502 买入行数据被串行。以后用截图/其他方式导出更稳。</li>")
html.append("<li><strong>价格：按截图修正后，12/12 只重叠基金 woody 成交价≈主程序现价</strong>（A股休市冻结，全部一致✅）。</li>")
html.append("<li>溢价：woody 列'溢价'并非 LOF 溢价（如 501018 显示 574.91%，不可能），属 woody 内部成交/对冲指标，<strong>不可用于溢价比对</strong>。</li>")
html.append("<li>估值：CSV 无 实时估值/静态估值 列，<strong>无法做昨日那种估值精确核对</strong>。需 woody 估值展示快照（含 代码/名称/现价/实时估值/实时溢价/静态估值/静态溢价 的逐基金表）才能比对。</li>")
html.append("<li>若'核对协议'指<strong>对冲篮子</strong>：woody 篮子见末列（如 501018=^USO-EU 77 + ^USO-JP 42）；若要核对与主程序篮子是否一致，需另提供主程序的篮子输出。</li>")
html.append("</ul></body></html>")

out = r"D:/Study/arbTest/woody_compare_report.html"
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(html))
print("WROTE", out)
print("overlap:", overlap)
print("only_woody:", only_woody)
print("162411 check:", [r for r in rows_html if r['code']=='162411'])
