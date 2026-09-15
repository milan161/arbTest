# -*- coding: utf-8 -*-
"""
原油 LOF（160723）五只持仓 ETF/ETC 的【历史收盘价】抓取器
========================================================

本脚本是 160723 持仓静态估值的**唯一权威数据源脚本**，从 oil_160723/fetch_all6_0911.py
规范移植而来，统一放在 src/ArbDashboard/backend/holding_valuation/ 下
（属于 Web 后端项目内部的正式数据管道目录，与 services/ 的 Web 逻辑、scripts/ 的临时工具区分开）。

标的（二季报口径，合计仓位 93.13%）：
    CRUD  WisdomTree WTI   伦敦  18.87%   -> 腾讯 ukCRUD
    BRNT  WisdomTree Brent 伦敦  18.57%   -> 腾讯 ukBRNT
    USO   US Oil Fund      纽约  18.78%   -> 新浪 USO
    OILK  ProShares K-1 Free 纽约  18.54%   -> 新浪 OILK
    BNO   US Brent Oil     纽约  18.37%   -> 新浪 BNO

数据源铁律（2026-09-11 实测，别改）：
  1. 伦敦两只走【腾讯】ukXXX，n 必须传大（脚本里 N_DAYS=800），能给约 1000 天历史
  2. 美股三只【必须走新浪】US_MinKService.getDailyK
     —— 腾讯的 usXXX 只返回最新 1 天，拿不到历史（已实测确认，别浪费时间试）
  3. 新浪偶发 HTTP 456 限流 → 脚本已内置重试 3 次、间隔递增
  4. 已死的源别再试：Yahoo（TLS 不通）、stooq（需 JS 挑战）、腾讯美股历史（只 1 天）
  5. 港股 0883 中海油 / 0857 中石油不是持仓（加进去误差从 4bp 涨到 13bp），不要抓
  6. 注意：备忘录-20260910.md 里写的"新浪已死""腾讯伦敦仅 41 天"是**过时误判**，
     2026-09-11 本脚本实测新浪美股长历史可用、腾讯伦敦 n=800 可到 ~1000 天，以此为准。

输出：项目根下 oil_160723/all6.csv  列 = date, nav, CRUD, BRNT, USO, OILK, BNO
      nav = 160723 官方净值（天天基金 api.fund.eastmoney.com/f10/lsjz）。
      本地数据库已有完整美元/人民币中间价，汇率不用抓。
      （统一落到 oil_160723/ 而非脚本同目录，保持与东哥核对过的权威数据区一致，
       后续主程序集成也从该路径读取 / 导入数据库。）

用法：
    python3 fetch_oil_etf_history.py

注意：
  - 最后一行若 = 今天，伦敦两只(CRUD/BRNT)是盘中价（LSE 北京时间 23:30 收盘），
    复算时请用 date < 今天 的记录。
  - 美股三只通常在北京时间次日凌晨才有完整收盘价，当天行可能为空，属正常。
  - 抓完后把 all6.csv 导入数据库 usa_etf_daily_prices（导入前先清该标的区间旧值，防残留）。
"""
import os
import json
import time
import urllib.request

import pandas as pd

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

N_DAYS = 800          # 抓取天数（腾讯伦敦实测可到 1000+，新浪美股可到 5000+）

# 输出固定到项目根 oil_160723/（与东哥核对过的权威数据区一致），不依赖运行时 cwd
# 脚本路径：src/ArbDashboard/backend/holding_valuation/fetch_oil_etf_history.py
# 上溯 4 级 -> D:/Study/arbTest
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
OUT_CSV = os.path.join(_PROJECT_ROOT, 'oil_160723', 'all6.csv')


def _get(url, enc='utf-8', referer=None, data=None, timeout=25, retry=3):
    last = None
    for i in range(retry):
        try:
            h = {'User-Agent': UA}
            if referer:
                h['Referer'] = referer
            r = urllib.request.urlopen(
                urllib.request.Request(url, headers=h, data=data), timeout=timeout)
            return r.read().decode(enc, 'ignore')
        except Exception as e:
            last = e
            if i < retry - 1:
                time.sleep(1.5 * (i + 1))
    raise last


# ------------------------------------------------------------------ 伦敦（腾讯）
def tx_kline(code, kind='us', n=N_DAYS):
    """腾讯日K。伦敦 ukXXX 可给约 1000 天历史；美股 usXXX 只给最新 1 天，别用它取历史"""
    u = ('https://web.ifzq.gtimg.cn/appstock/app/%sfqkline/get'
         '?param=%s,day,,,%d,qfq' % (kind, code, n))
    j = json.loads(_get(u, referer='https://gu.qq.com/'))
    d = j['data'][code]
    k = d.get('qfqday') or d.get('day')
    if not k:
        return {}
    return {x[0]: float(x[2]) for x in k}      # x = [date, open, close, high, low, ...]


# ------------------------------------------------------------------ 美股（新浪）
def sina_us(sym, n=N_DAYS):
    """新浪美股日K。唯一能拿到美股长历史的免费源"""
    u = ('https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var%20_/'
         'US_MinKService.getDailyK?symbol=' + sym + '&___qn=3')
    t = _get(u, referer='https://finance.sina.com.cn')
    i = t.find('(')
    arr = json.loads(t[i + 1:t.rfind(')')])
    out = {x['d']: float(x['c']) for x in arr}
    return {k: out[k] for k in sorted(out)[-n:]}


# ------------------------------------------------------------------ 官方净值（天天基金）
def em_nav(code='160723', pages=8):
    """天天基金历史净值 {date: nav}。复算要用作基准；本地已有则可用自己的"""
    out = {}
    for pg in range(1, pages + 1):
        try:
            j = json.loads(_get(
                'https://api.fund.eastmoney.com/f10/lsjz'
                '?fundCode=%s&pageIndex=%d&pageSize=20' % (code, pg),
                referer='https://fund.eastmoney.com/'))
            rows = j['Data']['LSJZList']
            if not rows:
                break
            for r in rows:
                out[r['FSRQ']] = float(r['DWJZ'])
            if len(rows) < 20:
                break
        except Exception:
            break
    return out


if __name__ == '__main__':
    print('抓取中...  (N_DAYS=%d)' % N_DAYS)
    src = [('CRUD', 'tx', 'ukCRUD'), ('BRNT', 'tx', 'ukBRNT'),
           ('USO', 'sina', 'USO'), ('OILK', 'sina', 'OILK'), ('BNO', 'sina', 'BNO')]
    cols = {}
    for name, kind, code in src:
        try:
            s = tx_kline(code) if kind == 'tx' else sina_us(code)
            cols[name] = s
            ks = sorted(s)
            print('  %-6s %-10s OK  %4d 条   %s ~ %s  末值 %.4f'
                  % (name, code, len(s), ks[0], ks[-1], s[ks[-1]]))
        except Exception as e:
            print('  %-6s %-10s FAIL  %s' % (name, code, str(e)[:60]))
            cols[name] = {}

    navs = {}
    try:
        navs = em_nav()
        print('  %-6s %-10s OK  %4d 条   %s ~ %s'
              % ('nav', '天天基金', len(navs),
                 min(navs) if navs else '-', max(navs) if navs else '-'))
    except Exception as e:
        print('  nav  FAIL  %s' % str(e)[:60])

    dates = sorted(set().union(*[set(v) for v in cols.values()], set(navs)))
    out = {'date': dates, 'nav': [navs.get(d) for d in dates]}
    for name, _, _ in src:
        out[name] = [cols[name].get(d) for d in dates]
    df = pd.DataFrame(out).set_index('date')
    df.index.name = 'date'
    df = df[['nav', 'CRUD', 'BRNT', 'USO', 'OILK', 'BNO']]
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    df.to_csv(OUT_CSV)
    print('\n已保存 %s   %d 行   %s ~ %s' % (OUT_CSV, len(df), df.index[0], df.index[-1]))
    print('\n非空计数:\n' + df.notna().sum().to_string())
    print('\n注意：最后一行若 = 今天，伦敦两只可能是【盘中价】未收盘（LSE 北京时间 23:30 收盘），'
          '\n      复算时请用 date < 今天的记录。')
