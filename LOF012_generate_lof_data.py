# -*- coding: utf-8 -*-
# 012_generate_lof_data.py - 生成LOF基金数据
# 版本: 1.0.1
# 最后修改时间: 2026-03-03
"""
生成LOF基金历史数据模块
负责从东财获取LOF基金历史净值数据，从新浪获取LOF基金历史收盘价数据，
并计算静态官方估值
"""

import os
import re
import json
import requests
# 禁用urllib3的警告
requests.packages.urllib3.disable_warnings()
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
import yaml
import time
import traceback
import sys

# 导入公共数据获取模块
from readers.data_fetcher import data_fetcher

# 导入LOF013模块
from LOF013_woody_web_crawler import WoodyWebCrawler

def load_access_status():
    """
    加载访问状态（合并API和LOF的状态）
    返回: dict - 访问状态
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    status_file = os.path.join(data_dir, "access_status.json")
    
    if not os.path.exists(status_file):
        # 返回默认状态
        return {
            'api': {
                'last_access_date': '',
                'access_times': {
                    '915': None,
                    '1435': None,
                    '1605': None
                }
            },
            'lof': {
                'last_process_date': '',
                'processed_funds': {}
            }
        }
    
    try:
        with open(status_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[状态文件] 加载访问状态失败: {e}")
        return {
            'api': {
                'last_access_date': '',
                'access_times': {
                    '915': None,
                    '1435': None,
                    '1605': None
                }
            },
            'lof': {
                'last_process_date': '',
                'processed_funds': {}
            }
        }

def save_access_status(status):
    """
    保存访问状态（合并API和LOF的状态）
    """
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    status_file = os.path.join(data_dir, "access_status.json")
    
    try:
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[状态文件] 保存访问状态失败: {e}")
        return False

def load_lof_access_status():
    """
    加载LOF数据处理状态（兼容旧函数）
    返回: dict - LOF数据处理状态
    """
    status = load_access_status()
    return status.get('lof', {
        'last_process_date': '',
        'processed_funds': {}
    })

def save_lof_access_status(status):
    """
    保存LOF数据处理状态（兼容旧函数）
    """
    full_status = load_access_status()
    full_status['lof'] = status
    return save_access_status(full_status)

class LofDataGenerator:
    def __init__(self):
        # 初始化数据保存路径
        self.data_path = os.path.join(os.path.dirname(__file__), "data")
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)
        
        # 初始化请求头
        self.sina_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://finance.sina.com.cn/",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "script",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "same-site",
        }
        
        self.eastmoney_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://quote.eastmoney.com/",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "Cookie": "qgqt=1; st_pvi=73981939933070; st_si=74568995531533; ASP.NET_SessionId=qvlc0m55kufmp22ppf1nid55"  # 关键：添加Cookie
        }
        
        # 保存最新日期，供后续使用
        self.latest_date = None
        
        # API数据存储
        self.api_data = None
        
        # 初始化WoodyWebCrawler
        self.woody_crawler = WoodyWebCrawler()
    
    def is_trading_day(self, date_str):
        """判断是否为交易日"""
        # 2026年A股休市日期
        a_stock_holidays_2026 = [
            # 元旦
            '2026-01-01', '2026-01-02', '2026-01-03',
            # 春节
            '2026-02-15', '2026-02-16', '2026-02-17', '2026-02-18', '2026-02-19', '2026-02-20', '2026-02-21', '2026-02-22', '2026-02-23',
            # 清明节
            '2026-04-04', '2026-04-05', '2026-04-06',
            # 劳动节
            '2026-05-01', '2026-05-02', '2026-05-03', '2026-05-04', '2026-05-05',
            # 端午节
            '2026-06-19', '2026-06-20', '2026-06-21',
            # 中秋节
            '2026-09-25', '2026-09-26', '2026-09-27',
            # 国庆节
            '2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07'
        ]
        
        # 转换为日期对象
        date = pd.to_datetime(date_str)
        
        # 检查是否为周末
        if date.weekday() >= 5:  # 5-6是周六和周日
            return False
        
        # 检查是否为A股休市日
        if date_str in a_stock_holidays_2026:
            return False
        
        return True
    
    def get_latest_a_share_trading_day(self):
        """
        获取过去的最近的一个A股交易日
        """
        # 从今天开始，向前查找最近的一个A股交易日
        today = datetime.now().date()
        current_date = today
        
        # 最多向前查找30天
        for _ in range(30):
            if self.is_trading_day(current_date.strftime('%Y-%m-%d')):
                return current_date
            # 向前一天
            current_date = current_date - timedelta(days=1)
        
        # 如果没有找到，返回今天
        return today
    
    def load_api_data(self):
        """从本地API数据表加载数据"""
        today = datetime.now().date().strftime('%Y%m%d')
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        woody_api_dir = os.path.join(data_dir, "woodyAPI")
        api_data_file = os.path.join(woody_api_dir, f"Data_woodyAPI_{today}.csv")
        
        import glob
        csv_files = glob.glob(os.path.join(woody_api_dir, "Data_woodyAPI_*.csv"))
        if csv_files:
            csv_files.sort(reverse=True)
            api_data_file = csv_files[0]
            print(f"  [API] 读取最新API文件: {os.path.basename(api_data_file)}")
        else:
            print("  [API] 未找到API数据CSV文件，请先运行011程序")
            return None
        
        try:
            import pandas as pd
            df = pd.read_csv(api_data_file)
            print(f"  [API] 成功加载本地API数据表，共{len(df)}条记录")
            
            # 转换为字典格式
            api_data = {}
            for _, row in df.iterrows():
                fund_code = row['symbol']
                fund_data = {}
                if pd.notna(row.get('netvalue')):
                    fund_data['netvalue'] = str(row['netvalue'])
                if pd.notna(row.get('CNY')):
                    fund_data['CNY'] = str(row['CNY'])
                if pd.notna(row.get('position')):
                    fund_data['position'] = str(row['position'])
                if pd.notna(row.get('calibration')):
                    fund_data['calibration'] = str(row['calibration'])
                if pd.notna(row.get('hedge')):
                    fund_data['hedge'] = str(row['hedge'])
                if pd.notna(row.get('symbol_hedge')):
                    fund_data['symbol_hedge'] = row['symbol_hedge']
                # 处理ETF价格和权重
                symbol_hedge = {}
                for col in df.columns:
                    if '_ratio' in col:
                        etf_name = col.replace('_ratio', '')
                        if etf_name.startswith('^'):
                            etf_name = '^' + etf_name[1:]
                        if pd.notna(row.get(col)):
                            if etf_name in symbol_hedge:
                                symbol_hedge[etf_name]['ratio'] = str(row[col])
                            else:
                                symbol_hedge[etf_name] = {'ratio': str(row[col])}
                    elif '_price' in col:
                        etf_name = col.replace('_price', '')
                        if etf_name.startswith('^'):
                            etf_name = '^' + etf_name[1:]
                        if pd.notna(row.get(col)):
                            if etf_name in symbol_hedge:
                                symbol_hedge[etf_name]['price'] = str(row[col])
                            else:
                                symbol_hedge[etf_name] = {'price': str(row[col])}
                if symbol_hedge:
                    fund_data['symbol_hedge'] = symbol_hedge
                api_data[fund_code] = fund_data
            
            # 存储API数据
            self.api_data = api_data
            return api_data
        except Exception as e:
            print(f"  [API] 加载本地API数据表失败: {e}")
            return None
    
    def classify_funds(self, api_data, config=None):
        """按照基金类型分组"""
        commodity_funds = []  # 商品类（黄金、原油）
        pure_etf_funds = []   # 纯ETF类
        index_funds = []       # 指数类
        
        # 遍历API数据，按类型分组
        print("  [API] 遍历API数据，按类型分组...")
        for fund_symbol, fund_data in api_data.items():
            code = fund_symbol.replace('SZ', '').replace('SH', '')
            fund_type = ''
            
            # 优先从配置中动态获取真实类别
            if config:
                for f in config.get('funds', []):
                    if str(f.get('code')) == code:
                        cat = f.get('category', '')
                        if cat in ['黄金', '原油']: fund_type = 'gold' if cat == '黄金' else 'oil'
                        elif cat == '纯ETF': fund_type = 'pure_etf'
                        elif cat == '指数': fund_type = 'index'
                        break
                        
            # 如果配置中未定义，则标记为 unknown，坚决摒弃硬编码
            if not fund_type:
                fund_type = 'unknown'
            
            print(f"  [API] 基金: {fund_symbol}, 类型: {fund_type}")
            
            if fund_type == 'gold' or fund_type == 'oil':
                commodity_funds.append((fund_symbol, fund_data))
            elif fund_type == 'pure_etf':
                pure_etf_funds.append((fund_symbol, fund_data))
            elif fund_type == 'index':
                index_funds.append((fund_symbol, fund_data))
        
        print(f"  [API] 商品类基金: {len(commodity_funds)}")
        print(f"  [API] 纯ETF类基金: {len(pure_etf_funds)}")
        print(f"  [API] 指数类基金: {len(index_funds)}")
        
        return commodity_funds, pure_etf_funds, index_funds
    
    def fetch_sina_us_stock_historical_data(self, symbol, max_records=100):
        """从新浪美股API直接获取标准ETF历史数据"""
        print(f"\n=== 新浪爬取 {symbol} 的历史数据 ===")
        url = f"https://stock.finance.sina.com.cn/usstock/api/jsonp.php/var/US_MinKService.getDailyK?symbol={symbol.lower()}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://finance.sina.com.cn/"
        }
        try:
            time.sleep(1)
            response = requests.get(url, headers=headers, timeout=15)
            match = re.search(r'\[.*\]', response.text, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                if len(data) > 0:
                    df = pd.DataFrame(data)
                    if 'd' in df.columns and 'c' in df.columns:
                        df = df[['d', 'c']].copy()
                        df.columns = ['日期', '价格']
                        df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
                        df['价格'] = pd.to_numeric(df['价格'], errors='coerce')
                        df = df.sort_values('日期', ascending=False).reset_index(drop=True)
                        # 回显成功读取到的ETF数据信息
                        latest_date = df['日期'].iloc[0]
                        latest_price = df['价格'].iloc[0]
                        print(f"  [OK] 成功读取{symbol}数据，最新日期: {latest_date}，最新价格: {latest_price}")
                        return df.head(max_records)
            print(f"  [ERROR] 未能从新浪获取 {symbol} 有效数据")
            return None
        except Exception as e:
            print(f"  [ERROR] 请求新浪美股数据失败: {e}")
            return None
    
    def get_futures_settlement_data(self):
        """从新浪获取期货结算价数据"""
        print("\n=== 从新浪获取期货结算价数据 ===")
        
        futures_data = data_fetcher.get_futures_settlement_data()
        
        # 打印获取的数据
        for fut in futures_data:
            print(f"  [OK] {fut['symbol']} 结算价: {fut['settle']}")
        
        return futures_data
    
    def _is_data_complete(self, df, date_str, columns):
        """公用判断函数：检查指定日期行的某些列是否全有非空且大于0的值"""
        if date_str not in df['日期'].values: return False
        row = df[df['日期'] == date_str].iloc[0]
        for col in columns:
            if col not in df.columns: return False
            val = row.get(col)
            if pd.isna(val) or val == '' or (isinstance(val, (int, float)) and val <= 0): return False
        return True

    def update_basic_file(self):
        """更新basic文件，包括调用LOF013获取校准值和从新浪获取数据"""
        print("\n=== 更新basic文件 ===")
        
        # 读取basic文件
        basic_file = os.path.join(self.data_path, "GLD_USO_basic_data.csv")
        if not os.path.exists(basic_file):
            print("  [ERROR] basic文件不存在")
            return False
        
        # 读取现有数据
        combined_df = pd.read_csv(basic_file, encoding='utf-8-sig')
        # 确保日期列是字符串类型
        combined_df['日期'] = combined_df['日期'].astype(str)
        
        # 统一日期格式为YYYY-MM-DD
        def unify_date_format(date_str):
            if '/' in date_str:
                parts = date_str.split('/')
                if len(parts) == 3:
                    year, month, day = parts
                    if len(year) == 4 and len(month) <= 2 and len(day) <= 2:
                        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            return date_str
        combined_df['日期'] = combined_df['日期'].apply(unify_date_format)
        
        # ====== 核心修复：一次性彻底清理历史残留的"价格"列，并自动落库 ======
        cols_to_drop = []
        for col in list(combined_df.columns):
            if col.endswith('价格') and col != '人民币中间价':
                base_sym = col.replace('价格', '')
                if base_sym in ['GLD', 'USO']:
                    # 坚决丢弃新浪的GLD和USO，保护Woody原汁原味数据
                    cols_to_drop.append(col)
                elif base_sym in combined_df.columns:
                    # 填补标准列空洞 (如 XOP价格 -> XOP)
                    combined_df[base_sym] = combined_df[base_sym].fillna(combined_df[col])
                    cols_to_drop.append(col)
                else:
                    # 直接重命名为标准列
                    combined_df.rename(columns={col: base_sym}, inplace=True)
        
        if cols_to_drop:
            combined_df.drop(columns=cols_to_drop, inplace=True)
        # ====================================================================
        
        # 检查是否已有今天的数据 (注释掉拦截：011更新汇率后今天这行已存在，直接return会跳过所有ETF补漏逻辑)
        today = datetime.now().strftime('%Y-%m-%d')
        if today in combined_df['日期'].values:
            print(f"  [INFO] basic文件已有 {today} 基础行(011已写入汇率)，继续往下执行ETF空洞检查...")
            # return True  <-- 必须注释掉这里！否则后续的 Woody 和 新浪兜底都会被截断！
        
        # 确定需要检查完整性的目标日期（T日），即最新需要估值的交易日
        if self.is_trading_day(today):
            target_date = today
        else:
            target_date = self.get_latest_a_share_trading_day().strftime('%Y-%m-%d')
            
        # 准确计算 T-1 日（用于期货、指数和美股ETF的基准对齐）
        t_minus_1_date = datetime.strptime(target_date, '%Y-%m-%d').date()
        for _ in range(10):
            t_minus_1_date = t_minus_1_date - timedelta(days=1)
            if self.is_trading_day(t_minus_1_date.strftime('%Y-%m-%d')):
                break
        t_minus_1_str = t_minus_1_date.strftime('%Y-%m-%d')

        if target_date not in combined_df['日期'].values:
            new_row = pd.DataFrame({'日期': [target_date]})
            combined_df = pd.concat([new_row, combined_df], ignore_index=True)
        if t_minus_1_str not in combined_df['日期'].values:
            new_row_t1 = pd.DataFrame({'日期': [t_minus_1_str]})
            combined_df = pd.concat([new_row_t1, combined_df], ignore_index=True)

        # 1. 调用LOF013获取大宗商品校准值和日期 (仅当 T-1 日缺失时才去爬取网页)
        need_fetch_calib = True
        if '黄金校准' in combined_df.columns and '原油校准' in combined_df.columns:
            target_row = combined_df[combined_df['日期'] == t_minus_1_str]
            if not target_row.empty:
                val_gold = target_row['黄金校准'].values[0]
                val_oil = target_row['原油校准'].values[0]
                if pd.notna(val_gold) and val_gold > 0 and pd.notna(val_oil) and val_oil > 0:
                    need_fetch_calib = False
                    print(f"  [INFO] basic文件已有 {t_minus_1_str} 的黄金和原油校准值，跳过 Woody  网页爬取")
                    
        if need_fetch_calib:
            calibration_values = self.woody_crawler.get_future_calibration_values()
            if calibration_values:
                # 处理黄金校准值
                if 'gold' in calibration_values and 'gold_date' in calibration_values:
                    gold_date = calibration_values['gold_date']
                    gold_calib = calibration_values['gold']
                    
                    # 检查是否已有该日期的记录
                    if gold_date not in combined_df['日期'].values:
                        # 插入新行
                        new_row = pd.DataFrame({'日期': [gold_date]})
                        combined_df = pd.concat([new_row, combined_df], ignore_index=True)
                    # 更新黄金校准值
                    combined_df.loc[combined_df['日期'] == gold_date, '黄金校准'] = gold_calib
                
                # 处理原油校准值
                if 'oil' in calibration_values and 'oil_date' in calibration_values:
                    oil_date = calibration_values['oil_date']
                    oil_calib = calibration_values['oil']
                    
                    # 检查是否已有该日期的记录
                    if oil_date not in combined_df['日期'].values:
                        # 插入新行
                        new_row = pd.DataFrame({'日期': [oil_date]})
                        combined_df = pd.concat([new_row, combined_df], ignore_index=True)
                    # 更新原油校准值
                    combined_df.loc[combined_df['日期'] == oil_date, '原油校准'] = oil_calib
        
        # 2. 从新浪获取数据
        print("\n=== 从新浪获取数据 ===")
        
        # 获取期货结算价
        need_fetch_futures = True
        futures_cols = ['GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle']
        if all(col in combined_df.columns for col in futures_cols):
            target_row = combined_df[combined_df['日期'] == t_minus_1_str]
            if not target_row.empty:
                if all(pd.notna(target_row[col].values[0]) for col in futures_cols):
                    need_fetch_futures = False
                    print(f"  [INFO] basic文件已有 {t_minus_1_str} 的期货结算价，跳过新浪爬取")
                    
        if need_fetch_futures:
            futures_data = self.get_futures_settlement_data()
            for fut in futures_data:
                symbol = fut['symbol']
                settle = fut['settle']
                col_name = f"{symbol}_settle"
                combined_df.loc[combined_df['日期'] == t_minus_1_str, col_name] = settle
        
        
        # ==========================================
        # 新增：从Woody网页获取ETF历史数据补充 (特别是区域变种如 ^GLD-EU 等)
        # ==========================================
        print("\n=== 获取Woody网页ETF数据补充 (区域变种锚点) ===")
        config = load_config()
        required_etfs = set()
        if config:
            for fund in config.get('funds', []):
                for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                    sym = item.get('symbol')
                    if sym:
                        # 统一变种符号前缀，与 combined_df 字段对齐
                        if ('-JP' in sym or '-EU' in sym or '-HK' in sym) and not sym.startswith('^'):
                            sym = f"^{sym}"
                        required_etfs.add(sym)
        
        for etf in required_etfs:
            # 核心优化：防 Woody 狂刷。美/欧 ETF 只检查 T-1，亚盘 ETF 检查 T
            if '-JP' in etf or '-HK' in etf:
                check_date = target_date
            else:
                check_date = t_minus_1_str
                
            if 'GLD' in etf or 'USO' in etf:
                need_fetch_etf = True
                if etf in combined_df.columns:
                    target_row = combined_df[combined_df['日期'] == check_date]
                    if not target_row.empty:
                        val = target_row[etf].values[0]
                        if pd.notna(val) and val > 0:
                            need_fetch_etf = False
                            print(f"  [INFO] basic文件已有 {check_date} 的 {etf} 价格，跳过 Woody 网页爬 取")
                            
                if need_fetch_etf:
                    df_woody = self.woody_crawler.fetch_woody_historical_data(etf, max_records=5)
                    if df_woody is not None and not df_woody.empty:
                        if etf not in combined_df.columns:
                            combined_df[etf] = None
                        
                        for _, row_etf in df_woody.iterrows():
                            us_date = row_etf['日期']
                            etf_price = row_etf['价格']
                            
                            # 取消时差偏移，直接将字面日期作为 A 股的基准同行日期
                            mapped_a_share_date = us_date
                            
                            if mapped_a_share_date:
                                if mapped_a_share_date not in combined_df['日期'].values:
                                    new_row_df = pd.DataFrame({'日期': [mapped_a_share_date]})
                                    combined_df = pd.concat([new_row_df, combined_df], ignore_index=True)
                                
                                current_val = combined_df.loc[combined_df['日期'] == mapped_a_share_date, etf]
                                if current_val.empty or pd.isna(current_val.values[0]) or current_val.values[0] == 0:
                                    combined_df.loc[combined_df['日期'] == mapped_a_share_date, etf] = etf_price
                                    print(f"  [Woody补漏] 成功填补 {mapped_a_share_date} 的 {etf} 价格: {etf_price} (源自美股 {us_date})")

        # ==========================================
        # 新增：从新浪获取标准ETF与指数数据兜底 (防止API缺失导致估值断层)
        # ==========================================
        print("\n=== 获取标准ETF与指数数据兜底(新浪) ===")
        # 核心隔离逻辑：剔除 GLD 和 USO，坚决不从新浪爬取这两只大宗本尊，避免覆盖Woody官方数据
        etfs_to_fetch = ['SPY', 'QQQ', 'SLV', 'XOP', 'XBI', '.INX', '.NDX']
        for etf in etfs_to_fetch:
            check_date_sina = t_minus_1_str # 标准美股 ETF 全部只对齐 T-1
            
            # 废弃“价格”后缀隔离法，新浪数据直接且干净地写入标准列 (如 XOP, SPY)
            target_col = etf
            
            need_fetch_etf = True
            if target_col in combined_df.columns:
                target_row = combined_df[combined_df['日期'] == check_date_sina]
                if not target_row.empty:
                    val = target_row[target_col].values[0]
                    if pd.notna(val) and val > 0:
                        need_fetch_etf = False
                        print(f"  [INFO] basic文件已有 {check_date_sina} 的 {target_col}，跳过新浪爬 取")
                        
            if need_fetch_etf:
                df_etf = self.fetch_sina_us_stock_historical_data(etf, max_records=5)
                if df_etf is not None and not df_etf.empty:
                    # 确保列存在
                    if target_col not in combined_df.columns:
                        combined_df[target_col] = None
                        
                    for _, row_etf in df_etf.iterrows():
                        us_date = row_etf['日期']
                        etf_price = row_etf['价格']
                        
                        # 取消时差偏移，直接将字面日期作为 A 股的基准同行日期
                        mapped_a_share_date = us_date
                        
                        if mapped_a_share_date:
                            if mapped_a_share_date not in combined_df['日期'].values:
                                new_row_df = pd.DataFrame({'日期': [mapped_a_share_date]})
                                combined_df = pd.concat([new_row_df, combined_df], ignore_index=True)
                            
                            # 检查当前值，如果为空或为0，则执行强力补漏
                            current_val = combined_df.loc[combined_df['日期'] == mapped_a_share_date, target_col]
                            if current_val.empty or pd.isna(current_val.values[0]) or current_val.values[0] == 0:
                                combined_df.loc[combined_df['日期'] == mapped_a_share_date, target_col] = etf_price
                                print(f"  [补漏] 成功填补 {mapped_a_share_date} 的 {target_col}: {etf_price} (源自美股 {us_date})")

        # 去重，确保每个日期只有一行
        combined_df = combined_df.drop_duplicates(subset=['日期'], keep='first')
        
        # 按日期降序排序
        combined_df['日期'] = pd.to_datetime(combined_df['日期'], errors='coerce')
        combined_df = combined_df.sort_values('日期', ascending=False)
        combined_df['日期'] = combined_df['日期'].dt.strftime('%Y-%m-%d')
        
        # 保存回basic文件
        try:
            combined_df.to_csv(basic_file, index=False, encoding='utf-8-sig')
            print(f"  [OK] 成功更新basic文件: {basic_file}")
            return True
        except Exception as e:
            print(f"  [ERROR] 保存basic文件失败: {e}")
            return False
    
    def fetch_official_exchange_rate(self, date):
        """从国家外汇管理局获取指定日期的人民币中间价"""
        print("正在访问外汇管理局汇率API...")
        
        # 使用公共数据获取模块获取汇率
        exchange_rate_data = data_fetcher.fetch_official_exchange_rate(date)
        
        if exchange_rate_data:
            print(f"外汇管理局响应状态码: 200")
            print(f"\n=== 解析JSON数据 ===")
            print(f"汇率数据日期: {exchange_rate_data['日期']}")
            print(f"人民币中间价: {exchange_rate_data['人民币中间价']}")
            print(f"\n[OK] 找到美元兑人民币汇率: {exchange_rate_data['人民币中间价']} (日期: {exchange_rate_data['日期']})")
            return exchange_rate_data
        else:
            print("\n[ERROR] 未能获取汇率数据")
            return None
    
    def fetch_lof_history_data(self, fund_code, start_date=None, need_fetch_nav_data=True, need_fetch_price_data=True):
        """从东财获取LOF基金历史净值数据, 从新浪获取LOF基金历史收盘价格数据"""
        # 计算日期范围
        end_date = datetime.now().date()
        if start_date is None:
            # 恢复日常模式：如果没有提供start_date，默认获取过去30天的数据
            start_date = (datetime.now() - timedelta(days=30)).date()
        start_date_str = start_date.strftime('%Y-%m-%d')
        end_date_str = end_date.strftime('%Y-%m-%d')
        print(f"获取数据，从 {start_date_str} 到 {end_date_str}")
        
        # 构建净值字典
        nav_dict = {}
        
        # 首先获取净值数据（如果需要）
        if need_fetch_nav_data:
            print(f"=== 开始从东财获取LOF基金 {fund_code} 历史净值数据 ===")
            
            # 使用公共数据获取模块获取净值数据
            nav_dict = data_fetcher.fetch_lof_nav_data(fund_code)
            
            print(f"[OK] 成功获取到 {len(nav_dict)} 条净值记录！")
        

        
        # 然后获取历史交易价格数据（从新浪API获取）
        # 无论是否获取到净值数据，只要需要获取价格数据，就从新浪获取
        if need_fetch_price_data:
            try:
                # 使用公共数据获取模块获取LOF价格数据
                price_df = data_fetcher.fetch_lof_price_data(fund_code)
                
                if price_df is not None:
                    # 解析新浪历史数据
                    lof_data = []
                    date_set = set()  # 用于跟踪已处理的日期
                    
                    for idx, row in price_df.iterrows():
                        date = row['日期']
                        close = row['LOF交易价格']
                        
                        # 跳过已经处理过的日期
                        if date in date_set:
                            continue
                        date_set.add(date)
                        
                        # 跳过非交易日
                        if not self.is_trading_day(date):
                            continue
                        
                        # 从净值字典中获取对应日期的净值
                        nav = nav_dict.get(date)
                        
                        lof_data.append({
                            '日期': date,
                            'LOF交易价格': close,  # 历史收盘价
                            'LOF净值': nav
                        })
                    
                    # 补齐有净值但没有收盘价的早期数据
                    for date, nav in nav_dict.items():
                        if date not in date_set:
                            if self.is_trading_day(date):
                                lof_data.append({
                                    '日期': date,
                                    'LOF交易价格': None,
                                    'LOF净值': nav
                                })

                    if lof_data:
                        # 转换为DataFrame
                        df = pd.DataFrame(lof_data)
                        # 按日期排序（降序）
                        df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                        df = df.sort_values('日期', ascending=False)
                        # 保留完整的日期格式，包含年份
                        df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                        
                        print(f"SUCCESS: 成功获取LOF基金 {fund_code} 历史数据，共{len(df)}条记录")
                        print(df.head())
                        return df
                    else:
                        print(f"警告: 新浪返回的数据为空，尝试使用净值数据")
                        # 如果新浪数据为空，尝试使用净值数据
                        if nav_dict:
                            # 转换为DataFrame
                            lof_data = []
                            for date, nav in nav_dict.items():
                                lof_data.append({
                                    '日期': date,
                                    'LOF交易价格': None,  # 交易价格为空
                                    'LOF净值': nav
                                })
                            df = pd.DataFrame(lof_data)
                            # 按日期排序（降序）
                            df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                            df = df.sort_values('日期', ascending=False)
                            # 保留完整的日期格式，包含年份
                            df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                            
                            print(f"SUCCESS: 成功获取LOF基金 {fund_code} 历史净值数据，共{len(df)}条记录")
                            print(df.head())
                            return df
                        else:
                            print(f"ERROR: 无法获取LOF基金 {fund_code} 历史数据")
                            return None
                else:
                    print(f"ERROR: 新浪返回的数据格式不正确")
                    # 即使新浪返回格式不正确，也尝试使用净值数据
                    if nav_dict:
                        # 转换为DataFrame
                        lof_data = []
                        for date, nav in nav_dict.items():
                            lof_data.append({
                                '日期': date,
                                'LOF交易价格': None,  # 交易价格为空
                                'LOF净值': nav
                            })
                        df = pd.DataFrame(lof_data)
                        # 按日期排序（降序）
                        df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                        df = df.sort_values('日期', ascending=False)
                        # 保留完整的日期格式，包含年份
                        df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                        
                        print(f"SUCCESS: 成功获取LOF基金 {fund_code} 历史净值数据，共{len(df)}条记录")
                        print(df.head())
                        return df
                    else:
                        return None
            except Exception as e:
                print(f"ERROR: 获取LOF基金历史数据出错: {e}")
                import traceback
                traceback.print_exc()
                # 即使出错，也尝试使用净值数据
                if nav_dict:
                    # 转换为DataFrame
                    lof_data = []
                    for date, nav in nav_dict.items():
                        lof_data.append({
                            '日期': date,
                            'LOF交易价格': None,  # 交易价格为空
                            'LOF净值': nav
                        })
                    df = pd.DataFrame(lof_data)
                    # 按日期排序（降序）
                    df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                    df = df.sort_values('日期', ascending=False)
                    # 保留完整的日期格式，包含年份
                    df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                    
                    print(f"SUCCESS: 成功获取LOF基金 {fund_code} 历史净值数据，共{len(df)}条记录")
                    print(df.head())
                    return df
                else:
                    # 无法获取数据
                    return None
        else:
            # 如果不需要获取交易价格数据，只返回净值数据
            if nav_dict:
                # 转换为DataFrame
                lof_data = []
                for date, nav in nav_dict.items():
                    lof_data.append({
                        '日期': date,
                        'LOF交易价格': None,  # 交易价格为空
                        'LOF净值': nav
                    })
                df = pd.DataFrame(lof_data)
                # 按日期排序（降序）
                df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                df = df.sort_values('日期', ascending=False)
                # 保留完整的日期格式，包含年份
                df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                
                print(f"SUCCESS: 成功获取LOF基金 {fund_code} 历史净值数据，共{len(df)}条记录")
                print(df.head())
                return df
            else:
                print(f"ERROR: 无法获取LOF基金 {fund_code} 历史数据")
                return None
    
    def calculate_static_valuation(self, lof_df, basic_df, futures_df, fund_code, config):
        """计算静态官方估值并生成扩展后的LOF历史数据文件"""
        # 检查lof_df是否为空或没有'日期'列
        if lof_df.empty or '日期' not in lof_df.columns:
            return None
        
        # 检查basic_df是否为空或没有'日期'列
        if basic_df.empty or '日期' not in basic_df.columns:
            return None
        
        # 调试：查看basic_df中的列名
        print(f"basic_df中的列名: {list(basic_df.columns)}")
        print(f"basic_df是否包含黄金校准: {'黄金校准' in basic_df.columns}")
        print(f"basic_df是否包含原油校准: {'原油校准' in basic_df.columns}")
        
        # 确保日期格式正确
        lof_df['日期'] = pd.to_datetime(lof_df['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
        basic_df['日期'] = pd.to_datetime(basic_df['日期'], errors='coerce').dt.strftime('%Y-%m-%d')
        
        # 重新加载配置文件，确保获取最新的配置
        config = load_config()
        
        # 从配置文件中获取对冲组合和仓位数据
        hedging_portfolio = []
        future_hedging = []
        equity_ratio = 100  # 默认仓位100%
        idx_url = ""
        idx_sym = None
        if config:
            funds = config.get('funds', [])
            for fund in funds:
                fund_code_config = fund.get('code')
                if str(fund_code_config) == str(fund_code):
                    hedging_portfolio = fund.get('valuation_portfolio', [])
                    future_hedging = fund.get('future_hedging', [])
                    # 获取仓位数据
                    holdings = fund.get('holdings', {}) or {}
                    equity_ratio = holdings.get('equity_ratio', 100)
                    if equity_ratio is None:
                        equity_ratio = 100
                    
                    # 💡 提前到最外层解析指数URL，防止内部抛异常导致未定义
                    idx_url = fund.get('sina_index_url', '')
                    if idx_url:
                        m = re.search(r'\.(INX|NDX|DJI)', idx_url, re.IGNORECASE)
                        idx_sym = f".{m.group(1).upper()}" if m else None
                    break
        
        # 如果配置文件中没有对冲组合，使用默认值
        if not hedging_portfolio:
            hedging_portfolio = [
                {"symbol": "GLD", "weight": 50, "anchor": "US"},
                {"symbol": "USO", "weight": 50, "anchor": "US"}
            ]

        # 核心改造：强制统一所有海外变种的符号，一律加上 ^ 前缀 (包括权重列)
        REGIONAL_VARIANTS = ['GLD-JP', 'GLD-EU', 'USO-JP', 'USO-EU', 'USO-HK']
        rename_map = {}
        for col in list(lof_df.columns):
            base_col = col.replace('权重', '').replace('^', '')
            if base_col in REGIONAL_VARIANTS:
                rename_map[col] = f"^{base_col}权重" if '权重' in col else f"^{base_col}"
        if rename_map:
            lof_df.rename(columns=rename_map, inplace=True)
            
        # 同时清洗本次配置文件中的符号，确保全流程匹配
        for item in hedging_portfolio:
            sym = item.get('symbol', '')
            if sym.replace('^', '') in REGIONAL_VARIANTS:
                item['symbol'] = f"^{sym.replace('^', '')}"
        
        # 重命名basic_df中的校准列，确保它们在合并后能够被正确识别
        basic_df_renamed = basic_df.copy()
        calibration_columns = ['黄金校准', '原油校准']
        specific_fund_columns = [f'{fund_code}校准', f'{fund_code}对冲']
        
        # 重命名校准列
        for col in calibration_columns + specific_fund_columns:
            if col in basic_df_renamed.columns:
                basic_df_renamed.rename(columns={col: f'{col}_basic'}, inplace=True)
        
        # 合并lof_df和basic_df
        merged_df = pd.merge(lof_df, basic_df_renamed, on='日期', how='outer')
        
        # 调试：查看合并后的数据框列名
        print(f"合并后的数据框列名: {list(merged_df.columns[:20])}...")
        print(f"是否包含黄金校准_basic: {'黄金校准_basic' in merged_df.columns}")
        print(f"是否包含原油校准_basic: {'原油校准_basic' in merged_df.columns}")
        
        # 对merged_df按日期降序排序，确保最新的日期在前面
        merged_df['日期'] = pd.to_datetime(merged_df['日期'], errors='coerce')
        merged_df = merged_df.sort_values('日期', ascending=False)
        merged_df['日期'] = merged_df['日期'].dt.strftime('%Y-%m-%d')
        
        # 重置索引，确保索引与排序后的行一致
        merged_df = merged_df.reset_index(drop=True)
        
        # 过滤非交易日（合并后可能包含周末数据，需要再次过滤）
        print("过滤非交易日数据...")
        merged_df['日期'] = pd.to_datetime(merged_df['日期'])
        initial_count = len(merged_df)
        merged_df = merged_df[merged_df['日期'].apply(lambda x: self.is_trading_day(x.strftime('%Y-%m-%d')) if pd.notna(x) else False)]
        filtered_count = initial_count - len(merged_df)
        if filtered_count > 0:
            print(f"已过滤 {filtered_count} 条非交易日数据")
        merged_df = merged_df.reset_index(drop=True)
        
        # 处理列名冲突，合并重复的列
        # 处理人民币中间价
        if '人民币中间价_x' in merged_df.columns and '人民币中间价_y' in merged_df.columns:
            # 优先使用basic_df中的人民币中间价（_y）
            merged_df['人民币中间价'] = merged_df['人民币中间价_y'].fillna(merged_df['人民币中间价_x'])
            merged_df = merged_df.drop(columns=['人民币中间价_x', '人民币中间价_y'])
        elif '人民币中间价_x' in merged_df.columns:
            merged_df.rename(columns={'人民币中间价_x': '人民币中间价'}, inplace=True)
        elif '人民币中间价_y' in merged_df.columns:
            merged_df.rename(columns={'人民币中间价_y': '人民币中间价'}, inplace=True)
        
        # 处理所有可能的ETF列冲突
        etf_columns = ['GLD', '^GLD-JP', '^GLD-EU', 'USO', '^USO-JP', '^USO-EU', '^USO-HK', 'SLV', 'XOP', 'XBI', 'SPY', 'QQQ']
        for etf_col in etf_columns:
            if f'{etf_col}_x' in merged_df.columns and f'{etf_col}_y' in merged_df.columns:
                # 优先使用basic_df中的数据（_y）
                merged_df[etf_col] = merged_df[f'{etf_col}_y'].fillna(merged_df[f'{etf_col}_x'])
                merged_df = merged_df.drop(columns=[f'{etf_col}_x', f'{etf_col}_y'])
            elif f'{etf_col}_x' in merged_df.columns:
                merged_df.rename(columns={f'{etf_col}_x': etf_col}, inplace=True)
            elif f'{etf_col}_y' in merged_df.columns:
                merged_df.rename(columns={f'{etf_col}_y': etf_col}, inplace=True)
        
        # 处理期货结算价列冲突
        future_columns = ['GC_settle', 'CL_settle', 'AG_settle', 'ES_settle', 'NQ_settle']
        for fut_col in future_columns:
            if f'{fut_col}_x' in merged_df.columns and f'{fut_col}_y' in merged_df.columns:
                # 优先使用basic_df中的数据（_y）
                merged_df[fut_col] = merged_df[f'{fut_col}_y'].fillna(merged_df[f'{fut_col}_x'])
                merged_df = merged_df.drop(columns=[f'{fut_col}_x', f'{fut_col}_y'])
            elif f'{fut_col}_x' in merged_df.columns:
                merged_df.rename(columns={f'{fut_col}_x': fut_col}, inplace=True)
            elif f'{fut_col}_y' in merged_df.columns:
                merged_df.rename(columns={f'{fut_col}_y': fut_col}, inplace=True)
        
        # 确保日期格式一致
        merged_df['日期'] = merged_df['日期'].dt.strftime('%Y-%m-%d')
        
        # 处理校准和对冲列
        calibration_columns = ['黄金校准', '原油校准']
        for calib_col in calibration_columns:
            # 从basic_df_renamed获取校准数据
            if f'{calib_col}_basic' in merged_df.columns:
                # 将校准数据复制到merged_df
                merged_df[calib_col] = merged_df[f'{calib_col}_basic']
                # 删除临时列
                merged_df = merged_df.drop(columns=[f'{calib_col}_basic'])
        
        # 处理特定基金的校准和对冲列
        specific_fund_columns = [f'{fund_code}校准', f'{fund_code}对冲']
        for fund_col in specific_fund_columns:
            # 从basic_df_renamed获取基金特定数据
            if f'{fund_col}_basic' in merged_df.columns:
                # 将基金特定数据复制到merged_df
                merged_df[fund_col] = merged_df[f'{fund_col}_basic']
                # 删除临时列
                merged_df = merged_df.drop(columns=[f'{fund_col}_basic'])
        
        # 对基础数据列进行极简重命名与合并（防重名引发 Series ValueError）
        for old_col, new_col in [('LOF净值', '净值'), ('LOF交易价格', '收盘价')]:
            if old_col in merged_df.columns:
                if new_col in merged_df.columns:
                    # 如果新老列同时存在，用老列填补新列的空缺，然后删掉老列
                    merged_df[new_col] = merged_df[new_col].fillna(merged_df[old_col])
                    merged_df.drop(columns=[old_col], inplace=True)
                else:
                    merged_df.rename(columns={old_col: new_col}, inplace=True)
                    
        # 终极保险：强制移除因合并产生的任何同名重复列，确保所有列名唯一
        merged_df = merged_df.loc[:, ~merged_df.columns.duplicated()]

        # 获取当前基金的类别，用于后续判断
        cat = ""
        if config:
            for f in config.get('funds', []):
                if str(f.get('code')) == str(fund_code):
                    cat = f.get('category', '')
                    break

        # 动态确立列名，消除歧义
        if cat == '黄金':
            calib_col = '黄金校准'
            hedge_col = '黄金对冲'
        elif cat == '原油':
            calib_col = '原油校准'
            hedge_col = '原油对冲'
        else:
            calib_col = f'{fund_code}校准'
            hedge_col = f'{fund_code}对冲'

        # 确保提前初始化所有将要操作的衍生列，彻底杜绝 DataFrame.at 取值时报 KeyError
        init_cols = ['仓位', 'ETF静态估值', '变化比例', 'ETF静态估值误差', 'ETF静态溢价', 
                     '期货结算价', '期货静态估值', '期货静态估值误差', '期货静态估值溢价',
                     '指数静态估值', '指数静态估值误差']
        for item in hedging_portfolio:
            if item.get('symbol'):
                init_cols.append(f"{item.get('symbol')}权重")
                
        for col in init_cols:
            if col not in merged_df.columns:
                merged_df[col] = None
        
        # 计算所有需要计算的静态官方估值，不限于最近7天
        if not merged_df.empty and '日期' in merged_df.columns:
            # 确保数据按日期降序排序
            merged_df['日期'] = pd.to_datetime(merged_df['日期'])
            merged_df = merged_df.sort_values('日期', ascending=False).reset_index(drop=True)
            
            # 只处理2026年1月1日之后的数据
            cutoff_date = pd.Timestamp('2026-01-01')
            merged_df = merged_df[merged_df['日期'] >= cutoff_date].reset_index(drop=True)
            
            # 只计算缺失估值的日期，保留历史数据
            recent_indices = []
            
            # 1. 先找最近有估值的日期
            latest_valuation_date = None
            latest_valuation_index = None
            for i, row in merged_df.iterrows():
                # 检查所有相关列是否都有值
                etf_valuation = row.get('ETF静态估值')
                change_ratio = row.get('变化比例')
                etf_error = row.get('ETF静态估值误差')
                etf_premium = row.get('ETF静态溢价')
                
                # 只有当所有相关列都有值时，才认为该日期已有完整的静态估值
                if pd.notna(etf_valuation) and pd.notna(change_ratio) and pd.notna(etf_error) and pd.notna(etf_premium):
                    latest_valuation_date = row['日期']
                    latest_valuation_index = i
                    break
            
            # 2. 确定需要计算的日期：所有在latest_valuation_index之前的日期（因为降序，之前意味着更新的日期）
            # 即：从第0行到latest_valuation_index（不包含）的所有行
            start_index = 0
            end_index = latest_valuation_index if latest_valuation_index is not None else len(merged_df)
            # 2. 强制回溯重新计算最近3天的估值，防止 011 的汇率/Woody数据更新后 012 直接跳过
            end_index = (latest_valuation_index + 3) if latest_valuation_index is not None else len(merged_df)
            end_index = min(end_index, len(merged_df))
            
            # 3. 收集需要计算的日期索引
            for i in range(start_index, end_index):
                recent_indices.append(i)
            
            # 按索引升序排序，确保从最新的日期开始计算（0是最新的）
            recent_indices.sort(reverse=False)
            
            # 如果没有需要计算的日期，直接跳过
            if not recent_indices:
                print(f"  ✅ 所有日期都已有静态估值，无需计算")
            
            # 初始化ERROR计数器和列表
            error_count = 0
            error_dates = []
            max_error_display = 3  # 最多显示3个ERROR
            
            # 然后遍历最近30天的行，计算静态官方估值
            for i in recent_indices:
                row = merged_df.loc[i]
                current_date_str = row['日期'].strftime('%Y-%m-%d')
                
                # 不跳过已有的静态官方估值，确保所有日期都能重新计算
                
                # 静态官方估值计算不需要当前LOF净值，只需要基准日期的LOF净值
                
                # 1. 基准日期有LOF净值
                # 2. 当前日期和基准日期有所有必要的ETF收盘价数据
                current_base_row = None
                current_base_date_str = None
                current_base_nav = None
                
                # 从当前日期的后一天开始，向后查找基准日期（因为数据是按日期降序排序的）
                # 限制查找范围，最多向后查找10天
                max_lookback = min(i+10, len(merged_df))
                for k in range(i+1, max_lookback):
                    potential_base_row = merged_df.iloc[k]
                    potential_base_date = potential_base_row['日期']
                    potential_base_date_str = potential_base_date.strftime('%Y-%m-%d')
                    
                    # 检查条件1：有LOF净值
                    lof_nav = potential_base_row.get('净值', 0)
                    if not (pd.notna(lof_nav) and lof_nav > 0):
                            continue
                    
                    # 检查条件2：有所有必要的ETF收盘价数据
                    has_all_etf_data = True
                    missing_etf = []
                    
                    for item in hedging_portfolio:
                        symbol = item.get('symbol')
                        if symbol in merged_df.columns:
                            etf_price = potential_base_row.get(symbol, 0)
                            if pd.isna(etf_price) or etf_price <= 0:
                                has_all_etf_data = False
                                missing_etf.append(f"{symbol} ({etf_price})")
                                break
                        else:
                            has_all_etf_data = False
                            missing_etf.append(f"{symbol} (列不存在)")
                            break
                    
                    # 检查是否有人民币中间价数据
                    if '人民币中间价' in merged_df.columns:
                        exchange_rate = potential_base_row.get('人民币中间价', 0)
                        if pd.isna(exchange_rate) or exchange_rate <= 0:
                            has_all_etf_data = False
                            missing_etf.append(f"人民币中间价 ({exchange_rate})")
                    else:
                        has_all_etf_data = False
                        missing_etf.append("人民币中间价 (列不存在)")
                    
                    if not has_all_etf_data:
                        continue
                    
                    # 如果两个条件都满足，选择为当前日期的基准日期
                    current_base_row = potential_base_row
                    current_base_date_str = potential_base_date
                    current_base_nav = potential_base_row['净值']
                    break
                
                # 计算静态官方估值
                try:
                    # 检查是否找到基准日期
                    if current_base_row is None:
                        error_count += 1
                        error_dates.append(current_date_str)
                        # 只显示前3个ERROR
                        if error_count <= max_error_display:
                            print(f"ERROR: 日期 {current_date_str}: 未找到满足条件的基准日期，无法计算估值")
                            # 增加具体的 Debug 输出帮助定位
                            print(f"  --> Debug {fund_code}: 为了计算 {current_date_str}，向前寻找基准日失败。")
                            print(f"  --> 检查当前日 {current_date_str} 是否有汇率: {row.get('人民币中间价', '无')}")
                            for item in hedging_portfolio:
                                sym = item.get('symbol')
                                print(f"  --> 检查当前日 {current_date_str} 是否有 {sym}: {row.get(sym, '无')}")
                            print(f"  --> 请检查 T-1 日是否缺少 '净值'，或者 T-1 日缺少 '人民币中间价'。")
                        # 不设置为None，保持字段为空
                        pass
                    else:
                        # 初始化变量
                        price_factor = 0.0
                        weight_sum = 0.0
                        
                        # 既然找到了基准日并准备计算，在此处为本行(T日)填充仓位、权重等基准属性
                        # 这保证了未收盘的T日(如4-10)绝对不会出现这些多余的数据
                        merged_df.at[i, '仓位'] = equity_ratio
                        for item in hedging_portfolio:
                            sym_w = item.get('symbol')
                            w_val = item.get('weight', 0)
                            merged_df.at[i, f"{sym_w}权重"] = w_val
                            
                        current_equity_ratio = equity_ratio if equity_ratio is not None else 100
                        if current_equity_ratio < 10:
                            current_equity_ratio = current_equity_ratio * 100
                        equity_ratio_float = current_equity_ratio / 100.0  # 转换为小数
                        
                        # 获取基准日期和当前日期的汇率
                        base_exchange_rate = current_base_row.get('人民币中间价', 1.0)
                        current_exchange_rate = row.get('人民币中间价', 1.0)
                        
                        # 计算汇率变化率
                        exchange_rate_change = 1.0
                        if base_exchange_rate > 0 and current_exchange_rate > 0:
                            exchange_rate_change = current_exchange_rate / base_exchange_rate
                        
                        # 遍历对冲组合，计算价格因子
                        valid_etf_count = 0
                        etf_price_info = []
                        
                        for item in hedging_portfolio:
                            symbol = item.get('symbol')
                            weight = item.get('weight', 100.0) / 100.0  # 转换为小数
                            weight_sum += weight
                            
                            if symbol in merged_df.columns:
                                base_price = current_base_row.get(symbol, 0)
                                current_price = row.get(symbol, 0)
                                etf_price_info.append(f"{symbol}: 基准={base_price}, 当前={current_price}")
                                if base_price > 0 and current_price > 0:
                                    price_factor += (current_price / base_price) * weight
                                    valid_etf_count += 1
                            else:
                                etf_price_info.append(f"{symbol}: 列不存在")
                        
                        # 计算ETF价格信息和相关因子
                        
                        # 初始化变量
                        etf_static_valuation = None
                        
                        # 只有当有所有ETF数据时才计算静态官方估值
                        if valid_etf_count == len(hedging_portfolio) and weight_sum > 0:
                            # 检查当前日期是否有所有必要的ETF数据
                            current_has_all_etf_data = True
                            for item in hedging_portfolio:
                                symbol = item.get('symbol')
                                
                                if symbol in merged_df.columns:
                                    current_price = row.get(symbol, 0)
                                    if current_price <= 0:
                                        current_has_all_etf_data = False
                                        break
                                else:
                                    current_has_all_etf_data = False
                                    break
                            
                            # 只有当当前日期也有所有ETF数据时，才计算静态官方估值
                            if current_has_all_etf_data:
                                # 价格因子 = Σ[(当前ETF价格 / 基准ETF价格) * 权重] （权重已经是小数）
                                
                                # 计算净值变化比例
                                # 公式：净值变化比例 = 仓位 * (price_factor * exchange_rate_change - 1)
                                net_value_change_ratio = equity_ratio_float * (price_factor * exchange_rate_change - 1)
                                
                                # 计算静态官方估值
                                # 公式：静态官方估值 = 基准日期净值 * (1 + 净值变化比例)
                                etf_static_valuation = current_base_nav * (1 + net_value_change_ratio)
                                
                                # 计算变化比例（格式化为百分比）
                                change_ratio_percent = net_value_change_ratio * 100
                                
                                # 保留4位小数
                                merged_df.at[i, 'ETF静态估值'] = round(etf_static_valuation, 4)
                                # 保留4位小数的百分比
                                merged_df.at[i, '变化比例'] = f"{change_ratio_percent:.4f}%"
                            else:
                                # 不设置为None，保持字段为空
                                pass
                        else:
                            # 不设置为None，保持字段为空
                            pass
                        
                        # 如果没有计算出ETF静态估值，尝试从DataFrame中获取
                        if etf_static_valuation is None:
                            etf_static_valuation = merged_df.at[i, 'ETF静态估值']
                        
                        # 计算静态官方估值误差
                        if '净值' in merged_df.columns:
                            lof_nav = row.get('净值')
                            
                            # 检查净值是否有效
                            if pd.notna(lof_nav) and lof_nav > 0:
                                # 尝试将ETF静态估值转换为数字类型
                                try:
                                    etf_static_valuation = float(etf_static_valuation)
                                    if pd.notna(etf_static_valuation):
                                        error = (etf_static_valuation - lof_nav) / lof_nav
                                        # 格式化为百分比，保留2位小数
                                        merged_df.at[i, 'ETF静态估值误差'] = f"{error:.2%}"
                                    else:
                                        merged_df.at[i, 'ETF静态估值误差'] = None
                                except (ValueError, TypeError):
                                    merged_df.at[i, 'ETF静态估值误差'] = None
                            else:
                                merged_df.at[i, 'ETF静态估值误差'] = None
                        else:
                            merged_df.at[i, 'ETF静态估值误差'] = None
                        
                        # 计算静态溢价（基于LOF交易价格与静态官方估值的差值）
                        if '收盘价' in merged_df.columns:
                            lof_price = row.get('收盘价', 0)
                            if pd.notna(lof_price) and lof_price > 0:
                                # 尝试将ETF静态估值转换为数字类型
                                try:
                                    etf_static_valuation = float(etf_static_valuation)
                                    if pd.notna(etf_static_valuation) and etf_static_valuation > 0:
                                        static_premium = (lof_price - etf_static_valuation) / etf_static_valuation
                                        # 格式化为百分比，保留2位小数
                                        merged_df.at[i, 'ETF静态溢价'] = f"{static_premium:.2%}"
                                    else:
                                        merged_df.at[i, 'ETF静态溢价'] = None
                                except (ValueError, TypeError):
                                    merged_df.at[i, 'ETF静态溢价'] = None
                            else:
                                merged_df.at[i, 'ETF静态溢价'] = None
                        else:
                            merged_df.at[i, 'ETF静态溢价'] = None
                            
                        # ==========================================
                        # 新增：计算纯指数静态估值 (专属双轨制)
                        # ==========================================
                        if idx_sym and idx_sym in merged_df.columns:
                            base_idx_price = current_base_row.get(idx_sym, 0)
                            curr_idx_price = row.get(idx_sym, 0)
                            if pd.notna(base_idx_price) and base_idx_price > 0 and pd.notna(curr_idx_price) and curr_idx_price > 0:
                                idx_change = curr_idx_price / base_idx_price
                                equity_ratio = row.get('仓位', 100)
                                if pd.isna(equity_ratio) or equity_ratio is None:
                                    equity_ratio = 100
                                if float(equity_ratio) < 10: equity_ratio = float(equity_ratio) * 100
                                equity_ratio_float = float(equity_ratio) / 100.0
                                
                                idx_net_change_ratio = equity_ratio_float * (idx_change * exchange_rate_change - 1)
                                idx_static_valuation = current_base_nav * (1 + idx_net_change_ratio)
                                merged_df.at[i, '指数静态估值'] = round(idx_static_valuation, 4)
                                
                                if '净值' in merged_df.columns:
                                    lof_nav = row.get('净值', 0)
                                    if pd.notna(lof_nav) and lof_nav > 0:
                                        idx_error = (idx_static_valuation - lof_nav) / lof_nav
                                        merged_df.at[i, '指数静态估值误差'] = f"{idx_error:.2%}"
                            
                        # ==========================================
                        # 新增：计算纯期货静态估值
                        # ==========================================
                        if future_hedging:
                            fut_item = future_hedging[0]
                            raw_symbol = fut_item.get('symbol', '')
                            # 映射到 basic_data.csv 的列名
                            mapping = {'MGC': 'GC', 'MCL': 'CL', 'Ag': 'AG', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC'}
                            base_fut_sym = mapping.get(raw_symbol, raw_symbol)
                            fut_col = f"{base_fut_sym}_settle"
                            
                            beta = fut_item.get('beta', 1.0)
                            
                            # 初始化变量
                            fut_static_valuation = None
                            
                            if fut_col in merged_df.columns:
                                # 读取期货结算价并保存
                                current_fut_price = row.get(fut_col, 0)
                                if pd.notna(current_fut_price) and current_fut_price > 0:
                                    # 直接存入浮点数
                                    merged_df.at[i, '期货结算价'] = float(current_fut_price)
                                else:
                                    merged_df.at[i, '期货结算价'] = None  # 强力清除历史遗留脏数据
                                
                                base_fut_price = current_base_row.get(fut_col, 0)
                                current_fut_price = row.get(fut_col, 0)
                                
                                if pd.notna(base_fut_price) and base_fut_price > 0 and pd.notna(current_fut_price) and current_fut_price > 0:
                                    fut_change = current_fut_price / base_fut_price
                                    # 提取仓位
                                    equity_ratio = row.get('仓位', 100)
                                    if pd.isna(equity_ratio) or equity_ratio is None:
                                        equity_ratio = 100
                                    if float(equity_ratio) < 10: equity_ratio = float(equity_ratio) * 100
                                    equity_ratio_float = float(equity_ratio) / 100.0
                                    
                                    # 核心公式：T日估值 = T-1日净值 * [1 + 仓位 * (T日期货/T-1日期货 * 汇率变动 - 1)]
                                    fut_net_change_ratio = equity_ratio_float * (fut_change * exchange_rate_change - 1)
                                    fut_static_valuation = current_base_nav * (1 + fut_net_change_ratio)
                                    
                                    merged_df.at[i, '期货静态估值'] = round(fut_static_valuation, 4)
                            
                            # 如果没有计算出期货静态估值，尝试从DataFrame中获取
                            if fut_static_valuation is None:
                                fut_static_valuation = merged_df.at[i, '期货静态估值']
                            
                            # 计算误差
                            if '净值' in merged_df.columns:
                                lof_nav = row.get('净值', 0)
                                if pd.notna(lof_nav) and lof_nav > 0:
                                    # 尝试将期货静态估值转换为数字类型
                                    try:
                                        fut_static_valuation = float(fut_static_valuation)
                                        if pd.notna(fut_static_valuation):
                                            fut_error = (fut_static_valuation - lof_nav) / lof_nav
                                            merged_df.at[i, '期货静态估值误差'] = f"{fut_error:.2%}"
                                        else:
                                            merged_df.at[i, '期货静态估值误差'] = None
                                    except (ValueError, TypeError):
                                        merged_df.at[i, '期货静态估值误差'] = None
                            
                            # 计算期货静态估值溢价（收盘价/期货静态估值 - 1）
                            if '收盘价' in merged_df.columns:
                                close_price = row.get('收盘价', 0)
                                if pd.notna(close_price) and close_price > 0:
                                    # 尝试将期货静态估值转换为数字类型
                                    try:
                                        fut_static_valuation = float(fut_static_valuation)
                                        if pd.notna(fut_static_valuation) and fut_static_valuation > 0:
                                            fut_premium = (close_price / fut_static_valuation - 1)
                                            merged_df.at[i, '期货静态估值溢价'] = f"{fut_premium:.2%}"
                                        else:
                                            merged_df.at[i, '期货静态估值溢价'] = None
                                    except (ValueError, TypeError):
                                        merged_df.at[i, '期货静态估值溢价'] = None
                        

                except Exception as e:
                    print(f"计算静态官方估值时出错: {e}")
                    import traceback
                    traceback.print_exc()
                    merged_df.at[i, 'ETF静态估值'] = None
                    merged_df.at[i, '变化比例'] = None
                    merged_df.at[i, 'ETF静态估值误差'] = None
                    merged_df.at[i, 'ETF静态溢价'] = None
            
            # 打印ERROR统计信息
            if error_count > 0:
                print(f"统计: 共有 {error_count} 个日期无法计算静态官方估值")
                if error_count > max_error_display:
                    print(f"已显示前 {max_error_display} 个ERROR，其余 {error_count - max_error_display} 个ERROR已省略")
        
        # 构建需要的列列表
        required_columns = [
            '日期', '人民币中间价', '仓位', '收盘价', '净值', 
            '变化比例', 'ETF静态估值', 'ETF静态估值误差', 'ETF静态溢价'
        ]
        
        # 添加ETF相关列
        for item in hedging_portfolio:
            symbol = item.get('symbol')
            required_columns.append(symbol)
            required_columns.append(f"{symbol}权重")
            
        # 将纯指数列追加到表里 (如果有)
        if idx_url and idx_sym:
            required_columns.extend([idx_sym, '指数静态估值', '指数静态估值误差'])
            
        # 物理对冲属性将在后续处理中添加，这里不再添加

        # 将期货相关列追加到表格，只有有期货的LOF才添加
        if future_hedging:
            required_columns.extend([
                '期货结算价', '期货静态估值', '期货静态估值误差', '期货静态估值溢价'
            ])
        
        # 处理列
        actual_columns = []
        try:
            # 定义数值型列
            numeric_columns = ['期货结算价', '期货静态估值']
            
            for col in required_columns:
                if col in merged_df.columns:
                    # 如果列已存在，检查是否需要转换为数值类型
                    if col in numeric_columns:
                        # 尝试将列转换为浮点数类型
                        try:
                            merged_df[col] = pd.to_numeric(merged_df[col], errors='coerce')
                        except Exception:
                            pass  # 如果转换失败，保持原样
                    actual_columns.append(col)
                else:
                    # 如果列不存在，添加该列并设置为NaN
                    # 对于数值型列，使用float类型；对于其他列，使用object类型
                    if col in numeric_columns:
                        merged_df[col] = pd.Series(dtype='float64')
                    else:
                        merged_df[col] = None
                    actual_columns.append(col)
            
            merged_df = merged_df[actual_columns]
        except Exception as e:
            print(f"处理列时出错: {e}")
            # 如果出错，使用所有实际存在的列
            actual_columns = list(merged_df.columns)
            # 保留人民币中间价列，以便在监控报表中显示
            merged_df = merged_df[actual_columns]
        
        # 排序回日期降序，保持与原来相同的输出格式
        merged_df = merged_df.sort_values('日期', ascending=False).reset_index(drop=True)
        
        return merged_df
    
    def generate_lof_history_data(self, fund_code):
        """生成LOF基金历史数据文件"""
        # 获取当前日期
        today = datetime.now().date()
        
        # 确定T日（最新的A股交易日）
        today_str = today.strftime('%Y-%m-%d')
        if self.is_trading_day(today_str):
            T = today
        else:
            T = self.get_latest_a_share_trading_day()
        
        # 计算T-1日（上一个交易日）
        T_minus_1 = T
        # 向前查找上一个交易日
        for _ in range(10):  # 最多向前查找10天
            T_minus_1 = T_minus_1 - timedelta(days=1)
            if self.is_trading_day(T_minus_1.strftime('%Y-%m-%d')):
                break
        T_minus_1_str = T_minus_1.strftime('%Y-%m-%d')
        T_str = T.strftime('%Y-%m-%d')
        
        # 1. 读取现有数据（如果存在）
        filepath = os.path.join(self.data_path, f"LOF_{fund_code}_history.csv")
        
        need_fetch_nav_data = True  # 是否需要获取净值数据
        need_fetch_price_data = True  # 是否需要获取交易价数据
        existing_df = None
        latest_date = None
        
        # 读取文件一次，复用数据
        if os.path.exists(filepath):
            try:
                existing_df = pd.read_csv(filepath, encoding='utf-8-sig')
                
                # 检查现有数据的最新日期
                if '日期' in existing_df.columns and not existing_df.empty:
                    # 转换日期列，使用format='mixed'自动推断日期格式
                    existing_df['日期'] = pd.to_datetime(existing_df['日期'], format='mixed')
                    # 获取最新日期
                    latest_date = existing_df['日期'].max().date()
                    print(f"现有数据的最新日期: {latest_date.strftime('%Y-%m-%d')}")
                    
                    # 完全去除时间锁，基于数据状态判断 (数据驱动)
                    if 'LOF交易价格' in existing_df.columns:
                        price_records = existing_df[existing_df['LOF交易价格'].notna()]
                        if not price_records.empty:
                            latest_price_date = price_records['日期'].max().date()
                            if latest_price_date >= T_minus_1:
                                need_fetch_price_data = False
                                print(f"[{fund_code}] 本地已有 T-1 日({T_minus_1_str})或更新的历史收盘价，跳过爬取。")
                            else:
                                need_fetch_price_data = True
                        else:
                            need_fetch_price_data = True
                    
                    # 基于数据状态判断净值
                    if 'LOF净值' in existing_df.columns:
                        nav_records = existing_df[existing_df['LOF净值'].notna()]
                        if not nav_records.empty:
                            latest_nav_date = nav_records['日期'].max().date()
                            if latest_nav_date >= T_minus_1:
                                need_fetch_nav_data = False
                                print(f"[{fund_code}] 本地已有 T-1 日({T_minus_1_str})或更新的历史净值，跳过爬取。")
                            else:
                                need_fetch_nav_data = True
                        else:
                            need_fetch_nav_data = True
                    else:
                        # 没有净值字段，需要去东财爬数据
                        need_fetch_nav_data = True
                else:
                    need_fetch_nav_data = True
                    need_fetch_price_data = True
            except Exception as e:
                need_fetch_nav_data = True
                need_fetch_price_data = True
        else:
            need_fetch_nav_data = True
            need_fetch_price_data = True
        
        # 2. 从东财和新浪获取数据
        lof_df = None
        if need_fetch_nav_data or need_fetch_price_data:
            # 确定开始日期
            start_date = None
            if latest_date:
                # 从最新日期的后一天开始获取数据
                start_date = latest_date + timedelta(days=1)
            else:
                # 如果没有现有数据，获取过去30天数据
                start_date = (datetime.now() - timedelta(days=30)).date()
            
            # 数据驱动：只要前面的逻辑判断缺少数据，就无视时间直接触发爬取
            if latest_date:
                # 从最后已有日期开始覆盖抓取，确保盘中残缺数据会被最终版覆盖
                start_date = latest_date
            else:
                start_date = (datetime.now() - timedelta(days=30)).date()
                
            print(f"[{fund_code}] 触发数据驱动更新，向新浪/东财提取从 {start_date} 起的缺失历史收盘价和净值...")
            lof_df = self.fetch_lof_history_data(fund_code, start_date, need_fetch_nav_data, need_fetch_price_data)
            
            # 检查lof_df是否为None
            if lof_df is None:
                lof_df = existing_df
        else:
            print(f"[{fund_code}] 本地数据已满载至最新交易日，无需发起任何网络爬取请求。")
            lof_df = existing_df
        
        # 3. 处理数据
        if lof_df is not None and not lof_df.empty and '日期' in lof_df.columns:
            # 确保日期格式正确
            lof_df['日期'] = pd.to_datetime(lof_df['日期'], format='%Y-%m-%d')
            # 去重，确保没有重复的日期
            lof_df = lof_df.drop_duplicates(subset=['日期'], keep='last')
            # 按日期排序（降序）
            lof_df = lof_df.sort_values('日期', ascending=False)
            # 保留完整的日期格式，包含年份
            lof_df['日期'] = lof_df['日期'].dt.strftime('%Y-%m-%d')
        else:
            print ( "ERROR: lof_df为空或没有'日期'列，无法处理" )
            return None
            
        # 4. 与现有数据合并（如果存在且有新数据）
        if existing_df is not None and lof_df is not existing_df:
            try:
                # 确保两个DataFrame的日期列格式一致
                lof_df['日期'] = pd.to_datetime(lof_df['日期'], format='mixed')
                
                # 合并两个DataFrame
                # 使用outer join，保留所有数据
                merged_df = pd.merge(existing_df, lof_df, on='日期', how='outer')
                
                # 处理重复的列（如果有）
                # 对于重复的列，保留新获取的数据
                for col in existing_df.columns:
                    if col != '日期' and f"{col}_x" in merged_df.columns and f"{col}_y" in merged_df.columns:
                        # 强制以新获取的数据（_y）为准，_y中没有的再用老数据（_x）兜底
                        merged_df[col] = merged_df[f"{col}_y"].fillna(merged_df[f"{col}_x"])
                        # 删除重复的列
                        merged_df = merged_df.drop(columns=[f"{col}_x", f"{col}_y"])
                
                # 去重，保留每个日期的最新数据
                merged_df = merged_df.drop_duplicates(subset=['日期'], keep='last')
                
                # 按日期降序排序
                merged_df = merged_df.sort_values('日期', ascending=False)
                # 保留完整的日期格式，包含年份
                merged_df['日期'] = merged_df['日期'].dt.strftime('%Y-%m-%d')
                
                # 使用合并后的数据
                lof_df = merged_df
            except Exception as e:
                print(f"合并数据时发生异常: {e}")
                traceback.print_exc()
        
        # 5. 加载基础数据，计算静态官方估值
        basic_filepath = os.path.join(self.data_path, "GLD_USO_basic_data.csv")
            
        if os.path.exists(basic_filepath):
            try:
                basic_df = pd.read_csv(basic_filepath, encoding='utf-8-sig')
                
                # 加载配置文件
                config = load_config()
                
                # 计算静态官方估值
                extended_lof_df = self.calculate_static_valuation(lof_df, basic_df, None, fund_code, config)
                
                # 使用扩展后的数据
                lof_df = extended_lof_df
            except Exception as e:
                print(f"计算静态官方估值时发生异常: {e}")
                traceback.print_exc()
        
        # 6. 保存数据
        if lof_df is not None:
            # 在保存文件之前，直接从basic_df合并校准数据
            try:
                # 正确获取data_dir路径
                data_dir = os.path.join(os.path.dirname(__file__), 'data')
                basic_filepath = os.path.join(data_dir, 'GLD_USO_basic_data.csv')
                if os.path.exists(basic_filepath):
                    basic_df = pd.read_csv(basic_filepath, encoding='utf-8-sig')
                    
                    fund_code_str = str(fund_code)
                    
                    # 获取当前基金的配置和类别
                    fund_config = None
                    fund_category = ''
                    if config:
                        for f in config.get('funds', []):
                            if str(f.get('code')) == fund_code_str:
                                fund_config = f
                                fund_category = f.get('category', '')
                                break
                    
                    # 确保日期格式一致
                    lof_df['日期'] = pd.to_datetime(lof_df['日期']).dt.strftime('%Y-%m-%d')
                    basic_df['日期'] = pd.to_datetime(basic_df['日期']).dt.strftime('%Y-%m-%d')
                    
                    # ==========================================
                    # 1. 合并 Woody 官方网页上披露的 "宏观大盘校准值" (仅供面板参考)
                    # ==========================================
                    if fund_category == '黄金':
                        if '黄金校准' in basic_df.columns:
                            # 从basic_df中提取黄金校准数据
                            gold_calib = basic_df[['日期', '黄金校准']]
                            # 合并到lof_df
                            lof_df = lof_df.merge(gold_calib, on='日期', how='left')
                            # 重命名为"黄金期货校准"
                            lof_df.rename(columns={'黄金校准': '黄金期货校准'}, inplace=True)
                    
                    elif fund_category == '原油':
                        if '原油校准' in basic_df.columns:
                            # 从basic_df中提取原油校准数据
                            oil_calib = basic_df[['日期', '原油校准']]
                            # 合并到lof_df
                            lof_df = lof_df.merge(oil_calib, on='日期', how='left')
                            # 重命名为"原油期货校准"
                            lof_df.rename(columns={'原油校准': '原油期货校准'}, inplace=True)

                    # ==========================================
                    # 1.5 动态合并该基金专属的 Woody API 官方校准值
                    # ==========================================
                    calib_col = f'{fund_code_str}校准'
                    if calib_col in basic_df.columns:
                        fund_calib = basic_df[['日期', calib_col]]
                        lof_df = lof_df.merge(fund_calib, on='日期', how='left')
                        lof_df.rename(columns={calib_col: f'{fund_code_str}官方校准'}, inplace=True)

                    # ==========================================
                    # 2. 通用动态计算：历史账本上的"校准值(物理兑换比)"和"对冲值"
                    # ==========================================
                    # 彻底抛弃硬编码，遍历基金配置中的估值组合 (完美兼容 161815 等混血基金)
                    etf_sum = pd.Series(0.0, index=lof_df.index)
                    if fund_config:
                        port = fund_config.get('valuation_portfolio', [])
                        for item in port:
                            sym = item.get('symbol', '').replace('^', '')
                            # 支持带 ^ 与不带 ^ 两种列名的容错
                            col_price = f"^{sym}" if f"^{sym}" in lof_df.columns else sym
                            col_weight = f"^{sym}权重" if f"^{sym}权重" in lof_df.columns else f"{sym}权重"
                            
                            if col_price in lof_df.columns and col_weight in lof_df.columns:
                                etf_sum += pd.to_numeric(lof_df[col_price], errors='coerce').fillna(0) * (pd.to_numeric(lof_df[col_weight], errors='coerce').fillna(0) / 100.0)
                    
                    nav_col = 'LOF净值' if 'LOF净值' in lof_df.columns else ('净值' if '净值' in lof_df.columns else None)
                    if nav_col and '人民币中间价' in lof_df.columns:
                        nav_series = pd.to_numeric(lof_df[nav_col], errors='coerce').replace(0, 1).fillna(1)
                        fx_series = pd.to_numeric(lof_df['人民币中间价'], errors='coerce').fillna(1)
                        lof_df['校准值'] = etf_sum * fx_series / nav_series
                    else:
                        lof_df['校准值'] = 0.0
                        
                    pos_series = pd.to_numeric(lof_df['仓位'], errors='coerce').fillna(100) / 100.0
                    lof_df['对冲值'] = lof_df['校准值'] / pos_series.replace(0, 1)

            except Exception as e:
                print(f"合并校准数据时发生异常: {e}")
                traceback.print_exc()
            
            # 截断过长历史，保留最近90个交易日的数据（约4个多月），保持文件精简
            lof_df = lof_df.head(90).copy()
            # 确保日期列是字符串格式
            lof_df['日期'] = lof_df['日期'].astype(str)
            
            # 重新排列列的顺序，确保"校准值"和"对冲值"列位于整齐合理的位置
            columns = list(lof_df.columns)
            target_index = len(columns)
            if '期货结算价' in columns: target_index = columns.index('期货结算价')
            elif 'ETF静态估值' in columns: target_index = columns.index('ETF静态估值')
                
            if '校准值' in columns:
                columns.remove('校准值')
                columns.insert(target_index, '校准值')
                target_index += 1
            if '对冲值' in columns:
                columns.remove('对冲值')
                columns.insert(target_index, '对冲值')
                
            lof_df = lof_df[columns]

            try:
                lof_df.to_csv(filepath, index=False, encoding='utf-8-sig')
            except PermissionError as e:
                print(f"  [ERROR] 保存文件失败: {e}")
                print(f"  💡 提示: 文件 {filepath} 极可能正被 Excel 或其他程序占用，请关闭后重试！")
                temp_filepath = filepath + '.tmp'
                try:
                    lof_df.to_csv(temp_filepath, index=False, encoding='utf-8-sig')
                    print(f"  [ℹ️] 作为备用，数据已临时保存至: {temp_filepath}")
                except Exception:
                    pass
        
        return lof_df

def load_config():
    """加载配置文件"""
    # 获取脚本所在目录的绝对路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 构建配置文件的绝对路径
    config_file = os.path.join(script_dir, "lof_config.yaml")
    if not os.path.exists(config_file):
        print(f"配置文件不存在: {config_file}")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return None

if __name__ == "__main__":
    # 测试生成LOF基金历史数据
    generator = LofDataGenerator()
    
    # 加载LOF访问状态
    status = load_lof_access_status()
    today = datetime.now().date().strftime('%Y-%m-%d')
    
    # 检查是否需要重置状态（新的一天）
    if status['last_process_date'] != today:
        status['last_process_date'] = today
        status['processed_funds'] = {}
        save_lof_access_status(status)
        print(f"[状态文件] 新的一天，重置处理状态")
    
    # 加载配置文件
    config = load_config()
    
    # 加载API数据
    api_data = generator.load_api_data()
    
    # 分类基金
    if api_data:
        commodity_funds, pure_etf_funds, index_funds = generator.classify_funds(api_data, config)
        
    if not config:
        print("❌ 无法加载配置文件 lof_config.yaml，程序退出。")
        sys.exit(1)
        
    # 从配置文件中获取所有基金代码
    funds = config.get('funds', [])
    fund_codes = [fund.get('code') for fund in funds if fund.get('code')]
    print(f"从配置文件中获取到 {len(fund_codes)} 个基金")
    print(f"基金列表: {fund_codes}")
    
    # 先更新basic文件
    print("\n=== 开始更新basic文件 ===")
    generator.update_basic_file()
    
    # 生成每个LOF基金的历史数据文件
    for fund_code in fund_codes:
        fund_code_str = str(fund_code)
        
        
        print(f"\n=== 生成LOF基金 {fund_code} 历史数据文件 ===")
        lof_data = generator.generate_lof_history_data(fund_code)
        
        # 更新处理状态
        if lof_data is not None:
            # 检查是否成功获取了收盘价和净值
            has_price = False
            has_nav = False
            
            if not lof_data.empty:
                # 检查是否有今天的收盘价数据
                today_str = datetime.now().date().strftime('%Y-%m-%d')
                today_data = lof_data[lof_data['日期'] == today_str]
                if not today_data.empty:
                    if 'LOF交易价格' in today_data.columns and not pd.isna(today_data['LOF交易价格'].iloc[0]):
                        has_price = True
                    if 'LOF净值' in today_data.columns and not pd.isna(today_data['LOF净值'].iloc[0]):
                        has_nav = True
            
            # 获取基金原有的处理状态兜底
            fund_status = status['processed_funds'].get(fund_code_str, {})
            
            # 更新状态
            status['processed_funds'][fund_code_str] = {
                'last_process_time': datetime.now().strftime('%H:%M:%S'),
                'has_price': fund_status.get('has_price', False) or has_price,
                'has_nav': fund_status.get('has_nav', False) or has_nav
            }
            save_lof_access_status(status)
            print(f"[状态文件] 已更新基金 {fund_code} 的处理状态")
            
        # ====== 拟人化休眠 ======
        import random
        time.sleep(random.uniform(1.5, 3.0))
    
    print("\n=== 测试完成 ===")
    print("\n=== LOF基金历史数据CSV文件已生成 ===")
    print("LOF基金历史数据已保存为 LOF_{fund_code}_history.csv (每个基金一个文件)")
    print("每次运行程序时，会先检查CSV文件中的最新日期，如果已有T日的数据则不更新，否则获取最新数据")
    print("LOF基金历史净值数据从东财获取，LOF基金历史收盘价格数据从新浪获取")
    print("LOF基金历史数据文件已包含静态官方估值")
    
