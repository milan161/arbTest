# -*- coding: utf-8 -*-
# 011_generate_basic_data.py - 生成基础数据
# 版本: 1.0.1
# 最后修改时间: 2026-03-03
"""
生成基础历史数据模块

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

# 导入公共数据获取模块
from readers.data_fetcher import data_fetcher
import json
from bs4 import BeautifulSoup

# 导入Woody网页爬虫模块
from LOF013_woody_web_crawler import WoodyWebCrawler

# 导入API模块
try:
    from telegram import FetchPalmmicroData
    API_AVAILABLE = True
    print("[API] 成功导入API模块")
except ImportError as e:
    print(f"[API] API模块不可用，将使用爬虫获取数据: {e}")
    API_AVAILABLE = False

class BasicDataGenerator:
    def __init__(self):
        # 初始化数据保存路径
        self.data_path = os.path.join(os.path.dirname(__file__), "data")
        if not os.path.exists(self.data_path):
            os.makedirs(self.data_path)
     
        
        # 保存最新日期，供后续使用
        self.latest_date = None
        
        # API数据存储
        self.api_data = None
        
        # 初始化WoodyWebCrawler
        self.woody_crawler = WoodyWebCrawler()
    
    def load_api_data_from_csv(self):
        """从本地API数据表加载数据"""
        today = datetime.now().date().strftime('%Y%m%d')
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        api_data_file = os.path.join(data_dir, f"Data_woodyAPI_{today}.csv")
        
        if not os.path.exists(api_data_file):
            print(f"  [API] 本地API数据表不存在: {api_data_file}")
            return None
        
        try:
            import pandas as pd
            df = pd.read_csv(api_data_file)
            print(f"  成功加载本地API数据表，共{len(df)}条记录")
            
            # 转换为字典格式
            api_data = {}
            for _, row in df.iterrows():
                symbol = row['symbol']
                api_data[symbol] = {
                    'type': row.get('type', ''),
                    'netvalue': row.get('netvalue', ''),
                    'date': row.get('date', ''),
                    'CNYholdings': row.get('CNYholdings', ''),
                    'CNY': row.get('CNY', ''),
                    'position': row.get('position', ''),
                    'calibration': row.get('calibration', ''),
                    'hedge': row.get('hedge', ''),
                    'symbol_hedge': row.get('symbol_hedge', '')
                }
                
                # 添加ETF字段（所有以 _ratio 或 _price 结尾的列）
                for col in df.columns:
                    if col.endswith('_ratio') or col.endswith('_price'):
                        api_data[symbol][col] = row[col]
            
            # 存储API数据
            self.api_data = api_data
            return api_data
        except Exception as e:
            print(f"  加载本地API数据表失败: {e}")
            return None
    
    def load_api_data(self, symbols):
        """从本地API.csv数据表加载数据"""
        # 从本地API数据表加载数据
        api_data = self.load_api_data_from_csv()
        return api_data

    def _fund_market_prefix(self, symbol):
        """根据基金代码判断市场前缀：50开头为SH，其它常见LOF为SZ"""
        s = str(symbol)
        if s.startswith("50"):
            return "sh"
        return "sz"
    
    def get_all_api_LOFCode(self, config):
        """
        获取所有需要从API获取的基金代码
        
        返回:
            str: 逗号分隔的基金代码字符串，如 "SZ160719,SH501018"
        """
        symbols = []
        
        # 获取所有LOF基金代码（排除161226）
        for fund in config.get('funds', []):
            fund_code = fund.get('code')
            if fund_code and fund_code != '161226':
                # 添加市场前缀
                prefix = "SH" if fund_code.startswith('50') else "SZ"
                symbols.append(f"{prefix}{fund_code}")
        
        return ",".join(symbols)
    
    def get_api_etf_list(self, config):
        """
        获取需要从API获取的ETF列表
        
        返回:
            list: 需要从API获取的ETF列表，如 ['SPY', 'QQQ', 'XOP', 'XBI', 'SLV']
        """
        etf_symbols = set()
        for fund in config.get('funds', []):
            for item in fund.get('valuation_portfolio', []):
                symbol = item.get('symbol', '')
                if symbol:
                    # 处理黄金ETF：只取GLD
                    if symbol.startswith('GLD'):
                        etf_symbols.add('GLD')
                    # 处理原油ETF：只取USO
                    elif symbol.startswith('USO'):
                        etf_symbols.add('USO')
                    # 其他ETF直接添加
                    else:
                        etf_symbols.add(symbol)
        
        # 排除GLD和USO（它们不需要从API获取净值）
        etf_list = [etf for etf in etf_symbols if etf not in ['GLD', 'USO']]
        
        return etf_list
    
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
  
     
    def _get_fund_type(self, category):
        """根据基金类别获取基金类型"""
        if category in ['黄金']:
            return 'gold'
        elif category in ['油气']:
            return 'oil'
        elif category in ['其他']:
            return 'pure_etf'
        elif category in ['指数']:
            return 'index'
        else:
            return 'other'
 
         
    def generate_enhanced_basic_data(self, config, should_access=True, time_slot=None):
        
        today_str = datetime.now().date().strftime('%Y-%m-%d')
        """从API获取数据并生成基础数据"""
        print("\n=== 第一步 从API获取数据  ===")
        
        # 导入必要的模块
        import pandas as pd
        import glob
        
        # 创建woodyAPI目录
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        woody_api_dir = os.path.join(data_dir, "woodyAPI")
        if not os.path.exists(woody_api_dir):
            os.makedirs(woody_api_dir)
            print(f"[API] 已创建woodyAPI目录: {woody_api_dir}")
        
        # 查找最新的CSV文件
        csv_files = glob.glob(os.path.join(woody_api_dir, "Data_woodyAPI_*.csv"))
        csv_file = None
        api_success = False
        
        if should_access:
            # 调用读取LOF代码的函数
            symbols_str = self.get_all_api_LOFCode(config)
            print(f"[API] LOF代码列表: {symbols_str}")
            
            # 调用API获取数据
            print(f"[API] 正在调用API获取数据...")
            try:
                if API_AVAILABLE:
                    result = FetchPalmmicroData(symbols_str)
                    print(f"[API] API调用完成")
                else:
                    result = None
                    print(f"[API] API模块不可用，跳过网络调用")
                
                # 检查API调用是否成功
                if result is not None:
                    # 保存API返回的数据到JSON文件
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M')  # 使用日期+小时+分钟格式
                    api_data_file = os.path.join(woody_api_dir, f"Data_woodyAPI_{timestamp}.json")
                    with open(api_data_file, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f"[API] API数据已保存到: {api_data_file}")
                    
                    # 生成CSV文件
                    csv_file = os.path.join(woody_api_dir, f"Data_woodyAPI_{timestamp}.csv")
                    # 准备数据
                    csv_data = []
                    # 检查result的结构
                    data = result
                    if 'text' in result:
                        data = result['text']
                    
                    # 预定义严格且清晰的列顺序
                    csv_columns = [
                        'symbol', 'type', 'CNY', 'position', 'date', 'netvalue', 
                        'CNYholdings', 'calibration', 'hedge', 'symbol_hedge',
                        'GLD_price', 'GLD_ratio', '^GLD-JP_price', '^GLD-JP_ratio', '^GLD-EU_price', '^GLD-EU_ratio',
                        'USO_price', 'USO_ratio', '^USO-JP_price', '^USO-JP_ratio', '^USO-HK_price', '^USO-HK_ratio', '^USO-EU_price', '^USO-EU_ratio'
                    ]

                    if isinstance(data, dict):
                        for symbol, fund_data in data.items():
                            # 智能获取 YAML 中配置的 type (分类)
                            fund_type = ""
                            code_6 = symbol[-6:] if len(symbol) >= 6 else ""
                            if config and 'funds' in config:
                                for f in config['funds']:
                                    if str(f.get('code')) == code_6:
                                        cat = f.get('category', '')
                                        fund_type = '商品' if cat in ['黄金', '原油'] else cat
                                        break

                            row = {col: "" for col in csv_columns}
                            row['symbol'] = symbol
                            row['type'] = fund_type
                            row['CNY'] = fund_data.get('CNY', '')
                            row['position'] = fund_data.get('position', '')
                            row['date'] = fund_data.get('date', '') # API 通常没有此字段，按要求预留
                            row['netvalue'] = fund_data.get('netvalue', '')
                            row['CNYholdings'] = fund_data.get('CNYholdings', '')
                            row['calibration'] = fund_data.get('calibration', '')
                            row['hedge'] = fund_data.get('hedge', '')
                            
                            sh_data = fund_data.get('symbol_hedge', '')
                            
                            if isinstance(sh_data, dict):
                                row['symbol_hedge'] = "" # 商品类，该列按要求留空
                                for etf, etf_data in sh_data.items():
                                    etf_name = etf
                                    # 还原正确的 ^ 前缀，严格映射到底层固定列
                                    if ('-JP' in etf_name or '-EU' in etf_name or '-HK' in etf_name) and not etf_name.startswith('^'):
                                        etf_name = f"^{etf_name}"
                                        
                                    if f"{etf_name}_price" in row:
                                        row[f"{etf_name}_price"] = etf_data.get('price', '')
                                    if f"{etf_name}_ratio" in row:
                                        row[f"{etf_name}_ratio"] = etf_data.get('ratio', '')
                            else:
                                # 纯ETF或指数类，直接原样填入 (如 "XOP")
                                row['symbol_hedge'] = str(sh_data)
                                
                            csv_data.append(row)
                    
                    if csv_data:
                        df = pd.DataFrame(csv_data, columns=csv_columns)
                        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
                        print(f"[API] CSV文件已生成: {csv_file}")
                        api_success = True
                    else:
                        print("[API] 无数据生成CSV文件")
                else:
                    print("[API] API调用失败，返回None")
            except Exception as e:
                print(f"[API] API调用出错: {e}")
            
            # 如果API调用失败，使用最新的本地文件
            if not api_success:
                print("[API] API调用失败，使用最新的本地数据")
                if csv_files:
                    csv_files.sort(reverse=True)
                    csv_file = csv_files[0]
                    print(f"[API] 使用最新的本地CSV文件: {csv_file}")
                else:
                    print("[API] 未找到API数据CSV文件")
                    return
            else:
                # API调用成功，更新访问状态
                if time_slot:
                    status = load_api_access_status()
                    status['access_times'][time_slot] = datetime.now().strftime('%H:%M:%S')
                    save_api_access_status(status)
                    print(f"[API] 已更新访问状态: {time_slot}")
        else:
            # 不访问API，使用最新的本地文件
            if csv_files:
                csv_files.sort(reverse=True)
                csv_file = csv_files[0]
                print(f"[API] 不访问API，使用最新的本地CSV文件: {csv_file}")
            else:
                print("[API] 未找到API数据CSV文件")
                return
        
        # 确保有CSV文件
        if not csv_file:
            # 查找最新的CSV文件
            if csv_files:
                csv_files.sort(reverse=True)
                csv_file = csv_files[0]
                print(f"[API] 使用最新的CSV文件: {csv_file}")
            else:
                print("[API] 未找到API数据CSV文件")
                return
        
        # 读取CSV文件
        df = pd.read_csv(csv_file, encoding='utf-8-sig')
        # 转换为字典格式
        api_data = {}
        for _, row in df.iterrows():
            fund_code = row['symbol']
            fund_data = {}
            if pd.notna(row.get('type')):
                fund_data['type'] = str(row['type'])
            if pd.notna(row.get('date')):
                fund_data['date'] = str(row['date'])
            if pd.notna(row.get('netvalue')):
                fund_data['netvalue'] = str(row['netvalue'])
            if pd.notna(row.get('CNYholdings')):
                fund_data['CNYholdings'] = str(row['CNYholdings'])
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
            # 常见的带^前缀的ETF列表
            common_etfs_with_caret = ['^GLD-EU', '^GLD-JP', '^USO-EU', '^USO-JP', '^USO-HK']
            
            for col in df.columns:
                if '_ratio' in col:
                    etf_name = col.replace('_ratio', '')
                    # 检查是否是常见的带^前缀的ETF
                    for etf in common_etfs_with_caret:
                        if etf_name == etf.replace('^', ''):
                            etf_name = etf
                            break
                    if pd.notna(row.get(col)):
                        if etf_name in symbol_hedge:
                            symbol_hedge[etf_name]['ratio'] = str(row[col])
                        else:
                            symbol_hedge[etf_name] = {'ratio': str(row[col])}
                elif '_price' in col:
                    etf_name = col.replace('_price', '')
                    # 检查是否是常见的带^前缀的ETF
                    for etf in common_etfs_with_caret:
                        if etf_name == etf.replace('^', ''):
                            etf_name = etf
                            break
                    if pd.notna(row.get(col)):
                        if etf_name in symbol_hedge:
                            symbol_hedge[etf_name]['price'] = str(row[col])
                        else:
                            symbol_hedge[etf_name] = {'price': str(row[col])}
            if symbol_hedge:
                fund_data['symbol_hedge'] = symbol_hedge
            api_data[fund_code] = fund_data
        
        print(f"[API] 从CSV文件成功读取数据: {csv_file}")
        print(f"[API] 共读取 {len(api_data)} 条记录")
        
        # 存储API数据到self.api_data
        self.api_data = api_data
        
        # ====== 核心新增：API数据源头直接同步更新 YAML 配置文件 ======
        if self.api_data and config and 'funds' in config:
            print("\n=== 根据 API 数据同步更新 YAML 配置文件 ===")
            config_changed = False
            for fund in config['funds']:
                code = str(fund.get('code', ''))
                if not code or code == '161226': continue
                prefix = "SH" if code.startswith('50') else "SZ"
                api_key = f"{prefix}{code}"
                
                if api_key in self.api_data:
                    api_fund = self.api_data[api_key]
                    
                    # 1. 更新仓位
                    pos_str = api_fund.get('position')
                    if pos_str and pd.notna(pos_str) and str(pos_str).strip():
                        try:
                            pos_val = float(pos_str)
                            if pos_val < 10: pos_val *= 100
                            if pos_val > 0:
                                if 'holdings' not in fund: fund['holdings'] = {}
                                old_pos = fund['holdings'].get('equity_ratio', 0)
                                if abs(old_pos - pos_val) > 0.01:
                                    fund['holdings']['equity_ratio'] = pos_val
                                    fund['holdings']['cash_ratio'] = 100.0 - pos_val
                                    config_changed = True
                                    print(f"  [YAML更新] {code} 仓位已修正: {old_pos}% -> {pos_val}%")
                        except Exception: pass
                    
                    # 2. 更新权重
                    sh = api_fund.get('symbol_hedge')
                    if isinstance(sh, dict) and sh:
                        port = fund.get('valuation_portfolio', [])
                        if not port: port = fund.get('hedging_portfolio', [])
                        for item in port:
                            sym = item.get('symbol', '').replace('^', '')
                            ratio_str = sh.get(sym, {}).get('ratio') or sh.get(f"^{sym}", {}).get('ratio')
                            if ratio_str and pd.notna(ratio_str) and str(ratio_str).strip():
                                try:
                                    ratio_float = float(ratio_str)
                                    if ratio_float < 1.0: ratio_float *= 100
                                    if ratio_float > 0:
                                        old_weight = item.get('weight', 0)
                                        if abs(old_weight - ratio_float) > 0.01:
                                            item['weight'] = ratio_float
                                            config_changed = True
                                            print(f"  [YAML更新] {code} {item.get('symbol')} 权重已修正: {old_weight}% -> {ratio_float}%")
                                except Exception: pass
            if config_changed:
                try:
                    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lof_config.yaml")
                    with open(config_file, 'w', encoding='utf-8') as f:
                        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
                    print(f"  [OK] lof_config.yaml 文件已成功更新保存")
                except Exception as e: print(f"  [ERROR] 保存 YAML 失败: {e}")
            else:
                print("  [ℹ️] YAML 配置文件中的仓位和权重已是最新，无需更新")
        # ==============================================================

        # =======================================================
        # 处理基础数据文件（作为备份）
        # ======================================================= 
      
        print("\n" + "="*40)
        print(f"第二步：处理basic基础文件（作为备份）")
        print("="*40)
        
        # 爬取汇率数据
        print("\n=== 从外汇管理局获取汇率数据 ===")
        # 使用公共数据获取模块获取汇率
        exchange_rate_data = data_fetcher.fetch_official_exchange_rate()
        if exchange_rate_data:
            print(f"汇率数据日期: {exchange_rate_data['日期']}")
            print(f"人民币中间价: {exchange_rate_data['人民币中间价']}")
        
        # 确定T日（最新的A股交易日）
        today_date = datetime.now().date()
        today_str = today_date.strftime('%Y-%m-%d')
        if self.is_trading_day(today_str):
            T = today_date
            print(f"今天是交易日，T日为: {T.strftime('%Y-%m-%d')}")
        else:
            T = self.get_latest_a_share_trading_day()
            print(f"今天不是交易日，最近的交易日为: {T.strftime('%Y-%m-%d')}")
        
        # 计算T-1日（上一个交易日）
        T_minus_1 = T
        # 向前查找上一个交易日
        for _ in range(10):  # 最多向前查找10天
            T_minus_1 = T_minus_1 - timedelta(days=1)
            if self.is_trading_day(T_minus_1.strftime('%Y-%m-%d')):
                break
        T_minus_1_str = T_minus_1.strftime('%Y-%m-%d')
        T_str = T.strftime('%Y-%m-%d')
        
        print(f"T-1日为: {T_minus_1_str}")
        
        # 定义基础数据文件路径
        filepath = os.path.join(self.data_path, 'GLD_USO_basic_data.csv')
        
        # 创建基础DataFrame
        # 检查文件是否存在
        if os.path.exists(filepath):
            # 读取现有文件
            combined_df = pd.read_csv(filepath, encoding='utf-8-sig')
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
            
            # 撤销热迁移：将 XXX净值 和 XXX价格 统一恢复为标准的 ETF 代码，防止下游引用报错
            for old_col, new_col in [('XOP净值', 'XOP'), ('SLV净值', 'SLV'), ('XBI净值', 'XBI'), ('SPY净值', 'SPY'), ('QQQ净值', 'QQQ'),
                                     ('XOP价格', 'XOP'), ('SLV价格', 'SLV'), ('XBI价格', 'XBI'), ('SPY价格', 'SPY'), ('QQQ价格', 'QQQ')]:
                if old_col in combined_df.columns:
                    if new_col in combined_df.columns:
                        combined_df[new_col] = combined_df[new_col].fillna(combined_df[old_col])
                        combined_df.drop(columns=[old_col], inplace=True)
                    else:
                        combined_df.rename(columns={old_col: new_col}, inplace=True)
        else:
            # 创建新文件
            combined_df = pd.DataFrame({'日期': []})
        
        # 确保T-1日在DataFrame中
        if not combined_df['日期'].isin([T_minus_1_str]).any():
            # 添加T-1日行
            new_row = pd.DataFrame({'日期': [T_minus_1_str]})
            combined_df = pd.concat([new_row, combined_df], ignore_index=True)
        
        # 将汇率数据添加到basic文件中
        if exchange_rate_data:
            # 统一汇率数据的日期格式
            exchange_rate_date = unify_date_format(exchange_rate_data['日期'])
            exchange_rate_data['日期'] = exchange_rate_date
            # 检查是否已有该日期的记录
            if not combined_df['日期'].isin([exchange_rate_date]).any():
                # 添加新行
                new_rate_row = pd.DataFrame([exchange_rate_data])
                combined_df = pd.concat([new_rate_row, combined_df], ignore_index=True)
            else:
                # 更新现有行
                combined_df.loc[combined_df['日期'] == exchange_rate_date, '人民币中间价'] = exchange_rate_data['人民币中间价']
            print(f"[汇率] 已添加/更新汇率数据: {exchange_rate_date} - {exchange_rate_data['人民币中间价']}")
        
        # 去重，确保每个日期只有一行
        combined_df = combined_df.drop_duplicates(subset=['日期'], keep='first')
        
        # 🚀 核心更新：直接读取 API 新增的 date 字段作为确切的基准日
        api_data_date = T_minus_1_str
        if self.api_data:
            print(f"\n=== 解析 API 数据的基准日期 ===")
            for fund_code, fund_data in self.api_data.items():
                api_date_val = fund_data.get('date')
                if api_date_val and str(api_date_val).strip():
                    try:
                        # 解析并统一格式为 YYYY-MM-DD
                        parsed_date = pd.to_datetime(str(api_date_val).strip()).strftime('%Y-%m-%d')
                        api_data_date = parsed_date
                        print(f"✅ 从 API 报文中成功提取到明确的基准日期: {api_data_date}")
                        break
                    except Exception as e:
                        pass
                        
            # 如果这个基准日在 basic 表里还不存在，主动为它创建一行
            if not combined_df['日期'].isin([api_data_date]).any():
                print(f"⚠️ 基础表中尚无 {api_data_date} 的记录，主动创建该行...")
                new_api_row = pd.DataFrame({'日期': [api_data_date]})
                combined_df = pd.concat([new_api_row, combined_df], ignore_index=True)
                # 重新去重和排序
                combined_df = combined_df.drop_duplicates(subset=['日期'], keep='first')
                combined_df['日期'] = pd.to_datetime(combined_df['日期'], errors='coerce')
                combined_df = combined_df.sort_values('日期', ascending=False)
                combined_df['日期'] = combined_df['日期'].dt.strftime('%Y-%m-%d')
        
        # 🛑 痛定思痛：彻底删除 011 从 API 提取价格并写入历史账本的代码！
        # 事实证明：Woody API 的 date 是滞后的净值基准日(如4-10)，但 price 却是最新的实时价(如4-13)！
        # 把 4-13 的价格强塞给 4-10 的行，就是导致张冠李戴、污染历史账本的元凶！
        # 从现在起，011 只负责取【校准值】和【对冲值】，所有【历史ETF价格】全权交由 012 的历史表格爬虫去补齐！
        
        # 添加LOF校准值
        if self.api_data:
            print("\n=== 从API获取LOF校准值与对冲值 ===")
            for fund_code, fund_data in self.api_data.items():
                # 提取基金代码（去掉前缀）
                code = fund_code
                if code.startswith('SZ') or code.startswith('SH'):
                    code = code[2:]
                
                # 💡 核心修复：坚决删除 if code in [...] 的硬编码，对所有基金一视同仁！
                target_date = api_data_date  # 默认使用全局兜底
                fund_date_str = fund_data.get('date')
                if fund_date_str and str(fund_date_str).strip():
                    try:
                        target_date = pd.to_datetime(str(fund_date_str).strip()).strftime('%Y-%m-%d')
                    except Exception:
                        pass
                
                # 确保该专属日期在 basic 表中存在
                if not combined_df['日期'].isin([target_date]).any():
                    new_row = pd.DataFrame({'日期': [target_date]})
                    combined_df = pd.concat([new_row, combined_df], ignore_index=True)
                    
                if 'calibration' in fund_data:
                    val = float(fund_data['calibration'])
                    col_name = f'{code}校准'
                    if col_name not in combined_df.columns:
                        combined_df[col_name] = None
                    combined_df.loc[combined_df['日期'] == target_date, col_name] = val
                    print(f"  [API] {code} 校准值: {val} (精准写入基准日: {target_date})")
                    
                if 'hedge' in fund_data:
                    val = float(fund_data['hedge'])
                    col_name = f'{code}对冲'
                    if col_name not in combined_df.columns:
                        combined_df[col_name] = None
                    combined_df.loc[combined_df['日期'] == target_date, col_name] = val
                    print(f"  [API] {code} 对冲值: {val} (精准写入基准日: {target_date})")
                
        # 保留所有历史数据，只更新T-1日的数据
        # 历史数据的检查和补充由013负责
        
        # 清理列名，移除所有空格
        combined_df.columns = [col.replace(' ', '') for col in combined_df.columns]
        
        # 调整列顺序，确保人民币中间价在B列
        # 按照用户指定的顺序排列列 - 重要：请勿修改此顺序
        # 列顺序：日期、人民币中间价、GLD、^GLD-EU 、^GLD-JP 、，USO、，^USO-EU 、，^USO-JP 、，^USO-HK、XOP价格、SLV价格、XBI价格、SPY价格、SPY净值、QQQ价格、QQQ净值、黄金校准、原油校准、162411校准、161127校准、161125校准、161130校准、.INX、.NDX、GC_settel 、CL_settle、 NQ_settle ES_settle
        # 注意：人民币中间价必须在B列，这是用户明确要求的
        ordered_columns = [
            '日期', '人民币中间价', 'GLD', '^GLD-EU', '^GLD-JP', 'USO',
            '^USO-EU', '^USO-JP', '^USO-HK', 'XOP', 'SLV',
            'XBI', 'SPY', 'QQQ', '黄金校准', '原油校准',
            '162411校准', '162411对冲', '161127校准', '161127对冲', '161125校准', '161125对冲', '161130校准', '161130对冲', '.INX', '.NDX',
            'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle'
        ]
        
        # 确保所有需要的列都存在
        for col in ordered_columns:
            if col not in combined_df.columns:
                combined_df[col] = None
        
        # 重新排列列：优先按 ordered_columns，其余未知列(如新浪兜底写入的 xxx价格)追加在尾部
        extra_cols = [col for col in combined_df.columns if col not in ordered_columns]
        combined_df = combined_df[ordered_columns + extra_cols]
        
        # 清理数据，将非数字值转换为NaN
        for col in combined_df.columns:
            if col != '日期':
                # 尝试转换为数字
                try:
                    combined_df[col] = pd.to_numeric(combined_df[col], errors='coerce')
                except:
                    pass
        
        # 移除重复的列（如果有）
        combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]
        
        # 强制按日期降序排序，保证 basic 表格永远整齐清晰
        combined_df['日期'] = pd.to_datetime(combined_df['日期'], errors='coerce')
        combined_df = combined_df.sort_values('日期', ascending=False)
        combined_df['日期'] = combined_df['日期'].dt.strftime('%Y-%m-%d')
        
        # 保存数据，添加错误处理
        try:
            combined_df.to_csv(filepath, index=False, encoding='utf-8-sig')
            print(f"SUCCESS: 基础数据已保存到: {filepath}")
            print(f"SUCCESS: 共保存了 {len(combined_df)} 条记录")
            print(f"基础数据列名: {combined_df.columns.tolist()}")
            print(f"数据:")
            print(combined_df)
        except Exception as e:
            print(f"WARNING: 保存基础数据失败: {e}")
            print("可能是文件被其他程序占用，如Excel。请关闭占用文件的程序后重试。")
            # 尝试保存到临时文件
            temp_filepath = filepath + '.tmp'
            try:
                combined_df.to_csv(temp_filepath, index=False, encoding='utf-8-sig')
                print(f"SUCCESS: 基础数据已保存到临时文件: {temp_filepath}")
            except Exception as e2:
                print(f"ERROR: 保存临时文件也失败: {e2}")
        
        return combined_df
    


def load_config():
    """加载配置文件"""
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(SCRIPT_DIR, "lof_config.yaml")
    if not os.path.exists(config_file):
        print(f"配置文件不存在: {config_file}")
        return None
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return None

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
                    '915': None,  # 9:15-14:35区间的访问时间
                    '1435': None,  # 14:35-16:05区间的访问时间
                    '1605': None   # 16:05-23:59区间的访问时间
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
    except Exception as e:
        print(f"[状态文件] 保存访问状态失败: {e}")

def load_api_access_status():
    """
    加载API访问状态（兼容旧函数）
    返回: dict - API访问状态
    """
    status = load_access_status()
    return status.get('api', {
        'last_access_date': '',
        'access_times': {
            '915': None,
            '1435': None,
            '1605': None
        }
    })

def save_api_access_status(status):
    """
    保存API访问状态（兼容旧函数）
    """
    full_status = load_access_status()
    full_status['api'] = status
    save_access_status(full_status)

def check_api_access_time():
    """
    检查当前时间是否允许访问API
    返回: (should_access, message, time_slot)
        should_access: bool - 是否应该访问API
        message: str - 提示信息
        time_slot: str - 时间区间标识
    """
    now = datetime.now()
    current_time = now.time()
    today = now.date().strftime('%Y%m%d')
    
    # 定义时间区间
    time_915 = datetime.strptime('09:15', '%H:%M').time()
    time_1435 = datetime.strptime('14:35', '%H:%M').time()
    time_1605 = datetime.strptime('16:05', '%H:%M').time()
    
    # 加载API访问状态
    status = load_api_access_status()
    
    # 检查是否需要重置状态（新的一天）
    if status['last_access_date'] != today:
        # 新的一天，重置状态
        status['last_access_date'] = today
        status['access_times'] = {
            '915': None,
            '1435': None,
            '1605': None
        }
        save_api_access_status(status)
    
    # 0:00 - 9:15
    if current_time < time_915:
        # 此时API数据可能是昨天的旧数据
        print("[时间提醒] 此时的API数据可能是昨天的旧数据，请注意！")
        # 第一次运行，访问API
        if not status['access_times']['915']:
            return True, "[API] 第一次运行，访问API获取数据", '915'
        else:
            # 9:15之前不再访问API
            return False, "[API] 9:15之前已访问过API，不再重复访问", None
    
    # 9:15 - 14:35
    elif time_915 <= current_time < time_1435:
        # 第一次运行，访问API
        if not status['access_times']['915']:
            return True, "[API] 9:15-14:35第一次运行，访问API获取数据", '915'
        else:
            # 第二次点击，不再访问API
            return False, "[API] 9:15-14:35已访问过API，无最新数据，请14:35之后再次点击", None
    
    # 14:35 - 16:05
    elif time_1435 <= current_time < time_1605:
        # 第一次运行，访问API（可能有JP数据）
        if not status['access_times']['1435']:
            return True, "[API] 14:35-16:05第一次运行，访问API获取最新数据（可能包含JP数据）", '1435'
        else:
            # 第二次点击，不再访问API
            return False, "[API] 14:35-16:05已访问过API，无最新数据，请16:35之后再次点击", None
    
    # 16:05 - 23:59
    else:  # current_time >= time_1605
        # 第一次运行，访问API（可能有HK数据）
        if not status['access_times']['1605']:
            return True, "[API] 16:05之后第一次运行，访问API获取最新数据（可能包含HK数据）", '1605'
        else:
            # 16:05之后已访问过API，不再访问
            return False, "[API] 16:05之后已访问过API，今天不再重复访问，避免被封账户", None

if __name__ == "__main__":
    import sys
    
    # 打印今天的日期
    today = datetime.now().date()
    print(f"今天是: {today.strftime('%Y-%m-%d')}")
    print(f"当前时间: {datetime.now().strftime('%H:%M:%S')}")
    
    # 检查是否应该访问API
    should_access, message, time_slot = check_api_access_time()
    print(message)
    
    # 测试生成基础数据
    generator = BasicDataGenerator()
    
    # 加载配置文件
    config = load_config()
    
    # 生成增强版基础数据文件，包含所有对冲ETF的历史数据
    basic_data = generator.generate_enhanced_basic_data(config, should_access=should_access, time_slot=time_slot)
    
    print("\n=== 基础数据CSV文件已生成 ===")
    print("基础数据包含历史汇率、GLD/USO及其区域变种的锚点数据，已保存为 GLD_USO_basic_data.csv")
    print("每次运行程序时，会先检查CSV文件中的最新日期，如果已有T-1日的GLD数据则不更新，否则获取最新数据")

    
