# -*- coding: utf-8 -*-
# 013_woody_web_crawler.py - Woody网页爬虫模块
# 版本: 1.0.0
# 最后修改时间: 2026-04-07
"""
Woody网页爬虫模块，负责从Woody网站爬取数据作为API的备份
"""

import os
# 强制全局禁用系统代理，防止所有爬虫报错 WinError 10061
os.environ['NO_PROXY'] = '*'
import re
import json
import requests
# 禁用urllib3的警告
requests.packages.urllib3.disable_warnings()
import pandas as pd
from io import StringIO
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

class WoodyWebCrawler:
    def __init__(self):
        # 初始化请求头
        self.woody_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://palmmicro.com/",
        }
        # 上次爬取日期，用于实现每天只爬一次的功能
        self.last_crawl_date = None
        # 登录会话对象
        self.session = None
    
    def login(self, username, password):
        """登录Woody网站，建立会话连接"""
        print(f"\n=== 尝试登录 Woody 网站 ===")
        
        # 创建会话对象
        self.session = requests.Session()
        
        # 首先访问登录页面获取必要的cookie和表单信息
        login_page_url = "https://palmmicro.com/account/logincn.php"
        
        try:
            print(f"[DEBUG] 访问登录页面: {login_page_url}")
            response = self.session.get(login_page_url, headers=self.woody_headers, timeout=15, verify=False)
            print(f"[DEBUG] 登录页面响应状态码: {response.status_code}")
            
            if response.status_code == 200:
                # 使用BeautifulSoup解析登录页面表单
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 查找登录表单
                login_form = soup.find('form')
                if login_form:
                    # 获取表单的action属性（提交URL）
                    form_action = login_form.get('action', '')
                    if form_action.startswith('/'):
                        login_post_url = f"https://palmmicro.com{form_action}"
                    else:
                        login_post_url = f"https://palmmicro.com/account/{form_action}"
                    
                    print(f"[DEBUG] 找到表单，action: {form_action}")
                    print(f"[DEBUG] 登录提交URL: {login_post_url}")
                    
                    # 获取所有表单字段
                    form_fields = {}
                    for input_tag in login_form.find_all('input'):
                        name = input_tag.get('name')
                        value = input_tag.get('value', '')
                        if name:
                            form_fields[name] = value
                            print(f"[DEBUG] 表单字段: {name} = {value}")
                    
                    # 更新表单数据，设置用户名和密码
                    login_data = form_fields.copy()
                    login_data['login'] = username  # 表单使用的是login字段
                    login_data['password'] = password
                    # 移除cpassword字段（登录时不需要确认密码）
                    login_data.pop('cpassword', None)
                    
                    print(f"[DEBUG] 最终登录数据: {login_data}")
                else:
                    # 如果找不到表单，使用默认配置
                    print("[DEBUG] 未找到表单，使用默认配置")
                    login_post_url = "https://palmmicro.com/account/php/_editemail.php"
                    login_data = {
                        'action': 'login',
                        'login': username,
                        'password': password,
                        'redirect': '/woody/res/stockhistorycn.php'
                    }
                
                print(f"[DEBUG] 发送登录请求到: {login_post_url}")
                response = self.session.post(login_post_url, data=login_data, headers=self.woody_headers, timeout=15, verify=False)
                
                print(f"[DEBUG] 登录响应状态码: {response.status_code}")
                
                # 检查是否有重定向
                if response.history:
                    print(f"[DEBUG] 发生重定向: {response.history}")
                    print(f"[DEBUG] 最终URL: {response.url}")
                
                if response.status_code == 200 or response.status_code == 302:
                    # 尝试访问一个需要登录的页面来验证
                    test_url = "https://palmmicro.com/woody/res/stockhistorycn.php?symbol=GLD"
                    test_response = self.session.get(test_url, headers=self.woody_headers, timeout=15, verify=False)
                    
                    print(f"[DEBUG] 验证页面状态码: {test_response.status_code}")
                    
                    if test_response.status_code == 200:
                        # 检查是否跳转到登录页面
                        if '登录帐号' not in test_response.text:
                            print("[SUCCESS] 登录成功！")
                            return True
                        else:
                            print("[ERROR] 登录失败，用户名或密码可能不正确")
                    else:
                        print(f"[ERROR] 验证登录失败，状态码: {test_response.status_code}")
                else:
                    print(f"[ERROR] 登录请求失败，状态码: {response.status_code}")
                    if response.status_code == 500:
                        print("[DEBUG] 服务器内部错误，尝试不使用action参数")
                        # 尝试不使用action参数
                        login_data.pop('action', None)
                        response = self.session.post(login_post_url, data=login_data, headers=self.woody_headers, timeout=15, verify=False)
                        print(f"[DEBUG] 重试状态码: {response.status_code}")
                        
                        # 验证登录
                        test_url = "https://palmmicro.com/woody/res/stockhistorycn.php?symbol=GLD"
                        test_response = self.session.get(test_url, headers=self.woody_headers, timeout=15, verify=False)
                        if test_response.status_code == 200 and '登录帐号' not in test_response.text:
                            print("[SUCCESS] 登录成功！")
                            return True
                                
            else:
                print(f"[ERROR] 无法访问登录页面，状态码: {response.status_code}")
                
        except Exception as e:
            print(f"[ERROR] 登录失败: {e}")
            import traceback
            traceback.print_exc()
            self.session = None
        
        return False
    
    def _make_request(self, url, timeout=15):
        """发送HTTP请求，优先使用已登录的会话"""
        print(f"[DEBUG] 发送请求到: {url}")
        
        if self.session is not None:
            # 使用已登录的会话
            response = self.session.get(url, headers=self.woody_headers, timeout=timeout, verify=False)
        else:
            # 使用普通请求，禁用代理
            response = requests.get(url, headers=self.woody_headers, timeout=timeout, verify=False, proxies={"http": None, "https": None})
        
        print(f"[DEBUG] 响应状态码: {response.status_code}")
        return response
    
    def _fund_market_prefix(self, symbol):
        """根据基金代码判断市场前缀：5开头为SH，其它常见LOF为SZ"""
        s = str(symbol)
        if s.startswith("5"):
            return "sh"
        return "sz"
    
    def get_future_calibration_values(self):
        """从Woody网页爬取所有期货（GC CL NQ ES）的校准值（统一使用calibrationhistorycn.php）"""
        today = datetime.now().date()
        if self.last_crawl_date == today:
            print("\n=== 今日已爬取过校准值，跳过 ===")
            return None
        
        print("\n=== woody网页爬取校准值 ===")
        
        calibration_values = {}
        symbol_map = {
            'GLD': ('gold', '黄金'),
            'USO': ('oil', '石油'),
            '^GSPC': ('sp500', '标普500'),
            '^NDX': ('nasdaq', '纳斯达克100')
        }
        
        for woody_sym, (key, name) in symbol_map.items():
            url = f'https://palmmicro.com/woody/res/calibrationhistorycn.php?symbol={woody_sym}'
            print(f"爬取{name}校准值，URL: {url}")
            
            try:
                response = self._make_request(url, timeout=15)
                
                if response.status_code == 200:
                    response.encoding = response.apparent_encoding
                    soup = BeautifulSoup(response.text, 'html.parser')
                    tables = soup.find_all('table')
                    
                    found = False
                    for table in tables:
                        rows = table.find_all('tr')
                        if len(rows) < 2:
                            continue
                        
                        all_cells = []
                        for row in rows:
                            cells = row.find_all(['td', 'th'])
                            for cell in cells:
                                text = cell.get_text(strip=True)
                                if text:
                                    all_cells.append(text)
                        
                        if '日期' in all_cells and '校准值' in all_cells:
                            date_idx = all_cells.index('日期')
                            calib_idx = all_cells.index('校准值')
                            
                            data_start = max(date_idx, calib_idx) + 1
                            
                            for i in range(data_start, len(all_cells)):
                                cell = all_cells[i]
                                if re.match(r'^\d{4}-\d{2}-\d{2}$', cell):
                                    date_value = cell
                                    if i + 1 < len(all_cells):
                                        next_cell = all_cells[i + 1]
                                        try:
                                            calib_value = float(next_cell)
                                            calibration_values[key] = calib_value
                                            calibration_values[f'{key}_date'] = date_value
                                            print(f"  [OK] {name}校准值: {calib_value} (日期: {date_value})")
                                            found = True
                                            break
                                        except ValueError:
                                            pass
                            if found:
                                break
                    
                    if not found:
                        print(f"  [ERROR] 未找到{name}校准值数据")
                else:
                    print(f"  [ERROR] 请求{name}校准值失败，状态码: {response.status_code}")
            except Exception as e:
                print(f"  [ERROR] 爬取{name}校准值失败: {e}")
        
        self.last_crawl_date = today
        return calibration_values if calibration_values else None
    
    def get_woody_backup_data(self, config):
        """从Woody网页爬取数据作为API失败时的备份"""
        print("\n=== 从Woody网页爬取备份数据 ===")
        
        backup_data = {}
        
        # 从配置文件中获取所有LOF基金
        if not config or 'funds' not in config:
            print("  [ERROR] 配置文件无效，无法爬取备份数据")
            return backup_data
        
        for fund in config['funds']:
            code = fund.get('code', '')
            name = fund.get('name', '')
            category = fund.get('category', '')
            
            if not code or code == '161226':
                continue  # 跳过无效代码和特殊基金
            
            print(f"  爬取基金: {name} ({code})")
            
            # 构建Woody网页URL
            prefix = "sh" if code.startswith('5') else "sz"
            url = f"https://palmmicro.com/woody/res/{prefix}{code}cn.php"
            
            try:
                # 每次请求前等待2秒，避免被封
                import time
                time.sleep(2)
                
                response = self._make_request(url, timeout=15)
                if response.status_code == 200:
                    # 尝试自动检测编码
                    response.encoding = response.apparent_encoding
                    page_text = response.text
                    
                    # 初始化基金数据
                    fund_data = {
                        'type': self._get_fund_type(category),
                        'position': None,
                        'calibration': None,
                        'hedge': None,
                        'symbol_hedge': {}
                    }
                    
                    # 提取仓位数据（使用正则表达式）
                    import re
                    position_pattern = r'仓位估算值使用([\d.]+)'
                    position_match = re.search(position_pattern, page_text)
                    if position_match:
                        position = position_match.group(1)
                        try:
                            position_float = float(position)
                            # 检查数据范围，判断是否需要转换
                            if position_float < 10:
                                position_float = position_float * 100
                            fund_data['position'] = position_float
                            print(f"    [BACKUP] 仓位: {fund_data['position']}%")
                        except ValueError:
                            pass
                    
                    # 使用BeautifulSoup解析HTML
                    soup = BeautifulSoup(page_text, 'html.parser')
                    
                    # 提取校准值数据
                    calibration_element = soup.find('td', text='校准值')
                    if calibration_element and calibration_element.next_sibling:
                        calibration = calibration_element.next_sibling.text.strip()
                        try:
                            fund_data['calibration'] = float(calibration)
                            print(f"    [BACKUP] 校准值: {fund_data['calibration']}")
                        except ValueError:
                            pass
                    
                    # 提取对冲值数据
                    hedge_element = soup.find('td', text='对冲值')
                    if hedge_element and hedge_element.next_sibling:
                        hedge = hedge_element.next_sibling.text.strip()
                        try:
                            fund_data['hedge'] = float(hedge)
                            print(f"    [BACKUP] 对冲值: {fund_data['hedge']}")
                        except ValueError:
                            pass
                    
                    # 提取ETF价格和权重数据
                    symbol_hedge = {}
                    table = None
                    for t in soup.find_all('table'):
                        if '基金指数对照表' in t.text or 'ETF' in t.text:
                            table = t
                            break
                    
                    if table:
                        rows = table.find_all('tr')
                        for row in rows[1:]:  # 跳过表头
                            cols = row.find_all('td')
                            if len(cols) >= 4:
                                etf_code = cols[0].text.strip()
                                etf_price = cols[1].text.strip()
                                etf_ratio = cols[2].text.strip().replace('%', '')
                                
                                try:
                                    symbol_hedge[etf_code] = {
                                        'price': float(etf_price),
                                        'ratio': float(etf_ratio) / 100  # 转换为小数形式
                                    }
                                    print(f"    [BACKUP] {etf_code} 价格: {symbol_hedge[etf_code]['price']}, 权重: {symbol_hedge[etf_code]['ratio'] * 100}%")
                                except ValueError:
                                    pass
                    
                    if symbol_hedge:
                        fund_data['symbol_hedge'] = symbol_hedge
                    
                    # 添加到备份数据
                    fund_key = f"{'SH' if code.startswith('5') else 'SZ'}{code}"
                    backup_data[fund_key] = fund_data
                    
                else:
                    print(f"    [ERROR] 请求失败，状态码: {response.status_code}")
            except Exception as e:
                print(f"    [ERROR] 爬取失败: {e}")
        
        return backup_data
    
    def get_woody_position_data(self, symbol):
        """从Woody网页爬取基金仓位数据"""
        print(f"\n=== woody网页爬取基金 {symbol} 的仓位数据 ===")
        
        # 构建URL（新的URL格式）
        prefix = self._fund_market_prefix(symbol)
        url = f"https://palmmicro.com/woody/res/{prefix}{symbol}cn.php"
        print(f"  [爬虫] 请求URL: {url}")
        
        try:
            # 添加延迟
            import time
            time.sleep(2)
            
            # 发送请求
            response = self._make_request(url, timeout=15)
            
            # 检查响应内容
            if response.status_code == 200:
                # 尝试自动检测编码
                response.encoding = response.apparent_encoding
                      
                # 使用BeautifulSoup解析HTML
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # 查找包含"仓位估算值使用"的文本
                page_text = soup.get_text()
                
                
                # 搜索"仓位估算值使用"关键字
                import re
                pattern = r'仓位估算值使用([\d.]+)'
                match = re.search(pattern, page_text)
                
                if match:
                    position = match.group(1)
                    print(f"找到仓位数据: {position}")
                    
                    # 查找更新日期
                    date_pattern = r'基金持仓更新于([\d-]+)'
                    date_match = re.search(date_pattern, page_text)
                    
                    if date_match:
                        date_str = date_match.group(1)
                        print(f"找到更新日期: {date_str}")
                    else:
                        date_str = datetime.now().strftime('%Y-%m-%d')
                        print(f"未找到更新日期，使用当前日期: {date_str}")
                    
                    # 转换仓位为浮点数
                    position_float = float(position)
                    # 检查数据范围，判断是否需要转换
                    # 如果值小于10，可能是小数形式（如0.88表示88%），需要转换为百分比形式
                    if position_float < 10:
                        position_float = position_float * 100
                    
                    print(f"  [OK] 成功获取{symbol}仓位数据: {position_float}%")
                    return {
                        'date': date_str,
                        'position': position_float
                    }
                else:
                    print(f"  [ERROR] 无法找到{symbol}仓位数据")
                    return None
            else:
                print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
                return None
        
        except Exception as e:
            print(f"  [ERROR] 请求失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_woody_holdings_data(self, symbol):
        """从Woody网页爬取基金持仓数据"""
        print(f"\n=== woody网页爬取基金 {symbol} 的持仓数据 ===")
        
        # 构建URL
        prefix = self._fund_market_prefix(symbol)
        url = f"https://palmmicro.com/woody/res/holdingscn.php?symbol={prefix}{symbol}"
        print(f"  [爬虫] URL: {url}")
        
        try:
            # 添加延迟
            import time
            time.sleep(2)
            
            # 发送请求
            response = self._make_request(url, timeout=15)
            
            # 检查响应内容
            if response.status_code == 200:
                # 尝试自动检测编码
                # 尝试自动检测编码
                response.encoding = response.apparent_encoding
                
                # 🚀 核心修复：绕过 bs4(4.13.0) 的 SoupStrainer Bug
                try:
                    tables = pd.read_html(StringIO(response.text), flavor='lxml')
                except Exception:
                    try:
                        tables = pd.read_html(response.text)
                    except Exception as e:
                        print(f"  [ERROR] 解析错误: HTML 表格提取失败 - {e}")
                        return None

                print(f"  ℹ️  找到 {len(tables)} 个表格")
                
                # 查找包含持仓数据的表格
                for i, table in enumerate(tables):
                    # print(f"表格 {i+1} 列名: {table.columns.tolist()}")
                    
                    # 查找包含'代码'和'旧比例(%)'列的表格
                    if '代码' in table.columns and '旧比例(%)' in table.columns:
                        print("找到持仓数据表格")
                        
                        # 提取ETF权重数据
                        holdings = []
                        for _, row in table.iterrows():
                            code = str(row['代码']).strip()
                            weight = row['旧比例(%)']
                            
                            # 跳过总计行
                            if code == '全部':
                                continue
                            
                            # 跳过空数据
                            if pd.isna(code) or pd.isna(weight):
                                continue
                            
                            # 确定锚点
                            anchor = 'US'
                            if code.startswith('^'):
                                # 处理欧洲市场的ETF
                                if '-EU' in code:
                                    anchor = 'EU'
                                code = code.lstrip('^')
                            
                            # 处理权重
                            if isinstance(weight, str):
                                weight = weight.replace('%', '')
                                try:
                                    weight_float = float(weight)
                                except ValueError:
                                    continue
                            else:
                                try:
                                    weight_float = float(weight)
                                except Exception:
                                    continue
                            
                            holdings.append({
                                'symbol': code,
                                'weight': weight_float,
                                'anchor': anchor
                            })
                        
                        if holdings:
                            print(f"  [OK] 成功获取{symbol}持仓数据，共{len(holdings)}个ETF")
                            # 只打印前5个ETF，避免输出过多
                            if len(holdings) > 5:
                                print(f"  ℹ️  前5个ETF: {holdings[:5]}")
                            else:
                                print(f"  ℹ️  ETF数据: {holdings}")
                            return holdings
                
                print(f"  [ERROR] 无法找到{symbol}持仓数据")
                return None
            else:
                print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
                return None
        
        except Exception as e:
            print(f"  [ERROR] 请求失败: {e}")
            return None
    
    def fetch_woody_historical_data(self, symbol, start_date=None, end_date=None, max_records=30):
        """从Woody网页爬取 ETF 的历史价格数据"""
        print(f"\n=== woody爬取 {symbol} 的价格数据 ===")

        # 构建URL，处理^前缀
        clean_symbol = symbol

        # 对于GLD和USO，由于Woody页面命名习惯，尝试移除^符号
        if clean_symbol in ['^GLD', '^USO']:
            clean_symbol = clean_symbol.replace('^', '')
        # 对于区域变种，确保有^前缀
        elif ('-JP' in clean_symbol or '-EU' in clean_symbol or '-HK' in clean_symbol) and not clean_symbol.startswith('^'):
            clean_symbol = f"^{clean_symbol}"

        url = f"https://palmmicro.com/woody/res/stockhistorycn.php?symbol={clean_symbol}"

        try:
            import time
            import random

            max_retries = 3
            tables = None

            for attempt in range(max_retries):
                # 拟人化随机延迟
                sleep_time = random.uniform(2.0, 4.0)
                if attempt > 0:
                    sleep_time = random.uniform(5.0, 10.0)
                    print(f"  ⏳ 第 {attempt + 1} 次重试，等待 {sleep_time:.1f} 秒...")

                time.sleep(sleep_time)

                try:
                    response = self._make_request(url, timeout=15)
                except Exception as req_err:
                    if attempt < max_retries - 1:
                        continue
                    print(f"  [ERROR] 网络请求失败: {req_err}")
                    return None
                
                if response.status_code == 200:
                    response.encoding = response.apparent_encoding
                    
                    # 检查是否触发反爬人机验证
                    if "Please wait while your request is being verified" in response.text or "One moment, please" in response.text:
                        if attempt < max_retries - 1:
                            continue
                        else:
                            print(f"  [ERROR] 遭遇反爬验证，已放弃获取 {symbol}")
                            return None
                    
                    # 尝试解析 HTML 表格
                    try:
                        tables = pd.read_html(StringIO(response.text), flavor='lxml')
                        if tables: break
                    except Exception:
                        try:
                            tables = pd.read_html(response.text)
                            if tables: break
                        except Exception as e:
                            if attempt < max_retries - 1:
                                continue
                            print(f"  [ERROR] HTML表格提取失败: {str(e)[:100]}")
                            return None
                else:
                    if attempt < max_retries - 1:
                        continue
                    print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
                    return None
            
            if not tables:
                print(f"  [ERROR] 页面未包含有效表格数据 ({symbol})")
                return None
            
            # 查找目标表格
            target_table = None
            max_rows = 0
            
            # 灵活匹配列名
            date_keywords = ['日期', 'Date', 'date']
            price_keywords = ['价格', '收盘', 'Close', 'Price', 'price']

            for i, table in enumerate(tables):
                # 提取所有可见文本 (包括列名和前几行数据)
                sample_texts = []
                if isinstance(table.columns, pd.MultiIndex):
                    sample_texts.extend([' '.join([str(c) for c in col_tuple]) for col_tuple in table.columns])
                else:
                    sample_texts.extend([str(c) for c in table.columns])
                
                # 检查前 3 行数据
                for r_idx in range(min(3, len(table))):
                    sample_texts.extend([str(val) for val in table.iloc[r_idx]])
                
                print(f"    [DEBUG] 表格 {i} 样本特征: {sample_texts[:10]}...")
                
                has_date = any(any(kw in str(t) for kw in date_keywords) for t in sample_texts)
                has_price = any(any(kw in str(t) for kw in price_keywords) for kw in price_keywords for t in sample_texts)
                
                if has_date and has_price:
                    if table.shape[0] > max_rows:
                        max_rows = table.shape[0]
                        target_table = table
            
            if target_table is not None:
                data = []
                
                # 精确查找列索引 (扫描列名和前几行)
                date_idx = -1
                price_idx = -1
                
                # 1. 扫描列名
                cols = []
                if isinstance(target_table.columns, pd.MultiIndex):
                    cols = [' '.join([str(c) for c in col_tuple]) for col_tuple in target_table.columns]
                else:
                    cols = [str(c) for c in target_table.columns]
                
                for idx, c in enumerate(cols):
                    if any(kw in c for kw in date_keywords): date_idx = idx
                    if any(kw in c for kw in price_keywords): price_idx = idx
                
                # 2. 如果没找到，扫描前几行
                if date_idx == -1 or price_idx == -1:
                    for r_idx in range(min(5, len(target_table))):
                        row_vals = [str(v) for v in target_table.iloc[r_idx]]
                        for idx, v in enumerate(row_vals):
                            if date_idx == -1 and any(kw in v for kw in date_keywords): date_idx = idx
                            if price_idx == -1 and any(kw in v for kw in price_keywords): price_idx = idx
                        if date_idx != -1 and price_idx != -1:
                            break
                
                if date_idx == -1 or price_idx == -1:
                    print(f"  [ERROR] 无法精确定位日期/价格列索引 ({symbol})")
                    return None

                for index, row in target_table.iterrows():
                    try:
                        d_raw = str(row.iloc[date_idx]).strip()
                        p_raw = str(row.iloc[price_idx]).strip()
                        
                        # 简单的日期格式过滤
                        if not re.match(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', d_raw):
                            continue
                            
                        # 标准化日期
                        d_clean = pd.to_datetime(d_raw).strftime('%Y-%m-%d')
                        # 处理带逗号的价格
                        p_float = float(p_raw.replace(',', ''))
                        
                        if p_float > 0:
                            # --- 智能收盘安全锁 ---
                            row_date_obj = datetime.strptime(d_clean, '%Y-%m-%d')
                            if '-JP' in symbol:
                                safe_close = row_date_obj + timedelta(hours=14, minutes=35)
                                m_name = "日本"
                            elif '-HK' in symbol:
                                safe_close = row_date_obj + timedelta(hours=16, minutes=35)
                                m_name = "香港"
                            elif '-EU' in symbol:
                                safe_close = row_date_obj + timedelta(days=1, hours=1, minutes=0)
                                m_name = "欧洲"
                            else:
                                safe_close = row_date_obj + timedelta(days=1, hours=5, minutes=30)
                                m_name = "美股"
                                
                            if datetime.now() < safe_close:
                                continue

                            data.append({'日期': d_clean, '价格': p_float})
                            if len(data) >= max_records:
                                break
                    except:
                        continue
                
                if data:
                    df = pd.DataFrame(data).drop_duplicates(subset=['日期']).sort_values('日期', ascending=False)
                    latest_d, latest_p = df['日期'].iloc[0], df['价格'].iloc[0]
                    print(f"  [OK] 成功读取 {symbol} 数据，最新日期: {latest_d}，最新价格: {latest_p}")
                    return df
                else:
                    print(f"  [ERROR] 表格内未发现有效数据行 ({symbol})")
                    return None
            else:
                print(f"  [ERROR] 未能识别包含日期/价格特征的表格 ({symbol})")
                return None

        except Exception as e:
            print(f"  [ERROR] 爬取历史数据异常: {e}")
            return None

    def fetch_sina_historical_data(self, symbol, max_records=30):
        """从新浪财经爬取美股ETF的历史价格数据"""
        # 符号需要小写，且去掉任何特殊前缀
        clean_symbol = symbol.lower().replace('^', '')
        print(f"\n=== 新浪爬取 {symbol} 的价格数据 ===")
        url = f"https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK?symbol={clean_symbol}"
        
        try:
            response = requests.get(url, headers=self.woody_headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            if response.status_code == 200:
                text = response.text
                if text == 'null' or not text:
                    print(f"  [SINA_ERROR] {symbol} 查询无数据 (返回 null 或空)")
                    return None
                
                data = json.loads(text)
                
                if not data:
                    print(f"  [SINA_ERROR] {symbol} 返回空数据列表")
                    return None

                df = pd.DataFrame(data)
                df = df[['d', 'c']]
                df.rename(columns={'d': '日期', 'c': '价格'}, inplace=True)
                df['价格'] = pd.to_numeric(df['价格'])
                df = df.sort_values('日期', ascending=False).head(max_records)
                
                latest_date = df['日期'].iloc[0]
                latest_price = df['价格'].iloc[0]
                print(f"  [SINA_OK] 成功读取{symbol}数据，最新日期: {latest_date}，最新价格: {latest_price}")
                return df
            else:
                print(f"  [SINA_ERROR] 请求失败，状态码: {response.status_code}")
                return None
        except Exception as e:
            print(f"  [SINA_ERROR] 请求失败: {e}")
            return None
    
    def get_lof_calibration_values(self, config=None):
        """从Woody网页爬取各个LOF的校准值"""
        print("\n=== woody网页爬取LOF校准值 ===")
        
        lof_calibration_values = {}
        
        # 从配置文件中获取需要获取校准值的LOF
        # 按类别判断：油气类、其他类、指数类
        lof_list = []
        if config and 'funds' in config:
            for fund in config['funds']:
                code = fund.get('code', '')
                name = fund.get('name', '')
                category = fund.get('category', '')
                
                if category in ['油气', '其他', '指数'] and code != '161226':
                    # 161226是特殊基金，不获取校准值
                    lof_list.append({'code': code, 'name': name})
        
        for lof in lof_list:
            code = lof['code']
            name = lof['name']
            url = f"https://palmmicro.com/woody/res/sz{code}cn.php"
            
            print(f"爬取{name}({code})校准值...")
            
            try:
                # 每次请求前等待1.5秒，避免被封
                import time
                time.sleep(1.5)
                
                response = self._make_request(url, timeout=15)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    # 查找校准记录表格
                    table = None
                    for t in soup.find_all('table'):
                        if '校准记录' in t.text or '校准值' in t.text:
                            table = t
                            break
                    
                    if table:
                        # 查找表格中的校准值
                        rows = table.find_all('tr')
                        for row in rows[1:]:  # 跳过表头
                            cols = row.find_all('td')
                            if len(cols) >= 3:
                                # 查找"校准值"列
                                calibration_value = cols[1].text.strip()
                                try:
                                    # 去掉千位分隔符
                                    calibration_value_clean = calibration_value.replace(',', '')
                                    lof_calibration_values[code] = float(calibration_value_clean)
                                    print(f"  [OK] {name}校准值: {calibration_value}")
                                    break
                                except ValueError:
                                    pass  # 跳过无法转换的值
                    else:
                        print(f"  [ERROR] 未找到校准记录表格")
                else:
                    print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
            except Exception as e:
                print(f"  [ERROR] 爬取{name}校准值失败: {e}")
        
        return lof_calibration_values
    
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
    
    def get_woody_exchange_rates(self):
        """从Woody网页爬取汇率数据，包括中间价和在岸价"""
        print("\n=== woody网页爬取汇率数据 ===")
        
        exchange_rates = {}
        
        # 使用SZ159518的页面，因为它包含汇率数据
        url = "https://palmmicro.com/woody/res/sz159518cn.php"
        
        try:
            response = self._make_request(url, timeout=15)
            if response.status_code == 200:
                response.encoding = response.apparent_encoding
                page_text = response.text
                
                # 使用BeautifulSoup解析HTML
                soup = BeautifulSoup(page_text, 'html.parser')
                
                # 查找包含汇率数据的表格
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 6:
                            code = cols[0].text.strip()
                            price = cols[1].text.strip()
                            time = cols[4].text.strip()
                            name = cols[5].text.strip()
                            
                            if code == 'USDCNY':
                                try:
                                    exchange_rates['USDCNY'] = {
                                        'rate': float(price),
                                        'time': time,
                                        'name': name
                                    }
                                    print(f"  [OK] 在岸人民币(USDCNY): {price} (时间: {time})")
                                except ValueError:
                                    pass
                            elif code == 'USCNY':
                                try:
                                    exchange_rates['USCNY'] = {
                                        'rate': float(price),
                                        'time': time,
                                        'name': name
                                    }
                                    print(f"  [OK] 人民币中间价(USCNY): {price} (时间: {time})")
                                except ValueError:
                                    pass
                
                if exchange_rates:
                    return exchange_rates
                else:
                    print("  [ERROR] 未找到汇率数据")
            else:
                print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"  [ERROR] 爬取汇率数据失败: {e}")
        
        return None
    
