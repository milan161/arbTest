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
from LOF035_fund_processor import generate_fund_data, read_fund_history_from_db

# 从 arbcore 导入公共函数
sys.path.insert(0, os.path.join(SCRIPT_DIR, "..", "arbcore"))
from fetchers.market_data_fetcher import get_exchange_rate, get_ib_night_prices

# 验证模块导入成功
print("模块导入成功 (LOF03):")
print(f"ConfigManager: {ConfigManager}")
print(f"DataProcessor: {DataProcessor}")
print(f"HtmlGenerator: {HtmlGenerator}")
print(f"JsGenerator: {JsGenerator}")
print("使用新架构运行...")

# 全局变量
silver_fund_data = None

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
    global_params = data_processor.get_latest_global_params()
    global_er = global_params.get('global_er', 7.0)
    calibrations = global_params.get('calibrations', {})
    
    print(f"使用全局参数: 汇率={global_er:.4f}, 校准值字典={calibrations}")

    # 提前计算所有基金的基准数据，注入前端JS，避免前端同步读取CSV卡死浏览器
    js_fund_base_data = {}
    for fund in cfg.get('funds', []):
        code = fund.get('code', '')
        if code == '161226': continue
        category = fund.get('category', '其他')
        
        lof_df = read_fund_history_from_db(code)
        lof_df_sorted = lof_df
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
            if position > 2: position = position / 100.0 # 兼容 95 和 0.95 两种写法
            # 兼容新旧版配置：优先使用 valuation_portfolio，若无则回退到 hedging_portfolio
            hedging_portfolio = fund.get('valuation_portfolio', [])
            if not hedging_portfolio:
                hedging_portfolio = fund.get('hedging_portfolio', [])
            
            # 在这里同样标准化注入的符号
            for item in hedging_portfolio:
                sym = str(item.get('symbol', ''))
                if any(sym.endswith(suffix) for suffix in ['-EU', '-JP', '-HK', '-UK']) and not sym.startswith('^'):
                    item['symbol'] = f"^{sym.replace('^', '')}"
            
            # === 核心修复：注入 JS 沙盘前，用基准日真实的 Woody 仓位和权重覆盖 ===
            db_pos = base_row.get('position', base_row.get('仓位'))
            if pd.notna(db_pos) and db_pos != '无' and db_pos != '':
                try:
                    pf = float(db_pos)
                    if pf > 2: pf = pf / 100.0
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
                sym = str(item['symbol'])
                price = 0.0
                
                for _, row in lof_df_sorted.iterrows():
                    try:
                        if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                            if sym in row and pd.notna(row[sym]) and row[sym] != '无' and row[sym] != '':
                                p = float(row[sym])
                                if p > 0:
                                    price = p
                                    break
                    except: pass
                
                if price <= 0:
                    base_sym = sym.replace('^', '').split('-')[0]
                    for _, row in lof_df_sorted.iterrows():
                        try:
                            if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                if base_sym in row and pd.notna(row[base_sym]) and row[base_sym] != '无':
                                    p = float(row[base_sym])
                                    if p > 0:
                                        price = p
                                        break
                                elif f"^{base_sym}" in row and pd.notna(row[f"^{base_sym}"]) and row[f"^{base_sym}"] != '无':
                                    p = float(row[f"^{base_sym}"])
                                    if p > 0:
                                        price = p
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

            if base_date and future_symbol_js:
                settle_col = f"{future_symbol_js}_settle"
                # 核心修复：从基准日(含)往前找，找到最近一个有期货结算价的交易日
                # lof_df is already sorted by date descending
                for _, row in lof_df.iterrows():
                    if row['date'] > base_date: continue # Skip future dates
                    
                    val = 0
                    if settle_col in row and pd.notna(row[settle_col]):
                        try: val = float(row[settle_col])
                        except: val = 0
                    
                    if val <= 0 and '期货结算价' in row and pd.notna(row['期货结算价']):
                        try: val = float(row['期货结算价'])
                        except: val = 0
                        
                    if val > 0:
                        base_future_price = val
                        break
                    
            # 终极兜底1：CSV 历史记录
            if base_future_price <= 0 and futures_history_df is not None and not futures_history_df.empty and base_date is not None:
                base_date_str = base_date.strftime('%Y-%m-%d') if isinstance(base_date, pd.Timestamp) else str(base_date)[:10]
                if base_date_str in futures_history_df.index:
                    val = futures_history_df.loc[base_date_str].get(f'{future_symbol_js}_close', 0.0)
                    if isinstance(val, pd.Series): val = val.iloc[0]
                    base_future_price = float(val) if pd.notna(val) else 0.0

            # 为 JS 预埋基准现货指数
            base_index_price = 0.0
            base_calib_val = 0.0
            if base_row is not None:
                try:
                    c_val = base_row.get('calibration', 0.0)
                    if pd.notna(c_val) and c_val != '无':
                        base_calib_val = float(c_val)
                except: pass
                
            if category == '指数' and base_row is not None:
                index_sym = 'NDX' if future_symbol_js == 'NQ' else ('GSPC' if future_symbol_js == 'ES' else None)
                if index_sym:
                    sym_variants = [index_sym, f"^{index_sym}", f".{index_sym}"]
                    if future_symbol_js == 'ES':
                        sym_variants.extend(['IDX', '^IDX', 'INX', '.INX'])
                    elif future_symbol_js == 'NQ':
                        sym_variants.extend(['.NDX'])
                        
                    for sym_variant in sym_variants:
                        for _, row in lof_df_sorted.iterrows():
                            try:
                                if pd.to_datetime(row['date']) <= pd.to_datetime(base_date):
                                    if sym_variant in row and pd.notna(row[sym_variant]) and row[sym_variant] != '无':
                                        val_f = float(row[sym_variant])
                                        if val_f > 0:
                                            base_index_price = val_f
                                            break
                            except: pass
                        if base_index_price > 0:
                            break
                # 如果宽表中未提供，采用反推法
                if base_index_price <= 0 and base_future_price > 0 and base_calib_val > 0:
                    base_index_price = base_future_price / base_calib_val
                    
            # =========================================================================
            # 💡 概念澄清与双校准参数隔离 (核心备注)
            # =========================================================================
            # 1. woody API 的 `hedge` (在此对应 hedge_value):
            #    - 用途：优先作为“魔法公式”来计算【纯ETF】和【指数】的估值（包含静态估值和ETF实时估值）。
            #    - 规则：如果没能从 woody API 获得有效的 hedge_value，则自动降级使用兜底的矩阵算法。
            #
            # 2. 期货校准 (在此对应 latest_calibration_factor):
            #    - 用途：专门用来计算“实时的期货校准估值” (实时期货价格 / 期货校准)。
            #    - 规则：只有【黄金】、【原油】类基金和【指数】类基金才会用到；【纯ETF】天然没有也不使用期货校准估值。千万不要混淆！
            # =========================================================================
            
        # 提取保存在历史账本中的对冲值 (物理兑换比)
            hedge_value = 0.0
            rmb_exposure = 0.0
            latest_calibration_factor = 0.0
            latest_exchange_rate = 0.0
            
            # 根据基金类别设置期货校准因子
            latest_calibration_factor = calibrations.get(future_symbol_js, 0.0)
            
            # 🌟 关键修复：只有当不是“指数”类基金时，才允许用基金自身的 calibration 覆盖全局期货校准
            # 对于指数基金，fund_data 里的 calibration 是 Index/NAV，而我们需要的是 Future/Index (如 1.002)
            if category != '指数' and base_row is not None:
                try:
                    cal = base_row.get('calibration', 0.0)
                    if pd.notna(cal) and cal != '无':
                        latest_calibration_factor = float(cal)
                except:
                    pass
                    
            # 如果基金自身没有校准值（或者是指数基金），用全局对应期货校准值兜底
            if latest_calibration_factor <= 0:
                latest_calibration_factor = calibrations.get(future_symbol_js, 0.0)
                if latest_calibration_factor <= 0: # 最后的兜底
                    if category == '黄金':
                        latest_calibration_factor = calibrations.get('GC', 10.9067)
                    elif category == '原油':
                        latest_calibration_factor = calibrations.get('CL', 0.8227)
            
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

            trade_future_sym = fund.get('trade_future', '')
            future_multiplier = 1
            if 'MGC' in trade_future_sym: future_multiplier = 10
            elif 'GC' in trade_future_sym: future_multiplier = 100
            elif 'MCL' in trade_future_sym: future_multiplier = 100
            elif 'CL' in trade_future_sym: future_multiplier = 1000
            elif 'MNQ' in trade_future_sym: future_multiplier = 2
            elif 'NQ' in trade_future_sym: future_multiplier = 20
            elif 'MES' in trade_future_sym: future_multiplier = 5
            elif 'ES' in trade_future_sym: future_multiplier = 50
            elif 'AG' in trade_future_sym.upper(): future_multiplier = 15

            # --- [核心修复] 提取基准日收盘价，用于计算涨跌幅 (denominator) ---
            # 无论是否有 NAV，涨跌幅基准必须是数据库中最新的那个收盘价 (T-1)
            base_close_price = 0.0
            valid_closes = lof_df[lof_df['close'] > 0]
            if not valid_closes.empty:
                base_close_price = float(valid_closes.iloc[0]['close'])

            js_fund_base_data[code] = {
                'name': fund.get('name', '未知基金'),
                'baseNav': float(base_nav),
                'baseClosePrice': base_close_price,
                'baseExchangeRate': float(base_exchange_rate) if base_exchange_rate is not None else None,
                'position': float(position),
                'hedgingPortfolio': [{'symbol': h['symbol'], 'weight': h['weight']/100.0} for h in hedging_portfolio],
                'baseEtfPrices': base_etf_prices,
                'category': category,
                'futureSymbol': future_symbol_js,
                'tradeEtf': trade_etf_sym,

                'tradeFuture': trade_future_sym,
                'futureMultiplier': future_multiplier,
     
                'baseIndexPrice': float(base_index_price),
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
    home_rows_mixed = ""
    for fund in cfg.get('funds', []):
        code = fund.get('code', '')
        
        # 161226单独显示在白银LOF特殊监控表格中，不在主表显示
        if code == '161226':
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            if fund_detail_page:
                detail_pages += fund_detail_page
            continue
        
        category = fund.get('category', '其他')
        # 处理单个基金的数据
        if category == '指数':
            # 指数基金需要生成两种行：一种为主表，一种为指数表
            fund_home_row_main, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            fund_home_row_index, _, _ = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=True, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            if fund_home_row_main and fund_detail_page:
                home_rows += fund_home_row_main
                home_rows_index += fund_home_row_index
                detail_pages += fund_detail_page
        elif category == '纯ETF':
            # 纯ETF单独放一个表
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            if fund_home_row and fund_detail_page:
                home_rows += fund_home_row
                home_rows_etf += fund_home_row
                detail_pages += fund_detail_page
            if fund_global_date and not global_date_str:
                global_date_str = fund_global_date
        elif category == '混合跨境':
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            if fund_home_row and fund_detail_page:
                home_rows += fund_home_row
                home_rows_mixed += fund_home_row
                detail_pages += fund_detail_page
            if fund_global_date and not global_date_str:
                global_date_str = fund_global_date
        else:
            # 黄金、原油等商品基金
            fund_home_row, fund_detail_page, fund_global_date = generate_fund_data(fund, data_processor, html_generator, futures_data, futures_history_df, is_index_table=False, calibrations=calibrations, global_er=global_er, etf_prices=ib_night_prices)
            if fund_home_row and fund_detail_page:
                home_rows += fund_home_row
                home_rows_main += fund_home_row
                detail_pages += fund_detail_page
            if fund_global_date and not global_date_str:
                global_date_str = fund_global_date

    # === 【临时硬编码】固定夜盘区显示的ETF品种，防止动态列表过长撑爆页面 ===
    active_etfs = ['XOP', 'GLD', 'KWEB', 'QQQ', 'RSPH', 'SLV', 'SPY', 'XBI', 'XLY', 'USO', 'XLE']

    # 从独立的模块生成前端巨量的 JavaScript 与 Admin 面板交互逻辑
    js_code = JsGenerator.generate_js_code(active_etfs, js_fund_base_data, calibrations, ib_night_prices)
    
    admin_js = JsGenerator.generate_admin_js()
    
    # 添加更多Debug信息
    print("\n=== 生成HTML前的调试信息 ===")
    print(f"汇率: {today_exchange_rate}")
    print(f"IB夜盘价格: {ib_night_prices}")
    print(f"IB状态信息: {ib_status_message}")
    print(f"黄金校准值: {calibrations.get('GC', 10.9067):.4f}")
    print(f"原油校准值: {calibrations.get('CL', 0.8227):.4f}")
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
            df = pd.read_sql(f"SELECT price FROM usa_etf_daily_prices WHERE symbol = '{symbol}' ORDER BY date DESC LIMIT 1", conn)
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
    manual_tds_list = []
    for sym in active_etfs:
        prev_close_val = get_prev_close(sym)
        value_attr = f'value="{prev_close_val}"' if prev_close_val != '-' else ''
        manual_tds_list.append(f'<td style="padding:2px 4px;"><input type="number" id="{sym.lower()}-price" {value_attr} step="0.01" style="width: 64px; padding: 2px; font-size: 12px; font-family: var(--font-mono); font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:2px; outline: none; color:#e65100; background-color:#fff3e0;" oninput="document.getElementById(\'source-manual\').checked=true; window.calculateRealTimeValues()"></td>')
    manual_tds = "".join(manual_tds_list)
        
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
    
    etf_to_future_map = {'USO': 'CL', 'XLE': 'CL', 'GLD': 'GC', 'SLV': 'AG0', 'SPY': 'ES', 'QQQ': 'NQ'}
    futures_tds_html = []
    for sym in active_etfs:
        future_sym = etf_to_future_map.get(sym)
        if future_sym:
            future_class = future_sym.lower().replace('ag0', 'ag0')
            futures_tds_html.append(f'<td style="padding:2px 4px;"><span class="{future_class}-price" style="font-weight:bold; color:#d35400; font-size: 13px;">-</span> <span class="{future_class}-change" style="font-size:11px;"></span></td>')
        else:
            futures_tds_html.append('<td style="padding:2px 4px; color:#999;">-</td>')
    final_html += "".join(futures_tds_html)
    
    final_html += '                            <tr style="border-bottom: 1px dashed #dee2e6; color: #6c757d; background-color: #fdfdfe; height: 24px;">\n'
    final_html += '                                <td style="padding: 2px 4px; text-align: left; font-weight: bold; border-right: 1px dashed #dee2e6; font-size: 12px;">昨收(SMART)</td>\n'
    final_html += f'                                {prev_tds}\n'
    final_html += f'                                <td rowspan="4" style="border-left: 1px solid #dee2e6; vertical-align: middle; background-color: #fff; padding: 2px; width: 85px;">\n'
    final_html += f'                                    <div id="active-source-badge" style="font-size: 10px; padding: 2px; border-radius: 2px; font-weight: bold; margin: 0 auto 2px; width: 75px; text-align: center; white-space: nowrap;"></div>\n'
    final_html += f'                                    <div id="ib-status-text" style="font-size: 10px; padding: 2px; border-radius: 2px; background-color: {ib_status_color}; color: white; margin: 0 auto; text-align: center; min-height: 28px; display: flex; align-items: center; justify-content: center; width: 75px;" title="{ib_status_message}">{ib_status_message}</div>\n'
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
    final_html += '                                    <label style="cursor: pointer; display: flex; align-items: center; gap: 2px; font-weight: bold; color: #2e7d32; margin: 0; font-size: 11px; white-space: nowrap;">\n'
    final_html += f'                                        <input type="radio" name="calc_source" id="source-futu" value="futu" {"checked" if not has_ib_data and has_futu_data else ""} onchange="window.calculateRealTimeValues()" style="margin: 0; transform: scale(0.7);"> 富途夜盘(买一)\n'
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
    final_html += '                <button class="tab-button" onclick="switchTab(1)" style="background: var(--primary-color); color: white; border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">黄金原油</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(2)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">纯ETF</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(3)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">指数</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(8)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">混合跨境</button>\n'
    final_html += '                <button class="tab-button" onclick="switchTab(4)" style="background: var(--secondary-light); color: var(--secondary-dark); border: none; padding: 10px 20px; border-radius: 6px 6px 0 0; cursor: pointer; font-weight: bold; font-size: 14px; font-family: var(--font-sans);">白银</button>\n'
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
    final_html += '                                <th rowspan="2" style="width: 60px;">商品代码</th><th rowspan="2" style="width: 50px;">类别</th><th rowspan="2" style="text-align: center; width: 90px;">名称</th><th rowspan="2" style="width: 45px;">仓位</th><th rowspan="2" style="width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)</th><th colspan="3" class="col-realtime-bg-th"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
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
        final_html += '                                <th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 60px;">纯ETF代码</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 50px;">类别</th><th rowspan="2" style="text-align: center; background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 90px;">名称</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 45px;">仓位</th><th rowspan="2" style="background-color: #fff3e0; border-bottom: 2px solid #ffb74d; width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)</th><th class="col-realtime-bg-th" style="width: 200px;"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
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
    final_html += '                                <th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 60px;">指数代码</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 50px;">类别</th><th rowspan="2" style="text-align: center; background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 90px;">名称</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 45px;">仓位</th><th rowspan="2" style="background-color: #e8eaf6; border-bottom: 2px solid #9fa8da; width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)</th><th colspan="3" class="col-realtime-bg-th"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
    final_html += '                            </tr>\n'
    final_html += '                            <tr>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 120px;">ETF估值 <span id="etf-freeze-warn-idx" style="display:none; color:#d32f2f; font-size:9px; font-weight:bold;">(15:00后冻结)</span></th>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 120px;">期货校准</th>\n'
    final_html += '                                <th class="col-realtime-bg-th" style="width: 120px;">纯期货映射</th>\n'
    final_html += '                            </tr>\n'
    final_html += '                        </thead>\n'
    final_html += '                        <tbody>' + home_rows_index + '</tbody>\n'
    final_html += '                    </table>\n'
    final_html += '                </div>\n'
    final_html += '            </div>\n'
    final_html += '            </div>\n'
    
    # --- 拆分的表 8：混合跨境 (TAB 8) ---
    final_html += '            <div id="tab-8" class="tab-content" style="margin-bottom: 10px;">\n'
    if home_rows_mixed:
        final_html += '                <div class="card" style="margin-bottom: 10px;">\n'
        final_html += '                <div style="overflow-x: auto; max-height: calc(100vh - 220px);">\n'
        final_html += '                    <table style="width: 100%; border-collapse: collapse; font-size: 11px;">\n'
        final_html += '                        <thead style="position: sticky; top: 0; background-color: #f3e5f5; z-index: 10; font-size: 11px;">\n'
        final_html += '                            <tr>\n'
        final_html += '                                <th rowspan="2" style="background-color: #f3e5f5; border-bottom: 2px solid #ab47bc; width: 60px;">混合代码</th><th rowspan="2" style="background-color: #f3e5f5; border-bottom: 2px solid #ab47bc; width: 50px;">类别</th><th rowspan="2" style="text-align: center; background-color: #f3e5f5; border-bottom: 2px solid #ab47bc; width: 90px;">名称</th><th rowspan="2" style="background-color: #f3e5f5; border-bottom: 2px solid #ab47bc; width: 45px;">仓位</th><th rowspan="2" style="background-color: #f3e5f5; border-bottom: 2px solid #ab47bc; width: 65px;">净值</th><th rowspan="2" class="col-static-bg-th" style="width: 95px;">静态官方估值<br><span style="font-size:10px;font-weight:normal;color:#d35400;">(点击本列可验算)</span></th><th rowspan="2" class="col-static-bg-th" style="width: 70px;">收盘价(T-1)</th><th rowspan="2" class="col-static-bg-th" style="width: 90px;">实时价(T)</th><th class="col-realtime-bg-th" style="width: 200px;"><div style="display: flex; align-items: center; justify-content: center; gap: 10px;"><span>实时估值 (含折溢价) <span style="font-size:11px;font-weight:normal;">(点击本列可验算)</span></span></div></th>\n'
        final_html += '                            </tr>\n'
        final_html += '                            <tr>\n'
        final_html += '                                <th class="col-realtime-bg-th" style="width: 200px;">混合估值 <span id="etf-freeze-warn-mix" style="display:none; color:#d32f2f; font-size:9px; font-weight:bold;">(15:00后冻结)</span></th>\n'
        final_html += '                            </tr>\n'
        final_html += '                        </thead>\n'
        final_html += '                        <tbody>' + home_rows_mixed + '</tbody>\n'
        final_html += '                    </table>\n'
        final_html += '                </div>\n'
        final_html += '            </div>\n'
    final_html += '            </div>\n'

    # --- 拆分的表 8：混合跨境 (TAB 8) ---
    # ...
    
    # 🌟 核心修复：从处理器模块提取被修改过的白银数据
    import LOF035_fund_processor
    silver_fund_data = LOF035_fund_processor.silver_fund_data

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
        final_html += '                    <p style="color: var(--secondary-color); margin-top: 15px;">此处为演示/新功能预留区域，暂无内容。</p>\n'
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
    # 检查并更新历史数据 (此逻辑已移至启动批处理文件 LOF_start_lof_system.bat 中显式执行，以保证流程清晰)
    # update_result, update_message = check_and_update_historical_data()
    # print(update_message)
    
    # 生成监控报表
    generate()
