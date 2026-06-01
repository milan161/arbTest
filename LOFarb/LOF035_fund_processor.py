# LOF035_fund_processor.py - 基金数据处理与HTML片段生成
import os
import pandas as pd
import datetime
import sqlite3
import traceback

# 共享数据库路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED_DB_PATH = os.path.join(os.path.dirname(SCRIPT_DIR), "database", "arb_master.db")

# 导入模块
from LOF031_config_manager import ConfigManager
from LOF032_data_processor import DataProcessor

# 全局变量
silver_fund_data = None

def read_fund_history_from_db(code):
    """
    【重构：大一统版本】直接从核心宽表 fund_data 读取基金的历史记录，
    并自动关联 exchange_rate 和 usa_etf_daily_prices 基础数据表。
    """
    try:
        # 1. 使用 DataProcessor 获取基金核心数据
        processor = DataProcessor(SCRIPT_DIR)
        fund_df = processor.read_lof_data(code)
        if fund_df.empty:
            return fund_df
            
        # 2. 获取全局基础数据 (汇率, ETF价格, 期货等)
        basic_df = processor.read_basic_data()
        if basic_df.empty:
            return fund_df
            
        # 3. 映射 basic_df 列名以兼容旧逻辑
        # 旧逻辑期望 exchange_rate, 而 read_basic_data 返回 "人民币中间价"
        if "人民币中间价" in basic_df.columns:
            basic_df = basic_df.rename(columns={"人民币中间价": "exchange_rate"})
            
        # 确保 date 列是 datetime 类型以便合并
        fund_df['date'] = pd.to_datetime(fund_df['date'])
        if not basic_df.empty:
            basic_df['date'] = pd.to_datetime(basic_df['date'])

        # 4. 执行左连接合并
        merged_df = pd.merge(fund_df, basic_df, on="date", how="left")
        
        # 4.5 新增：合并 fund_daily_factors 获取仓位和校准值
        try:
            conn = sqlite3.connect(SHARED_DB_PATH)
            factors_df = pd.read_sql(f"SELECT date, position, calibration FROM fund_daily_factors WHERE fund_code = '{code}'", conn)
            conn.close()
            if not factors_df.empty:
                factors_df['date'] = pd.to_datetime(factors_df['date'])
                merged_df = pd.merge(merged_df, factors_df, on="date", how="left")
        except Exception as e:
            print(f"⚠️ [DataProcessor] 合并基金 {code} 的因子数据(fund_daily_factors)失败: {e}")

        # 5. 自动去重并按日期排序
        if not merged_df.empty:
            merged_df = merged_df.drop_duplicates(subset=["date"]).sort_values("date", ascending=False).reset_index(drop=True)
            
        return merged_df
        
    except Exception as e:
        print(f"❌ [重构版] 读取基金 {code} 的复合历史数据失败: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df=None, is_index_table=False, calibrations=None, global_er=7.0, etf_prices=None):
    """处理单个基金的数据"""
    code = fund.get('code', '')
    name = fund.get('name', '未知基金')
    category = fund.get('category', '其他')
    
    if calibrations is None:
        calibrations = {'GC': 10.9067, 'CL': 0.8227}
    
    # 过滤etf_prices中的国内LOF基金代码（6位数字）
    if etf_prices:
        etf_prices = {k: v for k, v in etf_prices.items() if not (k.isdigit() and len(k) == 6)}

    # 初始化配置管理器
    config_manager = ConfigManager(os.path.join(SCRIPT_DIR, "lof_config.yaml"))
    
    # 获取仓位
    hold_cfg = fund.get('holdings', {})
    try:
        raw_pos = hold_cfg.get('equity_ratio', 100.0)
        pos_val = float(str(raw_pos).replace('%', ''))
        pos_float = pos_val / 100.0 if pos_val > 2 else pos_val
    except Exception:
        pos_float = 1.0
    
    # 获取对冲组合
    h_list = fund.get('valuation_portfolio', [])
    if not h_list:
        h_list = fund.get('hedging_portfolio', [])
    for item in h_list:
        sym = str(item.get('symbol', ''))
        if any(sym.endswith(suffix) for suffix in ['-EU', '-JP', '-HK', '-UK']) and not sym.startswith('^'):
            item['symbol'] = f"^{sym.replace('^', '')}"
    
    # 从数据库读取基金完美对账表
    lof_df = read_fund_history_from_db(code)
    
    if lof_df.empty:
        print(f"警告: 基金 {code} 无数据，跳过处理")
        return None, None, None
        
    # === 核心修复：动态提取基准日 (T-1) 的真实仓位和权重，彻底覆盖 YAML 默认值 ===
    _, _, base_row = data_processor.get_base_date_info(lof_df)
            
    # 补充：从 usa_etf_daily_prices 获取ETF基准价格
    if base_row is not None:
        base_date = base_row.get('date')
        if base_date:
            try:
                import sqlite3
                conn = sqlite3.connect(SHARED_DB_PATH)
                # 将日期转换为字符串格式
                date_str = str(base_date)[:10]
                etf_query = f"SELECT symbol, price FROM usa_etf_daily_prices WHERE date = '{date_str}'"
                etf_df = pd.read_sql(etf_query, conn)
                conn.close()
                for _, row in etf_df.iterrows():
                    sym = row['symbol']
                    base_row[sym] = row['price']  # 存储原始符号（如^INDA-EU）
            except Exception as e:
                print(f"⚠️ 基金 {code} 补充ETF基准价格失败: {e}")
    
    if base_row is not None:
        db_pos = base_row.get('position', base_row.get('仓位'))
        if pd.notna(db_pos) and db_pos != '无' and db_pos != '':
            try:
                pf = float(db_pos)
                if pf > 2: pf = pf / 100.0
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
    
    # ================================================================
    # 第一段：数据准备 - 解析配置、仓位、校准因子、汇率
    # ================================================================
    
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

    # 根据映射到的期货获取校准因子
    if future_symbol and future_symbol in calibrations:
        latest_calibration_factor = calibrations[future_symbol]
    elif category == '黄金':
        latest_calibration_factor = calibrations.get('GC', 10.9067)
    elif category == '原油':
        latest_calibration_factor = calibrations.get('CL', 0.8227)
    
    # 获取人民币中间价（从基金历史数据中获取）
    if not lof_df_sorted.empty:
        latest_row = lof_df_sorted.iloc[0]
        try:
            er = latest_row.get('exchange_rate', 0.0)
            if pd.notna(er) and er != '无' and er != '':
                latest_exchange_rate = float(er)
        except:
            pass
    
    # 判断是否已经收盘
    now_dt = datetime.datetime.now()
    is_after_close = (now_dt.hour > 15 or (now_dt.hour == 15 and now_dt.minute > 0)) or now_dt.weekday() >= 5
    
    has_future = bool(future_symbol) and str(future_symbol).strip() != 'None' and category != '纯ETF'
    
    # 硬编码：对于非纯正单一大宗商品的混合基金，坚决放弃其期货估值映射
    if code in ['163208', '160216', '161815']:
        has_future = False
        future_symbol = None
    
    # ================================================================
    # 第二段：ETF列处理 - 构建ETF列名列表
    # ================================================================
    
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
    
    # ================================================================
    # 第三段：历史数据行生成循环 - 生成最近20个交易日的历史数据行
    # ================================================================
    
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
        
        # 获取汇率数据
        exchange_rate = df_idx.loc[d_T].get('exchange_rate', 0)
        exchange_rate_str = f"{exchange_rate:.4f}" if isinstance(exchange_rate, (int, float)) and exchange_rate > 0 else "无"
        
        t1_exchange_rate = 0
        if d_T1:
            t1_exchange_rate = df_idx.loc[d_T1].get('exchange_rate', 0)
        t1_exchange_rate_str = f"{t1_exchange_rate:.4f}" if isinstance(t1_exchange_rate, (int, float)) and t1_exchange_rate > 0 else "无"

        # 计算 T-1 溢价：T日收盘价 / T-1日净值 - 1
        premium_str = "-"
        premium_cls = ""
        if c_T > 0 and n_T1 > 0:
            premium_num = (c_T / n_T1 - 1) * 100
            premium_cls, premium_str = html_generator.format_color(premium_num)
        
        etf_val_err_str = "-"
        etf_val_err_cls = ""
        # 🌟 修复：直接用最新公布的净值和算好的估值动态反算，忽略数据库可能被默认填充为0的 val_error
        if can_calc and isinstance(cur_est_val, (int, float)) and cur_est_val > 0 and n_T > 0:
            etf_val_err_num = (cur_est_val / n_T - 1) * 100
            etf_val_err_cls, etf_val_err_str = html_generator.format_color(etf_val_err_num)
        else:
            ee_val = df_idx.loc[d_T].get('val_error', df_idx.loc[d_T].get('ETF静态估值误差', '无'))
            if ee_val != '无' and pd.notna(ee_val):
                try:
                    etf_val_err_num = float(str(ee_val).replace('%', ''))
                    if abs(etf_val_err_num) > 0.0001:  # 过滤掉无意义的绝对0.00
                        etf_val_err_cls, etf_val_err_str = html_generator.format_color(etf_val_err_num)
                except: pass
        
        # 从LOF历史数据中读取期货结算价
        future_settle_str = "-"
        future_settle_num = 0.0
        # 尝试不同的列名
        settle_cols_to_try = [f"{future_symbol}_settle"] if future_symbol else []
        settle_cols_to_try.extend(['期货结算价', '期 货结算价', '期货Beta'])
        
        for settle_col in settle_cols_to_try:
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
        future_settle_num_t1 = 0.0
        if d_T1:
            for settle_col in settle_cols_to_try:
                if settle_col in df_idx.columns:
                    fs_price_t1 = df_idx.loc[d_T1].get(settle_col, '无')
                    if fs_price_t1 != '无' and pd.notna(fs_price_t1):
                        try:
                            fs_num = float(fs_price_t1)
                            if fs_num > 0:
                                future_settle_num_t1 = fs_num
                                future_settle_str_t1 = f"{fs_num:.2f}"
                            break
                        except:
                            pass
        
        # 从数据中读取期货静态估值、期货静态估值误差、溢价 (并加入动态计算兜底)
        future_static_val = '无'
        future_static_val_num = 0.0
        if '期货静态估值' in df_idx.columns:
            fs_val = df_idx.loc[d_T].get('期货静态估值', '无')
            if fs_val != '无' and pd.notna(fs_val):
                try:
                    future_static_val_num = float(fs_val)
                    if future_static_val_num > 0:
                        future_static_val = f"{future_static_val_num:.4f}"
                except: pass
                
        if future_static_val_num <= 0 and n_T1 > 0 and future_settle_num > 0 and future_settle_num_t1 > 0 and exchange_rate > 0 and t1_exchange_rate > 0:
            f_chg = future_settle_num / future_settle_num_t1
            r_chg = exchange_rate / t1_exchange_rate
            future_static_val_num = n_T1 * (1 + pos_float * (f_chg * r_chg - 1))
            if future_static_val_num > 0:
                future_static_val = f"{future_static_val_num:.4f}"
                
        future_val_err_str = "-"
        future_val_err_cls = ""
        # 🌟 修复：期货误差同样优先动态计算
        if future_static_val_num > 0 and n_T > 0:
            fv_err_num = (future_static_val_num / n_T - 1) * 100
            future_val_err_cls, future_val_err_str = html_generator.format_color(fv_err_num)
        elif '期货静态估值误差' in df_idx.columns:
            fv_err_val = df_idx.loc[d_T].get('期货静态估值误差', '无')
            if fv_err_val != '无' and pd.notna(fv_err_val):
                try:
                    fv_err_num = float(str(fv_err_val).replace('%', ''))
                    if abs(fv_err_num) > 0.0001:
                        future_val_err_cls, future_val_err_str = html_generator.format_color(fv_err_num)
                except: pass
            
        future_premium_str = "-"
        future_premium_cls = ""
        if future_static_val_num > 0 and c_T > 0:
            fp_num = (c_T / future_static_val_num - 1) * 100
            future_premium_cls, future_premium_str = html_generator.format_color(fp_num)
        elif '期货静态估值溢价' in df_idx.columns:
            fp_val = df_idx.loc[d_T].get('期货静态估值溢价', '无')
            if fp_val != '无' and pd.notna(fp_val):
                try:
                    fp_num = float(str(fp_val).replace('%', ''))
                    if abs(fp_num) > 0.0001:
                        future_premium_cls, future_premium_str = html_generator.format_color(fp_num)
                except: pass
        
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
        <tr class="secondary-page-row"><td class="num-font">{d_T.strftime('%m-%d')}</td><td>{exchange_rate_str}</td><td>{nav_str}</td><td class="secondary-close-price">{secondary_close_str}</td><td class="num-font {premium_cls}"><b>{premium_str}</b></td>{etf_td_html}<td class="num-font col-etf-bg" style="color:#d35400; font-weight:bold">{est_val_str}</td><td class="num-font col-etf-bg {etf_val_err_cls}">{etf_val_err_str}</td>{future_td_html}<td><button class="btn-verify" onclick="toggleVerify('{uid}')">▶ 验算</button></td></tr>
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
    
    # ================================================================
    # 第四段：主页行生成 - 生成主页显示的最新数据行
    # ================================================================
    
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
      
        # ================================================================
        # 第五段：期货实时估值计算 - 根据期货实时价格计算实时估值
        # ================================================================
        
        # 计算期货实时估值
        future_valuation = 0.0
        future_premium = None
        future_price = 0.0
        
        exact_future_valuation = 0.0
        exact_future_premium = None
        
        # 白银期货特殊处理
        silver_future_data = None
        vwap = 0.0
        settlement_price = 0.0
        
        # 获取期货校准值（使用从basic表格中获取的校准值）
        gold_calib = calibrations.get('GC', 10.9067)
        oil_calib = calibrations.get('CL', 0.8227)
                
        # 从API获取期货实时数据
        try:
            # 使用传入的futures_data参数
            if futures_data and code not in ['163208', '160216', '161815']:
                
                # 统一找到基准日期的汇率和日期
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

                # 统一寻找基准日期货收盘价
                base_future_price = 0.0
                if base_date is not None and future_symbol:
                    settle_col = f"{future_symbol}_settle"
                    for dt_candidate in df_idx.loc[:base_date].index.sort_values(ascending=False):
                        val = 0
                        if settle_col in df_idx.columns:
                            v = df_idx.loc[dt_candidate].get(settle_col)
                            if pd.notna(v) and v != '无' and v != '':
                                try: val = float(v)
                                except: val = 0
                        if val <= 0 and '期货结算价' in df_idx.columns:
                            v = df_idx.loc[dt_candidate].get('期货结算价')
                            if pd.notna(v) and v != '无' and v != '':
                                try: val = float(v)
                                except: val = 0
                        if val > 0:
                            base_future_price = val
                            break
                    if base_future_price <= 0 and futures_history_df is not None and not futures_history_df.empty:
                        base_date_str = base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else str(base_date)[:10]
                        if base_date_str in futures_history_df.index:
                            val = futures_history_df.loc[base_date_str].get(f'{future_symbol}_close', 0.0)
                            if isinstance(val, pd.Series): val = val.iloc[0]
                            base_future_price = float(val) if pd.notna(val) else 0.0

                # 提取期货价格
                if category == '黄金' and 'GC' in futures_data:
                    future_price = futures_data['GC']['price']
                    # 计算期货实时估值
                    if future_price > 0 and nav_home > 0:
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
                                    try:
                                        if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                            if symbol in row and pd.notna(row[symbol]):
                                                etf_price = row.get(symbol, 0)
                                                if isinstance(etf_price, (int, float)) and etf_price > 0:
                                                    base_etf_price = etf_price
                                                    break
                                    except: pass
                                
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
                        
                        # 阻止使用历史T-1收盘价伪造实时溢价，直接交由前端JS负责计算
                        # if latest_valid_close > 0 and future_valuation > 0:
                        #     future_premium = (latest_valid_close / future_valuation - 1) * 100
                        
                        # 针对黄金如果没有直接的期货收盘价，采用反推兜底
                        if base_future_price <= 0 and gold_calib > 0:
                            fallback_etf_price = 0.0
                            for item in h_list:
                                sym = item['symbol']
                                for _, row in lof_df_sorted.iterrows():
                                    try:
                                        if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                            val_e = row.get(sym, 0)
                                            if pd.notna(val_e) and isinstance(val_e, (int, float)) and val_e > 0:
                                                fallback_etf_price = float(val_e)
                                                break
                                    except: pass
                                if fallback_etf_price > 0: break
                            if fallback_etf_price > 0:
                                base_future_price = fallback_etf_price * gold_calib

                        if base_future_price <= 0 and oil_calib > 0:
                            fallback_etf_price = 0.0
                            for item in h_list:
                                sym = item['symbol']
                                for _, row in lof_df_sorted.iterrows():
                                    try:
                                        if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                            val_e = row.get(sym, 0)
                                            if pd.notna(val_e) and isinstance(val_e, (int, float)) and val_e > 0:
                                                fallback_etf_price = float(val_e)
                                                break
                                    except: pass
                                if fallback_etf_price > 0: break
                            if fallback_etf_price > 0:
                                base_future_price = fallback_etf_price * oil_calib

                        if base_future_price > 0:
                            future_change_rate = future_price / base_future_price
                            net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                            exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                            # if latest_valid_close > 0 and exact_future_valuation > 0:
                            #     exact_future_premium = (latest_valid_close / exact_future_valuation - 1) * 100
                
                elif category == '原油' and 'CL' in futures_data:
                    future_price = futures_data['CL']['price']
                    if future_price > 0 and nav_home > 0:
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
                                    try:
                                        if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                            if symbol in row and pd.notna(row[symbol]):
                                                etf_price = row.get(symbol, 0)
                                                if isinstance(etf_price, (int, float)) and etf_price > 0:
                                                    base_etf_price = etf_price
                                                    break
                                    except: pass
                                
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
                        
                        # if latest_valid_close > 0 and future_valuation > 0:
                        #     future_premium = (latest_valid_close / future_valuation - 1) * 100
                        
                        if base_future_price > 0:
                            future_change_rate = future_price / base_future_price
                            net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                            exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                            # if latest_valid_close > 0 and exact_future_valuation > 0:
                            #     exact_future_premium = (latest_valid_close / exact_future_valuation - 1) * 100
                
                elif category == '指数' and future_symbol and future_symbol in futures_data:
                    future_price = futures_data[future_symbol]['price']
                    if future_price > 0 and nav_home > 0:
                        if base_exchange_rate <= 0:
                            raise ValueError("没有找到基准汇率，严禁使用固定值，强制熔断")
                        
                        # 严禁降级！获取当期真实汇率，若无则熔断
                        current_exchange_rate = today_exchange_rate_float
                        exchange_rate_change = current_exchange_rate / base_exchange_rate
                        if current_exchange_rate <= 0:
                            raise ValueError("没有找到今日汇率，严禁使用固定值，强制熔断")
                        
                        # 新增：计算期货校准实时估值 (指数专用，去除升贴水还原成基准现货)
                        if latest_calibration_factor > 0:
                            calibrated_spot = future_price / latest_calibration_factor
                            
                            # 修复：指数校准必须拿"还原后的实时现货(NDX/GSPC)"除以"基准日的现货指数(NDX/GSPC)"
                            base_index_price = 0.0
                            index_sym = 'NDX' if future_symbol == 'NQ' else ('GSPC' if future_symbol == 'ES' else None)
                            if index_sym:
                                sym_variants = [index_sym, f"^{index_sym}", f".{index_sym}"]
                                if future_symbol == 'ES':
                                    sym_variants.extend(['IDX', '^IDX', 'INX', '.INX'])
                                elif future_symbol == 'NQ':
                                    sym_variants.extend(['.NDX'])
                                    
                                for sym_variant in sym_variants:
                                    if sym_variant in df_idx.columns:
                                        for _, row in lof_df_sorted.iterrows():
                                            try:
                                                if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                                    val = row.get(sym_variant)
                                                    if pd.notna(val) and val != '无' and val != '':
                                                        val_f = float(val)
                                                        if val_f > 0:
                                                            base_index_price = val_f
                                                            break
                                            except: pass
                                        if base_index_price > 0:
                                            break
                            
                            # 降级方案：如果没有爬到基准日现货指数，则利用基准日的校准值(升贴水)反推基准日现货
                            if base_index_price <= 0 and base_future_price > 0:
                                try:
                                    base_calib = float(base_row.get('calibration', 0.0)) if base_row is not None else 0.0
                                    if base_calib > 0:
                                        base_index_price = base_future_price / base_calib
                                except: pass
                            
                            if base_index_price > 0:
                                weighted_futures_change_rate = calibrated_spot / base_index_price
                                net_value_change_ratio = pos_float * (weighted_futures_change_rate * exchange_rate_change - 1)
                                future_valuation = nav_home * (1 + net_value_change_ratio)

                        # 新增：精准纯期货估值
                        if base_future_price > 0:
                            future_change_rate = future_price / base_future_price
                            net_value_change_ratio_exact = pos_float * (future_change_rate * exchange_rate_change - 1)
                            exact_future_valuation = nav_home * (1 + net_value_change_ratio_exact)
                            # if latest_valid_close > 0 and exact_future_valuation > 0:
                            #     exact_future_premium = (latest_valid_close / exact_future_valuation - 1) * 100
                
        except Exception as e:
            print(f"获取期货数据失败: {e}")
            
        # ================================================================
        # 第六段：白银期货(161226)特殊处理
        # ================================================================
            
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
        
        # ================================================================
        # 第七段：期货数据格式化 - 格式化期货价格为字符串，设置颜色和指示灯
        # ================================================================
        
        # 格式化期货数据
        future_price_str = f"{future_price:.2f}" if future_price > 0 else "-"
        future_valuation_str = f"{future_valuation:.4f}" if future_valuation > 0 else "-"
        future_premium_str = f"{future_premium:+.2f}%" if future_premium is not None else "-"
        
        # 为期货静态溢价设置颜色
        future_premium_cls = "" if future_premium is None or future_premium == 0 else ("premium-positive" if future_premium > 0 else "premium-negative")
        
        # 套利指示灯：<= -0.8% (折价) 红灯闪烁，否则绿灯休眠
        future_light_html = ""
        if future_premium_str != '-':
            if future_premium <= -0.8:
                future_light_html = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>'
            else:
                future_light_html = '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'
        
        # 构建估值+溢价的组合显示
        # etf_valuation_display = f'<span class="num-font" id="realtime-valuation-{code}">-</span>'
        # etf_valuation_display += f'<br><span class="num-font" id="realtime-premium-{code}" style="font-size:14px;">-</span><span id="realtime-light-{code}"></span>'
                # ================================================================
        # 新增：在后端 Python 中预先计算 ETF 实时估值 (对齐前端 JS 逻辑)
        # ================================================================
        etf_valuation = 0.0
        etf_premium = None

        if etf_prices and nav_home > 0 and base_row is not None:
            base_er = base_row.get('exchange_rate')
            if pd.notna(base_er) and base_er != '无' and base_er != '':
                try:
                    base_er_float = float(base_er)
                    if base_er_float > 0:
                        current_er = today_exchange_rate_float
                        exchange_rate_change = current_er / base_er_float

                        # 获取 magic formula 需要的 hedge_value
                        hedge_value = 0.0
                        try:
                            hv = base_row.get('hedge_value', base_row.get('hedge', 0.0))
                            if pd.notna(hv) and hv != '无' and hv != '':
                                hedge_value = float(hv)
                        except: pass

                        etf_calibration = hedge_value * pos_float if hedge_value > 0 and pos_float > 0 else 0

                        # 获取 primary symbol 的实时价格
                        primary_sym = h_list[0]['symbol'] if h_list else ''
                        clean_primary_sym = primary_sym.replace('^', '').split('-')[0].upper()
                        current_asset_price = 0.0

                        if clean_primary_sym in etf_prices:
                            price_dict = etf_prices[clean_primary_sym]
                            if isinstance(price_dict, dict) and price_dict.get('bid', 0) > 0:
                                current_asset_price = price_dict['bid']

                        # 魔法公式判断
                        if category not in ['黄金', '原油'] and etf_calibration > 0 and len(h_list) == 1 and pos_float > 0 and current_asset_price > 0:
                            etf_valuation = nav_home * (1.0 - pos_float) + (pos_float / etf_calibration) * (current_asset_price * current_er)
                        else:
                            # 矩阵兜底算法
                            weighted_etf_change_rate = 0.0
                            valid_weight = 0.0
                            has_valid_data = False

                            for item in h_list:
                                sym = str(item['symbol'])
                                clean_sym = sym.replace('^', '').split('-')[0].upper()
                                weight = item.get('weight', 0.0)

                                import re
                                is_a_share = bool(re.match(r'^[0-9]{5,6}$|^(sh|sz)[0-9]{6}$', clean_sym, re.IGNORECASE))
                                lookup_sym = re.sub(r'^(SH|SZ)', '', clean_sym) if is_a_share else clean_sym

                                cur_p = 0.0
                                if lookup_sym in etf_prices:
                                    pdct = etf_prices[lookup_sym]
                                    if isinstance(pdct, dict) and pdct.get('bid', 0) > 0:
                                        cur_p = pdct['bid']

                                base_p = 0.0
                                if sym in base_row and pd.notna(base_row[sym]) and base_row[sym] != '无' and base_row[sym] != '':
                                    try:
                                        bp = float(base_row[sym])
                                        if bp > 0: base_p = bp
                                    except: pass

                                if base_p > 0 and cur_p > 0 and weight > 0:
                                    change_rate = cur_p / base_p
                                    if not is_a_share:
                                        change_rate *= exchange_rate_change
                                    weighted_etf_change_rate += change_rate * weight
                                    valid_weight += weight
                                    has_valid_data = True

                            if has_valid_data:
                                if valid_weight < 0.98 or valid_weight > 1.02:
                                    weighted_etf_change_rate = weighted_etf_change_rate / valid_weight
                                etf_valuation = nav_home * (1 + pos_float * (weighted_etf_change_rate - 1))
                except Exception:
                    pass

        if latest_valid_close > 0 and etf_valuation > 0:
            etf_premium = (latest_valid_close / etf_valuation - 1) * 100

        # 格式化显示
        etf_val_str = f"{etf_valuation:.4f}" if etf_valuation > 0 else "-"
        etf_prem_str = f"{etf_premium:+.2f}%" if etf_premium is not None else "-"
        etf_prem_cls = "" if etf_premium is None or etf_premium == 0 else ("premium-positive" if etf_premium > 0 else "premium-negative")

        etf_light_html = ""
        if etf_prem_str != '-':
            if etf_premium <= -0.8:
                etf_light_html = '<span class="arb-light arb-light-red" title="存在折价套利空间 (≤-0.8%)"></span>'
            else:
                etf_light_html = '<span class="arb-light arb-light-green" title="无显著折价空间 (>-0.8%)"></span>'

        # 构建估值+溢价的组合显示
        etf_valuation_display = f'<span class="num-font" id="realtime-valuation-{code}">{etf_val_str}</span>'
        if etf_prem_str != '-':
            etf_valuation_display += f'<br><span class="num-font {etf_prem_cls}" id="realtime-premium-{code}" style="font-size:14px;">{etf_prem_str}</span><span id="realtime-light-{code}">{etf_light_html}</span>'
        else:
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
        <td colspan="3" onclick="window.openSandbox('{code}', 'etf')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="padding: 0;">
            <div style="display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;">
                <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{etf_valuation_display}</div>
                <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{futures_valuation_display}</div>
                <div style="flex: 1; width: 120px; padding: 8px 4px;">{exact_futures_valuation_display}</div>
            </div>
        </td>"""
        
        # 为大宗商品准备的合并实时估值单元格
        if code in ['163208', '160216', '161815']:
            combined_realtime_td_main = f"""
            <td colspan="3" onclick="window.openSandbox('{code}', 'etf')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="padding: 0;">
                <div style="display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;">
                    <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{etf_valuation_display}</div>
                    <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05); color:#9e9e9e;">混合不适用</div>
                    <div style="flex: 1; width: 120px; padding: 8px 4px; color:#9e9e9e;">混合不适用</div>
                </div>
            </td>"""
        else:
            combined_realtime_td_main = f"""
            <td colspan="3" onclick="window.openSandbox('{code}', 'etf')" class="clickable-cell col-realtime-bg" title="点击打开实时估值沙盘" style="padding: 0;">
                <div style="display: flex; width: 100%; height: 100%; align-items: center; justify-content: center;">
                    <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{etf_valuation_display}</div>
                    <div style="flex: 1; width: 120px; padding: 8px 4px; border-right: 1px dashed rgba(0,0,0,0.05);">{futures_valuation_display}</div>
                    <div style="flex: 1; width: 120px; padding: 8px 4px;">{exact_futures_valuation_display}</div>
                </div>
            </td>"""

        # ================================================================
        # 第八段：实时沙盘数据提取 - 提取沙盘计算所需的基础数据
        # ================================================================
        
        # ==========================================
        # 实时盘中沙盘 (Sandbox) 基础数据提取
        # ==========================================
        rt_base_date_str = "无"
        rt_base_nav = 0.0
        rt_base_fx = None
        base_etfs_text = ""
        base_future_price = 0.0
        
        if base_row is not None:
            row = base_row # 使用已找到的基准行
            try:
                rt_base_date_str = row['date'].strftime('%Y-%m-%d')
                rt_base_nav = float(row['nav'])
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
                if future_symbol:
                    settle_col = f"{future_symbol}_settle"
                    if settle_col in row:
                        val = row.get(settle_col)
                        if pd.notna(val) and val != '无' and val != '':
                            base_future_price = float(val)
                    if base_future_price <= 0 and '期货结算价' in row:
                        val = row.get('期货结算价')
                        if pd.notna(val) and val != '无' and val != '':
                            base_future_price = float(val)
            except (ValueError, TypeError):
                pass
                
        if not base_etfs_text:
            base_etfs_text = "无数据"
            
        unique_base_syms = []
        for item in h_list:
            sym = item['symbol']
            # 坚决不兜底合并：保留原汁原味的衍生品代码，以便沙盘精准独立调参
            clean_sym = sym.replace('^', '')
            if clean_sym not in unique_base_syms:
                unique_base_syms.append(clean_sym)
                
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

        # ================================================================
        # 第九段：HTML生成 - 生成所有HTML界面（三套对冲测算、交易UI等）
        # ================================================================
        
        # 定义交易UI组件 - 三套对冲测算 + 完整交易操作
        # 布局技术说明：
        # 1. 使用Flexbox布局实现响应式设计
        # 2. 采用垂直堆叠的容器结构，每个区域独立成块
        # 3. 所有区域使用justify-content: center实现水平居中
        # 4. 使用flex-wrap: wrap确保在小屏幕上自动换行
        # 5. 统一设置区域宽度和间距，确保视觉一致性
        # 6. 移除了之前的transform平移，使用自然的Flex布局实现对齐
        def get_three_hedge_calculations_with_trade():
            rt_prices_spans = []
            # h_list is available in the outer scope of generate_fund_data
            for item in h_list:
                sym = item['symbol']
                # JS will populate this span. The ID needs to be unique and JS-friendly.
                sanitized_sym = sym.replace('^', '').replace('-', '_').replace('.', '_')
                rt_prices_spans.append(f'<span style="font-family:monospace; font-weight:bold;">{sym}: <span id="sb-rt-price-{code}-{sanitized_sym}" style="color:#d35400;">-</span></span>')
            rt_prices_html = " | ".join(rt_prices_spans)
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
                                    <span id="sb-lof-qty-{code}-etf" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">-</span>
                                    <span style="font-size:11px; color:#333;">股 +</span>
                                    <span style="font-size:11px; color:#333;">{" + ".join(trade_etfs)}</span>
                                    <span id="sb-etf-qty-{code}-etf" class="num-font" style="font-size: 13px; color: #1565c0; font-weight:bold; min-width:30px; text-align:center; display:inline-block;">-</span>
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
                                    <span id="sb-lof-qty-{code}-future" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">-</span>
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
                                    <span id="sb-lof-qty-{code}-pure_future" class="num-font" style="font-size: 13px; color: #d32f2f; font-weight:bold; min-width:40px; text-align:center; display:inline-block;">-</span>
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
            elif category == '纯ETF' or category == '混合跨境':
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
    
    future_th_html = '<th class="col-future-bg-th">期货结算价</th><th class="col-future-bg-th">期货静态净值</th><th class="col-future-bg-th">期货静态溢价</th><th class="col-future-bg-th">期货估值误差</th>' if has_future else ''
    
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
                                <th>日期</th><th>{rate_header_name}</th><th>净值</th><th>收盘价</th><th>溢价</th>{etf_th_html}<th class="col-etf-bg-th">ETF静态净值</th><th class="col-etf-bg-th">ETF估值误差</th>{future_th_html}<th>验算</th>
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
                                <th>日期</th><th>{rate_header_name}</th><th>{future_symbol}收盘价</th><th>期货估值</th><th>收盘价</th><th>期货静态溢价</th><th>净值</th><th>估值误差比例</th><th>验算</th>
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

                <!-- 【区域名称：对冲数量区】三套对冲测算并排显示：ETF实时估值对冲数量、期货校准估值对冲数量、纯期货估值对冲数量 -->
                <!-- 【区域名称：实时盘口区】两个盘口：GLD实时盘口、GC实时盘口 -->
                <!-- 【区域名称：下单区】两个下单区：QMT/IB ETF下单区、IB期货下单区 -->
                <!-- 【区域名称：下单按键】两行按键：买入按键（上一行）、卖出按键（下一行） -->
                {get_three_hedge_calculations_with_trade()}

                <div style="margin-top: 15px; font-size: 13px; color: #888;">* 提示：面板打开时会自动填入主面板实盘价作为默认测试价。您可以随意修改输入框内的值，点击计算后推演该价位溢价率，不影响主面板自动刷新。也支持国金QMT。</div>
            </div>
        </div>"""
    
    # ================================================================
    # 第十段：函数返回 - 返回主页行、详情页和全局日期
    # ================================================================
    
    # 获取全局日期
    global_date = None
    if not lof_df_sorted.empty:
        global_date = lof_df_sorted.iloc[0]['date'].strftime('%Y-%m-%d')
    
    return home_row, detail_page, global_date