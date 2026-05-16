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
SHARED_DB_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "database", "arb_master.db")

# 导入模块
sys.path.insert(0, SCRIPT_DIR)
from LOF031_config_manager import ConfigManager
from LOF032_data_processor import DataProcessor
from LOF033_html_generator import HtmlGenerator
from LOF034_js_generator import JsGenerator

# 验证模块导入成功
print("模块导入成功:")
print(f"ConfigManager: {ConfigManager}")
print(f"DataProcessor: {DataProcessor}")
print(f"HtmlGenerator: {HtmlGenerator}")
print(f"JsGenerator: {JsGenerator}")
print("使用新架构运行...")

# 全局变量
silver_fund_data = None

# 辅助函数

def read_fund_history_from_db(code):
    """
    【重构：大一统版本】直接从核心宽表 fund_data 读取基金的所有历史记录
    """
    try:
        conn = sqlite3.connect(SHARED_DB_PATH)
        # 从 fund_data 提取该基金的数据，并进行字段映射以适配原有逻辑
        sql = f"""
            SELECT 
                date, 
                nav, 
                price as close, 
                static_val as static_valuation, 
                static_premium as premium,
                val_error
            FROM fund_data 
            WHERE fund_code = '{code}'
            ORDER BY date DESC
        """
        df = pd.read_sql(sql, conn)
        conn.close()
        if not df.empty and 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            # 自动去重
            df = df.drop_duplicates(subset=['date']).reset_index(drop=True)
        return df
    except Exception as e:
        print(f"❌ 读取 fund_data 表中基金 {code} 的数据失败: {e}")
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
        # 核心修复：适配大一统后的字段名
        ep_val = df_idx.loc[d_T].get('premium', df_idx.loc[d_T].get('ETF静态溢价', '无'))
        if ep_val != '无' and pd.notna(ep_val):
            try:
                etf_premium_num = float(str(ep_val).replace('%', ''))
                etf_premium_cls, etf_premium_str = html_generator.format_color(etf_premium_num)
            except: pass
        
        etf_val_err_str = "-"
        etf_val_err_cls = ""
        ee_val = df_idx.loc[d_T].get('val_error', df_idx.loc[d_T].get('ETF静态估值误差', '无'))
        if ee_val != '无' and pd.notna(ee_val):
            try:
                etf_val_err_num = float(str(ee_val).replace('%', ''))
                etf_val_err_cls, etf_val_err_str = html_generator.format_color(etf_val_err_num)
            except: pass
        
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
                etf_td_html += f"<td class='col-etf-bg'>{etf_val:.3f}</td>"
            else:
                etf_td_html += f"<td class='col-etf-bg'>-</td>"
        
        # 处理T-1日的ETF值
        etf_td_html_t1 = ''
        if d_T1:
            for col in etf_columns:
                etf_val_t1 = df_idx.loc[d_T1].get(col, 0) if col in df_idx.columns else 0
                if isinstance(etf_val_t1, (int, float)) and etf_val_t1 > 0:
                    etf_td_html_t1 += f"<td>{etf_val_t1:.3f}</td>"
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
        
        # 确定显示的价格类型和日期 - 使用 df_idx 确保与 est_home 日期一致
        price_date = est_home_date
        
        # 获取最近一个交易日的收盘价 - 优先从 df_idx（fund_history表）获取，与 est_home 同日期
        latest_valid_close = 0  # 核心修复：防止底层报错崩溃
        valid_closes_from_history = df_idx[df_idx['close'] > 0] if 'close' in df_idx.columns else pd.DataFrame()
        if not valid_closes_from_history.empty:
            latest_valid_close = valid_closes_from_history.iloc[0]['close']
            latest_close_date = valid_closes_from_history.index[0].strftime('%m-%d') if hasattr(valid_closes_from_history.index[0], 'strftime') else str(valid_closes_from_history.index[0])[-5:]
            close_str = f"{latest_valid_close:.3f}"
            price_date = latest_close_date
        else:
            # 兜底：使用 fund_data 表
            valid_closes = lof_df_sorted[lof_df_sorted['close'] > 0]
            if not valid_closes.empty:
                latest_valid_close = valid_closes.iloc[0]['close']
                latest_close_date = valid_closes.iloc[0]['date'].strftime('%m-%d')
                close_str = f"{latest_valid_close:.3f}"
                price_date = latest_close_date
            else:
                close_str = "无"
        
        # 计算T-1溢价，使用实时价除以静态官方估值 - 使用与 est_home 同日期的 close
        h_p_cls, h_p_txt = "", "-"
        if isinstance(est_home, (int, float)) and est_home > 0 and latest_valid_close > 0:
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
                        
                        # 严禁在Python端使用T-1的收盘价计算实时溢价，直接交由前端JS使用最新A股实盘价计算
                        
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
                        
                        # 严禁使用过期价格拼凑实时溢价
                        
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
        future_premium_str = f"{future_premium:+.2f}%" if future_premium is not None else "-"
        
        # 为期货溢价设置颜色
        future_premium_cls = "" if future_premium is None or future_premium == 0 else ("premium-positive" if future_premium > 0 else "premium-negative")
        
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
        exact_future_premium_str = f"{exact_future_premium:+.2f}%" if exact_future_premium is not None else "-"
        exact_future_premium_cls = "" if exact_future_premium is None or exact_future_premium == 0 else ("premium-positive" if exact_future_premium > 0 else "premium-negative")
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
                                        <option value="tdx">通达信</option>
                                        <!-- <option value="guojin_qmt">国金QMT (原生)</option> -->
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
                                    <input type="number" id="ib-trade-vol-{code}-{suffix}" value="10" step="10" oninput="this.dataset.manual='true'" style="width:60px; padding:2px; border:1px solid #ccc; border-radius:4px; font-family:Consolas; font-weight:bold; font-size:11px;">
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

                <div style="margin-top: 15px; font-size: 13px; color: #888;">* 提示：面板打开时会自动填入主面板实盘价作为默认测试价。您可以随意修改输入框内的值，点击计算后推演该价位溢价率，不影响主面板自动刷新。也支持国金QMT。</div>
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
        
        # 【重构：大一统版本】检查核心宽表 fund_data
        try:
            conn = sqlite3.connect(SHARED_DB_PATH)
            # 检查是否有该基金的最新记录且 static_val 不为空
            df = pd.read_sql(f"SELECT date, static_val FROM fund_data WHERE fund_code='{code}' AND static_val IS NOT NULL ORDER BY date DESC LIMIT 1", conn)
            conn.close()
            
            if not df.empty:
                latest_date = pd.to_datetime(df['date'].iloc[0]).date()
                if latest_date < today:
                    print(f"提示: 基金 {code} 的数据库记录日期({latest_date})落后于今日，需要更新")
                    need_update = True
            else:
                print(f"警告: 基金 {code} 在 fund_data 中尚无静态估值记录，需要更新")
                need_update = True
        except Exception as e:
            print(f"读取基金 {code} 的 fund_data 表失败: {e}")
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
            futures_history_df = futures_history_df.drop_duplicates(subset=['date'])
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
            if position > 1: position = position / 100.0 # 兼容 95 和 0.95 两种写法
            # 兼容新旧版配置：优先使用 valuation_portfolio，若无则回退到 hedging_portfolio
            hedging_portfolio = fund.get('valuation_portfolio', [])
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
                    cal = base_row.get('calibration', 0.0)
                    if pd.notna(cal) and cal != '无':
                        latest_calibration_factor = float(cal)
                except:
                    pass
                    
            # 如果基金自身没有校准值，且属于黄金原油，则用全局期货校准值兜底
            if latest_calibration_factor <= 0:
                if category == '黄金':
                    latest_calibration_factor = gold_calibration
                elif category == '原油':
                    latest_calibration_factor = oil_calibration
            
            if base_row is not None:
                try:
                    hv = base_row.get('hedge_value', base_row.get('hedge', 0.0))
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
                'tradeEtf': trade_etf_sym,
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

    # === 终极重构：全自动动态扫描并提取活跃美股 ETF ===
    active_etfs_set = set()
    for fund in cfg.get('funds', []):
        for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
            sym = item.get('symbol', '').replace('^', '').split('-')[0].upper()
            if sym and sym not in ['GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ']: active_etfs_set.add(sym)
        if fund.get('trade_etf'):
            for s in str(fund.get('trade_etf')).replace('，', ',').split(','):
                s = s.strip().upper()
                if s and s not in ['GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ']: active_etfs_set.add(s)
    
    # 自定义排序：XOP优先，其余按字母顺序
    etf_order = ['XOP', 'GLD', 'INDA', 'KWEB', 'QQQ', 'RSPH', 'SLV', 'SPY', 'XBI', 'XLY', 'USO', 'XLE']
    active_etfs = sorted(list(active_etfs_set), key=lambda x: (etf_order.index(x) if x in etf_order else 999, x))

    # 从独立的模块生成前端巨量的 JavaScript 与 Admin 面板交互逻辑
    js_code = JsGenerator.generate_js_code(active_etfs, js_fund_base_data, gold_calibration, oil_calibration)
    admin_js = JsGenerator.generate_admin_js()
    
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
    has_ib_data = any(ib_night_prices.get(sym) for sym in active_etfs)
    
    # 检查富途数据
    has_futu_data = False
    try:
        import requests
        futu_resp = requests.get('http://localhost:5000/api/futu_prices', timeout=2)
        if futu_resp.status_code == 200:
            futu_data = futu_resp.json()
            if futu_data.get('status') == 'success' and futu_data.get('prices'):
                has_futu_data = any(futu_data['prices'].get(sym) for sym in active_etfs)
    except:
        pass
    
    ib_status_color = "#28a745" if has_ib_data else "#6c757d"
    if "未连接" in ib_status_message or "失败" in ib_status_message or "超时" in ib_status_message:
        ib_status_color = "#d32f2f"
    
    # 获取昨收数据，优先使用本地basic文件数据，确保数据稳定可靠
    def get_prev_close(symbol):
        # 优先使用本地基础数据文件
        try:
            import pandas as pd
            conn = sqlite3.connect(SHARED_DB_PATH)
            # 修正：直接从 usa_etf_daily_prices 精准查询，不再依赖旧的宽表 basic_data
            df = pd.read_sql(f"SELECT price FROM usa_etf_daily_prices WHERE symbol = ? ORDER BY date DESC LIMIT 1", conn, params=(symbol,))
            conn.close()
            if not df.empty and pd.notna(df.iloc[0]['price']):
                return f"{df.iloc[0]['price']:.2f}"
        except Exception as e:
            print(f"从数据库获取 {symbol} 昨收价失败: {e}")
            pass
        # 本地数据不可用时，再尝试使用IB数据
        if ib_prev_closes.get(symbol):
            return f"{ib_prev_closes.get(symbol):.2f}"
        return "-"
    
    # === 动态构建 HTML 表头和列 ===
    etf_th_html = ''.join([f'<th style="font-size:13px; font-family: var(--font-mono); padding: 2px 4px;">{sym}</th>' for sym in active_etfs])
    prev_tds = ''.join([f'<td id="prev-val-{sym.lower()}" style="font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{get_prev_close(sym)}</td>' for sym in active_etfs])
    # 注意：字典获取 bid 的写法兼容字典或嵌套对象
    ib_tds = ''.join([f'<td id="ib-val-{sym.lower()}" style="font-weight:bold;color:#1976d2; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">{f"{ib_night_prices.get(sym, {}).get(chr(98)+chr(105)+chr(100), 0):.2f}" if ib_night_prices.get(sym) else "-"}</td>' for sym in active_etfs])
    futu_tds = ''.join([f'<td id="futu-val-{sym.lower()}" style="font-weight:bold;color:#2e7d32; font-family: var(--font-mono); padding:2px 4px; font-size: 13px;">-</td>' for sym in active_etfs])
    manual_tds = ''.join([f'<td style="padding:2px 4px;"><input type="number" id="{sym.lower()}-price" step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>' for sym in active_etfs])
        
    final_html += '        <div id="page-home" class="page-section active" style="margin-top: 0px; padding:0; background:transparent; box-shadow:none;">\n'
    # === 第二排：页头 + ABC控制面板 + IB夜盘数据 同排并列 ===
    final_html += '        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">\n'
    
    # === 左侧：页头 ===
    final_html += '            <div style="flex: 0 0 280px; background: white; padding: 8px 12px; border-radius: 6px; box-shadow: var(--shadow-sm); border: 1px solid var(--border-color); display: flex; flex-direction: column; justify-content: center; height: 118px;">\n'
    final_html += f'                <div style="font-size: 22px; font-weight: 700; color: #d32f2f; text-align: center; margin-bottom: 4px; letter-spacing: 1px;">LOF基金套利监控系统</div>\n'
    final_html += f'                <div style="font-size: 13px; color: var(--secondary-color); text-align: center; font-family: var(--font-mono);"><span id="current-date-time">{global_date_str}</span> | <span id="exchange-rate-display">{today_exchange_rate}</span></div>\n'
    final_html += '                 <div style="font-size: 11px; text-align: center; margin-top: 6px; color: #666;">A股实时行情: <select id="lof-source-select" onchange="switchLofSource(this.value)" style="font-size:10px; padding:1px 3px; cursor:pointer; border:1px solid #ccc; border-radius:3px; background:#fff; color:#333; font-weight:bold; margin-right:4px;"><option value="tongdaxin">通达信新版</option><option value="qmt">银河QMT</option><option value="sina">新浪轮询</option></select><span id="lof-source-badge" style="font-weight:bold; background:#f5f5f5; color:#333; padding:2px 4px; border-radius:3px; border:1px solid #ddd; margin-right:4px;">检测中...</span> <button onclick="reconnectLofSource()" style="font-size:10px; padding:1px 4px; cursor:pointer; border:1px solid #ccc; border-radius:3px; background:#fff; color:#333;" title="如果数据源连接断开，点击此按钮重连">🔄 重连</button></div>\n'
    final_html += '            </div>\n'
    
    # === 右侧：横排极致压缩版IB表格 (增加宽度) ===
    final_html += '            <div style="flex: 1 1 auto; min-width: 760px;">\n'
    final_html += '                <div style="background-color: #f8f9fa; border-radius: 4px; border: 1px solid #e9ecef; overflow: hidden; font-size: 13px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); font-family: var(--font-sans);">\n'
    final_html += '                    <table style="width: 100%; height: 100%; border-collapse: collapse; text-align: center;">\n'
    final_html += '                        <thead style="background-color: #e3f2fd; color: #1565c0; border-bottom: 1px solid #90caf9;">\n'
    final_html += '                            <tr style="height: 28px;">\n'
    final_html += '                                <th style="padding: 2px 4px; text-align: left; width: 100px; border-right: 1px solid #bbdefb; font-size: 12px;">夜盘数据</th>\n'
    final_html += f'                                {etf_th_html}\n'
    final_html += '                                <th style="width: 75px; border-left: 1px solid #bbdefb; font-size: 12px; padding: 2px 4px;">状态指示</th>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </thead>\n'
    final_html += '                        <tbody>\n'
    final_html += '                            <!-- 新浪期货 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; background-color: #fff9c4; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; font-weight: bold; border-right: 1px dashed #dee2e6; font-size: 12px; color:#d35400;">对应期货</td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="gc-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="gc-change" style="font-size:11px;"></span></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="cl-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="cl-change" style="font-size:11px;"></span></td>\n'
    final_html += ''.join(['<td style="padding:2px 4px; color:#999;">-</td>' for _ in range(max(0, len(active_etfs)-4))]) + '\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="es-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="es-change" style="font-size:11px;"></span></td>\n'
    final_html += '                                <td style="padding:2px 4px;"><span id="nq-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span id="nq-change" style="font-size:11px;"></span></td>\n'
    final_html += '                            <!-- 昨收盘 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; color: #6c757d; background-color: #fdfdfe; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; font-weight: bold; border-right: 1px dashed #dee2e6; font-size: 12px;">昨收(SMART)</td>\n'
    final_html += f'                                {prev_tds}\n'
    final_html += f'                                <td rowspan="4" style="border-left: 1px solid #dee2e6; vertical-align: middle; background-color: #fff; padding: 2px;">\n'
    final_html += f'                                    <div id="active-source-badge" style="font-size: 10px; padding: 2px; border-radius: 2px; font-weight: bold; margin: 0 auto 2px; width: 70px; text-align: center; white-space: nowrap;"></div>\n'
    final_html += f'                                    <div id="ib-status-text" style="font-size: 10px; padding: 2px; border-radius: 2px; background-color: {ib_status_color}; color: white; max-width: 75px; margin: 0 auto; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-align: center;" title="{ib_status_message}">{ib_status_message}</div>\n'
    final_html += '                                </td>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <!-- IB夜盘 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; background-color: #fff; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; border-right: 1px dashed #dee2e6;">\n'
    final_html += f'                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #1976d2; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += f'                                        <input type="radio" name="calc_source" id="source-ib" value="ib" {"checked" if has_ib_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> IB夜盘(买一)\n'
    final_html += '                                    </label>\n'
    final_html += '                                </td>\n'
    final_html += f'                                {ib_tds}\n'
    final_html += '                            </tr>\n'
    final_html += '                            <!-- 富途夜盘 -->\n'
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; background-color: #f8fbff; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; border-right: 1px dashed #dee2e6;">\n'
    final_html += '                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #0d47a1; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += '                                        <input type="radio" name="calc_source" id="source-futu" value="futu" {"checked" if not has_ib_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> 富途夜盘(买一)\n'
    final_html += '                                    </label>\n'
    final_html += '                                </td>\n'
    final_html += f'                                {futu_tds}\n'
    final_html += '                            </tr>\n'
    final_html += '                            <!-- 手工输入 -->\n'
    final_html += '                            <tr style="background-color: #fff; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; border-right: 1px dashed #dee2e6;">\n'
    final_html += f'                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #f57c00; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += f'                                        <input type="radio" name="calc_source" id="source-manual" value="manual" {"checked" if not has_ib_data and not has_futu_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> 手工输入\n'
    final_html += '                                    </label>\n'
    final_html += '                                </td>\n'
    final_html += f'                                {manual_tds}\n'
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
    final_html += '                <button class="tab-button" onclick="switchTab(7)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">自留地2</button>\n'
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
        official_light = ('<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' if sf["official_premium"] <= -0.8 else '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>') if sf["official_premium"] is not None else ''
        official_premium_cls = "premium-positive" if sf["official_premium"] and sf["official_premium"] > 0 else ("premium-negative" if sf["official_premium"] and sf["official_premium"] < 0 else "")
        official_premium_text = f'{sf["official_premium"]:+.2f}%' if sf["official_premium"] is not None else "-"
        final_html += f'                            <td class="num-font" style="width: 110px;">{sf["official_valuation"]:.4f}<br><span class="num-font {official_premium_cls}" style="font-size:14px;">{official_premium_text}</span>{official_light}</td>\n'
        # 参考估值和溢价
        reference_light = ('<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>' if sf["reference_premium"] <= -0.8 else '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>') if sf["reference_premium"] is not None else ''
        reference_premium_cls = "premium-positive" if sf["reference_premium"] and sf["reference_premium"] > 0 else ("premium-negative" if sf["reference_premium"] and sf["reference_premium"] < 0 else "")
        reference_premium_text = f'{sf["reference_premium"]:+.2f}%' if sf["reference_premium"] is not None else "-"
        final_html += f'                            <td class="num-font" style="width: 110px;">{sf["reference_valuation"]:.4f}<br><span class="num-font {reference_premium_cls}" style="font-size:14px;">{reference_premium_text}</span>{reference_light}</td>\n'
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
        import importlib
        importlib.reload(LOF004_sandbox) # 强制热重载，修改004沙盘代码后刷新浏览器秒生效！
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
    final_html += '                    <div style="text-align: center; font-size: 16px; font-weight: bold; color: #555; margin-bottom: 20px;">全盘维护中心</div>\n'
    final_html += '                    <div style="display: flex; gap: 30px; justify-content: center; flex-wrap: wrap;">\n'
    final_html += '                        <div style="width: 200px; background: #eef6ff; border: 1px solid #cfe3ff; border-radius: 8px; padding: 20px; display:flex; flex-direction:column; justify-content: center; gap: 12px; box-shadow: var(--shadow-sm);">\n'
    final_html += '                            <div style="font-weight: bold; color: #1e4fa3; font-size: 24px; text-align: center;">⚙️</div>\n'
    final_html += '                            <div style="font-size: 13px; color: #555; text-align:center; margin-bottom: 5px;">配置中心</div>\n'
    final_html += '                            <button class="admin-btn" style="background:#2f6fed; color:#fff; padding:10px 20px; font-size:14px; font-weight:bold; align-self: center; border-radius:6px; border:none; cursor:pointer; width: 100%;" onclick="openConfig()">打开配置面板</button>\n'
    final_html += '                            <div style="font-size: 11px; color: #555; text-align:center; margin-top: 5px;">状态: <b id="admin-lof00-status">未检测</b></div>\n'
    final_html += '                        </div>\n'
    final_html += '                        <div style="width: 200px; background: #fff8e1; border: 1px solid #ffecb3; border-radius: 8px; padding: 20px; display:flex; flex-direction:column; justify-content: center; gap: 12px; box-shadow: var(--shadow-sm);">\n'
    final_html += '                            <div style="font-weight: bold; color: #f57f17; font-size: 24px; text-align: center;">📥</div>\n'
    final_html += '                            <div style="font-size: 13px; color: #555; text-align:center; margin-bottom: 5px;">数据大一统更新</div>\n'
    final_html += '                            <button class="admin-btn" style="background:#fbc02d; color:#fff; padding:10px 20px; font-size:14px; font-weight:bold; align-self: center; border-radius:6px; border:none; cursor:pointer; width: 100%;" onclick="runAdminTask(\'01\')">拉取今日数据</button>\n'
    final_html += '                            <div style="font-size: 11px; color: #555; text-align:center; margin-top: 5px;">上次: <b id="admin-01-time">未运行</b></div>\n'
    final_html += '                        </div>\n'
    final_html += '                        <div style="width: 200px; background: #fce4ec; border: 1px solid #f8bbd0; border-radius: 8px; padding: 20px; display:flex; flex-direction:column; justify-content: center; gap: 12px; box-shadow: var(--shadow-sm);">\n'
    final_html += '                            <div style="font-weight: bold; color: #c2185b; font-size: 24px; text-align: center;">⚡</div>\n'
    final_html += '                            <div style="font-size: 13px; color: #555; text-align:center; margin-bottom: 5px;">Woody 因子强制更新</div>\n'
    final_html += '                            <button class="admin-btn" style="background:#d81b60; color:#fff; padding:10px 20px; font-size:14px; font-weight:bold; align-self: center; border-radius:6px; border:none; cursor:pointer; width: 100%;" onclick="runAdminTask(\'woody\')">强制刷新 Woody</button>\n'
    final_html += '                            <div style="font-size: 11px; color: #555; text-align:center; margin-top: 5px;">上次: <b id="admin-woody-time">未运行</b></div>\n'
    final_html += '                        </div>\n'
    final_html += '                        <div style="width: 200px; background: #e8f5e9; border: 1px solid #c8e6c9; border-radius: 8px; padding: 20px; display:flex; flex-direction:column; justify-content: center; gap: 12px; box-shadow: var(--shadow-sm);">\n'
    final_html += '                            <div style="font-weight: bold; color: #2e7d32; font-size: 24px; text-align: center;">🧮</div>\n'
    final_html += '                            <div style="font-size: 13px; color: #555; text-align:center; margin-bottom: 5px;">全市场静态计算</div>\n'
    final_html += '                            <button class="admin-btn" style="background:#43a047; color:#fff; padding:10px 20px; font-size:14px; font-weight:bold; align-self: center; border-radius:6px; border:none; cursor:pointer; width: 100%;" onclick="runAdminTask(\'012\')">重新计算估值</button>\n'
    final_html += '                            <div style="font-size: 11px; color: #555; text-align:center; margin-top: 5px;">上次: <b id="admin-012-time">未运行</b></div>\n'
    final_html += '                        </div>\n'
    final_html += '                    </div>\n'
    final_html += '                    <div style="text-align:center; font-size:12px; color:#888; margin-top:15px;" id="admin-msg"></div>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'
    final_html += '          </div>\n'
    
    # --- 拆分的表 7：自留地2 (TAB 7) ---
    final_html += '            <div id="tab-7" class="tab-content" style="margin-bottom: 10px;">\n'
    final_html += '                <div class="card" style="margin-bottom: 10px; padding: 40px; background-color: #fafafa; text-align: center; min-height: 300px;">\n'
    final_html += '                    <h2 style="color: var(--primary-color);">🌾 自留地 2 - 数据导出核对</h2>\n'
    final_html += '                    <p style="color: var(--secondary-color); margin-top: 15px; margin-bottom: 25px;">输入6位基金代码，导出包含验算公式的过去5天对账数据文件。</p>\n'
    final_html += '                    <div style="display: flex; justify-content: center; gap: 10px; align-items: center;">\n'
    final_html += '                        <input type="text" id="export-fund-code" placeholder="输入6位基金代码" maxlength="6" style="padding: 10px 15px; border: 1px solid #ccc; border-radius: 6px; font-size: 16px; font-family: var(--font-mono); width: 180px; text-align: center;" oninput="this.value=this.value.replace(/[^0-9]/g,\'\')">\n'
    final_html += '                        <button onclick="exportFundData()" style="background: var(--primary-color); color: white; border: none; padding: 10px 25px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: 16px; transition: 0.2s;">📥 导出 CSV</button>\n'
    final_html += '                    </div>\n'
    final_html += '                    <p id="export-msg" style="color: #d32f2f; margin-top: 15px; font-weight: bold;"></p>\n'
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
