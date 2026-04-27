# 03_generate_monitor_html.py - LOF基金套利报表生成器
# 版本: 1.2.0
# 最后修改时间: 2026-04-01

import os
import sys
import yaml
import pandas as pd
import datetime
import webbrowser
import subprocess
import json
import sqlite3

# 初始化路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "lof_config.yaml")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "lof_monitor.html")

# 共享数据库路径
SHARED_DB_PATH = r"D:\Study\arbTest\database\arb_master.db"

# 导入模块
sys.path.insert(0, SCRIPT_DIR)
from LOF031_config_manager import ConfigManager
from LOF032_data_processor import DataProcessor
from LOF033_html_generator import HtmlGenerator

# 验证模块导入成功
print("模块导入成功:")
print(f"ConfigManager: {ConfigManager}")
print(f"DataProcessor: {DataProcessor}")
print(f"HtmlGenerator: {HtmlGenerator}")
print("使用新架构运行...")

# 全局变量
silver_fund_data = None

# 辅助函数

def read_fund_history_from_db(code):
    """直接从 SQLite 数据库读取历史对账表，不再使用旧的 CSV Processor"""
    try:
        conn = sqlite3.connect(SHARED_DB_PATH)
        df = pd.read_sql(f"SELECT * FROM fund_history_{code} ORDER BY date DESC", conn)
        conn.close()
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        return df
    except Exception as e:
        print(f"读取数据库 fund_history_{code} 失败: {e}")
        return pd.DataFrame()

def get_exchange_rate():
    """获取当天的汇率"""
    today_exchange_rate = "无"
    try:
        conn = sqlite3.connect(SHARED_DB_PATH)
        df = pd.read_sql("SELECT date, usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
        conn.close()
        if not df.empty:
            rate = df.iloc[0]['usd_cny_mid']
            today_exchange_rate = f"汇率 - 中间价: {rate:.4f}"
    except Exception as e:
        print(f"获取汇率失败: {e}")
    return today_exchange_rate

def get_ib_night_prices():
    """获取IB夜盘价格"""
    ib_night_prices = {}
    ib_prev_closes = {}
    ib_status_message = ""
    try:
        import requests
        url = "http://localhost:5000/api/ib_prices"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'error':
                ib_status_message = data.get('message', 'IB未连接')
                ib_prev_closes = data.get('prev_closes', {})
                print(f"IB状态: {ib_status_message}")
            else:
                ib_night_prices = data.get('prices', {})
                ib_prev_closes = data.get('prev_closes', {})
                ib_status_message = "IB夜盘价格已获取"
                
                price_strs = []
                for sym, p in ib_night_prices.items():
                    if isinstance(p, dict) and p.get('bid'):
                        price_strs.append(f"{sym}=${p.get('bid'):.2f}")
                prices_log = ", ".join(price_strs) if price_strs else "无数据"
                print(f"IB夜盘价格: {prices_log}")
        else:
            ib_status_message = f"后台服务响应异常: {response.status_code}"
            print(ib_status_message)
    except Exception as e:
        ib_status_message = "后台服务(端口5000)未启动"
        print(f"无法连接到后台服务获取IB数据: {e}")
    return ib_night_prices, ib_prev_closes, ib_status_message

def generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df=None, is_index_table=False, gold_calibration=10.9067, oil_calibration=0.8227, global_er=7.0):
    """处理单个基金的数据"""
    code = fund.get('code', '')
    name = fund.get('name', '未知基金')
    category = fund.get('category', '其他')
    
    # 初始化配置管理器
    config_manager = ConfigManager(CONFIG_FILE)
    
    # 获取仓位
    hold_cfg = fund.get('holdings', {})
    try:
        raw_pos = hold_cfg.get('equity_ratio', 100.0)
        pos_val = float(str(raw_pos).replace('%', ''))
        pos_float = pos_val / 100.0 if pos_val > 1 else pos_val
    except Exception:
        pos_float = 1.0
    
    # 获取对冲组合
    h_list = fund.get('valuation_portfolio', [])
    if not h_list:
        h_list = fund.get('hedging_portfolio', [])
    REGIONAL_VARIANTS = ['GLD-JP', 'GLD-EU', 'USO-JP', 'USO-EU', 'USO-HK']
    for item in h_list:
        sym = item.get('symbol', '')
        if sym.replace('^', '') in REGIONAL_VARIANTS:
            item['symbol'] = f"^{sym.replace('^', '')}"
    
    # 从数据库读取基金完美对账表
    lof_df = read_fund_history_from_db(code)
    
    # 如果没有数据，直接跳过
    if lof_df.empty:
        print(f"警告: 基金 {code} 无数据，跳过处理")
        return None, None, None
        
    # === 核心修复：动态提取基准日 (T-1) 的真实仓位和权重，彻底覆盖 YAML 默认值 ===
    base_row = None
    for _, row in lof_df.sort_values('date', ascending=False).iterrows():
        nav_val = row.get('nav', 0)
        if pd.notna(nav_val) and nav_val and float(nav_val) > 0:
            base_row = row
            break
            
    if base_row is not None:
        db_pos = base_row.get('position', base_row.get('仓位'))
        if pd.notna(db_pos) and db_pos != '无' and db_pos != '':
            try:
                pf = float(db_pos)
                if pf > 1: pf = pf / 100.0
                if pf > 0: pos_float = pf
            except: pass
            
        for item in h_list:
            sym = item['symbol']
            weight_col = f"{sym}权重"
            if weight_col in base_row:
                db_w = base_row.get(weight_col)
                if pd.notna(db_w) and db_w != '无' and db_w != '':
                    try: item['weight'] = float(db_w)
                    except: pass
    
    # 准备数据
    lof_df_sorted = lof_df.sort_values('date', ascending=False).reset_index(drop=True)
    df_idx = lof_df_sorted.set_index('date').sort_index()
    history_rows = ""
    est_home = 0.0
    est_home_date = ""
    nav_home = 0.0
    nav_home_date = ""
    futures_history_rows = ""
    
    # 获取最新的校准因子和人民币中间价（从basic表格中获取校准因子）
    latest_calibration_factor = 0.0
    latest_exchange_rate = 0.0
    
    # 使用传入的全局最新汇率给前端推演 JS 作为今日兜底
    today_exchange_rate_float = global_er
    rate_header_name = "人民币中间价"
    

    # 根据基金类别设置校准因子
    if category == '黄金':
        latest_calibration_factor = gold_calibration
    elif category == '原油':
        latest_calibration_factor = oil_calibration
    
    # 获取人民币中间价（从基金历史数据中获取）
    if not lof_df_sorted.empty:
        latest_row = lof_df_sorted.iloc[0]
        try:
            er = latest_row.get('exchange_rate', 0.0)
            if pd.notna(er) and er != '无' and er != '':
                latest_exchange_rate = float(er)
        except:
            pass
    
    # 智能解析期货映射，不再硬编码，全面支持后续新增的指数（如161127等）
    future_symbol = None
    f_list = fund.get('future_hedging', [])
    if f_list:
        raw_sym = f_list[0].get('symbol', '').upper()
        mapping = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC', 'NQ': 'NQ', 'ES': 'ES'}
        future_symbol = mapping.get(raw_sym, raw_sym)
    else:
        trade_fut = fund.get('trade_future', '').upper()
        mapping = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC', 'NQ': 'NQ', 'ES': 'ES'}
        if trade_fut:
            future_symbol = mapping.get(trade_fut, trade_fut)
        else:
            if category == '黄金': future_symbol = 'GC'
            elif category == '原油' and code != '162411': future_symbol = 'CL'
            elif category == '指数':
                trade_etf = str(fund.get('trade_etf', '')).upper()
                if 'QQQ' in trade_etf: future_symbol = 'NQ'
                elif 'SPY' in trade_etf or 'XBI' in trade_etf: future_symbol = 'ES'
                else: future_symbol = 'NQ'
            elif code == '161226': future_symbol = 'AG0'
    
    # 判断是否已经收盘
    now_dt = datetime.datetime.now()
    is_after_close = (now_dt.hour > 15 or (now_dt.hour == 15 and now_dt.minute > 0)) or now_dt.weekday() >= 5
    
    has_future = bool(future_symbol) and str(future_symbol).strip() != 'None' and category != '纯ETF'
    
    # 处理ETF列，确保不重复
    etf_columns = []
    seen_symbols = set()
    for item in h_list:
        symbol = item['symbol']
        # 直接使用配置中的symbol作为列名，避免重复添加区域后缀
        column_name = symbol
        if column_name not in seen_symbols:
            etf_columns.append(column_name)
            seen_symbols.add(column_name)
    
    # 生成ETF列的HTML
    etf_th_html = ''.join([f"<th class='col-etf-bg-th'>{col}</th>" for col in etf_columns])
    
    # 生成历史数据行
    # 确保按日期降序排序，这样最新的数据在前面
    lof_df_sorted = lof_df.sort_values('date', ascending=False).reset_index(drop=True)
    sub = lof_df_sorted.head(20)
    for i in range(len(sub)):
        d_T = sub.iloc[i]['date']
        uid = f"{code}-{d_T.strftime('%Y%m%d')}"
        
        # 获取前一天和前两天的数据（必须是有净值的有效交易日）
        d_T1 = None
        d_T2 = None
        try:
            # 获取当前日期之后的所有记录（按日期降序排列）
            sorted_dates = df_idx.index.sort_values(ascending=False)
            current_idx = sorted_dates.get_loc(d_T)
            
            # 查找T-1：第一个有净值的有效交易日
            for i in range(current_idx + 1, len(sorted_dates)):
                candidate_date = sorted_dates[i]
                nav_val = df_idx.loc[candidate_date].get('nav', 0)
                if isinstance(nav_val, (int, float)) and nav_val > 0:
                    d_T1 = candidate_date
                    break
            
            # 查找T-2：第二个有净值的有效交易日
            if d_T1 is not None:
                t1_idx = sorted_dates.get_loc(d_T1)
                for i in range(t1_idx + 1, len(sorted_dates)):
                    candidate_date = sorted_dates[i]
                    nav_val = df_idx.loc[candidate_date].get('nav', 0)
                    if isinstance(nav_val, (int, float)) and nav_val > 0:
                        d_T2 = candidate_date
                        break
        except Exception as e:
            print(f"获取T-1/T-2日期时出错: {e}")
        
        def safe_float(val):
            if isinstance(val, pd.Series):
                val = val.iloc[0]
            if pd.isna(val) or val is None or val == '' or val == '无':
                return 0.0
            try:
                return float(val)
            except (ValueError, TypeError):
                return 0.0
                
        # 获取基金净值
        n_T = safe_float(df_idx.loc[d_T].get('nav', 0))
        n_T1 = safe_float(df_idx.loc[d_T1].get('nav', 0)) if d_T1 else 0.0
        n_T2 = safe_float(df_idx.loc[d_T2].get('nav', 0)) if d_T2 else 0.0
        
        # 获取收盘价
        c_T = safe_float(df_idx.loc[d_T].get('close', 0))
        
        # 重置静态官方估值和计算标志
        cur_est_val = '无'
        can_calc = False
        
        # 从增强版CSV中获取静态官方估值
        if 'static_valuation' in df_idx.columns:
            static_val = df_idx.loc[d_T].get('static_valuation', '无')
            # 检查static_val是否为数字
            if static_val != '无' and pd.notna(static_val):
                try:
                    # 尝试将static_val转换为数字
                    static_val_num = float(static_val)
                    if static_val_num > 0:
                        # 检查是否有所有必要的ETF数据
                        has_all_etf_data = True
                        for item in h_list:
                            symbol = item['symbol']
                            if symbol in df_idx.columns:
                                etf_price = df_idx.loc[d_T].get(symbol, 0)
                                if pd.isna(etf_price) or etf_price <= 0:
                                    has_all_etf_data = False
                                    break
                            else:
                                has_all_etf_data = False
                                break
                        
                        # 只有当有所有ETF数据时，才使用静态官方估值
                        if has_all_etf_data:
                            cur_est_val = static_val_num
                            can_calc = True
                        else:
                            # 如果没有所有ETF数据，设置cur_est_val为'无'
                            cur_est_val = '无'
                            can_calc = False
                except (ValueError, TypeError):
                    # 如果转换失败，保持cur_est_val为'无'
                    pass
        
        # 记录最新的估值和净值
        if n_T > 0 and nav_home == 0:
            nav_home = n_T
            nav_home_date = d_T.strftime('%m-%d')
        
        # 只在处理第一条记录时更新最新估值（因为数据已经按日期降序排序）
        if i == 0 and isinstance(cur_est_val, (int, float)) and cur_est_val > 0:
            est_home = cur_est_val
            est_home_date = d_T.strftime('%m-%d')
            print(f"成功: 更新最新估值: {est_home} (日期: {est_home_date})")
        
        est_val_str = f"{cur_est_val:.4f}" if can_calc and cur_est_val != '无' and pd.notna(cur_est_val) and cur_est_val > 0 else "无"
        
        # 从数据中读取ETF静态溢价、ETF静态估值误差
        etf_premium_str = "-"
        etf_premium_cls = ""
        if 'ETF静态溢价' in df_idx.columns:
            etf_premium_val = df_idx.loc[d_T].get('ETF静态溢价', '无')
            if etf_premium_val != '无' and pd.notna(etf_premium_val):
                try:
                    etf_premium_num = float(str(etf_premium_val).replace('%', ''))
                    etf_premium_cls, etf_premium_str = html_generator.format_color(etf_premium_num)
                except:
                    pass
        
        etf_val_err_str = "-"
        etf_val_err_cls = ""
        if 'ETF静态估值误差' in df_idx.columns:
            etf_val_err_val = df_idx.loc[d_T].get('ETF静态估值误差', '无')
            if etf_val_err_val != '无' and pd.notna(etf_val_err_val):
                try:
                    etf_val_err_num = float(str(etf_val_err_val).replace('%', ''))
                    etf_val_err_cls, etf_val_err_str = html_generator.format_color(etf_val_err_num)
                except:
                    pass
        
        # 从数据中读取期货静态估值、期货静态估值误差
        future_static_val = '无'
        future_static_val_num = 0.0
        if '期货静态估值' in df_idx.columns:
            fs_val = df_idx.loc[d_T].get('期货静态估值', '无')
            if fs_val != '无' and pd.notna(fs_val):
                try:
                    future_static_val_num = float(fs_val)
                    if future_static_val_num > 0:
                        future_static_val = f"{future_static_val_num:.4f}"
                except:
                    pass
        
        future_val_err_str = "-"
        future_val_err_cls = ""
        if '期货静态估值误差' in df_idx.columns:
            fv_err_val = df_idx.loc[d_T].get('期货静态估值误差', '无')
            if fv_err_val != '无' and pd.notna(fv_err_val):
                try:
                    fv_err_num = float(str(fv_err_val).replace('%', ''))
                    future_val_err_cls, future_val_err_str = html_generator.format_color(fv_err_num)
                except:
                    pass
        
        future_premium_str = "-"
        future_premium_cls = ""
        if '期货静态估值溢价' in df_idx.columns:
            fp_val = df_idx.loc[d_T].get('期货静态估值溢价', '无')
            if fp_val != '无' and pd.notna(fp_val):
                try:
                    fp_num = float(str(fp_val).replace('%', ''))
                    future_premium_cls, future_premium_str = html_generator.format_color(fp_num)
                except:
                    pass
        
        # 从LOF历史数据中读取期货结算价
        future_settle_str = "-"
        future_settle_num = 0.0
        # 尝试不同的列名
        for settle_col in ['期货结算价', '期 货结算价', '期货Beta']:
            if settle_col in df_idx.columns:
                fs_price = df_idx.loc[d_T].get(settle_col, '无')
                if fs_price != '无' and pd.notna(fs_price):
                    try:
                        future_settle_num = float(fs_price)
                        if future_settle_num > 0:
                            future_settle_str = f"{future_settle_num:.2f}"
                        break
                    except:
                        pass
        
        # 读取T-1日的期货结算价
        future_settle_str_t1 = "-"
        if d_T1:
            for settle_col in ['期货结算价', '期 货结算价', '期货Beta']:
                if settle_col in df_idx.columns:
                    fs_price_t1 = df_idx.loc[d_T1].get(settle_col, '无')
                    if fs_price_t1 != '无' and pd.notna(fs_price_t1):
                        try:
                            future_settle_num_t1 = float(fs_price_t1)
                            if future_settle_num_t1 > 0:
                                future_settle_str_t1 = f"{future_settle_num_t1:.2f}"
                            break
                        except:
                            pass
        
        # 获取汇率数据
        exchange_rate = df_idx.loc[d_T].get('exchange_rate', 0)
        
        # 处理汇率数据
        exchange_rate_str = f"{exchange_rate:.4f}" if isinstance(exchange_rate, (int, float)) and exchange_rate > 0 else "无"
        
        # 处理T-1日的汇率数据
        t1_exchange_rate = 0
        if d_T1:
            t1_exchange_rate = df_idx.loc[d_T1].get('exchange_rate', 0)
        t1_exchange_rate_str = f"{t1_exchange_rate:.4f}" if isinstance(t1_exchange_rate, (int, float)) and t1_exchange_rate > 0 else "无"
        
        # 从数据框中获取ETF值
        etf_td_html = ''
        for col in etf_columns:
            etf_val = df_idx.loc[d_T].get(col, 0) if col in df_idx.columns else 0
            if isinstance(etf_val, (int, float)) and etf_val > 0:
                etf_td_html += f"<td class='col-etf-bg'>{etf_val:.2f}</td>"
            else:
                etf_td_html += f"<td class='col-etf-bg'>-</td>"
        
        # 处理T-1日的ETF值
        etf_td_html_t1 = ''
        if d_T1:
            for col in etf_columns:
                etf_val_t1 = df_idx.loc[d_T1].get(col, 0) if col in df_idx.columns else 0
                if isinstance(etf_val_t1, (int, float)) and etf_val_t1 > 0:
                    etf_td_html_t1 += f"<td>{etf_val_t1:.2f}</td>"
                else:
                    etf_td_html_t1 += f"<td>-</td>"
        else:
            etf_td_html_t1 = ''.join([f"<td>-</td>" for _ in etf_columns])
        
        # 处理收盘价和净值，避免显示nan
        secondary_close_str = f"{c_T:.3f}" if isinstance(c_T, (int, float)) and c_T > 0 else "-"
        nav_str = f"{n_T:.4f}" if isinstance(n_T, (int, float)) and n_T > 0 else "无"
        t1_nav_str = f"{n_T1:.4f}" if d_T1 and isinstance(n_T1, (int, float)) and n_T1 > 0 else "无"
        
        colspan_main = 9 + len(etf_columns) + (4 if has_future else 0)
        
        future_td_html = ""
        future_verify_td_T_html = ""
        future_verify_td_T1_html = ""
        if has_future:
            future_td_html = f'<td class="col-future-bg">{future_settle_str}</td><td class="num-font col-future-bg" style="color:#1976d2; font-weight:bold">{future_static_val}</td><td class="num-font col-future-bg {future_premium_cls}"><b>{future_premium_str}</b></td><td class="num-font col-future-bg {future_val_err_cls}">{future_val_err_str}</td>'
            future_verify_td_T_html = f'<td>{future_settle_str}</td><td class="col-est" style="border-left: 2px solid #bbdefb; background-color: #e3f2fd50; color:#1976d2;">{future_static_val}</td>'
            future_verify_td_T1_html = f'<td>{future_settle_str_t1}</td><td>-</td>'
        
        # 生成历史数据行
        history_rows += f"""
        <tr class="secondary-page-row"><td class="num-font">{d_T.strftime('%m-%d')}</td><td>{exchange_rate_str}</td><td>{nav_str}</td><td class="secondary-close-price">{secondary_close_str}</td>{etf_td_html}<td class="num-font col-etf-bg" style="color:#d35400; font-weight:bold">{est_val_str}</td><td class="num-font col-etf-bg {etf_premium_cls}"><b>{etf_premium_str}</b></td><td class="num-font col-etf-bg {etf_val_err_cls}">{etf_val_err_str}</td>{future_td_html}<td><button class="btn-verify" onclick="toggleVerify('{uid}')">▶ 验算</button></td></tr>
        <tr id="verify-{uid}" class="verify-row secondary-page-row"><td colspan="{colspan_main}"><div class="verify-wrapper"><table class="check-table"><thead><tr><th>项</th><th>📅 日期</th><th>{rate_header_name}</th><th>净值</th>{etf_th_html}<th class="col-est">ETF静态净值</th>{('<th>期货结算价</th><th class="col-est" style="border-left: 2px solid #bbdefb; background-color: #e3f2fd50; color:#1976d2;">期货静态净值</th>' if has_future else '')}</tr></thead><tbody>
        <tr><td>本期(T)</td><td>{d_T.strftime('%m-%d')}</td><td>{exchange_rate_str}</td><td>{nav_str} {html_generator.pill_html(n_T, n_T1, True)}</td>{etf_td_html}<td class="col-est">{est_val_str} {html_generator.pill_html(cur_est_val, n_T1) if can_calc else ""}</td>{future_verify_td_T_html}</tr>
        <tr><td>基准(T-1)</td><td>{d_T1.strftime('%m-%d') if d_T1 else '无'}</td><td>{t1_exchange_rate_str}</td><td>{t1_nav_str} {html_generator.pill_html(n_T1, n_T2, True) if d_T2 else ""}</td>{etf_td_html_t1}<td>-</td>{future_verify_td_T1_html}</tr>
        </tbody></table></div></td></tr>"""
        
        # 生成期货历史数据行
        if future_symbol and futures_history_df is not None and not futures_history_df.empty:
            d_T_str = d_T.strftime('%Y-%m-%d')
            d_T1_str = d_T1.strftime('%Y-%m-%d') if d_T1 else ""
            
            f_c_T = 0.0
            f_c_T1 = 0.0
            if d_T_str in futures_history_df.index:
                val = futures_history_df.loc[d_T_str].get(f'{future_symbol}_close', 0)
                if isinstance(val, pd.Series): val = val.iloc[0]
                f_c_T = float(val) if pd.notna(val) else 0.0
                
            if d_T1_str in futures_history_df.index:
                val = futures_history_df.loc[d_T1_str].get(f'{future_symbol}_close', 0)
                if isinstance(val, pd.Series): val = val.iloc[0]
                f_c_T1 = float(val) if pd.notna(val) else 0.0
            
            f_val_T = 0.0
            if d_T1 and n_T1 > 0 and f_c_T1 > 0 and t1_exchange_rate > 0 and f_c_T > 0 and exchange_rate > 0:
                f_chg = f_c_T / f_c_T1
                r_chg = exchange_rate / t1_exchange_rate
                f_val_T = n_T1 * (1 + pos_float * (f_chg * r_chg - 1))
                
            f_val_str = f"{f_val_T:.4f}" if f_val_T > 0 else "无"
            f_c_str = f"{f_c_T:.2f}" if f_c_T > 0 else "-"
            f_c_T1_str = f"{f_c_T1:.2f}" if f_c_T1 > 0 else "-"
            
            f_prem_cls, f_prem_txt = html_generator.format_color((c_T / f_val_T - 1) * 100) if f_val_T > 0 and c_T > 0 else ("", "-")
            f_err_cls, f_err_txt = html_generator.format_color((f_val_T / n_T - 1) * 100) if f_val_T > 0 and n_T > 0 else ("", "-")
            
            f_uid = f"f-{code}-{d_T.strftime('%Y%m%d')}"
            
            futures_history_rows += f"""
            <tr class="secondary-page-row">
                <td class="num-font">{d_T.strftime('%m-%d')}</td><td>{exchange_rate_str}</td><td class="num-font">{f_c_str}</td>
                <td class="num-font" style="color:#1976d2; font-weight:bold">{f_val_str}</td>
                <td class="secondary-close-price">{secondary_close_str}</td><td class="num-font {f_prem_cls}"><b>{f_prem_txt}</b></td>
                <td>{nav_str}</td><td class="num-font {f_err_cls}">{f_err_txt}</td>
                <td><button class="btn-verify" onclick="toggleVerify('{f_uid}')">▶ 验算</button></td>
            </tr>
            <tr id="verify-{f_uid}" class="verify-row secondary-page-row"><td colspan="9"><div class="verify-wrapper"><table class="check-table">
            <thead><tr><th>项</th><th>📅 日期</th><th>净值</th><th>{rate_header_name}</th><th>{future_symbol} 收盘价</th><th class="col-est" style="border-left: 2px solid #bbdefb; background-color: #e3f2fd50; color:#1976d2;">期货估值</th></tr></thead><tbody>
            <tr><td>本期(T)</td><td>{d_T.strftime('%m-%d')}</td><td>{nav_str} {html_generator.pill_html(n_T, n_T1, True)}</td><td>{exchange_rate_str}</td><td>{f_c_str}</td><td class="col-est" style="border-left: 2px solid #bbdefb; background-color: #e3f2fd50; color:#1976d2;">{f_val_str} {html_generator.pill_html(f_val_T, n_T1) if f_val_T > 0 else ""}</td></tr>
            <tr><td>基准(T-1)</td><td>{d_T1.strftime('%m-%d') if d_T1 else '无'}</td><td>{t1_nav_str} {html_generator.pill_html(n_T1, n_T2, True) if d_T2 else ""}</td><td>{t1_exchange_rate_str}</td><td>{f_c_T1_str}</td><td>-</td></tr>
            </tbody></table></div></td></tr>"""
    
    # 生成主页行
    home_row = ""
    if not lof_df_sorted.empty:
        l_r = lof_df_sorted.iloc[0]
        h_p_cls, h_p_txt = "", "-"
        close_price = l_r.get('close', 0)
        if isinstance(est_home, (int, float)) and est_home > 0 and isinstance(close_price, (int, float)) and close_price > 0:
            h_p_cls, h_p_txt = html_generator.format_color((close_price / est_home - 1) * 100)
        
        tag_html = f'<span class="type-tag tag-gold">{category}</span>' if category == "黄金" else \
                   f'<span class="type-tag tag-oil">{category}</span>' if category == "原油" else \
                   f'<span class="type-tag tag-other">{category}</span>'
        
        # 处理est_home为字符串的情况
        est_home_display = est_home if isinstance(est_home, (int, float)) else "无"
        # 如果est_home为0，尝试从其他行获取有效数据
        if est_home == 0:
            valid_estimates = []
            for _, row in lof_df_sorted.iterrows():
                val = row.get('static_valuation', 0)
                try:
                    # 核心修复：坚信 012 算出的结果，只要有有效数字，它就是最新日期的估值
                    val_float = float(val)
                    if val_float > 0:
                        valid_estimates.append(val_float)
                        try: est_home_date = row['date'].strftime('%m-%d')
                        except Exception: est_home_date = str(row['date'])[-5:]
                        break
                except:
                    pass
            if valid_estimates:
                est_home = valid_estimates[0]
                est_home_display = est_home
            else:
                # 如果没有有效的静态官方估值，设置为"无"
                est_home_display = "无"
        est_home_str = f"{est_home_display:.4f}" if isinstance(est_home_display, (int, float)) else est_home_display
        
        # 处理收盘价为非数字的情况
        close_str = f"{close_price:.3f}" if isinstance(close_price, (int, float)) and close_price > 0 else "无"
        
        # 确定显示的价格类型和日期
        price_date = est_home_date
        
        # 获取最近一个交易日的收盘价
        latest_valid_close = 0  # 核心修复：防止底层报错崩溃
        valid_closes = lof_df_sorted[lof_df_sorted['close'] > 0]
        if not valid_closes.empty:
            latest_valid_close = valid_closes.iloc[0]['close']
            latest_close_date = valid_closes.iloc[0]['date'].strftime('%m-%d')
            close_str = f"{latest_valid_close:.3f}"
            price_date = latest_close_date
        else:
            close_str = "无"
        
        # 计算T-1溢价，使用实时价除以静态官方估值
        h_p_cls, h_p_txt = "", "-"
        if isinstance(est_home, (int, float)) and est_home > 0:
            if not valid_closes.empty:
                latest_valid_close = valid_closes.iloc[0]['close']
                h_p_cls, h_p_txt = html_generator.format_color((latest_valid_close / est_home - 1) * 100)
        
        # 计算估值误差比例（只有同一天的数据才进行计算）
        h_err_cls, h_err_txt = "", "-"
        if isinstance(est_home, (int, float)) and est_home > 0 and nav_home > 0 and est_home_date == nav_home_date:
            h_err_cls, h_err_txt = html_generator.format_color((est_home / nav_home - 1) * 100)
      
        # 计算期货实时估值
        future_valuation = 0.0
        future_premium = 0.0
        future_price = 0.0
        
        exact_future_valuation = 0.0
        exact_future_premium = 0.0
        
        # 白银期货特殊处理
        silver_future_data = None
        vwap = 0.0
        settlement_price = 0.0
        
        # 获取期货校准值（使用从basic表格中获取的校准值）
        gold_calib = gold_calibration
        oil_calib = oil_calibration
                
        # 从API获取期货实时数据
        try:
            # 使用传入的futures_data参数
            if futures_data:
                # 提取期货价格
                if category == '黄金' and 'GC' in futures_data:
                    future_price = futures_data['GC']['price']
                    # 计算期货实时估值
                    if future_price > 0 and nav_home > 0:
                        # 找到基准日期的汇率
                        base_date = None
                        base_exchange_rate = 0.0
                        for _, row in lof_df_sorted.iterrows():
                            nav_val = row.get('nav', 0)
                            fx_val = row.get('exchange_rate', 0)
                            if pd.notna(nav_val) and nav_val is not None and pd.notna(fx_val) and fx_val is not None:
                                try:
                                    if float(nav_val) > 0 and float(fx_val) > 0:
                                        base_date = row['date']
                                        base_exchange_rate = float(fx_val)
                                        break
                                except (ValueError, TypeError):
                                    pass
                        
                        if base_exchange_rate <= 0:
                            raise ValueError("没有找到基准汇率，严禁使用固定值，强制熔断")
                        
                        # 严禁降级！获取当期真实汇率，若无则熔断
                        current_exchange_rate = today_exchange_rate_float
                        if current_exchange_rate <= 0:
                            raise ValueError("没有找到今日汇率，严禁使用固定值，强制熔断")
                        
                        # 计算汇率变化率
                        exchange_rate_change = current_exchange_rate / base_exchange_rate
                        
                        # 计算期货ETF = 期货实时价格 / 校准值
                        futures_etf = future_price / gold_calib
                        
                        # 计算加权平均变化率
                        weighted_futures_change_rate = 0.0
                        
                        # 收集有效的ETF（权重≥2%）
                        valid_etfs = []
                        total_valid_weight = 0.0
                        
                        for item in h_list:
                            symbol = item['symbol']
                            weight = item.get('weight', 0.0)
                            if weight <= 0 or weight < 2.0 or 'SLV' in symbol:
                                continue
                            valid_etfs.append(item)
                            total_valid_weight += weight
                        
                        # 计算加权平均变化率
                        if total_valid_weight > 0:
                            for item in valid_etfs:
                                symbol = item['symbol']
                                weight = item.get('weight', 0.0)
                                
                                # 获取基准日期的ETF价格
                                base_etf_price = 0.0
                                for _, row in lof_df_sorted.iterrows():
                                    if row.get('date') == base_date:
                                        if symbol in row:
                                            etf_price = row.get(symbol, 0)
                                            if isinstance(etf_price, (int, float)) and etf_price > 0:
                                                base_etf_price = etf_price
                                        break
                                
                                if base_etf_price > 0:
                                    etf_change_rate = futures_etf / base_etf_price
                                    normalized_weight = weight / total_valid_weight
                                    weighted_futures_change_rate += etf_change_rate * normalized_weight
                        else:
                            weighted_futures_change_rate = futures_etf / 100
                        
                        if total_valid_weight <= 0:
                            weighted_futures_change_rate = 1.0
                        
                        # 计算期货实时估值（套用实时估值公式）
                        net_value_change_ratio = pos_float * (weighted_futures_change_rate * exchange_rate_change - 1)
                        future_valuation = nav_home * (1 + net_value_change_ratio)
                        
                        # 计算期货实时溢价
                        if latest_valid_close > 0 and future_valuation > 0:
                            future_premium = (latest_valid_close - future_valuation) / future_valuation * 100
                            
                        # 新增：精准期货估值 (利用 T-1 期货收盘价)
                        if futures_history_df is not None and not futures_history_df.empty and base_date is not None:
                            base_date_str = base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else str(base_date)[:10]
                            
                            # 直接从 012 产出的完美表里面读取基准日期货结算价，稳如泰山
                            base_future_price = 0.0
                            if '期货结算价' in df_idx.columns:
                                val = df_idx.loc[base_date].get('期货结算价')
                                if pd.notna(val) and val != '无' and val != '':
                                    base_future_price = float(val)

                            # 如果 basic_df 中没有，则降级到 futures_history.csv
                            if base_future_price <= 0 and base_date_str in futures_history_df.index:
                                val = futures_history_df.loc[base_date_str].get('GC_close', 0.0)
                                if isinstance(val, pd.Series): val = val.iloc[0]
                                base_future_price = float(val) if pd.notna(val) else 0.0

                            if base_future_price > 0:
                                future_change_rate = future_price / base_future_price
                                net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                                exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                                if latest_valid_close > 0 and exact_future_valuation > 0:
                                    exact_future_premium = (latest_valid_close - exact_future_valuation) / exact_future_valuation * 100
                
                elif category == '原油' and 'CL' in futures_data:
                    future_price = futures_data['CL']['price']
                    if future_price > 0 and nav_home > 0:
                        base_date = None
                        base_exchange_rate = 0.0
                        for _, row in lof_df_sorted.iterrows():
                            nav_val = row.get('nav', 0)
                            fx_val = row.get('exchange_rate', 0)
                            if pd.notna(nav_val) and nav_val is not None and pd.notna(fx_val) and fx_val is not None:
                                try:
                                    if float(nav_val) > 0 and float(fx_val) > 0:
                                        base_date = row['date']
                                        base_exchange_rate = float(fx_val)
                                        break
                                except (ValueError, TypeError):
                                    pass
                        
                        if base_exchange_rate <= 0:
                            raise ValueError("没有找到基准汇率，严禁使用固定值，强制熔断")
                        
                        # 严禁降级！获取当期真实汇率，若无则熔断
                        current_exchange_rate = today_exchange_rate_float
                        if current_exchange_rate <= 0:
                            raise ValueError("没有找到今日汇率，严禁使用固定值，强制熔断")
                        
                        exchange_rate_change = current_exchange_rate / base_exchange_rate
                        futures_etf = future_price / oil_calib
                        
                        weighted_futures_change_rate = 0.0
                        valid_etfs = []
                        total_valid_weight = 0.0
                        
                        for item in h_list:
                            symbol = item['symbol']
                            weight = item.get('weight', 0.0)
                            if weight <= 0 or weight < 2.0 or 'SLV' in symbol:
                                continue
                            valid_etfs.append(item)
                            total_valid_weight += weight
                        
                        if total_valid_weight > 0:
                            for item in valid_etfs:
                                symbol = item['symbol']
                                weight = item.get('weight', 0.0)
                                
                                base_etf_price = 0.0
                                for _, row in lof_df_sorted.iterrows():
                                    if row.get('date') == base_date:
                                        if symbol in row:
                                            etf_price = row.get(symbol, 0)
                                            if isinstance(etf_price, (int, float)) and etf_price > 0:
                                                base_etf_price = etf_price
                                        break
                                
                                if base_etf_price > 0:
                                    etf_change_rate = futures_etf / base_etf_price
                                    normalized_weight = weight / total_valid_weight
                                    weighted_futures_change_rate += etf_change_rate * normalized_weight
                        else:
                            weighted_futures_change_rate = futures_etf / 100
                        
                        if total_valid_weight <= 0:
                            weighted_futures_change_rate = 1.0
                        
                        net_value_change_ratio = pos_float * (weighted_futures_change_rate * exchange_rate_change - 1)
                        future_valuation = nav_home * (1 + net_value_change_ratio)
                        
                        if latest_valid_close > 0 and future_valuation > 0:
                            future_premium = (latest_valid_close - future_valuation) / future_valuation * 100
                            
                        # 新增：精准期货估值 (利用 T-1 期货收盘价)
                        if futures_history_df is not None and not futures_history_df.empty and base_date is not None:
                            base_date_str = base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else str(base_date)[:10]
                            
                            base_future_price = 0.0
                            if '期货结算价' in df_idx.columns:
                                val = df_idx.loc[base_date].get('期货结算价')
                                if pd.notna(val) and val != '无' and val != '':
                                    base_future_price = float(val)

                            if base_future_price <= 0 and base_date_str in futures_history_df.index:
                                val = futures_history_df.loc[base_date_str].get('CL_close', 0.0)
                                if isinstance(val, pd.Series): val = val.iloc[0]
                                base_future_price = float(val) if pd.notna(val) else 0.0

                            if base_future_price > 0:
                                future_change_rate = future_price / base_future_price
                                net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                                exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                                if latest_valid_close > 0 and exact_future_valuation > 0:
                                    exact_future_premium = (latest_valid_close - exact_future_valuation) / exact_future_valuation * 100
                
                elif category == '指数' and future_symbol and future_symbol in futures_data:
                    future_price = futures_data[future_symbol]['price']
                    if future_price > 0 and nav_home > 0:
                        base_date = None
                        base_exchange_rate = 0.0
                        for _, row in lof_df_sorted.iterrows():
                            nav_val = row.get('nav', 0)
                            fx_val = row.get('exchange_rate', 0)
                            if pd.notna(nav_val) and nav_val is not None and pd.notna(fx_val) and fx_val is not None:
                                try:
                                    if float(nav_val) > 0 and float(fx_val) > 0:
                                        base_date = row['date']
                                        base_exchange_rate = float(fx_val)
                                        break
                                except (ValueError, TypeError):
                                    pass
                        
                        if base_exchange_rate <= 0:
                            raise ValueError("没有找到基准汇率，严禁使用固定值，强制熔断")
                        
                        # 严禁降级！获取当期真实汇率，若无则熔断
                        current_exchange_rate = today_exchange_rate_float
                        if current_exchange_rate <= 0:
                            raise ValueError("没有找到今日汇率，严禁使用固定值，强制熔断")
                        
                        exchange_rate_change = current_exchange_rate / base_exchange_rate
                        
                        # 指数只有精准纯期货实时估值，不需要校准值
                        if futures_history_df is not None and not futures_history_df.empty and base_date is not None:
                            base_date_str = base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else str(base_date)[:10]
                            
                            base_future_price = 0.0
                            if '期货结算价' in df_idx.columns:
                                val = df_idx.loc[base_date].get('期货结算价')
                                if pd.notna(val) and val != '无' and val != '':
                                    base_future_price = float(val)

                            if base_future_price <= 0 and base_date_str in futures_history_df.index:
                                val = futures_history_df.loc[base_date_str].get(f'{future_symbol}_close', 0.0)
                                if isinstance(val, pd.Series): val = val.iloc[0]
                                base_future_price = float(val) if pd.notna(val) else 0.0

                            if base_future_price > 0:
                                future_change_rate = future_price / base_future_price
                                net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                                exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                                if latest_valid_close > 0 and exact_future_valuation > 0:
                                    exact_future_premium = (latest_valid_close - exact_future_valuation) / exact_future_valuation * 100
                
        except Exception as e:
            print(f"获取期货数据失败: {e}")
            
        # 特殊处理161226（白银期货）保证无论如何都显示
        if code == '161226':
            global silver_fund_data
            
            ag0_data = futures_data.get('AG0', {}) if futures_data else {}
            ag_future_price = ag0_data.get('price', 0)
            settlement_price = ag0_data.get('settlement', 0)
            vwap = ag0_data.get('vwap', 0)
            
            if ag_future_price > 0 and settlement_price > 0 and nav_home > 0:
                # 坚决不兜底，实事求是：VWAP是多少就是多少，如果是0就让估值为0
                eff_vwap = vwap
                official_valuation = nav_home * (eff_vwap / settlement_price) if eff_vwap > 0 else 0
                
                reference_valuation = nav_home * (1 + ag_future_price / settlement_price - 1)
                official_premium = (latest_valid_close - official_valuation) / official_valuation * 100 if official_valuation > 0 else 0
                reference_premium = (latest_valid_close - reference_valuation) / reference_valuation * 100 if reference_valuation > 0 else 0
            else:
                official_valuation = 0
                reference_valuation = 0
                official_premium = 0
                reference_premium = 0

            silver_fund_data = {
                'code': code,
                'name': name,
                'close': latest_valid_close if 'latest_valid_close' in locals() else 0,
                'nav': nav_home,
                'future_price': ag_future_price,
                'vwap': vwap if vwap > 0 else 0,
                'eff_vwap': eff_vwap if 'eff_vwap' in locals() else 0,
                'settlement_price': settlement_price,
                'official_valuation': official_valuation,
                'reference_valuation': reference_valuation,
                'official_premium': official_premium,
                'reference_premium': reference_premium
            }
            
            future_price = ag_future_price
            future_valuation = 0
            future_premium = 0
            exact_future_valuation = 0
            exact_future_premium = 0
        
        # 格式化期货数据
        future_price_str = f"{future_price:.2f}" if future_price > 0 else "-"
        future_valuation_str = f"{future_valuation:.4f}" if future_valuation > 0 else "-"
        future_premium_str = f"{future_premium:+.2f}%" if future_valuation > 0 else "-"
        
        # 为期货溢价设置颜色
        future_premium_cls = "" if future_premium == 0 else ("premium-positive" if future_premium > 0 else "premium-negative")
        
        # 套利指示灯：<= -0.8% (折价) 红灯闪烁，否则绿灯休眠
        future_light_html = ""
        if future_premium_str != '-':
            if future_premium <= -0.8:
                future_light_html = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>'
            else:
                future_light_html = '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'
        
        # 构建估值+溢价的组合显示
        etf_valuation_display = f'<span class="num-font" id="realtime-valuation-{code}">-</span>'
        etf_valuation_display += f'<br><span class="num-font" id="realtime-premium-{code}" style="font-size:14px;">-</span><span id="realtime-light-{code}"></span>'
        
        futures_valuation_display = f'<span class="num-font" id="rt-calib-val-{code}">{future_valuation_str}</span>'
        if future_premium_str != '-':
            futures_valuation_display += f'<br><span class="num-font {future_premium_cls}" id="rt-calib-prem-{code}" style="font-size:14px;">{future_premium_str}</span><span id="rt-calib-light-{code}">{future_light_html}</span>'
        else:
            futures_valuation_display += f'<br><span class="num-font" id="rt-calib-prem-{code}" style="font-size:14px;"></span><span id="rt-calib-light-{code}"></span>'
            
        exact_future_valuation_str = f"{exact_future_valuation:.4f}" if exact_future_valuation > 0 else "-"
        exact_future_premium_str = f"{exact_future_premium:+.2f}%" if exact_future_valuation > 0 else "-"
        exact_future_premium_cls = "" if exact_future_premium == 0 else ("premium-positive" if exact_future_premium > 0 else "premium-negative")
        exact_future_light_html = ""
        if exact_future_premium_str != '-':
            if exact_future_premium <= -0.8:
                exact_future_light_html = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>'
            else:
                exact_future_light_html = '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'
                
        exact_futures_valuation_display = f'<span class="num-font" id="rt-exact-val-{code}">{exact_future_valuation_str}</span>'
        if exact_future_premium_str != '-':
            exact_futures_valuation_display += f'<br><span class="num-font {exact_future_premium_cls}" id="rt-exact-prem-{code}" style="font-size:14px;">{exact_future_premium_str}</span><span id="rt-exact-light-{code}">{exact_future_light_html}</span>'
        else:
            exact_futures_valuation_display += f'<br><span class="num-font" id="rt-exact-prem-{code}" style="font-size:14px;"></span><span id="rt-exact-light-{code}"></span>'
        
        # 为指数表准备的合并实时估值单元格
        combined_realtime_td_index = f"""
        <td colspan="2" onclick="window.openSandbox('{code}', 'etf')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="padding: 0;">
            <div style="display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;">
                <div style="flex: 1; width: 140px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{etf_valuation_display}</div>
                <div style="flex: 1; width: 140px; padding: 8px 4px;">{exact_futures_valuation_display}</div>
            </div>
        </td>"""
        
        # 为大宗商品准备的合并实时估值单元格
        combined_realtime_td_main = f"""
        <td colspan="3" onclick="window.openSandbox('{code}', 'etf')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="padding: 0;">
            <div style="display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;">
                <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{etf_valuation_display}</div>
                <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{futures_valuation_display}</div>
                <div style="flex: 1; width: 120px; padding: 8px 4px;">{exact_futures_valuation_display}</div>
            </div>
        </td>"""

        # ==========================================
        # 实时盘中沙盘 (Sandbox) 基础数据提取
        # ==========================================
        rt_base_date_str = "无"
        rt_base_nav = 0.0
        rt_base_fx = None
        base_etfs_text = ""
        base_future_price = 0.0
        
        for _, row in lof_df_sorted.iterrows():
            nav_val = row.get('nav', 0)
            if pd.notna(nav_val) and nav_val is not None:
                try:
                    if float(nav_val) > 0:
                        rt_base_date_str = row['date'].strftime('%Y-%m-%d')
                        rt_base_nav = float(nav_val)
                        rt_base_fx = row.get('exchange_rate')
                        if pd.isna(rt_base_fx):
                            rt_base_fx = None
                        else:
                            rt_base_fx = float(rt_base_fx)
                        etf_texts = []
                        for item in h_list:
                            sym = item['symbol']
                            val = row.get(sym, 0)
                            weight_col = f"{sym}权重"
                            weight = row.get(weight_col, 0.0)
                            if pd.isna(weight):
                                weight = 0.0
                            weight = float(weight)
                            if pd.notna(val) and val is not None and val != '无' and val != '':
                                try:
                                    val_float = float(val)
                                    if val_float > 0:
                                        if weight > 0:
                                            etf_texts.append(f"{sym}: {val_float:.2f} 权重 {weight:.1f}%")
                                        else:
                                            etf_texts.append(f"{sym}: {val_float:.2f}")
                                except:
                                    pass
                        base_etfs_text = " | ".join(etf_texts)
                        
                        # 新增：提取期货基准价供 Sandbox 验算使用
                        if future_symbol and '期货结算价' in row:
                            val = row.get('期货结算价')
                            if pd.notna(val) and val != '无' and val != '':
                                base_future_price = float(val)
                                
                        break
                except (ValueError, TypeError):
                    pass
                
        if not base_etfs_text:
            base_etfs_text = "无数据"
            
        unique_base_syms = []
        for item in h_list:
            sym = item['symbol']
            base_sym = 'GLD' if 'GLD' in sym else ('USO' if 'USO' in sym else ('XOP' if 'XOP' in sym else ('SLV' if 'SLV' in sym else sym)))
            if base_sym not in unique_base_syms:
                unique_base_syms.append(base_sym)
                
        base_inputs_html = ""
        for b_sym in unique_base_syms:
            base_inputs_html += f"""
                <div style="display: flex; align-items: center; gap: 5px;">
                    <span style="color:#1565c0; font-size:14px; font-weight:bold;">{b_sym} 测试价:</span>
                    <input type="number" class="sandbox-input-{code}" data-base="{b_sym.lower()}" step="0.01" style="width: 70px; padding: 4px; font-size: 14px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; color:#1565c0; font-weight:bold;" oninput="window.calcSandbox('{code}')">
                </div>"""

        # 决定默认的外盘交易标的
        trade_etf_raw = fund.get("trade_etf", "SPY")
        trade_etfs = [s.strip().upper() for s in str(trade_etf_raw).replace('，', ',').split(',') if s.strip()]
        if not trade_etfs:
            trade_etfs = ["SPY"]
        default_us_symbol = trade_etfs[0]

        # 定义交易UI组件 - 三套对冲测算 + 完整交易操作
        # 布局技术说明：
        # 1. 使用Flexbox布局实现响应式设计
        # 2. 采用垂直堆叠的容器结构，每个区域独立成块
        # 3. 所有区域使用justify-content: center实现水平居中
        # 4. 使用flex-wrap: wrap确保在小屏幕上自动换行
        # 5. 统一设置区域宽度和间距，确保视觉一致性
        # 6. 移除了之前的transform平移，使用自然的Flex布局实现对齐
        def get_three_hedge_calculations_with_trade():
            html = f"""
                    <!-- 【布局技术：Flexbox垂直容器】用于垂直堆叠各个功能区域 -->
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px dashed #ffd54f; display: flex; flex-direction: column; gap: 12px; align-items: center; width: 100%; max-width: 1400px; margin-left: auto; margin-right: auto;">
                        <!-- 【区域名称：对冲数量区】三套对冲测算并排显示 -->
                        <!-- 【布局技术：Flexbox水平容器】用于并排显示三个对冲数量面板 -->
                        <div style="display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; width: 100%;">
                            <!-- 对冲数量区-1：ETF实时估值对冲数量 -->
                            <div style="display: flex; flex-direction: column; gap: 5px; background: var(--theme-etf-bg); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--theme-etf-border); flex: 1; min-width: 360px; box-sizing: border-box;">
                                <div style="text-align: center; font-weight: bold; color: var(--theme-etf-text); font-size: 13px; margin-bottom: 4px;">ETF实时估值   对冲数量</div>
                                <div style="display: flex; align-items: center; justify-content: center; gap: 6px; flex-wrap: wrap;">
                                    <span style="font-size:11px; color:#333;">投入</span>
                                    <input type="number" id="sb-target-capital-{code}-etf" value="100000" step="1000" oninput="window.calcHedgeQty('{code}', 'etf')" style="width: 60px; padding: 2px 4px; font-size: 11px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                                    <span style="font-size:11px; color:#333;">元 →</span>
                                    <span style="font-size:11px; color:#333;">LOF</span>
                                    <span id="sb-lof-qty-{code}-etf" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">?</span>
                                    <span style="font-size:11px; color:#333;">股 +</span>
                                    <span style="font-size:11px; color:#333;">{" + ".join(trade_etfs)}</span>
                                    <span id="sb-etf-qty-{code}-etf" class="num-font" style="font-size: 13px; color: #1565c0; font-weight:bold; min-width:30px; text-align:center; display:inline-block;">?</span>
                                    <span style="font-size:11px; color:#333;">股</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; font-size:10px; color:#666; margin-top: 2px;">
                                    <span>单位对冲值(k): <span id="sb-debug-hedge-{code}-etf" class="num-font" style="color:#1565c0;">-</span></span>
                                    <span>目标底层敞口: <span id="sb-debug-exposure-{code}-etf" class="num-font" style="color:#e65100;">-</span></span>
                                </div>
                                <!-- 锚点ETF数量显示 -->
                                <div style="display: flex; flex-wrap: wrap; gap: 8px; font-size:10px; color:#666; margin-top: 4px; justify-content: center;">
                                    <span id="sb-anchor-etfs-{code}-etf" style="width: 100%; text-align: center;">锚点ETF数量: -</span>
                                </div>
                            </div>
            """
            
            if has_future:
                html += f"""
                            <!-- 对冲数量区-2：期货校准估值对冲数量 -->
                            <div style="display: flex; flex-direction: column; gap: 5px; background: var(--theme-fut-bg); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--theme-fut-border); flex: 1; min-width: 360px; box-sizing: border-box;">
                                <div style="text-align: center; font-weight: bold; color: var(--theme-fut-text); font-size: 13px; margin-bottom: 4px;">期货校准估值   对冲数量</div>
                                <div style="display: flex; align-items: center; justify-content: center; gap: 6px; flex-wrap: wrap;">                                    <span style="font-size:11px; color:#333;">交易</span>
                                    <input type="number" id="sb-target-futures-lots-{code}-future" value="1" step="1" oninput="window.calcHedgeQty('{code}', 'future', true)" style="width: 60px; padding: 2px 4px; font-size: 11px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                                    <span style="font-size:11px; color:#333;">手期货 →</span>
                                    <span style="font-size:11px; color:#333;">对应 LOF</span>
                                    <span id="sb-lof-qty-{code}-future" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">?</span>
                                    <span style="font-size:11px; color:#333;">股</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; font-size:10px; color:#666; margin-top: 2px;">
                                    <span>单位对冲值(k): <span id="sb-debug-hedge-{code}-future" class="num-font" style="color:#1565c0;">-</span></span>
                                    <span>目标底层敞口: <span id="sb-debug-exposure-{code}-future" class="num-font" style="color:#e65100;">-</span></span>
                                </div>
                            </div>
                            
                            <!-- 对冲数量区-3：纯期货估值对冲数量 -->
                            <div style="display: flex; flex-direction: column; gap: 5px; background: var(--theme-pure-bg); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--theme-pure-border); flex: 1; min-width: 360px; box-sizing: border-box;">
                                <div style="text-align: center; font-weight: bold; color: var(--theme-pure-text); font-size: 13px; margin-bottom: 4px;">纯期货估值   对冲数量</div>
                                <div style="display: flex; align-items: center; justify-content: center; gap: 6px; flex-wrap: wrap;">                                    <span style="font-size:11px; color:#333;">交易</span>
                                    <input type="number" id="sb-target-futures-lots-{code}-pure_future" value="1" step="1" oninput="window.calcHedgeQty('{code}', 'pure_future', true)" style="width: 60px; padding: 2px 4px; font-size: 11px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; font-weight:bold; text-align:center; color:#d35400;">
                                    <span style="font-size:11px; color:#333;">手期货 →</span>
                                    <span style="font-size:11px; color:#333;">对应 LOF</span>
                                    <span id="sb-lof-qty-{code}-pure_future" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">?</span>
                                    <span style="font-size:11px; color:#333;">股</span>
                                </div>
                                <div style="display: flex; justify-content: space-between; font-size:10px; color:#666; margin-top: 2px;">
                                    <span>单位对冲值(k): <span id="sb-debug-hedge-{code}-pure_future" class="num-font" style="color:#1565c0;">-</span></span>
                                    <span>目标底层敞口: <span id="sb-debug-exposure-{code}-pure_future" class="num-font" style="color:#e65100;">-</span></span>
                                </div>
                            </div>
                """

            html += f"""
                        </div>

                        <!-- 【区域名称：实时盘口区】 -->
                        <div style="display: flex; gap: 50px; justify-content: center; flex-wrap: wrap; width: 100%;">
            """
            
            for idx, us_sym in enumerate(trade_etfs):
                suffix = f"etf" if idx == 0 else f"etf_{idx}"
                html += f"""
                            <!-- 实时盘口区-1：ETF实时盘口 ({us_sym}) -->
                            <div style="display: inline-flex; gap: 8px; font-size: 12px; background: var(--theme-etf-bg); padding: 5px 10px; border-radius: 4px; border: 1px solid var(--theme-etf-border); justify-content: flex-start; box-sizing: border-box;">
                                <span style="color:#666;">📊 <b style="color:var(--theme-etf-text);">{us_sym}</b> 实时盘口:</span>
                                <span style="color:#2e7d32; font-weight:bold; cursor:pointer; padding: 0 4px; border-radius: 3px;" onclick="document.getElementById('ib-trade-price-{code}-{suffix}').value = document.getElementById('sb-ib-bid-{code}-{suffix}').innerText" title="点击将买一价填入限价框" onmouseover="this.style.backgroundColor='#e8f5e9'" onmouseout="this.style.backgroundColor='transparent'">买一(Bid): <span id="sb-ib-bid-{code}-{suffix}">未能读到实时数据</span></span>
                                <span style="color:#d32f2f; font-weight:bold; cursor:pointer; padding: 0 4px; border-radius: 3px;" onclick="document.getElementById('ib-trade-price-{code}-{suffix}').value = document.getElementById('sb-ib-ask-{code}-{suffix}').innerText" title="点击将卖一价填入限价框" onmouseover="this.style.backgroundColor='#ffebee'" onmouseout="this.style.backgroundColor='transparent'">卖一(Ask): <span id="sb-ib-ask-{code}-{suffix}">未能读到实时数据</span></span>
                                <span style="color:#999; font-size: 10px;">(点击填入)</span>
                            </div>
                """
            
            if has_future:
                html += f"""
                            <!-- 实时盘口区-2：期货实时盘口 -->
                            <div style="display: inline-flex; gap: 8px; font-size: 12px; background: var(--theme-pure-bg); padding: 5px 10px; border-radius: 4px; border: 1px solid var(--theme-pure-border); justify-content: flex-start; box-sizing: border-box;">
                                <span style="color:#666;">📊 <b style="color:var(--theme-pure-text);">{future_symbol}</b> 实时盘口:</span>
                                <span style="color:#2e7d32; font-weight:bold; cursor:pointer; padding: 0 4px; border-radius: 3px;" title="点击将买一价填入限价框" onmouseover="this.style.backgroundColor='#e8f5e9'" onmouseout="this.style.backgroundColor='transparent'">买一(Bid): <span id="sb-future-bid-{code}">未能读到实时数据</span></span>
                                <span style="color:#d32f2f; font-weight:bold; cursor:pointer; padding: 0 4px; border-radius: 3px;" title="点击将卖一价填入限价框" onmouseover="this.style.backgroundColor='#ffebee'" onmouseout="this.style.backgroundColor='transparent'">卖一(Ask): <span id="sb-future-ask-{code}">未能读到实时数据</span></span>
                                <span style="color:#999; font-size: 10px;">(点击填入)</span>
                            </div>
                """

            html += f"""
                        </div>

                        <!-- 【区域名称：下单区】 -->
                        <div style="display: flex; gap: 40px; justify-content: center; flex-wrap: wrap; width: 100%;">
                            <!-- 下单区-1：A股 LOF下单区 (支持QMT/TDX双通道) -->
                            <div style="display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 320px;">
                                <div style="display: flex; align-items: center; gap: 4px; background: #fff5f5; padding: 3px 8px; border-radius: 4px; border: 1px solid #ffcdd2; white-space: nowrap;">
                                    <select id="trade-broker-{code}-etf" style="font-size:11px; padding:1px; border:1px solid #ffcdd2; border-radius:3px; background:#fff; color:#d32f2f; font-weight:bold; cursor:pointer;" title="选择实盘交易通道">
                                        <option value="yinhe_qmt">银河QMT (8888)</option>
                                        <option value="guojin_qmt">国金QMT (原生)</option>
                                        <option value="tdx">通达信(暂无下单功能)</option>
                                    </select>
                                    <span style="font-weight:bold; color:#d32f2f; font-size:11px;">{name}:</span>
                                    <span style="color:#666; font-size: 11px;">数量:</span>
                                    <input type="number" id="trade-vol-{code}-etf" value="100" step="100" oninput="this.dataset.manual='true'" style="width:60px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; font-size:11px;">
                                    <span style="color:#666; font-size: 11px;">限价:</span>
                                    <input type="number" id="trade-price-{code}-etf" step="0.001" style="width:60px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; color:#d32f2f; font-size:11px;">
                                </div>
                                <span id="trade-msg-{code}-etf" style="font-size:10px; font-weight:bold; height: 11px;"></span>
                            </div>
            """
            
            for idx, us_sym in enumerate(trade_etfs):
                suffix = f"etf" if idx == 0 else f"etf_{idx}"
                html += f"""
                            <!-- 下单区-2：IB ETF下单区 ({us_sym}) -->
                            <div style="display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 320px;">
                                <div style="display: flex; align-items: center; gap: 6px; background: #e3f2fd; padding: 3px 8px; border-radius: 4px; border: 1px solid #bbdefb; white-space: nowrap;">
                                    <span style="font-weight:bold; color:#1565c0; font-size:11px;">🌍 IB {us_sym}:</span>
                                    <input type="hidden" id="ib-trade-sym-{code}-{suffix}" value="{us_sym}">
                                    <span style="color:#666; font-size: 11px;">数量:</span>
                                    <input type="number" id="ib-trade-vol-{code}-{suffix}" value="10" step="1" oninput="this.dataset.manual='true'" style="width:60px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; font-size:11px;">
                                    <span style="color:#666; font-size: 11px;">限价:</span>
                                    <input type="number" id="ib-trade-price-{code}-{suffix}" step="0.01" style="width:80px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; color:#1565c0; font-size:11px;">
                                </div>
                                <span id="ib-trade-msg-{code}-{suffix}" style="font-size:10px; font-weight:bold; height: 11px;"></span>
                            </div>
                """
            
            if has_future:
                html += f"""
                            <!-- 下单区-3：IB期货下单区 -->
                            <div style="display: flex; flex-direction: column; align-items: flex-start; gap: 2px; width: 320px;">
                                <div style="display: flex; align-items: center; gap: 6px; background: #fff3e0; padding: 3px 8px; border-radius: 4px; border: 1px solid #ffcc80; white-space: nowrap;">
                                    <span style="font-weight:bold; color:#e65100; font-size:11px;">🌍 IB期货 ({future_symbol}):</span>
                                    <span style="color:#666; font-size: 11px;">数量:</span>
                                    <input type="number" id="ib-future-vol-{code}" value="1" step="1" oninput="this.dataset.manual='true'" style="width:60px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; font-size:11px;">
                                    <span style="color:#666; font-size: 11px;">限价:</span>
                                    <input type="number" id="ib-future-price-{code}" step="0.01" style="width:80px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; color:#e65100; font-size:11px;">
                                </div>
                                <span id="ib-future-msg-{code}" style="font-size:10px; font-weight:bold; height: 11px;"></span>
                            </div>
                """

            html += f"""
                        </div>

                        <!-- 【区域名称：下单按键】 -->
                        <div style="display: flex; flex-direction: column; gap: 12px; width: 100%; max-width: 1100px;">
                            <!-- 第一行：买入/开仓按键 -->
                            <div style="display: flex; gap: 50px; justify-content: center; flex-wrap: wrap;">
                                <button onclick="window.executeTrade('{code}', 'BUY', 'etf')" style="background:#2e7d32; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(46,125,50,0.3); transition:0.2s;">{code} 折价买入</button>
            """
            
            for idx, us_sym in enumerate(trade_etfs):
                suffix = f"etf" if idx == 0 else f"etf_{idx}"
                html += f"""                                <button onclick="window.executeIbTrade('{code}', 'SELL', '{suffix}')" style="background:#e65100; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(230,81,0,0.3); transition:0.2s;">IB {us_sym} 卖空开仓</button>\n"""
            
            if has_future:
                html += f"""                    <button onclick="alert('期货交易功能开发中')" style="background:#e65100; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(230,81,0,0.3); transition:0.2s;">{future_symbol} 期货 卖空开仓</button>"""
                
            html += f"""
                            </div>
                            <!-- 第二行：卖出/平仓按键 -->
                            <div style="display: flex; gap: 50px; justify-content: center; flex-wrap: wrap;">
                                <button onclick="window.executeTrade('{code}', 'SELL', 'etf')" style="background:#d32f2f; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(211,47,47,0.3); transition:0.2s;">{code} 溢价卖出</button>
            """
            
            for idx, us_sym in enumerate(trade_etfs):
                suffix = f"etf" if idx == 0 else f"etf_{idx}"
                html += f"""                                <button onclick="window.executeIbTrade('{code}', 'BUY', '{suffix}')" style="background:#1565c0; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(21,101,192,0.3); transition:0.2s;">IB {us_sym} 买入平仓</button>\n"""
            
            if has_future:
                html += f"""                    <button onclick="alert('期货交易功能开发中')" style="background:#1565c0; color:white; border:none; padding:5px 0; width:180px; border-radius:4px; cursor:pointer; font-weight:bold; font-size:11px; box-shadow: 0 2px 4px rgba(21,101,192,0.3); transition:0.2s;">{future_symbol} 期货 买入平仓</button>"""
                
            html += f"""
                            </div>
                        </div>
                    </div>
            """
            return html

        if is_index_table:
            # 指数表只有两列实时估值
            home_row = f"""
            <tr style="user-select: none;">
                <td class="num-font" style="width: 60px;"><b>{code}</b></td><td style="width: 50px;">{tag_html}</td><td style='text-align: center; width: 90px;'>{name}</td>
                <td class="num-font" style="width: 45px;">{pos_float*100:.2f}%</td>
                <td style="width: 65px;"><span class="num-font">{nav_home:.4f}</span><span class="base-date-hint">{nav_home_date}</span></td>
                <td class="col-static-bg clickable-cell" onclick="showDetail('page-{code}')" title="点击查看【静态官方估值】对账明细" style="width: 95px;"><span class="num-font" style="font-weight:bold;color:#d35400">{est_home_str}</span><span class="base-date-hint">{est_home_date}</span></td>
                <td class="col-static-bg" style="width: 70px;"><span class="num-font">{close_str}</span><span class="base-date-hint">{price_date}</span></td>
                <td class="col-static-bg" style="width: 90px; border-right: 2px solid #fff;"><span class="num-font" id="realtime-price-{code}">-</span><br><span id="t-1-premium-{code}" class="num-font premium-big {h_p_cls}" style="font-size:14px;">{h_p_txt}</span></td>
                {combined_realtime_td_index}
            </tr>"""
        else:
            # 主表（大宗商品）有三列实时估值
            if category == '其他':
                home_row = f"""
                <tr style="user-select: none;">
                    <td class="num-font" style="width: 60px;"><b>{code}</b></td><td style="width: 50px;">{tag_html}</td><td style='text-align: center; width: 90px;'>{name}</td>
                    <td class="num-font" style="width: 45px;">{pos_float*100:.2f}%</td>
                    <td style="width: 65px;"><span class="num-font">{nav_home:.4f}</span><span class="base-date-hint">{nav_home_date}</span></td>
                    <td class="col-static-bg clickable-cell" onclick="showDetail('page-{code}')" title="点击查看【静态官方估值】对账明细" style="width: 95px;"><span class="num-font" style="font-weight:bold;color:#d35400">{est_home_str}</span><span class="base-date-hint">{est_home_date}</span></td>
                    <td class="col-static-bg" style="width: 70px;"><span class="num-font">{close_str}</span><span class="base-date-hint">{price_date}</span></td>
                    <td class="col-static-bg" style="width: 90px; border-right: 2px solid #fff;"><span class="num-font" id="realtime-price-{code}">-</span><br><span id="t-1-premium-{code}" class="num-font premium-big {h_p_cls}" style="font-size:14px;">{h_p_txt}</span></td>
                    <td onclick="window.openSandbox(\'{code}\', \'etf\')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="width: 120px;">{etf_valuation_display}</td>
                    <td colspan="2" style="color:#9e9e9e; text-align:center; width: 240px;">无期货对应</td>
                </tr>"""
            elif category == '纯ETF':
                # 纯ETF表格只显示ETF估值列，并且让列均匀分布
                home_row = f"""
                <tr style="user-select: none;">
                    <td class="num-font" style="width: 60px;"><b>{code}</b></td><td style="width: 50px;">{tag_html}</td><td style='text-align: center; width: 90px;'>{name}</td>
                    <td class="num-font" style="width: 45px;">{pos_float*100:.2f}%</td>
                    <td style="width: 65px;"><span class="num-font">{nav_home:.4f}</span><span class="base-date-hint">{nav_home_date}</span></td>
                    <td class="col-static-bg clickable-cell" onclick="showDetail('page-{code}')" title="点击查看【静态官方估值】对账明细" style="width: 95px;"><span class="num-font" style="font-weight:bold;color:#d35400">{est_home_str}</span><span class="base-date-hint">{est_home_date}</span></td>
                    <td class="col-static-bg" style="width: 70px;"><span class="num-font">{close_str}</span><span class="base-date-hint">{price_date}</span></td>
                    <td class="col-static-bg" style="width: 90px; border-right: 2px solid #fff;"><span class="num-font" id="realtime-price-{code}">-</span><br><span id="t-1-premium-{code}" class="num-font premium-big {h_p_cls}" style="font-size:14px;">{h_p_txt}</span></td>
                    <td onclick="window.openSandbox(\'{code}\', \'etf\')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="flex: 1; min-width: 200px;">{etf_valuation_display}</td>
                </tr>"""
            else:
                home_row = f"""
                <tr style="user-select: none;">
                    <td class="num-font" style="width: 60px;"><b>{code}</b></td><td style="width: 50px;">{tag_html}</td><td style='text-align: center; width: 90px;'>{name}</td>
                    <td class="num-font" style="width: 45px;">{pos_float*100:.2f}%</td>
                    <td style="width: 65px;"><span class="num-font">{nav_home:.4f}</span><span class="base-date-hint">{nav_home_date}</span></td>
                    <td class="col-static-bg clickable-cell" onclick="showDetail('page-{code}')" title="点击查看【静态官方估值】对账明细" style="width: 95px;"><span class="num-font" style="font-weight:bold;color:#d35400">{est_home_str}</span><span class="base-date-hint">{est_home_date}</span></td>
                    <td class="col-static-bg" style="width: 70px;"><span class="num-font">{close_str}</span><span class="base-date-hint">{price_date}</span></td>
                    <td class="col-static-bg" style="width: 90px; border-right: 2px solid #fff;"><span class="num-font" id="realtime-price-{code}">-</span><br><span id="t-1-premium-{code}" class="num-font premium-big {h_p_cls}" style="font-size:14px;">{h_p_txt}</span></td>
                    {combined_realtime_td_main}
                </tr>"""
    
    # 生成对冲ETF信息
    hedge_info = ""
    if h_list:
        hedge_info += "<div>对冲ETF: "
        for i, item in enumerate(h_list):
            symbol = item['symbol']
            weight = item.get('weight', 0)
            etf_name = symbol
            if i > 0:
                hedge_info += " + "
            hedge_info += f"{etf_name} ({weight:.2f}%)"
        hedge_info += "</div>"
    
    future_th_html = '<th class="col-future-bg-th">期货结算价</th><th class="col-future-bg-th">期货静态净值</th><th class="col-future-bg-th">期货溢价</th><th class="col-future-bg-th">期货估值误差</th>' if has_future else ''
    
    # 生成详情页面
    detail_page = ""
    if home_row:
        detail_page = f"""
        <div id="page-{code}" class="page-section card secondary-page">
            <div class="history-header" style="position: sticky; top: 0; z-index: 100; display: flex; align-items: center; justify-content: space-between; padding: 8px 15px !important; height: auto !important; min-height: 40px !important;">
                <div style="display: flex; align-items: center; gap: 20px;">
                    <div style="font-size:18px; font-weight:bold;">{name} ({code})</div>
                    <div style="font-size:13px; color:#333;">
                        基础仓位: <span style="font-weight:bold; color:#000;">{pos_float*100:.2f}%</span>
                        <span style="margin-left:30px; font-weight:bold; color:#000;">{hedge_info.replace('<div>对冲ETF: ', '对冲ETF: ').replace('</div>', '')}</span>
                    </div>
                </div>
                <button onclick="goHome()" class="back-btn">⬅ 返回主面板</button>
            </div>
            <div style="overflow-x: auto; max-height: calc(100vh - 250px);">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead style="position: sticky; top: 0; background-color: #e3f2fd; z-index: 10;">
                        <tr>
                                <th>日期</th><th>{rate_header_name}</th><th>净值</th><th>收盘价</th>{etf_th_html}<th class="col-etf-bg-th">ETF静态净值</th><th class="col-etf-bg-th">ETF溢价</th><th class="col-etf-bg-th">ETF估值误差</th>{future_th_html}<th>验算</th>
                        </tr>
                    </thead>
                    <tbody>{history_rows}</tbody>
                </table>
            </div>
        </div>"""
        
        if futures_history_rows:
            detail_page += f"""
            <div id="page-futures-{code}" class="page-section card secondary-page">
                <div class="history-header" style="position: sticky; top: 0; z-index: 100; background-color: #f8faff; display: flex; align-items: center; justify-content: space-between; padding: 8px 15px !important; height: auto !important; min-height: 40px !important;">
                    <div style="display: flex; align-items: center; gap: 20px;">
                        <div style="font-size:18px; font-weight:bold; color: #1976d2;">{name} ({code}) - 期货估值对账表</div>
                        <div style="font-size:13px; color:#333;">
                            基础仓位: <span style="font-weight:bold; color:#000;">{pos_float*100:.2f}%</span>
                            <span style="margin-left:30px; font-weight:bold; color:#000;">挂钩锚点: {future_symbol} 新浪期货历史收盘价</span>
                        </div>
                    </div>
                    <button onclick="goHome()" class="back-btn">⬅ 返回主面板</button>
                </div>
                <div style="overflow-x: auto; max-height: calc(100vh - 250px);">
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead style="position: sticky; top: 0; background-color: #e3f2fd; z-index: 10;">
                            <tr>
                                <th>日期</th><th>{rate_header_name}</th><th>{future_symbol}收盘价</th><th>期货估值</th><th>收盘价</th><th>期货溢价</th><th>净值</th><th>估值误差比例</th><th>验算</th>
                            </tr>
                        </thead>
                        <tbody>{futures_history_rows}</tbody>
                    </table>
                </div>
            </div>"""
            
        # 生成实时期货校准实时估值面板HTML
        future_panel_html = ""
        pure_future_panel_html = ""
        if future_symbol:
            future_panel_html = f"""
                <div style="background: var(--theme-fut-bg); padding: 10px; border-radius: 8px; border: 1px solid var(--theme-fut-border); box-shadow: var(--shadow-sm); flex: 1; min-width: 360px;">
                    <div style="text-align: center; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--theme-fut-border);">
                        <span style="font-size:15px; font-weight:bold; color:var(--theme-fut-text);">期货校准实时估值</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: center;">
                            <span style="color:#e65100; font-size:13px; font-weight:bold;">{future_symbol}测试价:</span>
                            <input type="number" id="sb-fut-price-{code}" step="0.01" style="width: 90px; padding: 3px; font-size: 13px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; color:#e65100; font-weight:bold;" oninput="window.calcFutureSandbox('{code}')">
                            <span style="color:#666; font-size:12px;">校准:</span>
                            <input type="number" id="sb-fut-calib-{code}" step="0.0001" style="width: 75px; padding: 3px; font-size: 13px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px;" value="{latest_calibration_factor if latest_calibration_factor > 0 else ''}" placeholder="{'' if latest_calibration_factor > 0 else '缺少'}" oninput="window.calcFutureSandbox('{code}')">
                            <span style="color:#666; font-size:13px; font-weight:bold;">校准ETF:</span>
                            <span id="sb-equiv-etf-{code}" class="num-font" style="font-size: 14px; font-weight: bold; color: #e65100;">-</span>
                        </div>
                        <div style="display: flex; align-items: center; gap: 16px; justify-content: center;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="color:#666; font-size:13px; font-weight:bold;">估值:</span>
                                <span id="sb-fut-val-{code}" class="num-font" style="font-size: 18px; font-weight: bold; color: #e65100;">-</span>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="color:#666; font-size:13px; font-weight:bold;">预测溢价:</span>
                                <span id="sb-fut-target-prem-{code}" class="num-font" style="font-size: 14px; font-weight: bold;">-</span>
                            </div>
                        </div>
                    </div>
                </div>
            """
            
            # 生成纯期货实时估值面板HTML
            pure_future_panel_html = f"""
                <div style="background: var(--theme-pure-bg); padding: 10px; border-radius: 8px; border: 1px solid var(--theme-pure-border); box-shadow: var(--shadow-sm); flex: 1; min-width: 360px;">
                    <div style="text-align: center; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--theme-pure-border);">
                        <span style="font-size:15px; font-weight:bold; color:var(--theme-pure-text);">纯期货实时估值</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 8px; justify-content: center;">
                            <span style="color:#e65100; font-size:13px; font-weight:bold;">{future_symbol}测试价:</span>
                            <input type="number" id="sb-pure-fut-price-{code}" step="0.01" style="width: 110px; padding: 3px; font-size: 13px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; color:#e65100; font-weight:bold;" oninput="window.calcPureFutureSandbox('{code}')">
                        </div>
                        <div style="display: flex; align-items: center; gap: 16px; justify-content: center;">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="color:#666; font-size:13px; font-weight:bold;">估值:</span>
                                <span id="sb-pure-val-{code}" class="num-font" style="font-size: 18px; font-weight: bold; color: #2e7d32;">-</span>
                            </div>
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span style="color:#666; font-size:13px; font-weight:bold;">预测溢价:</span>
                                <span id="sb-pure-target-prem-{code}" class="num-font" style="font-size: 14px; font-weight: bold;">-</span>
                            </div>
                        </div>
                    </div>
                </div>
            """
        
        # 构建完整的基准信息文本（去冗余优化）
        full_base_info = f'📅 <b>【T-1 基准日】</b> {rt_base_date_str}'
        full_base_info += f' | 💰 <b>净值:</b> <span class="num-font" style="color:var(--primary-dark);">{rt_base_nav:.4f}</span>'
        if rt_base_fx is not None:
            full_base_info += f' | 💱 <b>汇率:</b> <span class="num-font">{rt_base_fx:.4f}</span>'
        else:
            full_base_info += f' | 💱 <b>汇率:</b> <span class="num-font" style="color:var(--neg-color);">无数据</span>'
        full_base_info += f' | 📊 <b>ETF收盘价:</b> <span class="num-font">{base_etfs_text}</span>'
        if future_symbol:
            full_base_info += f' | 📊 <b>{future_symbol}结算价:</b> <span class="num-font" style="color:var(--theme-fut-text);">{base_future_price:.2f}</span>'
        
        detail_page += f"""
        <!-- ========== 二级面板：实时估值沙盘（简称"沙盘"） ========== -->
        <div id="page-rt-etf-{code}" class="page-section card secondary-page">
            <div class="history-header" style="position: sticky; top: 0; z-index: 100; background-color: #fffdf5; border-bottom: 2px solid #ffcc80; display: flex; align-items: center; justify-content: space-between; padding: 8px 15px !important; height: auto !important; min-height: 40px !important;">
                <div style="display: flex; align-items: center; gap: 20px;">
                    <div style="font-size:18px; font-weight:bold; color: #d35400;">{name} ({code}) - 实时估值计算器</div>
                    <div style="font-size:13px; color:#333;">基础仓位: <span style="font-weight:bold; color:#000;">{pos_float*100:.2f}%</span></div>
                </div>
                <button onclick="goHome()" class="back-btn">⬅ 返回主面板</button>
            </div>
            <div style="padding: 10px 15px;">
                <!-- 【区域名称：基准数据区】包含基准日、基准净值、基准汇率、基准日ETF收盘价、基准日期货结算价等 -->
                    <div style="background: var(--theme-base-bg); padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; border: 1px solid var(--theme-base-border); font-size: 13px; color: var(--theme-base-text);">
                    {full_base_info}
                </div>

                <!-- 【区域名称：LOF价格区】包含人民币中间价、A股LOF测试单价等 -->
                    <div style="background: #ffffff; padding: 8px 12px; border-radius: 6px; margin-bottom: 12px; border: 1px solid var(--border-color); box-shadow: var(--shadow-sm);">
                    <div style="display: flex; align-items: center; justify-content: center; gap: 18px; flex-wrap: wrap;">
                        <span style="color:#1976d2; font-size:13px; font-weight:bold;">{rate_header_name}:</span>
                        <span class="num-font" id="sb-exchange-rate-{code}" style="font-size: 15px; font-weight: bold; color: #1976d2;">{latest_exchange_rate if latest_exchange_rate > 0 else '-'}</span>
                        <span style="color:#d32f2f; font-size:13px; font-weight:bold;">A股 LOF 测试单价:</span>
                        <input type="number" id="sb-target-price-{code}" step="0.001" style="width: 95px; padding: 4px; font-size: 14px; font-family:Consolas; border: 1px solid #ccc; border-radius: 4px; color:#d32f2f; font-weight:bold;" title="手动输入测试单价" oninput="window.calcSandbox('{code}'); window.calcFutureSandbox('{code}'); window.calcPureFutureSandbox('{code}')">
                        <span style="color:#666; font-size:11px;">(该单价会同时用于三个估值计算)</span>
                    </div>
                </div>

                <!-- 【区域名称：实时估值区】三个估值面板并排显示：ETF实时估值、期货校准实时估值、期货实时估值 -->
                <div style="display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 15px;">
                    <!-- ETF实时估值面板 -->
                        <div style="background: var(--theme-etf-bg); padding: 10px; border-radius: 8px; border: 1px solid var(--theme-etf-border); box-shadow: var(--shadow-sm); flex: 1; min-width: 360px;">
                            <div style="text-align: center; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px dashed var(--theme-etf-border);">
                                <span style="font-size:15px; font-weight:bold; color:var(--theme-etf-text);">ETF实时估值</span>
                        </div>
                        <div style="display: flex; flex-direction: column; gap: 8px; align-items: center;">
                            <div style="display: flex; flex-direction: column; gap: 4px; align-items: center;">
                                {base_inputs_html}
                            </div>
                            <div style="display: flex; align-items: center; gap: 16px; justify-content: center;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="color:#666; font-size:13px; font-weight:bold;">估值:</span>
                                    <span id="sb-val-{code}" class="num-font" style="font-size: 18px; font-weight: bold; color: #1976d2;">-</span>
                                </div>
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="color:#666; font-size:13px; font-weight:bold;">预测溢价:</span>
                                    <span id="sb-target-prem-{code}" class="num-font" style="font-size: 14px; font-weight: bold;">-</span>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 期货校准实时估值面板 -->
                    {future_panel_html}
                    
                    <!-- 期货实时估值面板 -->
                    {pure_future_panel_html}
                </div>

                <!-- 【区域名称：对冲数量区】三套对冲测算并排显示：ETF实时估值对冲数量、期货校准估值对冲数量、纯期货估值对冲数量 -->
                <!-- 【区域名称：实时盘口区】两个盘口：GLD实时盘口、GC实时盘口 -->
                <!-- 【区域名称：下单区】两个下单区：QMT/IB ETF下单区、IB期货下单区 -->
                <!-- 【区域名称：下单按键】两行按键：买入按键（上一行）、卖出按键（下一行） -->
                {get_three_hedge_calculations_with_trade()}

                <div style="margin-top: 15px; font-size: 13px; color: #888;">* 提示：面板打开时会自动填入主面板实盘价作为默认测试价。您可以随意修改输入框内的值，点击计算后推演该价位溢价率，不影响主面板自动刷新。</div>
            </div>
        </div>"""
    
    # 获取全局日期
    global_date = None
    if not lof_df_sorted.empty:
        global_date = lof_df_sorted.iloc[0]['date'].strftime('%Y-%m-%d')
    
    return home_row, detail_page, global_date

def check_and_update_historical_data():
    """检查并更新历史数据
    Returns:
        (bool, str): (是否更新成功, 状态信息)
    """
    print("开始检查历史数据...")
    
    # 加载配置
    config_manager = ConfigManager(CONFIG_FILE)
    cfg = config_manager.load_config()
    if not cfg:
        print("无法加载配置文件，退出程序")
        return False, "无法加载配置文件"
    
    # 获取今天的日期
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    
    # 检查是否需要更新数据
    need_update = False
    
    # 检查所有基金的历史数据文件
    for fund in cfg.get('funds', []):
        code = fund.get('code', '')
        if not code:
            continue
        
        table_name = f"fund_history_{code}"
        try:
            conn = sqlite3.connect(SHARED_DB_PATH)
            df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
            conn.close()
            
            # 确保日期列存在
            if 'date' not in df.columns:
                # 尝试其他可能的日期列名
                for col in ['Date', '日期']:
                    if col in df.columns:
                        df.rename(columns={col: 'date'}, inplace=True)
                        break
            
            if 'date' in df.columns:
                # 尝试转换日期列
                try:
                    # 检查日期列的格式
                    sample_date = str(df['date'].iloc[0]) if len(df) > 0 else ''
                    if '-' in sample_date and len(sample_date) == 10 and sample_date.startswith('2026'):
                        # 已经是完整日期格式（2026-02-25）
                        df['date'] = pd.to_datetime(df['date'], format='%Y-%m-%d', errors='coerce')
                    else:
                        # 尝试将月-日格式转换为完整日期（假设2026年）
                        df['date'] = pd.to_datetime('2026-' + df['date'], format='%Y-%m-%d', errors='coerce')
                except Exception as e:
                    print(f"日期转换失败: {e}")
                    df['date'] = pd.to_datetime(df['date'], errors='coerce')
                
                # 过滤掉日期为空的行
                df = df[df['date'].notna()]
                
                if len(df) > 0:
                    # 获取最新日期
                    latest_date = df['date'].max().date()
                    
                    if latest_date < today:
                        print(f"提示: 基金 {code} 的 SQLite 数据日期({latest_date})小于今天，需要更新")
                        need_update = True
                else:
                    print(f"警告: 基金 {code} 的 SQLite 表为空，需要更新")
                    need_update = True
                    break
            else:
                print(f"警告: 基金 {code} 的 SQLite 表没有日期列，需要更新")
                need_update = True
                break
        except Exception as e:
            print(f"读取基金 {code} 的 SQLite 表失败: {e}")
            need_update = True
            break
    
    # 如果需要更新数据，执行大一统更新脚本
    if need_update:
        print("正在更新历史数据...")
        
        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            # 执行每日大一统数据更新
            print("执行 LOF011_daily_updater.py...")
            subprocess.run([sys.executable, "-X", "utf8", os.path.join(SCRIPT_DIR, "LOF011_daily_updater.py")], 
                         check=True, capture_output=True, text=True, encoding="utf-8", env=env)
            
            # 执行纯享版静态估值计算
            print("执行 LOF012_calculate_static_valuation.py...")
            subprocess.run([sys.executable, "-X", "utf8", os.path.join(SCRIPT_DIR, "LOF012_calculate_static_valuation.py")], 
                         check=True, capture_output=True, text=True, encoding="utf-8", env=env)
            
            print("成功: 数据与估值更新成功")
            return True, "历史数据更新成功"
        except subprocess.CalledProcessError as e:
            print(f"失败: 更新历史数据失败: {e}")
            print(f"错误输出: {e.stderr}")
            return False, f"更新历史数据失败: {e.stderr}"
        except Exception as e:
            print(f"失败: 更新历史数据时发生错误: {e}")
            return False, f"更新历史数据时发生错误: {str(e)}"
    else:
        print("成功: 历史数据已是最新，不需要更新")
        return False, "历史数据已是最新，不需要更新"

def get_futures_data():
    """从LOF02的API端点获取期货数据"""
    try:
        import requests
        url = "http://localhost:5000/api/futures"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"获取期货数据失败，状态码: {response.status_code}")
            return None
    except Exception as e:
        print(f"获取期货数据出错: {e}")
        return None

def generate(futures_data=None, ib_data=None):
    """生成监控报表"""
    print("开始生成LOF基金套利报表...")
    
    # 获取当天的汇率
    today_exchange_rate = get_exchange_rate()
    
    if ib_data is None:
        ib_night_prices, ib_prev_closes, ib_status_message = get_ib_night_prices()
    else:
        ib_night_prices, ib_prev_closes, ib_status_message = ib_data
        
    if futures_data is None:
        futures_data = get_futures_data()
    print(f"获取到的期货数据: {futures_data}")
    
    # 加载配置
    config_manager = ConfigManager(CONFIG_FILE)
    cfg = config_manager.load_config()
    if not cfg:
        print("无法加载配置文件，退出程序")
        return
    
    # 生成报表内容
    home_rows = ""
    detail_pages = ""
    global_date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    
    # 初始化数据处理器和HTML生成器
    data_processor = DataProcessor(DATA_DIR)
    html_generator = HtmlGenerator()
    
    # 遍历基金
    global silver_fund_data
    silver_fund_data = None
    
    # 读取期货历史数据
    futures_history_df = pd.DataFrame()
    futures_csv_path = os.path.join(DATA_DIR, "futures_history.csv")
    if os.path.exists(futures_csv_path):
        futures_history_df = pd.read_csv(futures_csv_path)
        if 'date' in futures_history_df.columns:
            futures_history_df['date'] = pd.to_datetime(futures_history_df['date']).dt.strftime('%Y-%m-%d')
            futures_history_df.set_index('date', inplace=True)

    # ====== 新架构：直接从数据库读取全局通用参数 ======
    try:
        conn = sqlite3.connect(SHARED_DB_PATH)
        # 获取最新全局汇率
        er_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
        global_er = er_df.iloc[0]['usd_cny_mid'] if not er_df.empty else 7.0

        # 获取最新期货校准值
        gc_df = pd.read_sql("SELECT calibration FROM futures_daily WHERE symbol='GC' AND calibration IS NOT NULL ORDER BY date DESC LIMIT 1", conn)
        gold_calibration = gc_df.iloc[0]['calibration'] if not gc_df.empty else 10.9067
        
        cl_df = pd.read_sql("SELECT calibration FROM futures_daily WHERE symbol='CL' AND calibration IS NOT NULL ORDER BY date DESC LIMIT 1", conn)
        oil_calibration = cl_df.iloc[0]['calibration'] if not cl_df.empty else 0.8227
        conn.close()
    except Exception as e:
        print(f"读取全局参数失败: {e}")
        global_er = 7.0
        gold_calibration = 10.9067
        oil_calibration = 0.8227
    print(f"使用期货校准值: 黄金={gold_calibration}, 原油={oil_calibration}")

    # 提前计算所有基金的基准数据，注入前端JS，避免前端同步读取CSV卡死浏览器
    js_fund_base_data = {}
    for fund in cfg.get('funds', []):
        code = fund.get('code', '')
        if code == '161226': continue
        category = fund.get('category', '其他')
        
        lof_df = read_fund_history_from_db(code)
        base_date = None
        base_nav = 0.0
        base_row = None
        for _, row in lof_df.iterrows():
            nav = row.get('nav', 0)
            if pd.notna(nav) and nav is not None:
                try:
                    if float(nav) > 0:
                        base_date = row['date']
                        base_nav = float(nav)
                        base_row = row
                        break
                except (ValueError, TypeError):
                    pass

        if base_date and base_nav:
            position = fund.get('holdings', {}).get('equity_ratio', 100.0) / 100.0
            if position > 1: position = position / 100.0
            hedging_portfolio = fund.get('hedging_portfolio', [])
            hedging_portfolio = fund.get('valuation_portfolio', [])
            
            # 在这里同样标准化注入的符号
            for item in hedging_portfolio:
                sym = item.get('symbol', '')
                if sym.replace('^', '') in ['GLD-JP', 'GLD-EU', 'USO-JP', 'USO-EU', 'USO-HK']:
                    item['symbol'] = f"^{sym.replace('^', '')}"
            
            # === 核心修复：注入 JS 沙盘前，用基准日真实的 Woody 仓位和权重覆盖 ===
            db_pos = base_row.get('position', base_row.get('仓位'))
            if pd.notna(db_pos) and db_pos != '无' and db_pos != '':
                try:
                    pf = float(db_pos)
                    if pf > 1: pf = pf / 100.0
                    if pf > 0: position = pf
                except: pass

            for item in hedging_portfolio:
                sym = item['symbol']
                weight_col = f"{sym}权重"
                if weight_col in base_row:
                    db_w = base_row.get(weight_col)
                    if pd.notna(db_w) and db_w != '无' and db_w != '':
                        try: item['weight'] = float(db_w)
                        except: pass

            base_exchange_rate = base_row.get('exchange_rate')
            if pd.isna(base_exchange_rate):
                base_exchange_rate = None
            else:
                base_exchange_rate = float(base_exchange_rate)
            
            base_etf_prices = {}
            for item in hedging_portfolio:
                sym = item['symbol']
                price = 0.0
                if sym in base_row and pd.notna(base_row[sym]) and base_row[sym] is not None and base_row[sym] != '无' and base_row[sym] != '':
                    try:
                        price = float(base_row[sym])
                    except:
                        pass
                
                if price <= 0:
                    base_sym = 'GLD' if 'GLD' in sym else ('USO' if 'USO' in sym else ('XOP' if 'XOP' in sym else ('XBI' if 'XBI' in sym else ('SLV' if 'SLV' in sym else ('SPY' if 'SPY' in sym else ('QQQ' if 'QQQ' in sym else sym))))))
                    if base_sym in base_row and pd.notna(base_row[base_sym]) and base_row[base_sym] is not None and base_row[base_sym] != '无':
                        try: price = float(base_row[base_sym])
                        except: pass
                    elif f"^{base_sym}" in base_row and pd.notna(base_row[f"^{base_sym}"]) and base_row[f"^{base_sym}"] is not None and base_row[f"^{base_sym}"] != '无':
                        try: price = float(base_row[f"^{base_sym}"])
                        except: pass
                    # 对于XBI，尝试从其他行获取价格
                    elif base_sym == 'XBI':
                        # 遍历历史数据，找到最近的XBI价格
                        for _, row in lof_df.iterrows():
                            if 'XBI' in row and pd.notna(row['XBI']) and row['XBI'] is not None and row['XBI'] != '无':
                                try:
                                    temp_price = float(row['XBI'])
                                    if temp_price > 0:
                                        price = temp_price
                                        break
                                except: pass
                base_etf_prices[sym] = price
                
            trade_etf_sym = fund.get("trade_etf", "")
            trade_etf_price = 0.0
            if trade_etf_sym and base_row is not None:
                if trade_etf_sym in base_row and not pd.isna(base_row[trade_etf_sym]):
                    trade_etf_price = float(base_row[trade_etf_sym])
            if trade_etf_price <= 0 and base_etf_prices:
                trade_etf_price = list(base_etf_prices.values())[0]
                
            future_symbol_js = ''
            f_list = fund.get('future_hedging', [])
            if f_list:
                raw_sym = f_list[0].get('symbol', '').upper()
                mapping = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC', 'NQ': 'NQ', 'ES': 'ES'}
                future_symbol_js = mapping.get(raw_sym, raw_sym)
            else:
                trade_fut = fund.get('trade_future', '').upper()
                mapping = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC', 'NQ': 'NQ', 'ES': 'ES'}
                if trade_fut:
                    future_symbol_js = mapping.get(trade_fut, trade_fut)
                else:
                    if category == '黄金': future_symbol_js = 'GC'
                    elif category == '原油' and code != '162411': future_symbol_js = 'CL'
                    elif category == '指数':
                        trade_etf = str(fund.get('trade_etf', '')).upper()
                        if 'QQQ' in trade_etf: future_symbol_js = 'NQ'
                        elif 'SPY' in trade_etf or 'XBI' in trade_etf: future_symbol_js = 'ES'
                        else: future_symbol_js = 'NQ'
                    elif code == '161226': future_symbol_js = 'AG0'
                    
            base_future_price = 0.0
            if base_row is not None:
                val = base_row.get('期货结算价', 0.0)
                if pd.notna(val) and val != '无' and val != '':
                    base_future_price = float(val)
            
        # 提取保存在历史账本中的对冲值 (物理兑换比)
            hedge_value = 0.0
            rmb_exposure = 0.0
            latest_calibration_factor = 0.0
            latest_exchange_rate = 0.0
            
            # 根据基金类别设置校准因子
            if category == '黄金':
                latest_calibration_factor = gold_calibration
            elif category == '原油':
                latest_calibration_factor = oil_calibration
            
            if base_row is not None:
                try:
                    hv = base_row.get('hedge_value', 0.0)
                    if pd.notna(hv) and hv != '无':
                        hedge_value = float(hv)
                except:
                    pass
                try:
                    re = base_row.get('rmb_exposure', 0.0)
                    if pd.notna(re) and re != '无':
                        rmb_exposure = float(re)
                except: pass
                try:
                    er = base_row.get('exchange_rate', 0.0)
                    if pd.notna(er) and er != '无':
                        latest_exchange_rate = float(er)
                except: pass
            
            # 动态计算 ETF 对冲值
            etf_hedge_value = 0.0
            if trade_etf_price > 0 and base_nav > 0 and position > 0 and base_exchange_rate is not None:
                etf_hedge_value = (trade_etf_price * base_exchange_rate) / (base_nav * position)
                
            # 动态计算 期货 对冲值
            fut_hedge_value = 0.0
            if base_future_price > 0 and base_nav > 0 and position > 0 and base_exchange_rate is not None:
                fut_hedge_value = (base_future_price * base_exchange_rate) / (base_nav * position)
            
            # 提取 JS 沙盘实时运算专用汇率
            today_er_for_js = global_er

            js_fund_base_data[code] = {
                'name': fund.get('name', '未知基金'),
                'baseNav': float(base_nav),
                'baseExchangeRate': float(base_exchange_rate) if base_exchange_rate is not None else None,
                'position': float(position),
                'hedgingPortfolio': [{'symbol': h['symbol'], 'weight': h['weight']/100.0} for h in hedging_portfolio],
                'baseEtfPrices': base_etf_prices,
                'category': category,
                'futureSymbol': future_symbol_js,
                'baseFuturePrice': base_future_price,
                'hedgeValue': hedge_value,
                'etfHedgeValue': etf_hedge_value,
                'rmbExposure': rmb_exposure,
                'futHedgeValue': fut_hedge_value,
                'latestCalibrationFactor': latest_calibration_factor,
                'latestExchangeRate': latest_exchange_rate,
                'todayExchangeRate': today_er_for_js,
                'rateType': fund.get('rate_type', 'midpoint')
            }
    
    home_rows_main = ""
    home_rows_index = ""
    home_rows_etf = ""
    for fund in cfg.get('funds', []):
        code = fund.get('code', '')
        
        # 161226单独显示在白银LOF特殊监控表格中，不在主表显示
        if code == '161226':
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, gold_calibration=gold_calibration, oil_calibration=oil_calibration, global_er=global_er)
            if fund_detail_page:
                detail_pages += fund_detail_page
            continue
        
        category = fund.get('category', '其他')
        # 处理单个基金的数据
        if category == '指数':
            # 指数基金需要生成两种行：一种为主表，一种为指数表
            fund_home_row_main, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, gold_calibration=gold_calibration, oil_calibration=oil_calibration, global_er=global_er)
            fund_home_row_index, _, _ = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=True, gold_calibration=gold_calibration, oil_calibration=oil_calibration, global_er=global_er)
            if fund_home_row_main and fund_detail_page:
                home_rows += fund_home_row_main
                home_rows_index += fund_home_row_index
                detail_pages += fund_detail_page
        elif category == '纯ETF':
            # 纯ETF单独放一个表
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, gold_calibration=gold_calibration, oil_calibration=oil_calibration, global_er=global_er)
            if fund_home_row and fund_detail_page:
                home_rows += fund_home_row
                home_rows_etf += fund_home_row
                detail_pages += fund_detail_page
            if fund_global_date and not global_date_str:
                global_date_str = fund_global_date
        else:
            # 黄金、原油等商品基金
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, gold_calibration=gold_calibration, oil_calibration=oil_calibration, global_er=global_er)
            if fund_home_row and fund_detail_page:
                home_rows += fund_home_row
                home_rows_main += fund_home_row
                detail_pages += fund_detail_page
            if fund_global_date and not global_date_str:
                global_date_str = fund_global_date

    # 生成JavaScript代码，注意转义大括号
    js_code = r'''
        <script>
            // 注入Python预先计算的基金基准数据，彻底抛弃前端读CSV
            window.fundBaseData = ''' + json.dumps(js_fund_base_data, ensure_ascii=False) + r''';
            window.calibData = { "gold": ''' + str(gold_calibration) + r''', "oil": ''' + str(oil_calibration) + r''' };

            // WebSocket连接
            var socket = io();

            // 连接成功
            socket.on('connect', function() {
                console.log('WebSocket连接成功');
            });

            // 断开连接
            socket.on('disconnect', function() {
                console.log('WebSocket断开连接');
            });

            // 接收期货价格更新
            socket.on('futures_price_update', function(data) {
                console.log('收到期货价格更新:', data);
                // 更新期货价格显示
                if (data.symbol === 'GC') {
                    var gcPriceElement = document.querySelector('#gc-price');
                    if (gcPriceElement) {
                        gcPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'CL') {
                    var clPriceElement = document.querySelector('#cl-price');
                    if (clPriceElement) {
                        clPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'AG0') {
                    var agPriceElement = document.querySelector('#ag0-price');
                    if (agPriceElement) {
                        agPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'NQ') {
                    var nqPriceElement = document.querySelector('#nq-price');
                    if (nqPriceElement) {
                        nqPriceElement.textContent = data.price.toFixed(2);
                    }
                } else if (data.symbol === 'ES') {
                    var esPriceElement = document.querySelector('#es-price');
                    if (esPriceElement) {
                        esPriceElement.textContent = data.price.toFixed(2);
                    }
                }
                
                // 触发估值计算
                updateFuturesData();
            });

            // 接收期货价格快照
            socket.on('futures_price_snapshot', function(data) {
                console.log('收到期货价格快照:', data);
                // 更新所有期货价格
                if (data.prices) {
                    if (data.prices.GC) {
                        var gcPriceElement = document.querySelector('#gc-price');
                        if (gcPriceElement) {
                            gcPriceElement.textContent = data.prices.GC.toFixed(2);
                        }
                    }
                    if (data.prices.CL) {
                        var clPriceElement = document.querySelector('#cl-price');
                        if (clPriceElement) {
                            clPriceElement.textContent = data.prices.CL.toFixed(2);
                        }
                    }
                    if (data.prices.AG) {
                        var agPriceElement = document.querySelector('#ag0-price');
                        if (agPriceElement) {
                            agPriceElement.textContent = data.prices.AG.toFixed(2);
                        }
                    }
                    if (data.prices.NQ) {
                        var nqPriceElement = document.querySelector('#nq-price');
                        if (nqPriceElement) {
                            nqPriceElement.textContent = data.prices.NQ.toFixed(2);
                        }
                    }
                    if (data.prices.ES) {
                        var esPriceElement = document.querySelector('#es-price');
                        if (esPriceElement) {
                            esPriceElement.textContent = data.prices.ES.toFixed(2);
                        }
                    }
                }
            });

            // 更新时间显示
            function updateTime() {
                const now = new Date();
                const timeString = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                const dateString = now.toISOString().split('T')[0];
                document.getElementById('current-date-time').textContent = `${dateString} ${timeString}`;
            }
            
            // 高效的O(1)计算实时估值函数，抛弃AJAX读取CSV的卡顿机制
            function calculateETFRealTimeValuation(fundCode, category, gldPrice, usoPrice, xopPrice, xbiPrice, slvPrice, spyPrice, qqqPrice, staticValuation) {
                var baseData = window.fundBaseData[fundCode];
                if (!baseData || !baseData.position || baseData.hedgingPortfolio.length === 0) {
                    return 0;
                }
                
                // 动态获取：如果在岸价要求且后台提供了在岸价，则使用在岸价；否则降级中间价
                var reqSpot = (baseData.rateType === 'spot');
                var todayExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                
                if (!todayExchangeRate || todayExchangeRate <= 0) {
                    return 0; // 彻底没有有效汇率，强制熔断返回0
                }
                
                // 🌟 魔法捷径：提取 O(1) 常量折叠对冲因子
                var hedgeValue = baseData.hedgeValue;
                if (!hedgeValue || hedgeValue <= 0) {
                    hedgeValue = baseData.etfHedgeValue; // 降级兜底
                }

                // 🌟 魔法捷径：仅限单一资产(如XOP/QQQ)使用常量折叠。多资产变种组合绝不能用单一价格乘整体Hedge！
                if (hedgeValue && hedgeValue > 0 && baseData.hedgingPortfolio.length === 1) {
                    var primarySym = baseData.hedgingPortfolio[0].symbol;
                    var currentAssetPrice = 0;
                    if (primarySym.includes('GLD')) currentAssetPrice = gldPrice;
                    else if (primarySym.includes('USO')) currentAssetPrice = usoPrice;
                    else if (primarySym.includes('XOP')) currentAssetPrice = xopPrice;
                    else if (primarySym.includes('XBI')) currentAssetPrice = xbiPrice;
                    else if (primarySym.includes('SLV')) currentAssetPrice = slvPrice;
                    else if (primarySym.includes('SPY')) currentAssetPrice = spyPrice;
                    else if (primarySym.includes('QQQ')) currentAssetPrice = qqqPrice;
                    
                    if (currentAssetPrice > 0) {
                        return baseData.baseNav * (1.0 - baseData.position) + (currentAssetPrice * todayExchangeRate) / hedgeValue;
                    }
                }
                
                // 🌟 矩阵兜底：当魔法因子完全缺失时，退回 T-1 权重矩阵
                var weightedEtfChangeRate = 0;
                var hasValidData = false;
                var validWeight = 0;
                
                for (var i = 0; i < baseData.hedgingPortfolio.length; i++) {
                    var item = baseData.hedgingPortfolio[i];
                    var currentPrice = 0;
                    if (item.symbol.includes('GLD')) currentPrice = gldPrice;
                    else if (item.symbol.includes('USO')) currentPrice = usoPrice;
                    else if (item.symbol.includes('XOP')) currentPrice = xopPrice;
                    else if (item.symbol.includes('XBI')) currentPrice = xbiPrice;
                    else if (item.symbol.includes('SLV')) currentPrice = slvPrice;
                    else if (item.symbol.includes('SPY')) currentPrice = spyPrice;
                    else if (item.symbol.includes('QQQ')) currentPrice = qqqPrice;
                    
                    var basePrice = baseData.baseEtfPrices[item.symbol];
                    if (basePrice > 0 && currentPrice > 0 && item.weight > 0) {
                        weightedEtfChangeRate += (currentPrice / basePrice) * item.weight;
                        validWeight += item.weight;
                        hasValidData = true;
                    }
                }
                
                if (!hasValidData) return 0;
                if (validWeight < 0.98 || validWeight > 1.02) {
                    weightedEtfChangeRate = weightedEtfChangeRate / validWeight;
                }
                
                if (!baseData.baseExchangeRate || isNaN(baseData.baseExchangeRate) || baseData.baseExchangeRate <= 0) {
                    return 0;
                }
                
                var exchangeRateChange = todayExchangeRate / baseData.baseExchangeRate;
                return baseData.baseNav * (1 + baseData.position * (weightedEtfChangeRate * exchangeRateChange - 1));
            }
            
            // 暴露到全局供其他模块调用
            window.calculateETFRealTimeValuation = calculateETFRealTimeValuation;
            
            window.openSandbox = function(code, type) {
                // 无论点击哪个列，都显示同一个沙盒页面
                showDetail('page-rt-etf-' + code);
                
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                // 取后端注入的精确汇率 (避开 DOM 正则匹配导致的格式错乱)
                var fxRate = baseData.todayExchangeRate || '';
                // 设置所有三个估值模块的汇率
                var fxEl = document.getElementById('sb-exchange-rate-' + code);
                if(fxEl) fxEl.textContent = fxRate;
                
                // 1. 初始化ETF估值的价格数据（使用与主面板相同的实时价格）
                var inputs = document.querySelectorAll('.sandbox-input-' + code);
                inputs.forEach(function(inp) {
                    var baseSym = inp.getAttribute('data-base');
                    
                    // 严格同步主面板当前生效的测试价 (无论是手工干预还是IB夜盘)
                    if (window.currentEtfPrices && window.currentEtfPrices[baseSym] !== undefined && window.currentEtfPrices[baseSym] > 0) {
                        inp.value = window.currentEtfPrices[baseSym];
                    } else {
                        // 兜底逻辑：如果全局变量未初始化，则依据单选状态提取
                        var useIB = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                        if (useIB) {
                            var upperSym = baseSym.toUpperCase();
                            if (window.latestIbPrices && window.latestIbPrices[upperSym] && window.latestIbPrices[upperSym].bid) {
                                inp.value = window.latestIbPrices[upperSym].bid;
                            } else {
                                var ibValEl = document.getElementById('ib-val-' + baseSym);
                                inp.value = ibValEl ? (parseFloat(ibValEl.textContent) || '') : '';
                            }
                        } else {
                            var manualEl = document.getElementById(baseSym + '-price');
                            inp.value = manualEl ? (manualEl.value || manualEl.textContent) : '';
                        }
                    }
                });
                
                // 设置ETF估值的实时价格 - 直接从 realtime-price-{code} 读取即可，不需要 sb-live-price-{code}
                var livePriceEl = document.getElementById('realtime-price-' + code);
                if(livePriceEl) {
                    var lpText = livePriceEl.textContent;
                    var lpMatch = lpText.match(/[\d.]+/);
                    var tpInput = document.getElementById('sb-target-price-' + code);
                    if (lpMatch && tpInput) { tpInput.value = parseFloat(lpMatch[0]); }
                }
                
                // 2. 初始化期货校准估值的价格数据（使用与主面板相同的实时期货价格）
                var futSym = baseData.futureSymbol;
                var futPriceEl = null;
                if (futSym === 'GC') futPriceEl = document.getElementById('gc-price');
                else if (futSym === 'CL') futPriceEl = document.getElementById('cl-price');
                else if (futSym === 'NQ') futPriceEl = document.getElementById('nq-price');
                else if (futSym === 'ES') futPriceEl = document.getElementById('es-price');
                
                var futPrice = '';
                if (futPriceEl) {
                    futPrice = futPriceEl.textContent || futPriceEl.value || '';
                }
                
                var sbFutPriceEl = document.getElementById('sb-fut-price-' + code);
                if (sbFutPriceEl) {
                    if (futPrice) {
                        sbFutPriceEl.value = parseFloat(futPrice);
                    }
                }
                
                // 设置校准值（使用与主面板相同的校准值）
                var calib = baseData.category === '黄金' ? window.calibData.gold : window.calibData.oil;
                var sbFutCalibEl = document.getElementById('sb-fut-calib-' + code);
                if (sbFutCalibEl && calib > 0) {
                    sbFutCalibEl.value = calib;
                }
                
                // 3. 初始化纯期货估值的价格数据（使用与主面板相同的实时期货价格）
                var sbPureFutPriceEl = document.getElementById('sb-pure-fut-price-' + code);
                if (sbPureFutPriceEl) {
                    if (futPrice) {
                        sbPureFutPriceEl.value = parseFloat(futPrice);
                    }
                }
                
                // 根据点击的列切换标签页
                if (type === 'future') {
                    switchValuationTab(code, 'future');
                } else if (type === 'pure_future') {
                    switchValuationTab(code, 'pure_future');
                }
                
                // 主动调用一次计算函数
                if (window.calcSandbox) {
                    window.calcSandbox(code);
                }
                if (window.calcFutureSandbox) {
                    window.calcFutureSandbox(code);
                }
                if (window.calcPureFutureSandbox) {
                    window.calcPureFutureSandbox(code);
                }
                
                // 启动盘口轮询定时器
                window.pollOrderBookIntervals = window.pollOrderBookIntervals || {};
                if(window.pollOrderBookIntervals[code]) clearInterval(window.pollOrderBookIntervals[code]);
                window.pollOrderBook(code);
                window.pollOrderBookIntervals[code] = setInterval(function() { window.pollOrderBook(code); }, 1000);
                
                // 5. 直接从主面板读取估值，然后用A股 LOF 测试单价计算溢价
                var targetPriceEl = document.getElementById('sb-target-price-' + code);
                var targetPrice = 0;
                if (targetPriceEl) {
                    if (targetPriceEl.value) {
                        targetPrice = parseFloat(targetPriceEl.value);
                    }
                }
                
                // 注意：不再从主面板复制估值，因为沙盒会自己主动计算
                // var etfVal = document.getElementById('realtime-valuation-' + code);
                // var sbEtfVal = document.getElementById('sb-val-' + code);
                // var sbEtfPrem = document.getElementById('sb-prem-' + code);
                // if (sbEtfVal) {
                //     if (etfVal) {
                //         sbEtfVal.textContent = etfVal.textContent;
                //     }
                // }
                // if (sbEtfPrem) {
                //     if (etfVal) {
                //         if (targetPrice > 0) {
                //             var etfValNum = parseFloat(etfVal.textContent);
                //             if (!isNaN(etfValNum)) {
                //                 if (etfValNum > 0) {
                //                     var prem = (targetPrice / etfValNum - 1);
                //                     sbEtfPrem.textContent = (prem * 100).toFixed(2) + '%';
                //                     sbEtfPrem.style.color = prem >= 0 ? '#dc2626' : '#15803d';
                //                 }
                //             }
                //         }
                //     }
                // }
                
                // 注意：不再从主面板复制期货校准和纯期货估值，因为沙盒会自己计算
                // var calibVal = document.getElementById('rt-calib-val-' + code);
                // var sbCalibVal = document.getElementById('sb-fut-val-' + code);
                // var sbCalibPrem = document.getElementById('sb-fut-prem-' + code);
                // if (sbCalibVal) {
                //     if (calibVal) {
                //         sbCalibVal.textContent = calibVal.textContent;
                //     }
                // }
                // if (sbCalibPrem) {
                //     if (calibVal) {
                //         if (targetPrice > 0) {
                //             var calibValNum = parseFloat(calibVal.textContent);
                //             if (!isNaN(calibValNum)) {
                //                 if (calibValNum > 0) {
                //                     var prem = (targetPrice / calibValNum - 1);
                //                     sbCalibPrem.textContent = (prem * 100).toFixed(2) + '%';
                //                     sbCalibPrem.style.color = prem >= 0 ? '#dc2626' : '#15803d';
                //                 }
                //             }
                //         }
                //     }
                // }
                // 
                // var exactVal = document.getElementById('rt-exact-val-' + code);
                // var sbExactVal = document.getElementById('sb-pure-val-' + code);
                // var sbExactPrem = document.getElementById('sb-pure-prem-' + code);
                // if (sbExactVal) {
                //     if (exactVal) {
                //         sbExactVal.textContent = exactVal.textContent;
                //     }
                // }
                // if (sbExactPrem) {
                //     if (exactVal) {
                //         if (targetPrice > 0) {
                //             var exactValNum = parseFloat(exactVal.textContent);
                //             if (!isNaN(exactValNum)) {
                //                 if (exactValNum > 0) {
                //                     var prem = (targetPrice / exactValNum - 1);
                //                     sbExactPrem.textContent = (prem * 100).toFixed(2) + '%';
                //                     sbExactPrem.style.color = prem >= 0 ? '#dc2626' : '#15803d';
                //                 }
                //             }
                //         }
                //     }
                // }
                
                // 5. 设置交易价格
                if (livePriceEl) {
                    var lpText = livePriceEl.textContent;
                    var lpMatch = lpText.match(/[\d.]+/);
                    if (lpMatch) {
                        var qmtPriceInput = document.getElementById('trade-price-' + code + '-etf');
                        if (qmtPriceInput) qmtPriceInput.value = parseFloat(lpMatch[0]);
                        var futQmtPriceInput = document.getElementById('trade-price-' + code + '-future');
                        if (futQmtPriceInput) futQmtPriceInput.value = parseFloat(lpMatch[0]);
                        var pureQmtPriceInput = document.getElementById('trade-price-' + code + '-pure_future');
                        if (pureQmtPriceInput) pureQmtPriceInput.value = parseFloat(lpMatch[0]);
                    }
                }
                
                // 设置期货校准和纯期货估值的目标价格
                if (targetPrice > 0) {
                    var futTargetPriceInput = document.getElementById("sb-fut-target-price-" + code);
                    if (futTargetPriceInput) futTargetPriceInput.value = targetPrice;
                    var pureTargetPriceInput = document.getElementById("sb-pure-target-price-" + code);
                    if (pureTargetPriceInput) pureTargetPriceInput.value = targetPrice;
                }
                
                // 6. 设置IB交易价格
                var suffixes = ['etf'];
                var idx = 1;
                while(document.getElementById('ib-trade-sym-' + code + '-etf_' + idx)) {
                    suffixes.push('etf_' + idx);
                    idx++;
                }
                
                suffixes.forEach(function(suffix) {
                    var defaultSymEl = document.getElementById('ib-trade-sym-' + code + '-' + suffix);
                    if (defaultSymEl) {
                        var defaultSym = defaultSymEl.value.toUpperCase();
                        var ibPriceEl = document.getElementById('ib-trade-price-' + code + '-' + suffix);
                        var bidEl = document.getElementById('sb-ib-bid-' + code + '-' + suffix);
                        var askEl = document.getElementById('sb-ib-ask-' + code + '-' + suffix);
                        
                        if (window.latestIbPrices && window.latestIbPrices[defaultSym]) {
                            var p = window.latestIbPrices[defaultSym];
                            if (bidEl && p.bid) bidEl.textContent = p.bid.toFixed(2);
                            if (askEl && p.ask) askEl.textContent = p.ask.toFixed(2);
                            if (ibPriceEl && p.bid) ibPriceEl.value = p.bid.toFixed(2);
                        } else {
                            var refPriceEl = document.getElementById(defaultSym.toLowerCase() + '-price');
                            if (refPriceEl && ibPriceEl) ibPriceEl.value = refPriceEl.value || refPriceEl.textContent;
                        }
                    }
                });
                
                // 7. 计算三套对冲数量
                window.calcHedgeQty(code, 'etf');
                window.calcHedgeQty(code, 'future');
                window.calcHedgeQty(code, 'pure_future');
            };
            
            // 🎯 新增：独立的对冲数量计算逻辑
            window.calcHedgeQty = function(code, stype, isReverse = false) { // Added isReverse parameter
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                var capitalInput = document.getElementById('sb-target-capital-' + code + '-' + stype);
                var capitalA = capitalInput ? parseFloat(capitalInput.value) || 0 : 0;
                
                // 直接从 realtime-price-{code} 读取，更可靠
                var realtimePriceEl = document.getElementById('realtime-price-' + code);
                var lofLivePriceStr = realtimePriceEl ? realtimePriceEl.textContent : '';
                var lofLiveMatch = lofLivePriceStr ? lofLivePriceStr.match(/[\d.]+/) : null;
                var lofRealtimePrice = lofLiveMatch ? parseFloat(lofLiveMatch[0]) : 0;
                
                // 优先使用数据库里算出来的无坚不摧的物理兑换比
                var hedgeValue = baseData.baseHedgeValue;
                // 如果库里没读到，降级用近似估算兜底
                if (!hedgeValue || hedgeValue <= 0) {
                    if (stype === 'etf') hedgeValue = baseData.etfHedgeValue;
                    else if (stype === 'future' || stype === 'pure_future') hedgeValue = baseData.futHedgeValue;
                }
                
                var lofQtyEl = document.getElementById('sb-lof-qty-' + code + '-' + stype);
                var etfQtyEl = document.getElementById('sb-etf-qty-' + code + '-' + stype);
                
                var dbgHedgeEl = document.getElementById('sb-debug-hedge-' + code + '-' + stype);
                var dbgExposureEl = document.getElementById('sb-debug-exposure-' + code + '-' + stype);
                
                // Determine the hedgeValue based on the type and whether it's a reverse calculation
                var hedgeValue = 0;
                if (isReverse) { // For future modes (input is futures lots), use the API-provided hedgeValue (LOF shares per future lot)
                    hedgeValue = baseData.hedgeValue;
                } else { // For ETF mode (input is capital), use API hedgeValue or fallback to derived etfHedgeValue
                    hedgeValue = baseData.hedgeValue;
                    if (!hedgeValue || hedgeValue <= 0) {
                        hedgeValue = baseData.etfHedgeValue;
                    }
                }

                if(dbgHedgeEl) dbgHedgeEl.textContent = hedgeValue > 0 ? hedgeValue.toFixed(4) : '-';
                
                console.log('calcHedgeQty 调试信息:', {
                    code: code,
                    stype: stype,
                    capitalInput: capitalInput,
                    capitalA: capitalA,
                    realtimePriceEl: realtimePriceEl,
                    lofLivePriceStr: lofLivePriceStr,
                    lofRealtimePrice: lofRealtimePrice,
                    hedgeValue: hedgeValue,
                    etfHedgeValue: baseData.etfHedgeValue,
                    futHedgeValue: baseData.futHedgeValue,
                    baseHedgeValue: baseData.hedgeValue,
                    lofQtyEl: lofQtyEl,
                    etfQtyEl: etfQtyEl
                });
                
                if (hedgeValue && hedgeValue > 0 && capitalA > 0 && lofRealtimePrice > 0) {
                    var finalEtfQty = 0;
                    var finalLofQty = 0;
                    
                    if (baseData.category === '纯ETF' || baseData.category === '指数') {
                        // 纯ETF/指数类：美股定A股（底层直接1对1映射）
                        var tempLofQty = capitalA / lofRealtimePrice;
                        finalEtfQty = Math.max(1, Math.round(tempLofQty / hedgeValue));
                        finalLofQty = Math.round((finalEtfQty * hedgeValue) / 100) * 100;
                    } else {
                        // 黄金/原油商品类：A股定美股（底层由一篮子资产混合）
                        finalLofQty = Math.round((capitalA / lofRealtimePrice) / 100) * 100;
                        finalEtfQty = Math.max(1, Math.round(finalLofQty / hedgeValue));
                    }
                    
                    var realExposure = capitalA * baseData.position;
                    if(dbgExposureEl) dbgExposureEl.textContent = realExposure > 0 ? realExposure.toFixed(2) + ' 元' : '-';
                    
                    if(lofQtyEl) lofQtyEl.textContent = finalLofQty;
                    if(etfQtyEl) etfQtyEl.textContent = finalEtfQty;
                    
                    // 顺便把结果自动填入下方的 QMT 和 IB 准备发送指令的输入框中
                    var tradeVolEl = document.getElementById('trade-vol-' + code + '-' + stype);
                    var ibTradeVolEl = document.getElementById('ib-trade-vol-' + code + '-' + stype);
                    var ibFutureVolEl = document.getElementById('ib-future-vol-' + code);
                    
                    // 检测是否是用户主动修改沙盘推演数值（即：解除锁定）
                    var isUserTrigger = (window.event && window.event.type === 'input' && window.event.target && window.event.target.id.startsWith('sb-target-'));
                    if (isUserTrigger) {
                        if (tradeVolEl) delete tradeVolEl.dataset.manual;
                        if (ibTradeVolEl) delete ibTradeVolEl.dataset.manual;
                        if (ibFutureVolEl) delete ibFutureVolEl.dataset.manual;
                    }
                    
                    // 只有在未被用户手动修改过的情况下，才执行自动填充
                    if(tradeVolEl && !tradeVolEl.dataset.manual) tradeVolEl.value = finalLofQty;
                    
                    // 动态拆分给多个 ETF 框
                    var tradeEtfs = [];
                    var defaultSymEl = document.getElementById('ib-trade-sym-' + code + '-etf');
                    if (defaultSymEl) {
                        tradeEtfs.push({sym: defaultSymEl.value, suffix: 'etf', weight: 0});
                        var idx = 1;
                        while(true) {
                            var symEl = document.getElementById('ib-trade-sym-' + code + '-etf_' + idx);
                            if (symEl) {
                                tradeEtfs.push({sym: symEl.value, suffix: 'etf_' + idx, weight: 0});
                                idx++;
                            } else {
                                break;
                            }
                        }
                        var totalTradeWeight = 0;
                        tradeEtfs.forEach(function(t) {
                            var w = 0;
                            baseData.hedgingPortfolio.forEach(function(hp) {
                                if (hp.symbol.includes(t.sym)) w += hp.weight;
                            });
                            t.weight = w;
                            totalTradeWeight += w;
                        });
                        if (totalTradeWeight > 0) {
                            tradeEtfs.forEach(function(t) { t.normWeight = t.weight / totalTradeWeight; });
                        } else {
                            tradeEtfs[0].normWeight = 1;
                            for (var j = 1; j < tradeEtfs.length; j++) tradeEtfs[j].normWeight = 0;
                        }
                    }
                    
                    tradeEtfs.forEach(function(t) {
                        var ibVolEl = document.getElementById('ib-trade-vol-' + code + '-' + t.suffix);
                        if (ibVolEl && !ibVolEl.dataset.manual) {
                            var qty = Math.max(1, Math.round(finalEtfQty * t.normWeight));
                            if (t.normWeight === 0) qty = 0;
                            ibVolEl.value = qty;
                        }
                    });

                    // 兼容后续包含期货模式的新版赋值
                    if(typeof isReverse !== 'undefined' && isReverse && ibFutureVolEl && !ibFutureVolEl.dataset.manual) ibFutureVolEl.value = typeof futuresLots !== 'undefined' ? futuresLots : 0;
                } else {
                    if(lofQtyEl) lofQtyEl.textContent = '?';
                    if(etfQtyEl) etfQtyEl.textContent = '?';
                }
            };

            window.calcSandbox = function(code) {
                var baseData = window.fundBaseData[code];
                if (!baseData) return;
                
                // 同步提取并展示当前外盘实盘价供参考
                var defaultSym = document.getElementById('ib-trade-sym-' + code + '-etf');
                if (defaultSym) {
                    var refPriceEl = document.getElementById(defaultSym.value.toLowerCase() + '-price');
                    var sbRefEl = document.getElementById('sb-ref-price-' + code);
                    if (sbRefEl && refPriceEl) sbRefEl.textContent = refPriceEl.value || '-';
                }
                
                var reqSpot = (baseData.rateType === 'spot');
                var fx = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                
                if (!fx || isNaN(fx) || fx <= 0) {
                    var valEl = document.getElementById('sb-val-' + code);
                    var premEl = document.getElementById('sb-prem-' + code);
                    var targetPremEl = document.getElementById('sb-target-prem-' + code);
                    if (valEl) valEl.textContent = 'ERR: 无汇率';
                    if (premEl) premEl.textContent = '-';
                    if (targetPremEl) targetPremEl.textContent = '-';
                    return;
                }
                
                var inputs = document.querySelectorAll('.sandbox-input-' + code);
                var inputVals = {};
                inputs.forEach(function(inp) {
                    inputVals[inp.getAttribute('data-base')] = parseFloat(inp.value) || 0;
                });
                
                var weightedChange = 0;
                var validWeight = 0;
                var val = null;
                var hedgeValue = baseData.hedgeValue;
                if (!hedgeValue || hedgeValue <= 0) hedgeValue = baseData.etfHedgeValue;
                
                if (hedgeValue && hedgeValue > 0 && baseData.hedgingPortfolio && baseData.hedgingPortfolio.length === 1) {
                    var primarySym = baseData.hedgingPortfolio[0].symbol;
                    var baseSym = 'unknown';
                    if (primarySym.includes('GLD')) baseSym = 'gld';
                    else if (primarySym.includes('USO')) baseSym = 'uso';
                    else if (primarySym.includes('XOP')) baseSym = 'xop';
                    else if (primarySym.includes('XBI')) baseSym = 'xbi';
                    else if (primarySym.includes('SLV')) baseSym = 'slv';
                    else if (primarySym.includes('SPY')) baseSym = 'spy';
                    else if (primarySym.includes('QQQ')) baseSym = 'qqq';
                    
                    var currentPrice = inputVals[baseSym] || 0;
                    if (currentPrice > 0) {
                        val = baseData.baseNav * (1.0 - baseData.position) + (currentPrice * fx) / hedgeValue;
                    }
                }
                
                if (!val) {
                    var weightedChange = 0;
                    var validWeight = 0;
                    
                    baseData.hedgingPortfolio.forEach(function(h) {
                        var sym = h.symbol;
                        var baseSym = 'unknown';
                        if (sym.includes('GLD')) baseSym = 'gld';
                        else if (sym.includes('USO')) baseSym = 'uso';
                        else if (sym.includes('XOP')) baseSym = 'xop';
                        else if (sym.includes('XBI')) baseSym = 'xbi';
                        else if (sym.includes('SLV')) baseSym = 'slv';
                        else if (sym.includes('SPY')) baseSym = 'spy';
                        else if (sym.includes('QQQ')) baseSym = 'qqq';
                        
                        var currentPrice = inputVals[baseSym] || 0;
                        var basePrice = baseData.baseEtfPrices[sym];
                        var weight = h.weight;
                        
                        if (basePrice > 0 && currentPrice > 0 && weight > 0) {
                            weightedChange += (currentPrice / basePrice) * weight;
                            validWeight += h.weight;
                        }
                    });
                
                    if (validWeight === 0) {
                        var valEl = document.getElementById('sb-val-' + code);
                        var premEl = document.getElementById('sb-prem-' + code);
                        var targetPremEl = document.getElementById('sb-target-prem-' + code);
                        if (valEl) valEl.textContent = '-';
                        if (premEl) premEl.textContent = '-';
                        if (targetPremEl) targetPremEl.textContent = '-';
                        return;
                    }
                    
                    if (validWeight < 0.98 || validWeight > 1.02) {
                        weightedChange = weightedChange / validWeight;
                    }
                    
                    var fxChange = fx / baseData.baseExchangeRate;
                    val = baseData.baseNav * (1 + baseData.position * (weightedChange * fxChange - 1));
                }
                
                var valEl = document.getElementById('sb-val-' + code);
                if (valEl) valEl.textContent = val.toFixed(4);
                
                // 计算当前实盘价对应溢价 - 直接从 realtime-price-{code} 读取
                var livePriceEl = document.getElementById('realtime-price-' + code);
                var livePriceStr = livePriceEl ? livePriceEl.textContent : '';
                var livePriceMatch = livePriceStr.match(/[\d.]+/);
                if (livePriceMatch) {
                    var livePrice = parseFloat(livePriceMatch[0]);
                    var prem = (livePrice / val - 1) * 100;
                    var premEl = document.getElementById('sb-prem-' + code);
                    if (premEl) {
                        premEl.textContent = (prem >= 0 ? '+' : '') + prem.toFixed(2) + '%';
                        premEl.style.color = prem >= 0 ? '#2e7d32' : '#d32f2f';
                    }
                }
                
                // 计算测试 LOF 盘中价对应的溢价率
                var targetPrice = parseFloat(document.getElementById('sb-target-price-' + code)?.value) || 0;
                var targetPremEl = document.getElementById('sb-target-prem-' + code);
                var targetLightEl = document.getElementById('sb-target-light-' + code);
                if (targetPremEl) {
                    if (targetPrice > 0 && val > 0) {
                        var targetPrem = (targetPrice / val - 1) * 100;
                        targetPremEl.textContent = (targetPrem >= 0 ? '+' : '') + targetPrem.toFixed(2) + '%';
                        targetPremEl.style.color = targetPrem >= 0 ? '#2e7d32' : '#d32f2f';
                        if (targetLightEl) targetLightEl.innerHTML = targetPrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                    } else {
                        targetPremEl.textContent = '-';
                        targetPremEl.style.color = '';
                        if (targetLightEl) targetLightEl.innerHTML = '';
                    }
                }
            };
            
            window.calcFutureSandbox = function(code) {
                try {
                    var baseData = window.fundBaseData[code];
                    if (!baseData) return;
                    
                    // 同步提取并展示当前期货实盘价供参考
                    var futSym = baseData.futureSymbol;
                    var futPriceEl = futSym === 'GC' ? document.getElementById('gc-price') : document.getElementById('cl-price');
                    var sbRefEl = document.getElementById('sb-fut-ref-price-' + code);
                    if (sbRefEl && futPriceEl) sbRefEl.textContent = futPriceEl.textContent || '-';
                    
                    var fxText = document.getElementById('sb-exchange-rate-' + code)?.textContent || '';
                    var fx = parseFloat(fxText);
                    if (!fx || isNaN(fx)) {
                        var futValEl = document.getElementById('sb-fut-val-' + code);
                        var futPremEl = document.getElementById('sb-fut-prem-' + code);
                        var futTargetPremEl = document.getElementById('sb-fut-target-prem-' + code);
                        if (futValEl) futValEl.textContent = 'ERR: 无汇率';
                        if (futPremEl) futPremEl.textContent = '-';
                        if (futTargetPremEl) futTargetPremEl.textContent = '-';
                        return;
                    }
                    var fxChange = fx / baseData.baseExchangeRate;

                    var futPrice = parseFloat(document.getElementById('sb-fut-price-' + code)?.value) || 0;
                    var calib = parseFloat(document.getElementById('sb-fut-calib-' + code)?.value) || 1;
                    var equivEtf = 0;
                    if (calib > 0) equivEtf = futPrice / calib;
                    var equivEtfEl = document.getElementById('sb-equiv-etf-' + code);
                    if (equivEtfEl) equivEtfEl.textContent = equivEtf > 0 ? equivEtf.toFixed(4) : '-';

                    var validWeight = 0;
                    baseData.hedgingPortfolio.forEach(function(h) {
                        if (h.weight >= 0.02 && !h.symbol.includes('SLV')) validWeight += h.weight; // 只计算有效权重且排除SLV
                    });
                    
                    var weightedChange = 0;
                    if (validWeight > 0) {
                        baseData.hedgingPortfolio.forEach(function(h) {
                            if (h.weight >= 0.02 && !h.symbol.includes('SLV')) {
                                var basePrice = baseData.baseEtfPrices[h.symbol];
                                if (basePrice > 0 && equivEtf > 0) {
                                    weightedChange += (equivEtf / basePrice) * (h.weight / validWeight);
                                }
                            }
                        });
                    } else if (equivEtf > 0) {
                        weightedChange = equivEtf / 100;
                    }

                    if (validWeight === 0 && equivEtf === 0) {
                        var futValEl = document.getElementById('sb-fut-val-' + code);
                        var futPremEl = document.getElementById('sb-fut-prem-' + code);
                        var futTargetPremEl = document.getElementById('sb-fut-target-prem-' + code);
                        if (futValEl) futValEl.textContent = '-';
                        if (futPremEl) futPremEl.textContent = '-';
                        if (futTargetPremEl) futTargetPremEl.textContent = '-';
                        return;
                    }

                    var val = baseData.baseNav * (1 + baseData.position * (weightedChange * fxChange - 1));
                    var futValEl = document.getElementById('sb-fut-val-' + code);
                    if (futValEl) futValEl.textContent = val.toFixed(4);

                    // 计算预测溢价：使用统一的 A股 LOF 测试单价
                    var targetPrice = parseFloat(document.getElementById('sb-target-price-' + code)?.value) || 0;
                    var targetPremEl = document.getElementById('sb-fut-target-prem-' + code);
                    var targetLightEl = document.getElementById('sb-fut-target-light-' + code);
                    if (targetPremEl) {
                        if (targetPrice > 0 && val > 0) {
                            var targetPrem = (targetPrice / val - 1) * 100;
                            targetPremEl.textContent = (targetPrem >= 0 ? '+' : '') + targetPrem.toFixed(2) + '%';
                            targetPremEl.style.color = targetPrem >= 0 ? '#2e7d32' : '#d32f2f';
                            if (targetLightEl) targetLightEl.innerHTML = targetPrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                        } else {
                            targetPremEl.textContent = '-';
                            targetPremEl.style.color = '';
                            if (targetLightEl) targetLightEl.innerHTML = '';
                        }
                    }
                } catch (e) {
                    console.error('计算期货校准估值失败:', e);
                }
            };
            
            window.calcPureFutureSandbox = function(code) {
                try {
                    var baseData = window.fundBaseData[code];
                    if (!baseData) return;
                    
                    // 同步提取并展示当前期货实盘价供参考
                    var futSym = baseData.futureSymbol;
                    var futPriceEl = null;
                    if (futSym === 'GC') futPriceEl = document.getElementById('gc-price');
                    else if (futSym === 'CL') futPriceEl = document.getElementById('cl-price');
                    else if (futSym === 'NQ') futPriceEl = document.getElementById('nq-price');
                    else if (futSym === 'ES') futPriceEl = document.getElementById('es-price');
                    var sbRefEl = document.getElementById('sb-pure-ref-price-' + code);
                    if (sbRefEl && futPriceEl) sbRefEl.textContent = futPriceEl.textContent || '-';
                    
                    var reqSpot = (baseData.rateType === 'spot');
                    var fx = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                    
                    if (!fx || isNaN(fx) || fx <= 0) {
                        var pureValEl = document.getElementById('sb-pure-val-' + code);
                        var purePremEl = document.getElementById('sb-pure-prem-' + code);
                        var pureTargetPremEl = document.getElementById('sb-pure-target-prem-' + code);
                        if (pureValEl) pureValEl.textContent = 'ERR: 无汇率';
                        if (purePremEl) purePremEl.textContent = '-';
                        if (pureTargetPremEl) pureTargetPremEl.textContent = '-';
                        return;
                    }

                    var futPrice = parseFloat(document.getElementById('sb-pure-fut-price-' + code)?.value) || 0;
                    
                    if (futPrice <= 0) {
                        var pureValEl = document.getElementById('sb-pure-val-' + code);
                        var purePremEl = document.getElementById('sb-pure-prem-' + code);
                        var pureTargetPremEl = document.getElementById('sb-pure-target-prem-' + code);
                        if (pureValEl) pureValEl.textContent = '-';
                        if (purePremEl) purePremEl.textContent = '-';
                        if (pureTargetPremEl) pureTargetPremEl.textContent = '-';
                        return;
                    }

                    var derivedFutureHedge = 0;
                    if (baseData.baseFuturePrice > 0 && baseData.baseExchangeRate > 0) {
                        derivedFutureHedge = (baseData.baseFuturePrice * baseData.baseExchangeRate) / (baseData.baseNav * baseData.position);
                    }
                    
                    if (derivedFutureHedge > 0) {
                        var val = baseData.baseNav * (1.0 - baseData.position) + (futPrice * fx) / derivedFutureHedge;
                        
                        var pureValEl = document.getElementById('sb-pure-val-' + code);
                        if (pureValEl) pureValEl.textContent = val.toFixed(4);

                        // 计算预测溢价：使用统一的 A股 LOF 测试单价
                        var targetPrice = parseFloat(document.getElementById('sb-target-price-' + code)?.value) || 0;
                        var targetPremEl = document.getElementById('sb-pure-target-prem-' + code);
                        var targetLightEl = document.getElementById('sb-pure-target-light-' + code);
                        if (targetPremEl) {
                            if (targetPrice > 0 && val > 0) {
                                var targetPrem = (targetPrice / val - 1) * 100;
                                targetPremEl.textContent = (targetPrem >= 0 ? '+' : '') + targetPrem.toFixed(2) + '%';
                                targetPremEl.style.color = targetPrem >= 0 ? '#2e7d32' : '#d32f2f';
                                if (targetLightEl) targetLightEl.innerHTML = targetPrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            } else {
                                targetPremEl.textContent = '-';
                                targetPremEl.style.color = '';
                                if (targetLightEl) targetLightEl.innerHTML = '';
                            }
                        }
                    } else {
                        var exactChange = 0;
                        if (baseData.baseFuturePrice > 0) exactChange = futPrice / baseData.baseFuturePrice;
                        
                        if (exactChange > 0) {
                            var fxChange = fx / baseData.baseExchangeRate;
                            var val = baseData.baseNav * (1 + baseData.position * (exactChange * fxChange - 1));
                            var pureValEl = document.getElementById('sb-pure-val-' + code);
                            if (pureValEl) pureValEl.textContent = val.toFixed(4);
                            
                            var targetPrice = parseFloat(document.getElementById('sb-target-price-' + code)?.value) || 0;
                            var targetPremEl = document.getElementById('sb-pure-target-prem-' + code);
                            var targetLightEl = document.getElementById('sb-pure-target-light-' + code);
                            if (targetPremEl) {
                                if (targetPrice > 0 && val > 0) {
                                    var targetPrem = (targetPrice / val - 1) * 100;
                                    targetPremEl.textContent = (targetPrem >= 0 ? '+' : '') + targetPrem.toFixed(2) + '%';
                                    targetPremEl.style.color = targetPrem >= 0 ? '#2e7d32' : '#d32f2f';
                                    if (targetLightEl) targetLightEl.innerHTML = targetPrem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                                } else {
                                    targetPremEl.textContent = '-';
                                    targetPremEl.style.color = '';
                                    if (targetLightEl) targetLightEl.innerHTML = '';
                                }
                            }
                        } else {
                            var pureValEl = document.getElementById('sb-pure-val-' + code);
                            var pureTargetPremEl = document.getElementById('sb-pure-target-prem-' + code);
                            if (pureValEl) pureValEl.textContent = '-';
                            if (pureTargetPremEl) pureTargetPremEl.textContent = '-';
                        }
                    }
                } catch (e) {
                    console.error('计算纯期货估值失败:', e);
                }
            };
            
            // 统一的沙盘执行交易接口
            window.executeTrade = function(code, action, sandboxType) {
                var brokerEl = document.getElementById('trade-broker-' + code + '-' + sandboxType);
                var broker = brokerEl ? brokerEl.value : 'yinhe_qmt';

                if (broker === 'tdx') {
                    alert('通达信下单功能因API存在Bug已禁用，请选择其他通道。');
                    return;
                }

                // 使用 Emoji 模拟原生系统弹窗的颜色警示效果
                var brokerNameDisplay = broker === 'yinhe_qmt' ? '🔵【银河QMT】' : (broker === 'guojin_qmt' ? '🟡【国金QMT】' : '🔴【通达信】');
                
                var priceStr = document.getElementById('trade-price-' + code + '-' + sandboxType).value;
                if (!priceStr) { alert('⚠️ 请在 ' + brokerNameDisplay + ' 交易参数中填入委托限价！'); return; }
                var price = parseFloat(priceStr);
                
                var vol = parseInt(document.getElementById('trade-vol-' + code + '-' + sandboxType).value);
                if (!vol || vol <= 0 || vol % 100 !== 0) { alert('⚠️ 委托数量必须是100的整数倍！'); return; }
                
                var actionText = action === 'BUY' ? '折价买入' : '溢价卖出(或折价赎回)';
                if (!confirm('🚨 危险操作确认 🚨\n\n您确定要通过 ' + brokerNameDisplay + ' 自动执行以下交易吗？\n\n方向: ' + actionText + '\n代码: ' + code + '\n价格: ' + price + '\n数量: ' + vol)) return;
                
                var msgEl = document.getElementById('trade-msg-' + code + '-' + sandboxType);
                msgEl.textContent = '🚀 指令发送中...';
                msgEl.style.color = '#f57c00';
                
                // 自动补全交易所后缀，5开头补SH，否则补SZ
                var fullSymbol = code + (code.startsWith('5') ? '.SH' : '.SZ');
                
                fetch('http://localhost:5000/api/trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action, symbol: fullSymbol, volume: vol, price: price, broker: broker })
                })
                .then(res => res.json())
                .then(data => {
                    msgEl.textContent = (data.status === 'success' ? '✅ ' : '❌ ') + data.message;
                    msgEl.style.color = data.status === 'success' ? '#2e7d32' : '#d32f2f';
                })
                .catch(err => { msgEl.textContent = '❌ 网络请求失败'; msgEl.style.color = '#d32f2f'; });
            };
            
            // IB 外盘独立交易接口
            window.executeIbTrade = function(code, action, sandboxType) {
                var symInput = document.getElementById('ib-trade-sym-' + code + '-' + sandboxType).value.trim().toUpperCase();
                var volInput = parseInt(document.getElementById('ib-trade-vol-' + code + '-' + sandboxType).value);
                var priceInput = parseFloat(document.getElementById('ib-trade-price-' + code + '-' + sandboxType).value);
                
                if (!symInput) { alert('⚠️ 请输入美股标的代码！'); return; }
                if (!volInput || volInput <= 0) { alert('⚠️ 委托数量必须大于0！'); return; }
                if (!priceInput || priceInput <= 0) { alert('⚠️ 请输入有效的限价！'); return; }
                
                var actionText = action === 'BUY' ? '买入平仓' : '卖空开仓';
                if (!confirm('🚨 IB 危险操作确认\n\n您确定要通过 IB 自动执行以下美股交易吗？\n\n方向: ' + actionText + '\n标的: ' + symInput + '\n价格: ' + priceInput + '\n数量: ' + volInput)) return;
                
                var msgEl = document.getElementById('ib-trade-msg-' + code + '-' + sandboxType);
                msgEl.textContent = '🚀 指令发送中...';
                msgEl.style.color = '#f57c00';
                
                fetch('http://localhost:5000/api/ib_trade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: action, symbol: symInput, volume: volInput, price: priceInput })
                })
                .then(res => res.json())
                .then(data => {
                    msgEl.textContent = (data.status === 'success' ? '✅ ' : '❌ ') + data.message;
                    msgEl.style.color = data.status === 'success' ? '#1565c0' : '#d32f2f';
                })
                .catch(err => { msgEl.textContent = '❌ 网络请求失败'; msgEl.style.color = '#d32f2f'; });
            };
            
            // 手动输入夜盘数据的功能
            window.calculateRealTimeValues = function() {
                
                var afterClose = isAfterMarketClose() || !isTradingDay();
                var warnEl = document.getElementById('etf-freeze-warn');
                var warnElIdx = document.getElementById('etf-freeze-warn-idx');
                if (warnEl) {
                    warnEl.style.display = afterClose ? 'inline' : 'none';
                }
                if (warnElIdx) {
                    warnElIdx.style.display = afterClose ? 'inline' : 'none';
                }
                
                var useIB = document.getElementById('source-ib') && document.getElementById('source-ib').checked;
                var badge = document.getElementById('active-source-badge');
                var gldPrice = 0, usoPrice = 0, xopPrice = 0, xbiPrice = 0, slvPrice = 0, spyPrice = 0, qqqPrice = 0;
                
                console.log('===== calculateRealTimeValues 调试 =====');
                console.log('数据源:', useIB ? 'IB' : '手工');
                
                // 根据用户的单选框，决定是从IB读取文本，还是从输入框读取数字
                if (useIB) {
                    if(badge) { badge.textContent = '🟢 应用: IB夜盘'; badge.style.backgroundColor = '#e8f5e9'; badge.style.color = '#2e7d32'; badge.style.border = '1px solid #a5d6a7'; }
                    var g = document.getElementById('ib-val-gld')?.textContent || '0';
                    var u = document.getElementById('ib-val-uso')?.textContent || '0';
                    var x = document.getElementById('ib-val-xop')?.textContent || '0';
                    var xbi = document.getElementById('ib-val-xbi')?.textContent || '0';
                    var s = document.getElementById('ib-val-slv')?.textContent || '0';
                    var spy = document.getElementById('ib-val-spy')?.textContent || '0';
                    var qqq = document.getElementById('ib-val-qqq')?.textContent || '0';
                    gldPrice = parseFloat(g) || 0;
                    usoPrice = parseFloat(u) || 0;
                    xopPrice = parseFloat(x) || 0;
                    xbiPrice = parseFloat(xbi) || 0;
                    slvPrice = parseFloat(s) || 0;
                    spyPrice = parseFloat(spy) || 0;
                    qqqPrice = parseFloat(qqq) || 0;
                } else {
                    if(badge) { badge.textContent = '✍️ 应用: 手工'; badge.style.backgroundColor = '#fff8e1'; badge.style.color = '#f57f17'; badge.style.border = '1px solid #ffe082'; }
                    gldPrice = parseFloat(document.getElementById('gld-price')?.value) || 0;
                    usoPrice = parseFloat(document.getElementById('uso-price')?.value) || 0;
                    xopPrice = parseFloat(document.getElementById('xop-price')?.value) || 0;
                    xbiPrice = parseFloat(document.getElementById('xbi-price')?.value) || 0;
                    slvPrice = parseFloat(document.getElementById('slv-price')?.value) || 0;
                    spyPrice = parseFloat(document.getElementById('spy-price')?.value) || 0;
                    qqqPrice = parseFloat(document.getElementById('qqq-price')?.value) || 0;
                }
                
                console.log('价格 - GLD:', gldPrice, 'USO:', usoPrice, 'XOP:', xopPrice, 'XBI:', xbiPrice, 'SLV:', slvPrice, 'SPY:', spyPrice, 'QQQ:', qqqPrice);
                console.log('汇率元素:', document.getElementById('exchange-rate-display')?.textContent);
                
                var allRows = document.querySelectorAll('tbody tr');
                var filteredRows = Array.from(allRows).filter(row => {
                    var isHomePage = !!row.closest('#page-home');
                    var closeCell = row.querySelector('td:nth-child(5)');
                    var isSecondaryClose = closeCell && closeCell.classList.contains('secondary-close');
                    return isHomePage && !isSecondaryClose;
                });
                
                filteredRows.forEach(function(row) {
                    var cells = row.querySelectorAll('td');
                    if (cells.length >= 9) { // 指数表9列，大宗表11列
                        var codeCell = cells[0];
                        var categoryCell = cells[1];
                        var staticValuationCell = cells[5]; // 因前面插入了仓位列，索引顺延
                        
                        var code = codeCell.textContent.trim();
                        var category = categoryCell.textContent.trim();
                        var staticValuation = parseFloat(staticValuationCell.textContent) || 0;
                        
                        var closePriceElement = document.getElementById('realtime-price-' + code);
                        var closePriceText = closePriceElement ? closePriceElement.textContent : '';
                        var closePriceMatch = closePriceText.match(/\d+(?:\.\d+)?/);
                        var closePrice = closePriceMatch ? parseFloat(closePriceMatch[0]) : 0;
                        
                        if (closePrice === 0 || (closePrice >= 100000 && closePrice <= 999999)) {
                            closePrice = staticValuation;
                            if (closePrice === 0) return;
                        }
                        
                        var etfValuationElement = document.getElementById('realtime-valuation-' + code);
                        var etfPremiumElement = document.getElementById('realtime-premium-' + code);
                        var etfLightElement = document.getElementById('realtime-light-' + code);
                        
                        if (etfValuationElement) {
                            etfValuationElement.textContent = '-';
                            etfValuationElement.style.color = '';
                            etfValuationElement.style.fontWeight = '';
                        }
                        if (etfPremiumElement) {
                            etfPremiumElement.textContent = '-';
                            etfPremiumElement.style.color = '';
                            etfPremiumElement.style.fontWeight = '';
                        }
                        if (etfLightElement) {
                            etfLightElement.innerHTML = '';
                        }
                        
                        // 核心修复：废弃硬编码！动态遍历其底层篮子，只要所有成分都有报价才允许计算
                        var canCalculate = false;
                        var fData = window.fundBaseData[code];
                        if (fData && fData.hedgingPortfolio && fData.hedgingPortfolio.length > 0) {
                            canCalculate = true;
                            fData.hedgingPortfolio.forEach(function(item) {
                                var curP = 0;
                                if (item.symbol.includes('GLD')) curP = gldPrice;
                                else if (item.symbol.includes('USO')) curP = usoPrice;
                                else if (item.symbol.includes('XOP')) curP = xopPrice;
                                else if (item.symbol.includes('XBI')) curP = xbiPrice;
                                else if (item.symbol.includes('SLV')) curP = slvPrice;
                                else if (item.symbol.includes('SPY')) curP = spyPrice;
                                else if (item.symbol.includes('QQQ')) curP = qqqPrice;
                                if (curP <= 0) canCalculate = false;
                            });
                        }
                        
                        if (canCalculate) {
                            
                            var etfRealTimeValuation = window.calculateETFRealTimeValuation(code, category, gldPrice, usoPrice, xopPrice, xbiPrice, slvPrice, spyPrice, qqqPrice, staticValuation);
                            
                            if (etfRealTimeValuation && etfRealTimeValuation > 0) {
                                var etfRealTimePremium = (closePrice - etfRealTimeValuation) / etfRealTimeValuation * 100;
                                
                                if (etfValuationElement) {
                                    etfValuationElement.textContent = etfRealTimeValuation.toFixed(4);
                                    etfValuationElement.style.color = afterClose ? '#757575' : '#007bff';
                                    etfValuationElement.style.fontWeight = 'bold';
                                }

                                if (etfPremiumElement) {
                                    etfPremiumElement.textContent = (etfRealTimePremium >= 0 ? '+' : '') + etfRealTimePremium.toFixed(2) + '%';
                                    etfPremiumElement.style.color = afterClose ? '#9e9e9e' : (etfRealTimePremium >= 0 ? '#2e7d32' : '#d32f2f');
                                    etfPremiumElement.style.fontWeight = 'bold';
                                }
                                if (etfLightElement) {
                                    if (afterClose) {
                                        etfLightElement.innerHTML = '<span class="arb-light" style="background-color:#bdbdbd; opacity:0.6;" title="收盘后由于IB行情限制，已冻结"></span>';
                                    } else {
                                        if (etfRealTimePremium <= -0.8) {
                                            etfLightElement.innerHTML = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>';
                                            
                                        } else {
                                            etfLightElement.innerHTML = '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                                        }
                                    }
                                }
                            }
                        }
                    }
                });
                
                // 记录当前生效的主面板价格池，供沙盘同步使用
                window.currentEtfPrices = {
                    gld: gldPrice,
                    uso: usoPrice,
                    xop: xopPrice,
                    xbi: xbiPrice,
                    slv: slvPrice,
                    spy: spyPrice,
                    qqq: qqqPrice
                };
                
                localStorage.setItem('nightSessionPrices', JSON.stringify({
                    GLD: gldPrice, USO: usoPrice, XOP: xopPrice, XBI: xbiPrice, SLV: slvPrice, SPY: spyPrice, QQQ: qqqPrice, timestamp: new Date().getTime()
                }));
                
                // 行情跳动后，刷新所有已打开沙盘的对冲数量
                Object.keys(window.fundBaseData).forEach(function(c) {
                    ['etf', 'future', 'pure_future'].forEach(function(t) {
                        window.calcHedgeQty(c, t);
                    });
                });
            };
            
            function updateFuturesData() {
                var xhr = new XMLHttpRequest();
                xhr.open('GET', 'http://localhost:5000/api/futures', true);
                xhr.onreadystatechange = function() {
                    if (xhr.readyState === 4 && xhr.status === 200) {
                        try {
                            var data = JSON.parse(xhr.responseText);
                            var ag0Price = data.AG0 ? data.AG0.price : 0;
                            var ag0ChangePercent = data.AG0 ? data.AG0.change_percent : 0;
                            var gcPrice = data.GC ? data.GC.price : 0;
                            var gcChangePercent = data.GC ? data.GC.change_percent : 0;
                            var clPrice = data.CL ? data.CL.price : 0;
                            var clChangePercent = data.CL ? data.CL.change_percent : 0;
                            var nqPrice = data.NQ ? data.NQ.price : 0;
                            var nqChangePercent = data.NQ ? data.NQ.change_percent : 0;
                            var esPrice = data.ES ? data.ES.price : 0;
                            var esChangePercent = data.ES ? data.ES.change_percent : 0;
                            
                            if (document.getElementById('ag0-price')) {
                                document.getElementById('ag0-price').textContent = ag0Price > 0 ? ag0Price.toFixed(2) : '-';
                            }
                            if (document.getElementById('ag0-change')) {
                                var ag0ChangeText = ag0ChangePercent >= 0 ? '+' + ag0ChangePercent.toFixed(2) + '%' : ag0ChangePercent.toFixed(2) + '%';
                                var ag0ChangeColor = ag0ChangePercent >= 0 ? '#2e7d32' : '#d32f2f';
                                document.getElementById('ag0-change').textContent = ag0Price > 0 ? ag0ChangeText : '-';
                                document.getElementById('ag0-change').style.color = ag0ChangeColor;
                            }
                            if (document.getElementById('gc-price')) {
                                document.getElementById('gc-price').textContent = gcPrice > 0 ? gcPrice.toFixed(2) : '-';
                            }
                            if (document.getElementById('gc-change')) {
                                var gcChangeText = gcChangePercent >= 0 ? '+' + gcChangePercent.toFixed(2) + '%' : gcChangePercent.toFixed(2) + '%';
                                var gcChangeColor = gcChangePercent >= 0 ? '#2e7d32' : '#d32f2f';
                                document.getElementById('gc-change').textContent = gcPrice > 0 ? gcChangeText : '-';
                                document.getElementById('gc-change').style.color = gcChangeColor;
                            }
                            if (document.getElementById('cl-price')) {
                                document.getElementById('cl-price').textContent = clPrice > 0 ? clPrice.toFixed(2) : '-';
                            }
                            if (document.getElementById('cl-change')) {
                                var clChangeText = clChangePercent >= 0 ? '+' + clChangePercent.toFixed(2) + '%' : clChangePercent.toFixed(2) + '%';
                                var clChangeColor = clChangePercent >= 0 ? '#2e7d32' : '#d32f2f';
                                document.getElementById('cl-change').textContent = clPrice > 0 ? clChangeText : '-';
                                document.getElementById('cl-change').style.color = clChangeColor;
                            }
                            if (document.getElementById('nq-price')) {
                                document.getElementById('nq-price').textContent = nqPrice > 0 ? nqPrice.toFixed(2) : '-';
                            }
                            if (document.getElementById('nq-change')) {
                                var nqChangeText = nqChangePercent >= 0 ? '+' + nqChangePercent.toFixed(2) + '%' : nqChangePercent.toFixed(2) + '%';
                                var nqChangeColor = nqChangePercent >= 0 ? '#2e7d32' : '#d32f2f';
                                document.getElementById('nq-change').textContent = nqPrice > 0 ? nqChangeText : '-';
                                document.getElementById('nq-change').style.color = nqChangeColor;
                            }
                            if (document.getElementById('es-price')) {
                                document.getElementById('es-price').textContent = esPrice > 0 ? esPrice.toFixed(2) : '-';
                            }
                            if (document.getElementById('es-change')) {
                                var esChangeText = esChangePercent >= 0 ? '+' + esChangePercent.toFixed(2) + '%' : esChangePercent.toFixed(2) + '%';
                                var esChangeColor = esChangePercent >= 0 ? '#2e7d32' : '#d32f2f';
                                document.getElementById('es-change').textContent = esPrice > 0 ? esChangeText : '-';
                                document.getElementById('es-change').style.color = esChangeColor;
                            }
                            window.lastKnownFutures = { GC: gcPrice, CL: clPrice, NQ: nqPrice, ES: esPrice };
                            window.updateFuturesTableColumns(gcPrice, clPrice, nqPrice, esPrice);
                            
                            // 更新详情页面上的期货测试价输入框
                            try {
                                Object.keys(window.fundBaseData).forEach(function(code) {
                                    var baseData = window.fundBaseData[code];
                                    if (!baseData || !baseData.futureSymbol) return;
                                    
                                    var futPrice = 0;
                                    if (baseData.futureSymbol === 'GC') futPrice = gcPrice;
                                    else if (baseData.futureSymbol === 'CL') futPrice = clPrice;
                                    else if (baseData.futureSymbol === 'NQ') futPrice = nqPrice;
                                    else if (baseData.futureSymbol === 'ES') futPrice = esPrice;
                                    
                                    if (futPrice > 0) {
                                        // 更新期货校准测试价输入框
                                        var futPriceInput = document.getElementById('sb-fut-price-' + code);
                                        if (futPriceInput) {
                                            futPriceInput.value = futPrice.toFixed(2);
                                        }
                                        
                                        // 更新纯期货测试价输入框
                                        var pureFutPriceInput = document.getElementById('sb-pure-fut-price-' + code);
                                        if (pureFutPriceInput) {
                                            pureFutPriceInput.value = futPrice.toFixed(2);
                                        }
                                        
                                        // 触发计算函数
                                        if (window.calcFutureSandbox) window.calcFutureSandbox(code);
                                        if (window.calcPureFutureSandbox) window.calcPureFutureSandbox(code);
                                    }
                                });
                            } catch (e) {
                                console.error('更新期货测试价输入框失败:', e);
                            }
                            
                            // 更新ETF实时估值
                            try {
                                Object.keys(window.fundBaseData).forEach(function(code) {
                                    if (window.calcSandbox) window.calcSandbox(code);
                                });
                            } catch (e) {
                                console.error('更新ETF实时估值失败:', e);
                            }
                        } catch (e) { console.error('处理期货数据失败:', e); }
                    } else if (xhr.readyState === 4) {
                        setTimeout(updateFuturesData, 3000);
                    }
                };
                xhr.send();
            }
            
            // 核心功能：前端纯JS无刷新算透期货校准和纯期货两列估值
            window.updateFuturesTableColumns = function(gcPrice, clPrice, nqPrice, esPrice) {
                Object.keys(window.fundBaseData).forEach(function(code) {
                    var baseData = window.fundBaseData[code];
                    if (!baseData || !baseData.position) return;

                    var reqSpot = (baseData.rateType === 'spot');
                    var effectiveExchangeRate = (reqSpot && window.latestExchangeRates && window.latestExchangeRates.spot) ? window.latestExchangeRates.spot : baseData.todayExchangeRate;
                    if (!effectiveExchangeRate || effectiveExchangeRate <= 0) {
                        if (baseData && baseData.latestExchangeRate) {
                            effectiveExchangeRate = baseData.latestExchangeRate;
                        } else {
                            return; // 彻底没有汇率，放弃此基金的计算
                        }
                    }

                    var futPrice = 0;
                    if (baseData.futureSymbol === 'GC') futPrice = gcPrice;
                    else if (baseData.futureSymbol === 'CL') futPrice = clPrice;
                    else if (baseData.futureSymbol === 'NQ') futPrice = nqPrice;
                    else if (baseData.futureSymbol === 'ES') futPrice = esPrice;
                    if (futPrice <= 0) return;
                    
                    if (!baseData.baseExchangeRate || isNaN(baseData.baseExchangeRate) || baseData.baseExchangeRate <= 0) {
                        return;
                    }
                    
                    var fxChange = effectiveExchangeRate / baseData.baseExchangeRate;
                    
                    var staticValuation = 0;
                    var allRows = document.querySelectorAll('#page-home tbody tr');
                    var targetRow = Array.from(allRows).find(r => r.cells.length >= 10 && r.cells[0].textContent.trim() === code);
                    if (targetRow) staticValuation = parseFloat(targetRow.cells[5].textContent) || 0;

                    var closePriceElement = document.getElementById('realtime-price-' + code);
                    var closePriceText = closePriceElement ? closePriceElement.textContent : '';
                    var closePriceMatch = closePriceText.match(/\d+(?:\.\d+)?/);
                    var livePrice = closePriceMatch ? parseFloat(closePriceMatch[0]) : 0;
                    if (livePrice === 0 || livePrice > 9999) livePrice = staticValuation;
                    if (livePrice === 0) return;
                    
                    var premiumBasePrice = livePrice;
                    
                    // 提取统一对冲基石
                    var hedgeValue = baseData.hedgeValue;
                    if (!hedgeValue || hedgeValue <= 0) hedgeValue = baseData.etfHedgeValue;

                    // ====== [魔法] 列2: 期货校准估值 ======
                    var calib = baseData.category === '黄金' ? window.calibData.gold : window.calibData.oil;
                    var calibFactor = baseData.latestCalibrationFactor > 0 ? baseData.latestCalibrationFactor : calib;
                    
                    if (hedgeValue && hedgeValue > 0 && calibFactor > 0) {
                        var equivEtf = futPrice / calibFactor;
                        var calibVal = baseData.baseNav * (1.0 - baseData.position) + (equivEtf * effectiveExchangeRate) / hedgeValue;
                        
                        var calibValEl = document.getElementById('rt-calib-val-' + code);
                        var calibPremEl = document.getElementById('rt-calib-prem-' + code);
                        var calibLightEl = document.getElementById('rt-calib-light-' + code);
                        if (calibValEl) { calibValEl.textContent = calibVal.toFixed(4); calibValEl.style.color = '#1976d2'; calibValEl.style.fontWeight = 'bold'; }
                        if (calibPremEl) {
                            var prem = (premiumBasePrice / calibVal - 1) * 100;
                            calibPremEl.textContent = (prem >= 0 ? '+' : '') + prem.toFixed(2) + '%';
                            calibPremEl.style.color = prem >= 0 ? '#2e7d32' : '#d32f2f';
                            if (calibLightEl) calibLightEl.innerHTML = prem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                        }
                    } else {
                        // 降级: 矩阵方式
                        var equivEtf = calib > 0 ? futPrice / calib : 0;
                        var validWeight = 0;
                        baseData.hedgingPortfolio.forEach(function(h) { if(h.weight >= 0.02 && !h.symbol.includes('SLV')) validWeight += h.weight; });
                        var weightedChange = 0;
                        if (validWeight > 0) {
                            baseData.hedgingPortfolio.forEach(function(h) {
                                if (h.weight >= 0.02 && !h.symbol.includes('SLV') && baseData.baseEtfPrices[h.symbol] > 0) {
                                    weightedChange += (equivEtf / baseData.baseEtfPrices[h.symbol]) * (h.weight / validWeight);
                                }
                            });
                        } else if (equivEtf > 0) weightedChange = equivEtf / 100;
                        
                        if (weightedChange > 0) {
                            var calibVal = baseData.baseNav * (1 + baseData.position * (weightedChange * fxChange - 1));
                            var calibValEl = document.getElementById('rt-calib-val-' + code);
                            var calibPremEl = document.getElementById('rt-calib-prem-' + code);
                            var calibLightEl = document.getElementById('rt-calib-light-' + code);
                            if (calibValEl) { calibValEl.textContent = calibVal.toFixed(4); calibValEl.style.color = '#1976d2'; calibValEl.style.fontWeight = 'bold'; }
                            if (calibPremEl) {
                                var prem = (premiumBasePrice / calibVal - 1) * 100;
                                calibPremEl.textContent = (prem >= 0 ? '+' : '') + prem.toFixed(2) + '%';
                                calibPremEl.style.color = prem >= 0 ? '#2e7d32' : '#d32f2f';
                                if (calibLightEl) calibLightEl.innerHTML = prem <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            }
                        }
                    }

                    // ====== [魔法] 列3: 纯期货映射 ======
                    var derivedFutureHedge = 0;
                    if (baseData.baseFuturePrice > 0 && baseData.baseExchangeRate > 0) {
                        derivedFutureHedge = (baseData.baseFuturePrice * baseData.baseExchangeRate) / (baseData.baseNav * baseData.position);
                    }
                    
                    if (derivedFutureHedge > 0) {
                        var exactVal = baseData.baseNav * (1.0 - baseData.position) + (futPrice * effectiveExchangeRate) / derivedFutureHedge;
                        var exactValEl = document.getElementById('rt-exact-val-' + code);
                        var exactPremEl = document.getElementById('rt-exact-prem-' + code);
                        var exactLightEl = document.getElementById('rt-exact-light-' + code);
                        if (exactValEl) { exactValEl.textContent = exactVal.toFixed(4); exactValEl.style.color = '#1976d2'; exactValEl.style.fontWeight = 'bold'; }
                        if (exactPremEl) {
                            var prem2 = (premiumBasePrice / exactVal - 1) * 100;
                            exactPremEl.textContent = (prem2 >= 0 ? '+' : '') + prem2.toFixed(2) + '%';
                            exactPremEl.style.color = prem2 >= 0 ? '#2e7d32' : '#d32f2f';
                            if (exactLightEl) exactLightEl.innerHTML = prem2 <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                        }
                    } else {
                        // 降级: 矩阵方式
                        var exactChange = 0;
                        if (baseData.baseFuturePrice > 0) exactChange = futPrice / baseData.baseFuturePrice;
                        if (exactChange > 0) {
                            var exactVal = baseData.baseNav * (1 + baseData.position * (exactChange * fxChange - 1));
                            var exactValEl = document.getElementById('rt-exact-val-' + code);
                            var exactPremEl = document.getElementById('rt-exact-prem-' + code);
                            var exactLightEl = document.getElementById('rt-exact-light-' + code);
                            if (exactValEl) { exactValEl.textContent = exactVal.toFixed(4); exactValEl.style.color = '#1976d2'; exactValEl.style.fontWeight = 'bold'; }
                            if (exactPremEl) {
                                var prem2 = (premiumBasePrice / exactVal - 1) * 100;
                                exactPremEl.textContent = (prem2 >= 0 ? '+' : '') + prem2.toFixed(2) + '%';
                                exactPremEl.style.color = prem2 >= 0 ? '#2e7d32' : '#d32f2f';
                                if (exactLightEl) exactLightEl.innerHTML = prem2 <= -0.8 ? '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' : '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>';
                            }
                        }
                    }
                });
            };

            function isTradingDay() {
                const today = new Date();
                const dayOfWeek = today.getDay();
                if (dayOfWeek === 0 || dayOfWeek === 6) return false;
                return true;
            }

            function isTradingHours() {
                const now = new Date();
                const hour = now.getHours();
                const minute = now.getMinutes();
                if ((hour === 9 && minute >= 30) || (hour === 10) || (hour === 11 && minute < 30) || 
                    (hour === 13) || (hour === 14) || (hour === 15 && minute === 0)) {
                    return true;
                }
                return false;
            }

            function isAfterMarketClose() {
                const now = new Date();
                const hour = now.getHours();
                const minute = now.getMinutes();
                if (hour > 15 || (hour === 15 && minute > 0)) {
                    return true;
                }
                return false;
            }

            var exchangeRateInterval = null;
            
            // 实时更新顶部汇率显示，并在获取到今日数据后自动停止轮询
            function updateExchangeRate() {
                fetch('http://localhost:5000/api/exchange_rate')
                    .then(r => r.json())
                    .then(data => {
                        if (data.rate) {
                            var el = document.getElementById('exchange-rate-display');
                            // 为了不破坏原有的 UI 更新流，如果是基础心跳仅更新文本前缀，但不影响沙盘实际底层 JS 取值
                            if (el && el.textContent.indexOf('在岸价') === -1) { el.textContent = '汇率: ' + data.rate.toFixed(4); }
                        
                            // 获取到有效汇率后，自动隐藏警告条
                            var warnEl = document.getElementById('exchange-rate-warning');
                            if (warnEl) warnEl.style.display = 'none';
                            
                            // 获取浏览器本地当前的日期 (格式: YYYY-MM-DD)
                            var d = new Date();
                            var todayStr = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
                            
                            // 如果读取到的汇率日期正好是今天，销毁定时器，停止轮询
                            if (data.date === todayStr) {
                                if (exchangeRateInterval) {
                                    clearInterval(exchangeRateInterval);
                                    console.log("✅ 已静默获取到今日最新汇率(" + data.date + ")，停止轮询以节省性能。");
                                }
                            }
                        }
                    })
                    .catch(e => {});
            }

            function updateLOFData() {
                const tradingDay = isTradingDay();
                const tradingHours = isTradingHours();
                const afterClose = isAfterMarketClose();
                
                fetch('http://localhost:5000/api/lof')
                    .then(response => response.json())
                    .then(data => {
                        var allRows = document.querySelectorAll('tbody tr');
                        var filteredRows = Array.from(allRows).filter(row => {
                            var isHomePage = !!row.closest('#page-home');
                            var closeCell = row.querySelector('td:nth-child(5)');
                            var isSecondaryClose = closeCell && closeCell.classList.contains('secondary-close');
                            return isHomePage && !isSecondaryClose;
                        });
                        
                        filteredRows.forEach(function(row) {
                            var cells = row.querySelectorAll('td');
                            if (cells.length >= 9) {
                                var codeCell = cells[0];
                                var code = codeCell.textContent.trim();
                                var realTimePriceElement = document.getElementById('realtime-price-' + code);
                                var t1PremiumElement = document.getElementById('t-1-premium-' + code);
                                var staticValuation = parseFloat(cells[5].textContent) || 0; // 修正列索引，第5列才是静态估值
                                
                                if (data[code] && data[code].price > 0) {
                                    if (realTimePriceElement) {
                                        realTimePriceElement.textContent = data[code].price.toFixed(3);
                                        if (!tradingDay || afterClose) {
                                            realTimePriceElement.style.color = '#2e7d32';
                                            realTimePriceElement.style.fontWeight = 'bold';
                                        } else {
                                            realTimePriceElement.style.color = '';
                                            realTimePriceElement.style.fontWeight = '';
                                        }
                                    }
                                    if (t1PremiumElement && staticValuation > 0) {
                                        var pct = (data[code].price / staticValuation - 1) * 100;
                                        var cls = pct >= 0 ? "" : "neg-value";
                                        var sign = pct > 0 ? "+" : "";
                                        t1PremiumElement.textContent = sign + pct.toFixed(2) + "%";
                                        t1PremiumElement.className = "num-font premium-big " + cls;
                                    }
                                } else {
                                    if (!tradingDay) {
                                        if (realTimePriceElement) realTimePriceElement.textContent = '非交易日';
                                    } else if (tradingHours) {
                                        if (realTimePriceElement) realTimePriceElement.textContent = '读取不到实时价格';
                                    } else if (afterClose) {
                                        if (realTimePriceElement) realTimePriceElement.textContent = '读取不到当天收盘价';
                                    } else {
                                        if (realTimePriceElement) realTimePriceElement.textContent = '休盘';
                                    }
                                    if (t1PremiumElement) t1PremiumElement.textContent = '';
                                }
                            }
                        });
                    })
                    .catch(error => {
                        console.error('获取LOF基金数据失败:', error);
                    })
                    .finally(() => {
                        setTimeout(function() {
                            window.calculateRealTimeValues();
                            if (window.lastKnownFutures) {
                                window.updateFuturesTableColumns(window.lastKnownFutures.GC, window.lastKnownFutures.CL, window.lastKnownFutures.NQ, window.lastKnownFutures.ES);
                            }
                            
                            // A股价格跳动后，刷新底层建议下单数量
                            Object.keys(window.fundBaseData).forEach(function(c) {
                                ['etf', 'future', 'pure_future'].forEach(function(t) {
                                    window.calcHedgeQty(c, t);
                                });
                            });
                        }, 100);
                    });
            }
            
            function showDetail(pageId) {
                var pages = document.querySelectorAll('.page-section');
                pages.forEach(function(page) { page.classList.remove('active'); });
                var targetPage = document.getElementById(pageId);
                if (targetPage) { targetPage.classList.add('active'); }
            }
            
            function goHome() {
                var pages = document.querySelectorAll('.page-section');
                pages.forEach(function(page) { page.classList.remove('active'); });
                var homePage = document.getElementById('page-home');
                if (homePage) { homePage.classList.add('active'); }
            }
            
            function toggleVerify(uid) {
                var verifyRow = document.getElementById('verify-' + uid);
                if (verifyRow) {
                    if (verifyRow.style.display === 'none' || verifyRow.style.display === '') {
                        verifyRow.style.display = 'table-row';
                    } else {
                        verifyRow.style.display = 'none';
                    }
                }
            }
            
            window.updateTime = updateTime;
            window.updateFuturesData = updateFuturesData;
            window.updateLOFData = updateLOFData;
            window.showDetail = showDetail;

            // 切换估值标签
            function switchValuationTab(code, type) {
                // 隐藏所有面板
                if (document.getElementById('panel-etf-' + code)) {
                    document.getElementById('panel-etf-' + code).style.display = 'none';
                }
                if (document.getElementById('panel-future-' + code)) {
                    document.getElementById('panel-future-' + code).style.display = 'none';
                }
                
                // 重置所有标签样式
                if (document.getElementById('tab-etf-' + code)) {
                    document.getElementById('tab-etf-' + code).style.background = '#e0e0e0';
                    document.getElementById('tab-etf-' + code).style.color = '#333';
                }
                if (document.getElementById('tab-future-' + code)) {
                    document.getElementById('tab-future-' + code).style.background = '#e0e0e0';
                    document.getElementById('tab-future-' + code).style.color = '#333';
                }
                
                // 显示当前面板并设置标签样式
                if (type === 'etf') {
                    if (document.getElementById('panel-etf-' + code)) {
                        document.getElementById('panel-etf-' + code).style.display = 'block';
                    }
                    if (document.getElementById('tab-etf-' + code)) {
                        document.getElementById('tab-etf-' + code).style.background = '#d35400';
                        document.getElementById('tab-etf-' + code).style.color = 'white';
                    }
                } else if (type === 'future') {
                    if (document.getElementById('panel-future-' + code)) {
                        document.getElementById('panel-future-' + code).style.display = 'block';
                    }
                    if (document.getElementById('tab-future-' + code)) {
                        document.getElementById('tab-future-' + code).style.background = '#1976d2';
                        document.getElementById('tab-future-' + code).style.color = 'white';
                    }
                }
            }
            window.switchValuationTab = switchValuationTab;
            
            // 切换主面板TAB
            function switchTab(tabIndex) {
                // 隐藏所有tab内容
                var tabContents = document.querySelectorAll('.tab-content');
                tabContents.forEach(function(tab) {
                    tab.classList.remove('active');
                });
                
                // 重置所有tab按钮样式
                var tabButtons = document.querySelectorAll('.tab-button');
                tabButtons.forEach(function(button) {
                    button.style.background = 'var(--secondary-light)';
                    button.style.color = 'var(--secondary-dark)';
                });
                
                // 显示当前tab内容并设置按钮样式
                var activeTab = document.getElementById('tab-' + tabIndex);
                if (activeTab) {
                    activeTab.classList.add('active');
                }
                
                var activeButton = tabButtons[tabIndex - 1];
                if (activeButton) {
                    activeButton.style.background = 'var(--primary-color)';
                    activeButton.style.color = 'white';
                }
            }
            window.switchTab = switchTab;
            
            window.goHome = goHome;
            window.updateExchangeRate = updateExchangeRate;
            
            function fetchLofSource() {
                fetch('http://localhost:5000/api/lof_source')
                    .then(r => r.json())
                    .then(d => {
                        var badge = document.getElementById('lof-source-badge');
                        if(badge) {
                            badge.textContent = d.source;
                            if(d.source.includes('新浪')) {
                                badge.style.background = '#fff3e0'; badge.style.color = '#e65100'; badge.style.border = '1px solid #ffe082';
                            } else {
                                badge.style.background = '#e8f5e9'; badge.style.color = '#2e7d32'; badge.style.border = '1px solid #a5d6a7';
                            }
                        }
                    }).catch(e => console.log('获取A股行情源失败'));
            }
            
            function reconnectLofSource() {
                var badge = document.getElementById('lof-source-badge');
                if(badge) { badge.textContent = "重连中..."; badge.style.background = '#f5f5f5'; badge.style.color = '#333'; badge.style.border = '1px solid #ddd'; }
                fetch('http://localhost:5000/api/reconnect_lof', {method: 'POST'})
                    .then(r => r.json())
                    .then(d => { setTimeout(fetchLofSource, 1500); })
                    .catch(e => { alert('重连请求失败，请检查02后台是否运行'); fetchLofSource(); });
            }
            
            window.reconnectLofSource = reconnectLofSource;

            window.onload = function() {
                window.updateTime();
                setInterval(window.updateTime, 1000);
                
                window.updateExchangeRate();
                exchangeRateInterval = setInterval(window.updateExchangeRate, 10000);
                
                window.updateFuturesData();
                setInterval(window.updateFuturesData, 30000);
                
                window.updateLOFData();
                setInterval(window.updateLOFData, 5000);
                
                fetchLofSource();
                setInterval(fetchLofSource, 15000); // 定期刷新以防后台发生通道异常降级
                
                var storedPrices = localStorage.getItem('nightSessionPrices');
                if (storedPrices) {
                    try {
                        var prices = JSON.parse(storedPrices);
                        var now = new Date().getTime();
                        var timeDiff = now - (prices.timestamp || 0);
                        
                        // 修复: 将过期时间从 1 小时放宽到 72 小时，避免周末停盘期间手工输入的数据丢失
                        if (timeDiff < 72 * 60 * 60 * 1000) {
                            if (prices.GLD && document.getElementById('gld-price')) document.getElementById('gld-price').value = parseFloat(prices.GLD).toFixed(3);
                            if (prices.USO && document.getElementById('uso-price')) document.getElementById('uso-price').value = parseFloat(prices.USO).toFixed(3);
                            if (prices.XOP && document.getElementById('xop-price')) document.getElementById('xop-price').value = parseFloat(prices.XOP).toFixed(3);
                            if (prices.XBI && document.getElementById('xbi-price')) document.getElementById('xbi-price').value = parseFloat(prices.XBI).toFixed(3);
                            if (prices.SLV && document.getElementById('slv-price')) document.getElementById('slv-price').value = parseFloat(prices.SLV).toFixed(3);
                            if (prices.SPY && document.getElementById('spy-price')) document.getElementById('spy-price').value = parseFloat(prices.SPY).toFixed(3);
                            if (prices.QQQ && document.getElementById('qqq-price')) document.getElementById('qqq-price').value = parseFloat(prices.QQQ).toFixed(3);
                            window.calculateRealTimeValues();
                        }
                    } catch (e) { console.error('解析本地存储数据失败:', e); }
                }
            };
            
            setInterval(async function() {
                try {
                    const response = await fetch('http://localhost:5000/api/ib_prices');
                    const data = await response.json();
                    
                    if (data.status === 'success' && data.prices) {
                        const prices = data.prices;
                        window.latestIbPrices = prices; // 存入全局供 Sandbox 调用
                        const prevCloses = data.prev_closes || {};
                        
                        // 仅更新 IB 展示行的数据，绝不干扰用户的手工输入框
                        if (document.getElementById('ib-val-gld')) {
                            document.getElementById('ib-val-gld').textContent = prices.GLD && prices.GLD.bid ? prices.GLD.bid.toFixed(2) : '-';
                            document.getElementById('ib-val-uso').textContent = prices.USO && prices.USO.bid ? prices.USO.bid.toFixed(2) : '-';
                            document.getElementById('ib-val-xop').textContent = prices.XOP && prices.XOP.bid ? prices.XOP.bid.toFixed(2) : '-';
                            document.getElementById('ib-val-xbi').textContent = prices.XBI && prices.XBI.bid ? prices.XBI.bid.toFixed(2) : '-';
                            document.getElementById('ib-val-slv').textContent = prices.SLV && prices.SLV.bid ? prices.SLV.bid.toFixed(2) : '-';
                            if(document.getElementById('ib-val-spy')) document.getElementById('ib-val-spy').textContent = prices.SPY && prices.SPY.bid ? prices.SPY.bid.toFixed(2) : '-';
                            if(document.getElementById('ib-val-qqq')) document.getElementById('ib-val-qqq').textContent = prices.QQQ && prices.QQQ.bid ? prices.QQQ.bid.toFixed(2) : '-';
                        }

                        // 动态更新已打开的 Sandbox 中的盘口信息
                        Object.keys(window.fundBaseData).forEach(function(fundCode) {
                            var suffixes = ['future', 'pure_future'];
                            var idx = 0;
                            while(true) {
                                var suf = idx === 0 ? 'etf' : 'etf_' + idx;
                                if (document.getElementById('ib-trade-sym-' + fundCode + '-' + suf)) {
                                    suffixes.push(suf);
                                    idx++;
                                } else if (idx > 0) {
                                    break;
                                } else {
                                    idx++;
                                }
                            }
                            
                            suffixes.forEach(function(type) {
                                var symInput = document.getElementById('ib-trade-sym-' + fundCode + '-' + type);
                                if (symInput) {
                                    var sym = symInput.value.toUpperCase();
                                    var bidEl = document.getElementById('sb-ib-bid-' + fundCode + '-' + type);
                                    var askEl = document.getElementById('sb-ib-ask-' + fundCode + '-' + type);
                                    if (prices[sym]) {
                                        if (bidEl && prices[sym].bid) bidEl.textContent = prices[sym].bid.toFixed(2);
                                        if (askEl && prices[sym].ask) askEl.textContent = prices[sym].ask.toFixed(2);
                                    } else {
                                        if (bidEl) bidEl.textContent = '未能读到实时数据';
                                        if (askEl) askEl.textContent = '未能读到实时数据';
                                    }
                                }
                            });
                        });
                        
                        const statusElement = document.getElementById('ib-status-text');
                        if (statusElement) {
                            statusElement.textContent = data.message || ('已更新 ' + data.timestamp.split(' ')[1]);
                            statusElement.style.backgroundColor = '#28a745';
                        }
                        
                        const prevElement = document.getElementById('ib-prev-closes');
                        if (prevElement) {
                            // 彻底更新独立 Table 单元格，废弃纯文本写入
                            if (document.getElementById('prev-val-gld')) document.getElementById('prev-val-gld').textContent = prevCloses.GLD ? prevCloses.GLD.toFixed(2) : '-';
                            if (document.getElementById('prev-val-uso')) document.getElementById('prev-val-uso').textContent = prevCloses.USO ? prevCloses.USO.toFixed(2) : '-';
                            if (document.getElementById('prev-val-xop')) document.getElementById('prev-val-xop').textContent = prevCloses.XOP ? prevCloses.XOP.toFixed(2) : '-';
                            if (document.getElementById('prev-val-slv')) document.getElementById('prev-val-slv').textContent = prevCloses.SLV ? prevCloses.SLV.toFixed(2) : '-';
                        if (document.getElementById('prev-val-xbi')) document.getElementById('prev-val-xbi').textContent = prevCloses.XBI ? prevCloses.XBI.toFixed(2) : '-';
                        if (document.getElementById('prev-val-spy')) document.getElementById('prev-val-spy').textContent = prevCloses.SPY ? prevCloses.SPY.toFixed(2) : '-';
                        if (document.getElementById('prev-val-qqq')) document.getElementById('prev-val-qqq').textContent = prevCloses.QQQ ? prevCloses.QQQ.toFixed(2) : '-';
                        }
                        
                        window.calculateRealTimeValues();
                    } else if (data.status === 'error') {
                        if (document.getElementById('ib-val-gld')) {
                            document.getElementById('ib-val-gld').textContent = '未能读到实时数据';
                            document.getElementById('ib-val-uso').textContent = '未能读到实时数据';
                            document.getElementById('ib-val-xop').textContent = '未能读到实时数据';
                            document.getElementById('ib-val-xbi').textContent = '未能读到实时数据';
                            document.getElementById('ib-val-slv').textContent = '未能读到实时数据';
                            if(document.getElementById('ib-val-spy')) document.getElementById('ib-val-spy').textContent = '未能读到实时数据';
                            if(document.getElementById('ib-val-qqq')) document.getElementById('ib-val-qqq').textContent = '未能读到实时数据';
                        }
                        
                        // 更新已打开的 Sandbox 中的盘口信息为"未能读到实时数据"
                        Object.keys(window.fundBaseData).forEach(function(fundCode) {
                            var suffixes = ['future', 'pure_future'];
                            var idx = 0;
                            while(true) {
                                var suf = idx === 0 ? 'etf' : 'etf_' + idx;
                                if (document.getElementById('ib-trade-sym-' + fundCode + '-' + suf)) {
                                    suffixes.push(suf);
                                    idx++;
                                } else if (idx > 0) {
                                    break;
                                } else {
                                    idx++;
                                }
                            }
                            suffixes.forEach(function(type) {
                                var bidEl = document.getElementById('sb-ib-bid-' + fundCode + '-' + type);
                                var askEl = document.getElementById('sb-ib-ask-' + fundCode + '-' + type);
                                if (bidEl) bidEl.textContent = '未能读到实时数据';
                                if (askEl) askEl.textContent = '未能读到实时数据';
                            });
                            
                            // 更新期货盘口信息
                            var futureBidEl = document.getElementById('sb-future-bid-' + fundCode);
                            var futureAskEl = document.getElementById('sb-future-ask-' + fundCode);
                            if (futureBidEl) futureBidEl.textContent = '未能读到实时数据';
                            if (futureAskEl) futureAskEl.textContent = '未能读到实时数据';
                        });
                        
                        const statusElement = document.getElementById('ib-status-text');
                        if (statusElement) {
                            statusElement.textContent = data.message || 'IB未连接/非夜盘';
                            statusElement.style.backgroundColor = '#d32f2f';
                        }
                        window.calculateRealTimeValues();
                    }
                    
                    // 无论 success 还是 error（非夜盘），只要后端传了昨收，就静默更新，解决白天没昨收数据的问题
                    const prevCloses = data.prev_closes || {};
                    if (document.getElementById('prev-val-gld')) document.getElementById('prev-val-gld').textContent = prevCloses.GLD ? prevCloses.GLD.toFixed(2) : '-';
                    if (document.getElementById('prev-val-uso')) document.getElementById('prev-val-uso').textContent = prevCloses.USO ? prevCloses.USO.toFixed(2) : '-';
                    if (document.getElementById('prev-val-xop')) document.getElementById('prev-val-xop').textContent = prevCloses.XOP ? prevCloses.XOP.toFixed(2) : '-';
                    if (document.getElementById('prev-val-slv')) document.getElementById('prev-val-slv').textContent = prevCloses.SLV ? prevCloses.SLV.toFixed(2) : '-';
                    if (document.getElementById('prev-val-spy')) document.getElementById('prev-val-spy').textContent = prevCloses.SPY ? prevCloses.SPY.toFixed(2) : '-';
                    if (document.getElementById('prev-val-qqq')) document.getElementById('prev-val-qqq').textContent = prevCloses.QQQ ? prevCloses.QQQ.toFixed(2) : '-';
                    
                } catch (e) {
                    console.error('刷新IB价格失败:', e);
                }
            }, 5000); // 从15秒缩短至5秒，加速夜盘数据抓取
        </script>
    '''

    admin_js = r'''
        <script>
            const ADMIN_BASE = 'http://localhost:5002';
            let prevTaskStatus = {};

            function openConfig() {
                window.open(ADMIN_BASE + '/admin/config', '_blank');
            }

            function formatShortDate(ts) {
                if (!ts) return '未运行';
                return ts.replace(/^\d{4}-/, '').replace(' ', ' ');
            }

            function setAdminStatus(key, status, lastRun) {
                var statusEl = document.getElementById('admin-' + key + '-status');
                var lastEl = document.getElementById('admin-' + key + '-time');
                if (statusEl) statusEl.textContent = status || '未知';
                if (lastEl) lastEl.textContent = formatShortDate(lastRun);
            }

            function setLof00Status(running, port) {
                var el = document.getElementById('admin-lof00-status');
                if (!el) return;
                if (running) {
                    el.textContent = '在线 (端口 ' + port + ')';
                } else {
                    el.textContent = '未启动';
                }
            }

            async function refreshAdminStatus() {
                try {
                    const resp = await fetch(ADMIN_BASE + '/admin/status');
                    const data = await resp.json();
                    
                    try {
                        const resp2 = await fetch(ADMIN_BASE + '/admin/lof00');
                        const info = await resp2.json();
                        setLof00Status(info.running, info.port);
                        const lastEl = document.getElementById('admin-lof00-last');
                        if (lastEl) lastEl.textContent = formatShortDate(new Date().toISOString().replace('T',' ').slice(0,19));
                    } catch (e) {
                        setLof00Status(false, '');
                    }
                    var msgEl = document.getElementById('admin-msg');
                    if (msgEl) msgEl.textContent = '';
                } catch (e) {
                    var msgEl = document.getElementById('admin-msg');
                    if (msgEl) msgEl.textContent = '维护状态获取失败';
                }
            }

            async function runAdminTask(task) {
                var msgEl = document.getElementById('admin-msg');
                if (msgEl) msgEl.textContent = '启动中...';
                try {
                    // 弹出类似 VSCode 终端的新窗口，实时观看运行状态
                    window.open(ADMIN_BASE + '/admin/stream/' + task, 'log_' + task, 'width=900,height=600');
                    
                    const resp = await fetch(ADMIN_BASE + '/admin/run/' + task, { method: 'POST' });
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    if (msgEl) msgEl.textContent = '已启动：' + task;
                    setTimeout(refreshAdminStatus, 1000);
                } catch (e) {
                    if (msgEl) msgEl.textContent = '启动失败';
                }
            }

            function openLog(task) {
                window.open(ADMIN_BASE + '/admin/logtext/' + task, '_blank');
            }

            document.addEventListener('DOMContentLoaded', function() {
                refreshAdminStatus();
                setInterval(refreshAdminStatus, 15000);
            });
        </script>
    '''
    
    # 添加更多Debug信息
    print("\n=== 生成HTML前的调试信息 ===")
    print(f"汇率: {today_exchange_rate}")
    print(f"IB夜盘价格: {ib_night_prices}")
    print(f"IB状态信息: {ib_status_message}")
    print(f"黄金校准值: {gold_calibration}")
    print(f"原油校准值: {oil_calibration}")
    print(f"生成的主页行数: {len(home_rows)}")
    print(f"生成的详情页面数: {len(detail_pages)}")
    print("=============================")
    # 生成最终HTML
    # 使用字符串拼接而不是f-string来避免大括号冲突
    html_generator = HtmlGenerator()
    final_html = ''
    
    # 生成顶部导航栏
    header_html = html_generator.generate_header(global_date_str, today_exchange_rate, ib_night_prices, ib_status_message)
    final_html += header_html
    
    # 判断数据来源
    has_ib_data = bool(ib_night_prices.get('GLD') or ib_night_prices.get('USO') or ib_night_prices.get('XOP'))
    gld_ib = f"{ib_night_prices.get('GLD', {}).get('bid', 0):.2f}" if ib_night_prices.get('GLD') else "-"
    uso_ib = f"{ib_night_prices.get('USO', {}).get('bid', 0):.2f}" if ib_night_prices.get('USO') else "-"
    xop_ib = f"{ib_night_prices.get('XOP', {}).get('bid', 0):.2f}" if ib_night_prices.get('XOP') else "-"
    xbi_ib = f"{ib_night_prices.get('XBI', {}).get('bid', 0):.2f}" if ib_night_prices.get('XBI') else "-"
    slv_ib = f"{ib_night_prices.get('SLV', {}).get('bid', 0):.2f}" if ib_night_prices.get('SLV') else "-"
    spy_ib = f"{ib_night_prices.get('SPY', {}).get('bid', 0):.2f}" if ib_night_prices.get('SPY') else "-"
    qqq_ib = f"{ib_night_prices.get('QQQ', {}).get('bid', 0):.2f}" if ib_night_prices.get('QQQ') else "-"
    
    ib_status_color = "#28a745" if has_ib_data else "#6c757d"
    if "未连接" in ib_status_message or "失败" in ib_status_message or "超时" in ib_status_message:
        ib_status_color = "#d32f2f"
    
    # 获取昨收数据，优先使用本地basic文件数据，确保数据稳定可靠
    def get_prev_close(symbol):
        # 优先使用本地基础数据文件
        try:
            import pandas as pd
            conn = sqlite3.connect(SHARED_DB_PATH)
            df = pd.read_sql("SELECT * FROM basic_data", conn)
            conn.close()
            if symbol in df.columns:
                # 获取最新的非空值
                latest_value = df[symbol].dropna().tail(1)
                if not latest_value.empty:
                    return f"{latest_value.iloc[0]:.2f}"
        except Exception:
            pass
        # 本地数据不可用时，再尝试使用IB数据
        if ib_prev_closes.get(symbol):
            return f"{ib_prev_closes.get(symbol):.2f}"
        return "-"
    
    prev_gld = get_prev_close('GLD')
    prev_uso = get_prev_close('USO')
    prev_xop = get_prev_close('XOP')
    prev_xbi = get_prev_close('XBI')
    prev_slv = get_prev_close('SLV')
    prev_spy = get_prev_close('SPY')
    prev_qqq = get_prev_close('QQQ')
    prev_text = f"昨收(SMART): GLD ${prev_gld} | USO ${prev_uso} | XOP ${prev_xop} | XBI ${prev_xbi} | SLV ${prev_slv} | SPY ${prev_spy} | QQQ ${prev_qqq}"
        
    final_html += '        <div id="page-home" class="page-section active" style="margin-top: 0px; padding:0; background:transparent; box-shadow:none;">\n'
    # === 第二排：页头 + ABC控制面板 + IB夜盘数据 同排并列 ===
    final_html += '        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">\n'
    
    # === 左侧：页头 ===
    final_html += '            <div style="flex: 0 0 280px; background: white; padding: 8px 12px; border-radius: 6px; box-shadow: var(--shadow-sm); border: 1px solid var(--border-color); display: flex; flex-direction: column; justify-content: center;">\n'
    final_html += f'                <div style="font-size: 22px; font-weight: 700; color: #d32f2f; text-align: center; margin-bottom: 4px; letter-spacing: 1px;">LOF基金套利监控系统</div>\n'
    final_html += f'                <div style="font-size: 13px; color: var(--secondary-color); text-align: center; font-family: var(--font-mono);"><span id="current-date-time">{global_date_str}</span> | <span id="exchange-rate-display">{today_exchange_rate}</span></div>\n'
    final_html += '                 <div style="font-size: 11px; text-align: center; margin-top: 6px; color: #666;">A股实时行情: <span id="lof-source-badge" style="font-weight:bold; background:#f5f5f5; color:#333; padding:2px 4px; border-radius:3px; border:1px solid #ddd; margin-right:4px;">检测中...</span> <button onclick="reconnectLofSource()" style="font-size:10px; padding:1px 4px; cursor:pointer; border:1px solid #ccc; border-radius:3px; background:#fff; color:#333;" title="如果您刚打开了QMT或通达信，点击此按钮可让程序重新挂载极速通道">🔄 尝试重连</button></div>\n'
    final_html += '            </div>\n'
    
    # === 右侧：横排极致压缩版IB表格 (增加宽度) ===
    final_html += '            <div style="flex: 1 1 auto; min-width: 680px;">\n'
    final_html += '                <div style="background-color: #f8f9fa; border-radius: 4px; border: 1px solid #e9ecef; overflow: hidden; font-size: 13px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); font-family: var(--font-sans);">\n'
    final_html += '                    <table style="width: 100%; height: 100%; border-collapse: collapse; text-align: center;">\n'
    final_html += '                        <thead style="background-color: #e3f2fd; color: #1565c0; border-bottom: 1px solid #90caf9;">\n'
    final_html += '                            <tr style="height: 28px;">\n'
    final_html += '                                <th style="padding: 2px 4px; text-align: left; width: 80px; border-right: 1px solid #bbdefb; font-size: 12px;">数据源</th>\n'
    final_html += '                                <th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">GLD</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">USO</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">XOP</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">XBI</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">SLV</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">SPY</th><th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">QQQ</th>\n'
    final_html += '                                <th style="width: 75px; border-left: 1px solid #bbdefb; font-size: 12px; padding: 2px 4px;">状态指示</th>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </thead>\n'
    final_html += '                        <tbody>\n'
    final_html += '                            <!-- 新浪期货 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; background-color: #fff9c4; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; font-weight: bold; border-right: 1px dashed #dee2e6; font-size: 12px; color:#d35400;">对应期货</td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="gc-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="gc-change" style="font-size:11px;"></span></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="cl-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="cl-change" style="font-size:11px;"></span></td>\n'
    final_html += '                                <td style="padding:2px 4px; color:#999;">-</td>\n'
    final_html += '                                <td style="padding:2px 4px; color:#999;">-</td>\n'
    final_html += '                                <td style="padding:2px 4px; color:#999;">-</td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="es-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="es-change" style="font-size:11px;"></span></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="nq-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="nq-change" style="font-size:11px;"></span></td>\n'
    final_html += '                            <!-- 昨收盘 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; color: #6c757d; background-color: #fdfdfe; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; font-weight: bold; border-right: 1px dashed #dee2e6; font-size: 12px;">昨收(SMART)</td>\n'
    final_html += f'                                <td id="prev-val-gld" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_gld}</td><td id="prev-val-uso" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_uso}</td><td id="prev-val-xop" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_xop}</td><td id="prev-val-xbi" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_xbi}</td><td id="prev-val-slv" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_slv}</td><td id="prev-val-spy" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_spy}</td><td id="prev-val-qqq" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{prev_qqq}</td>\n'
    final_html += f'                                <td rowspan="4" style="border-left: 1px solid #dee2e6; vertical-align: middle; background-color: #fff; padding: 2px;">\n'
    final_html += f'                                    <div id="active-source-badge" style="font-size: 10px; padding: 2px; border-radius: 2px; font-weight: bold; margin: 0 auto 2px; width: 70px; text-align: center; white-space: nowrap;"></div>\n'
    final_html += f'                                    <div id="ib-status-text" style="font-size: 10px; padding: 2px; border-radius: 2px; background-color: {ib_status_color}; color: white; max-width: 75px; margin: 0 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: center;" title="{ib_status_message}">{ib_status_message}</div>\n'
    final_html += '                                </td>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <!-- IB夜盘 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; background-color: #fff; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; border-right: 1px dashed #dee2e6;">\n'
    final_html += f'                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #1976d2; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += f'                                        <input type="radio" name="calc_source" id="source-ib" value="ib" {"checked" if has_ib_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> 夜盘(买一)\n'
    final_html += '                                    </label>\n'
    final_html += '                                </td>\n'
    final_html += f'                                <td id="ib-val-gld" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{gld_ib}</td><td id="ib-val-uso" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{uso_ib}</td><td id="ib-val-xop" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{xop_ib}</td><td id="ib-val-xbi" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{xbi_ib}</td><td id="ib-val-slv" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{slv_ib}</td><td id="ib-val-spy" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{spy_ib}</td><td id="ib-val-qqq" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{qqq_ib}</td>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <!-- 手工输入 -->\n'
    final_html += '                            <tr style="background-color: #fff; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; border-right: 1px dashed #dee2e6;">\n'
    final_html += f'                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #f57c00; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += f'                                        <input type="radio" name="calc_source" id="source-manual" value="manual" {"checked" if not has_ib_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> 手工干预\n'
    final_html += '                                    </label>\n'
    final_html += '                                </td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="gld-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="uso-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="xop-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="xbi-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="slv-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="spy-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><input type="number" id="qqq-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </tbody>\n'
    final_html += '                    </table>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'
    final_html += '        </div>\n'
    final_html += '            <style>#page-home tbody tr:nth-child(even) { background-color: #e3f2fd; }\n'
    final_html += '                .tab-content { display: none; }\n'
    final_html += '                .tab-content.active { display: block; }\n'
    final_html += '                .tab-button:hover { background-color: #e3f2fd !important; color: #1976d2 !important; }\n'
    final_html += '            </style>\n'
    
    # --- TAB导航栏 ---
    final_html += '            <div style="display: flex; gap: 2px; margin-bottom: 10px; border-bottom: 2px solid #e0e0e0;">\n'
    final_html += '                <button class="tab-button" onclick="switchTab(1)" style="background: var(--primary-color); color: white; border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">商品套利</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(2)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">纯ETF套利</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(3)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">指数套利</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(4)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">白银专区</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(5)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans); margin-left: auto;">🧪 新功能调试</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(6)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">⚙️ LOF基金配置</button>\n'
    final_html += '            </div>\n'
    
    # --- 拆分的表 1：大宗商品 (TAB 1) ---
    final_html += '            <div id="tab-1" class="tab-content active" style="margin-bottom: 10px;">\n'
    final_html += '                <div class="card" style="margin-bottom: 10px;">\n'
    final_html += '                <div style="overflow-x: auto; max-height: calc(100vh - 220px);">\n'
    final_html += '                    <table style="width: 100%; border-collapse: collapse; font-size: 11px;">\n'
    final_html += '                        <thead style="position: sticky; top: 0; background-color: #e3f2fd; z-index: 10; font-size: 11px;">\n'
    final_html += '                            <tr>\n'
    final_html += '                                <th rowspan="2" style="width: 60px;">商品代码</th><th rowspan="2" style="width: 50px;">类别</th><th rowspan="2" style="text-align: center; width: 90px;">名称</th><th rowspan="2" style="width: 45px;">仓位</th><th rowspan="2" style="width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)<br><span style="font-size:10px;font-weight:normal;">(T-1溢价)</span></th><th colspan="3" class="col-realtime-bg-th"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <tr>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 120px;">ETF <span id="etf-freeze-warn" style="display:none; color:#d32f2f; font-size:9px; font-weight:bold;">(15:00后冻结)</span></th><th class="col-realtime-bg-th" style="width: 120px;">期货校准</th><th class="col-realtime-bg-th" style="width: 120px;">纯期货映射</th>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </thead>\n'
    final_html += '                        <tbody>' + home_rows_main + '</tbody>\n'
    final_html += '                    </table>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'
    final_html += '            </div>\n'
    
    # --- 拆分的表 2：纯ETF (TAB 2) ---
    final_html += '            <div id="tab-2" class="tab-content" style="margin-bottom: 10px;">\n'
    if home_rows_etf:
        final_html += '                <div class="card" style="margin-bottom: 10px;">\n'
        final_html += '                <div style="overflow-x: auto; max-height: calc(100vh - 220px);">\n'
        final_html += '                    <table style="width: 100%; border-collapse: collapse; font-size: 11px;">\n'
        final_html += '                        <thead style="position: sticky; top: 0; background-color: #fff3e0; z-index: 10; font-size: 11px;">\n'
        final_html += '                            <tr>\n'
        final_html += '                                <th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 60px;">纯ETF代码</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 50px;">类别</th><th rowspan="2" style="text-align: center; background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 90px;">名称</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 45px;">仓位</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)<br><span style="font-size:10px;font-weight:normal;">(T-1溢价)</span></th><th class="col-realtime-bg-th" style="width: 200px;"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
        final_html += '                            </tr>\n'
        final_html += '                            <tr>\n'
        final_html += '                                <th class="col-realtime-bg-th" style="width: 200px;">ETF估值 <span id="etf-freeze-warn-etf" style="display:none; color:#d32f2f; font-size:9px; font-weight:bold;">(15:00后冻结)</span></th>\n'
        final_html += '                            </tr>\n'
        final_html += '                        </thead>\n'
        final_html += '                        <tbody>' + home_rows_etf + '</tbody>\n'
        final_html += '                    </table>\n'
        final_html += '                </div>\n'
        final_html += '            </div>\n'
    final_html += '            </div>\n'
    
    # --- 拆分的表 3：跨境指数 (TAB 3) ---
    final_html += '            <div id="tab-3" class="tab-content" style="margin-bottom: 10px;">\n'
    final_html += '                <div class="card" style="margin-bottom: 10px;">\n'
    final_html += '                <div style="overflow-x: auto; max-height: calc(100vh - 220px);">\n'
    final_html += '                    <table style="width: 100%; border-collapse: collapse; font-size: 11px;">\n'
    final_html += '                        <thead style="position: sticky; top: 0; background-color: #e8eaf6; z-index: 10; font-size: 11px;">\n'
    final_html += '                            <tr>\n'
    final_html += '                                <th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 60px;">指数代码</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 50px;">类别</th><th rowspan="2" style="text-align: center; background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 90px;">名称</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 45px;">仓位</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)<br><span style="font-size:10px;font-weight:normal;">(T-1溢价)</span></th><th colspan="2" class="col-realtime-bg-th"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <tr>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 140px;">ETF估值 <span id="etf-freeze-warn-idx" style="display:none; color:#d32f2f; font-size:9px; font-weight:bold;">(15:00后冻结)</span></th>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 140px;">纯期货映射</th>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </thead>\n'
    final_html += '                        <tbody>' + home_rows_index + '</tbody>\n'
    final_html += '                    </table>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'
    final_html += '            </div>\n'
    
    # 添加白银期货单独表格 (TAB 4)
    final_html += '            <div id="tab-4" class="tab-content" style="margin-bottom: 10px;">\n'
    if silver_fund_data:
        is_trading_time = futures_data.get('is_trading_time', False) if futures_data else False
        vwap_label = "期货均价(VWAP)" if is_trading_time else "今日结算价(或平替)"
        final_html += '            <div class="card" style="margin-bottom: 10px;">\n'
        final_html += '            <div style="padding: 5px; background-color: #e3f2fd; border-bottom: 1px solid #bbdefb;">\n'
        final_html += '            </div>\n'
        final_html += '            <div style="overflow-x: auto; max-height: calc(100vh - 220px);">\n'
        final_html += '                <table style="width: 100%; border-collapse: collapse; font-size: 11px;">\n'
        final_html += '                    <thead style="position: sticky; top: 0; background-color: #e3f2fd; z-index: 10; font-size: 11px;">\n'
        final_html += '                        <tr>\n'
        final_html += f'                            <th style="width: 60px;">白银代码</th><th style="width: 90px;">名称</th><th style="width: 65px;">净值</th><th style="width: 70px;">昨结算价</th><th style="width: 70px;">最新价</th><th style="width: 85px;">期货成交价</th><th style="width: 100px;"><span style="color:#d35400;">{vwap_label}</span></th><th style="width: 110px;">官方估值</th><th style="width: 110px;">参考估值</th>\n'
        final_html += '                        </tr>\n'
        final_html += '                    </thead>\n'
        final_html += '                    <tbody>\n'
        
        # 生成白银基金行
        sf = silver_fund_data
        final_html += '                        <tr>\n'
        final_html += f'                            <td class="num-font" style="width: 60px;"><b>{sf["code"]}</b></td>\n'
        final_html += f'                            <td style="width: 90px;">{sf["name"]}</td>\n'
        final_html += f'                            <td class="num-font" style="width: 65px;">{sf["nav"]:.4f}</td>\n'
        final_html += f'                            <td class="num-font" style="width: 70px;">{sf["settlement_price"]:.2f}</td>\n'
        final_html += f'                            <td class="num-font" style="width: 70px;">{sf["close"]:.3f}</td>\n'
        final_html += f'                            <td class="num-font" style="width: 85px;">{sf["future_price"]:.2f}</td>\n'
        final_html += f'                            <td class="num-font" style="color:#d35400; font-weight:bold; width: 100px;">{sf["eff_vwap"]:.2f}</td>\n'
        # 官方估值和溢价
        official_light = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' if sf["official_premium"] <= -0.8 else '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'
        official_premium_cls = "premium-positive" if sf["official_premium"] > 0 else "premium-negative"
        final_html += f'                            <td class="num-font" style="width: 110px;">{sf["official_valuation"]:.4f}<br><span class="num-font {official_premium_cls}" style="font-size:14px;">{sf["official_premium"]:+.2f}%</span>{official_light}</td>\n'
        # 参考估值和溢价
        reference_light = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' if sf["reference_premium"] <= -0.8 else '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'
        reference_premium_cls = "premium-positive" if sf["reference_premium"] > 0 else "premium-negative"
        final_html += f'                            <td class="num-font" style="width: 110px;">{sf["reference_valuation"]:.4f}<br><span class="num-font {reference_premium_cls}" style="font-size:14px;">{sf["reference_premium"]:+.2f}%</span>{reference_light}</td>\n'
        final_html += '                        </tr>\n'
        final_html += '                    </tbody>\n'
        final_html += '                </table>\n'
        final_html += '            </div>\n'
        final_html += '        </div>\n'
    else:
        final_html += '                <div style="padding: 20px; text-align: center; color: #666;">暂无白银数据</div>\n'
    final_html += '            </div>\n'  # 闭合tab-4容器
    
    # --- 拆分的表 5：新功能调试 (TAB 5) ---
    final_html += '            <div id="tab-5" class="tab-content" style="margin-bottom: 10px;">\n'
    
    # 【机密隔离】尝试动态加载本地私密沙盘模块
    try:
        import LOF004_sandbox
        final_html += LOF004_sandbox.generate_private_sniper_panel()
    except ImportError:
        final_html += '                <div class="card" style="margin-bottom: 10px; padding: 40px; background-color: #fafafa; text-align: center; min-height: 300px;">\n'
        final_html += '                    <h2 style="color: var(--primary-color);">🌾 自留地</h2>\n'
        final_html += '                    <p style="color: var(--secondary-color); margin-top: 15px;">此处为学生演示/新功能预留区域，暂无内容。</p>\n'
        final_html += '                </div>\n'
        
    final_html += '            </div>\n'

    # --- 拆分的表 6：LOF基金配置 (TAB 6) ---
    final_html += '            <div id="tab-6" class="tab-content" style="margin-bottom: 10px;">\n'
    final_html += '                <div class="card" style="margin-bottom: 10px; padding: 25px; background-color: #fafafa;">\n'
    final_html += '                    <div style="text-align: center; font-size: 16px; font-weight: bold; color: #555; margin-bottom: 20px;">LOF基金配置中心</div>\n'
    final_html += '                    <div style="display: flex; gap: 30px; justify-content: center;">\n'
    final_html += '                        <div style="width: 200px; background: #eef6ff; border: 1px solid #cfe3ff; border-radius: 8px; padding: 20px; display:flex; flex-direction:column; justify-content: center; gap: 12px; box-shadow: var(--shadow-sm);">\n'
    final_html += '                            <div style="font-weight: bold; color: #1e4fa3; font-size: 24px; text-align: center;">⚙️</div>\n'
    final_html += '                            <div style="font-size: 13px; color: #555; text-align:center; margin-bottom: 5px;">配置中心</div>\n'
    final_html += '                            <button class="admin-btn" style="background:#2f6fed; color:#fff; padding:10px 20px; font-size:14px; font-weight:bold; align-self: center; border-radius:6px; border:none; cursor:pointer; width: 100%;" onclick="openConfig()">打开配置面板</button>\n'
    final_html += '                            <div style="font-size: 11px; color: #555; text-align:center; margin-top: 5px;">状态: <b id="admin-lof00-status">未检测</b></div>\n'
    final_html += '                        </div>\n'
    final_html += '                    </div>\n'
    final_html += '                    <div style="text-align:center; font-size:12px; color:#888; margin-top:15px;" id="admin-msg"></div>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'

    final_html += '        </div>\n'  # 统一闭合主面板 page-home 容器

    final_html += '        ' + detail_pages + '\n'

    final_html += '    </div>\n'
    final_html += js_code
    final_html += admin_js
    final_html += '</body>\n'
    final_html += '</html>'
    
    # 保存HTML文件
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(final_html)
        print(f"监控报表生成成功: {OUTPUT_FILE}")
        
    except Exception as e:
        print(f"保存报表失败: {e}")
        
    return final_html

if __name__ == '__main__':
    # 检查并更新历史数据
    update_result, update_message = check_and_update_historical_data()
    print(update_message)
    
    # 生成监控报表
    generate()
