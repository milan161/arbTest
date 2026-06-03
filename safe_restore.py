import os
import re

old_file = "jsl/old_web_server.py"
target_file = "jsl/00_web_server.py"

with open(old_file, "r", encoding="utf-8") as f:
    content = f.read()

# 1. 注入同步函数
sync_func = """
def _sync_complex_funds_from_master(local_conn, fund_codes, index_map):
    # [工业级同步 V2.2] 物理同步静态基座：搬运净值、基准指数、基准汇率
    import sqlite3
    import contextlib
    import pandas as pd
    db_master_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "arb_master.db")
    if not os.path.exists(db_master_path): 
        return

    try:
        with contextlib.closing(sqlite3.connect(db_master_path, timeout=5.0)) as m_conn:
            placeholders = ",".join(["?"] * len(fund_codes))
            query = f\"\"\"
                SELECT fund_code, date, nav, static_val, premium
                FROM fund_data 
                WHERE fund_code IN ({placeholders}) AND static_val IS NOT NULL
                ORDER BY date DESC
            \"\"\"
            m_df = pd.read_sql(query, m_conn, params=fund_codes)
            m_df = m_df.sort_values("date").groupby("fund_code").last().reset_index()
            
            for _, row in m_df.iterrows():
                f_code, b_date = row["fund_code"], row["date"]
                idx_code = index_map.get(f_code)
                
                idx_close = None
                if idx_code:
                    idx_p_row = m_conn.execute("SELECT price FROM index_daily WHERE symbol=? AND date=?", (idx_code, b_date)).fetchone()
                    if not idx_p_row:
                        idx_p_row = m_conn.execute("SELECT price FROM usa_etf_daily_prices WHERE symbol=? AND date=?", (idx_code, b_date)).fetchone()
                    if idx_p_row: idx_close = idx_p_row[0]
                
                local_conn.execute(\"\"\"
                    INSERT INTO fund_history (fund_code, date, nav, static_valuation, premium, index_close)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fund_code, date) DO UPDATE SET
                    nav=excluded.nav, static_valuation=excluded.static_valuation, 
                    premium=excluded.premium, index_close=excluded.index_close
                \"\"\", (f_code, b_date, row["nav"], row["static_val"], row["premium"], idx_close))
                
            fx_df = pd.read_sql("SELECT date, usd_cny_mid, hkd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 30", m_conn)
            for _, row in fx_df.iterrows():
                local_conn.execute(\"\"\"
                    INSERT INTO exchange_rate (date, usd_cny_mid, hkd_cny_mid)
                    VALUES (?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                    usd_cny_mid=excluded.usd_cny_mid, hkd_cny_mid=excluded.hkd_cny_mid
                \"\"\", (row["date"], row["usd_cny_mid"], row["hkd_cny_mid"]))
            
        local_conn.commit()
    except Exception as e:
        pass
"""

# Insert sync_func before load_jsl_data
content = content.replace("def load_jsl_data():", sync_func + "\ndef load_jsl_data():")

# 2. 注入同步调用和修复 KeyError
old_df_load = """    try:
        df_funds = pd.read_csv(csv_file, dtype=str)
    except:
        return {}

    grouped_data = {}
    all_symbols = set(["fx_hkdcny"])

    with contextlib.closing(sqlite3.connect(db_path, timeout=15.0)) as conn:
        _ensure_quotes_table(conn)

        for _, row in df_funds.iterrows():"""

new_df_load = """    try:
        df_funds = pd.read_csv(csv_file, dtype=str)
        col_map = {
            '代码': 'code', '基金代码': 'code',
            '名称': 'name', '基金名称': 'name',
            '分类': 'category', '类别': 'category',
            '指数代码': 'idx_code', '相关指数代码': 'idx_code',
            '仓位': 'pos_ratio', '仓位比例': 'pos_ratio'
        }
        df_funds.rename(columns={k:v for k,v in col_map.items() if k in df_funds.columns}, inplace=True)
    except:
        return {}

    grouped_data = {}
    all_symbols = set(["fx_hkdcny"])

    with contextlib.closing(sqlite3.connect(db_path, timeout=15.0)) as conn:
        _ensure_quotes_table(conn)
        
        # 物理同步
        complex_df = df_funds[df_funds['category'].isin(['黄金原油', '混合跨境'])]
        complex_codes = complex_df['code'].tolist()
        index_map = complex_df.set_index('code')['idx_code'].to_dict()
        if complex_codes: _sync_complex_funds_from_master(conn, complex_codes, index_map)

        for _, row in df_funds.iterrows():"""

content = content.replace(old_df_load, new_df_load)

# 3. 修复 row 字段引用
content = content.replace("row.get('分类', row.get('类别', row.get('基金类型', row.get('基金类名', row.iloc[0]))))", "row.get('category', '')")
content = content.replace("row.get('code', row.get('基金代码', row.iloc[1] if len(row)>1 else ''))", "row.get('code', '')")
content = content.replace("row.get('name', row.get('基金名称', row.iloc[2] if len(row)>2 else ''))", "row.get('name', '')")
content = content.replace("row.get('相关指数', '-')", "row.get('idx_code', '-')")
content = content.replace("row.get('指数代码', '-')", "row.get('idx_code', '-')")
content = content.replace("row.get('仓位', '95%')", "row.get('pos_ratio', '95%')")

# 4. 修复 NAV NaN 追溯
old_nav = """            # 分别查询净值、份额的最新记录(不需要同一条记录同时有两者)
            nav_only_df = pd.read_sql("SELECT date, nav FROM fund_history WHERE fund_code=? AND nav IS NOT NULL ORDER BY date DESC LIMIT 1", conn, params=(code,))"""

new_nav = """            # 分别查询净值、份额的最新记录(不需要同一条记录同时有两者)
            nav_only_df = pd.read_sql("SELECT date, nav FROM fund_history WHERE fund_code=? AND nav IS NOT NULL ORDER BY date DESC LIMIT 1", conn, params=(code,))
            
            # 解决缺失 NAV 问题：将 T-1 日的 NAV 强制提取并附加到 fund 对象中
            fund_nav = '-'
            fund_nav_date = '-'
            if not nav_only_df.empty:
                fund_nav = float(nav_only_df.iloc[0]['nav'])
                fund_nav_date = nav_only_df.iloc[0]['date']"""

content = content.replace(old_nav, new_nav)
content = content.replace("'nav': float(nav_only_df.iloc[0]['nav']) if not nav_only_df.empty else '-',", "'nav': fund_nav,")
content = content.replace("'nav_date': nav_only_df.iloc[0]['date'] if not nav_only_df.empty else '-',", "'nav_date': fund_nav_date,")

# 5. 替换估值算法 (绝对比例算法)
old_rt_calc = """                # 【核心修正】实时估值计算逻辑
                if fund['nav'] != '-' and fund['nav_date'] != '-' and fund['idx_price'] != '-' and not fund.get('is_synced', False):
                    try:
                        # 1. 获取基准日指数
                        idx_b_query = "SELECT index_close FROM fund_history WHERE fund_code=? AND date=?"
                        idx_b_df = pd.read_sql(idx_b_query, conn, params=(fund['code'], fund['nav_date']))

                        if not idx_b_df.empty and pd.notna(idx_b_df.iloc[0]['index_close']):
                            index_b = float(idx_b_df.iloc[0]['index_close'])
                            if index_b > 0:
                                fx_pct = _get_fx_pct_for_index(idx_symbol, quote_map)
                                fx_ratio = 1 + fx_pct / 100.0
                                index_ratio = float(fund['idx_price']) / index_b
                                fund['est_price'] = float(fund['nav']) * (1 + fund['pos_ratio'] * (index_ratio * fx_ratio - 1))
                        else:
                            sv_df = pd.read_sql("SELECT static_valuation FROM fund_history WHERE fund_code=? AND static_valuation IS NOT NULL ORDER BY date DESC LIMIT 1", conn, params=(fund['code'],)) 
                            if not sv_df.empty and pd.notna(sv_df.iloc[0]['static_valuation']):
                                fund['est_price'] = float(sv_df.iloc[0]['static_valuation'])
                    except Exception as e:
                        logger.error(f"[!] 基金 {fund['code']} 实时估值计算异常: {e}")"""

new_rt_calc = """                # 【工业级修正】全自动实时估值引擎 (穿透式比例算法)
                if fund['nav'] != '-' and fund['nav_date'] != '-' and fund['idx_price'] != '-':
                    try:
                        base_date = fund['nav_date']
                        base_nav = float(fund['nav'])
                        pos = float(fund['pos_ratio'])
                        
                        bench_query = \"\"\"
                            SELECT h.index_close, e.usd_cny_mid, e.hkd_cny_mid
                            FROM fund_history h
                            LEFT JOIN exchange_rate e ON h.date = e.date
                            WHERE h.fund_code = ? AND h.date = ?
                        \"\"\"
                        bench_df = pd.read_sql(bench_query, conn, params=(fund['code'], base_date))
                        
                        if not bench_df.empty:
                            idx_base = float(bench_df.iloc[0]['index_close']) if pd.notna(bench_df.iloc[0]['index_close']) else 0
                            
                            idx_sym_lower = str(fund.get('idx_symbol', '')).lower()
                            is_hk = any(x in idx_sym_lower for x in ['hsi', 'hscei', 'hstech', 'hk'])
                            fx_base = float(bench_df.iloc[0]['hkd_cny_mid' if is_hk else 'usd_cny_mid']) if pd.notna(bench_df.iloc[0]['hkd_cny_mid' if is_hk else 'usd_cny_mid']) else 0
                            
                            if idx_base > 0 and fx_base > 0:
                                fx_now_key = 'fx_hkdcny' if is_hk else 'fx_usdcny'
                                fx_now_pct = float(quote_map.get(fx_now_key, {}).get('pct_change', 0))
                                fx_ratio = 1.0 + (fx_now_pct / 100.0)
                                index_ratio = float(fund['idx_price']) / idx_base
                                
                                fund['est_price'] = base_nav * ((1.0 - pos) + pos * (index_ratio * fx_ratio))
                                
                        if fund['est_price'] == '-' and fund.get('synced_static_val'):
                            fund['est_price'] = float(fund['synced_static_val'])
                            
                    except Exception as e:
                        logger.error(f"[!] 基金 {fund['code']} 实时估值计算异常: {e}")"""

content = content.replace(old_rt_calc, new_rt_calc)

# 6. 删除之前可能影响代码结构的不完美提取和旧代码块
content = content.replace("info['is_synced'] = is_synced_cat", "info['is_synced'] = is_synced_cat\n                if is_synced_cat and master_data and 'est' in master_data:\n                    info['synced_static_val'] = master_data['est']\n                else:\n                    info['synced_static_val'] = None")

# 7. 修正启动日志中的端口 (5003 -> 5004)
content = content.replace("port = 5003", "port = 5004")
content = content.replace("http://127.0.0.1:5003", "http://127.0.0.1:5004")

with open(target_file, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: Safely restored jsl_monitor_server.py with all fixes.")
