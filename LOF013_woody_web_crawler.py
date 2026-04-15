# -*- coding: utf-8 -*-
# 013_woody_web_crawler.py - Woody网页爬虫模块
# 版本: 1.0.0
# 最后修改时间: 2026-04-07
"""
Woody网页爬虫模块，负责从Woody网站爬取数据作为API的备份
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
    
    def _fund_market_prefix(self, symbol):
        """根据基金代码判断市场前缀：5开头为SH，其它常见LOF为SZ"""
        s = str(symbol)
        if s.startswith("5"):
            return "sh"
        return "sz"
    
    def get_future_calibration_values(self):
        """从Woody网页爬取期货校准值"""
        # 检查是否今天已经爬取过
        today = datetime.now().date()
        if self.last_crawl_date == today:
            print("\n=== 今日已爬取过校准值，跳过 ===")
            return None
        
        print("\n=== woody网页爬取期货校准值 ===")
        
        calibration_values = {}

        # 黄金期货校准值
        print("爬取黄金期货校准值...")
        gold_url = "https://palmmicro.com/woody/res/sz161116cn.php"  # 嘉实黄金LOF
        
        try:
            response = requests.get(gold_url, headers=self.woody_headers, timeout=15, verify=False)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # 查找基金指数对照表
                table = None
                for t in soup.find_all('table'):
                    if '基金指数对照表' in t.text or '校准值' in t.text:
                        table = t
                        break
                
                if table:
                    # 查找表格中的校准值
                    rows = table.find_all('tr')
                    for row in rows[1:]:  # 跳过表头
                        cols = row.find_all('td')
                        if len(cols) >= 5:  # 确保有足够的列
                            code = cols[0].text.strip()
                            if code == 'GLD':
                                calibration_value = cols[3].text.strip()
                                date_str = cols[4].text.strip()  # 爬取日期
                                try:
                                    calibration_values['gold'] = float(calibration_value)
                                    calibration_values['gold_date'] = date_str
                                    print(f"  [OK] 黄金期货校准值: {calibration_values['gold']} (日期: {date_str})")
                                    break
                                except ValueError:
                                    pass  # 跳过无法转换的值
                else:
                    print("  [ERROR] 未找到基金指数对照表")
            else:
                print(f"  [ERROR] 请求黄金期货校准值失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"  [ERROR] 爬取黄金期货校准值失败: {e}")
        
        # 石油期货校准值
        print("  爬取石油期货校准值...")
        oil_url = "https://palmmicro.com/woody/res/sz160723cn.php"  # 嘉实原油LOF
        
        try:
            response = requests.get(oil_url, headers=self.woody_headers, timeout=15, verify=False)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # 查找基金指数对照表
                table = None
                for t in soup.find_all('table'):
                    if '基金指数对照表' in t.text or '校准值' in t.text:
                        table = t
                        break
                
                if table:
                    # 查找表格中的校准值
                    rows = table.find_all('tr')
                    for row in rows[1:]:  # 跳过表头
                        cols = row.find_all('td')
                        if len(cols) >= 5:  # 确保有足够的列
                            code = cols[0].text.strip()
                            if code == 'USO':
                                calibration_value = cols[3].text.strip()
                                date_str = cols[4].text.strip()  # 爬取日期
                                try:
                                    calibration_values['oil'] = float(calibration_value)
                                    calibration_values['oil_date'] = date_str
                                    print(f"  [OK] 石油期货校准值: {calibration_values['oil']} (日期: {date_str})")
                                    break
                                except ValueError:
                                    pass  # 跳过无法转换的值
                else:
                    print("  [ERROR] 未找到基金指数对照表")
            else:
                print(f"  [ERROR] 请求石油期货校准值失败，状态码: {response.status_code}")
        except Exception as e:
            print(f"  [ERROR] 爬取石油期货校准值失败: {e}")
        
        # 更新上次爬取日期
        self.last_crawl_date = today
        
        return calibration_values
    
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
                
                response = requests.get(url, headers=self.woody_headers, timeout=15, verify=False)
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
        
        # 使用公用的请求头
        headers = self.woody_headers
        
        try:
            # 添加延迟
            import time
            time.sleep(2)
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            print(f"响应状态码: {response.status_code}")
            
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
        
        # 使用公用的请求头
        headers = self.woody_headers
        
        try:
            # 添加延迟
            import time
            time.sleep(2)
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            print(f"响应状态码: {response.status_code}")
            
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
        """从Woody网页爬取 GLD、USO及其锚点的历史价格数据"""
        # 检查是否为GLD、USO及其锚点
        is_gld_related = 'GLD' in symbol
        is_uso_related = 'USO' in symbol
        
        if not (is_gld_related or is_uso_related):
            print(f"[Woody] {symbol} 不是GLD或USO相关ETF，跳过获取历史数据")
            return None
        
        print(f"\n=== woody爬取 {symbol} 的价格数据 ===")
        
        # 构建URL，处理^前缀
        clean_symbol = symbol
        
        # 对于GLD和USO，需要移除^符号
        if clean_symbol in ['^GLD', '^USO']:
            clean_symbol = clean_symbol.replace('^', '')
        # 对于区域变种，确保有^前缀
        elif ('-JP' in clean_symbol or '-EU' in clean_symbol or '-HK' in clean_symbol) and not clean_symbol.startswith('^'):
            clean_symbol = f"^{clean_symbol}"
        
        url = f"https://palmmicro.com/woody/res/stockhistorycn.php?symbol={clean_symbol}"
        
        # 使用公用的请求头
        headers = self.woody_headers
        
        try:
            import time
            import random
            
            max_retries = 3
            tables = None
            
            for attempt in range(max_retries):
                # 增加随机拟人化延迟，减轻服务器压力
                sleep_time = random.uniform(3.0, 5.0)
                if attempt > 0:
                    sleep_time = random.uniform(10.0, 15.0)  # 被拦截后，惩罚性拉长等待时间
                    print(f"  ⏳ 遭遇服务器防火墙拦截或网络异常，强制休眠 {sleep_time:.1f} 秒后进行第 {attempt + 1} 次重试...")
                
                time.sleep(sleep_time)
                
                # ==== 修复1：将网络请求包裹在 try 中，处理 10054 ConnectionResetError 等掉线异常 ====
                try:
                    response = requests.get(url, headers=headers, timeout=15, verify=False)
                except Exception as req_err:
                    if attempt < max_retries - 1:
                        continue
                    print(f"  [ERROR] 网络请求失败: {req_err}")
                    return None
                
                if response.status_code == 200:
                    response.encoding = response.apparent_encoding
                    
                    # === 核心拦截：检测是否触发了人机验证 ===
                    if "Please wait while your request is being verified" in response.text or "One moment, please" in response.text:
                        if attempt < max_retries - 1:
                            continue  # 触发重试
                        else:
                            print(f"  [ERROR] 连续 {max_retries} 次遭遇反爬验证，已放弃获取 {symbol}")
                            return None
                    
                    # 🚀 核心修复：绕过 bs4(4.13.0) 的 SoupStrainer Bug
                    try:
                        tables = pd.read_html(StringIO(response.text), flavor='lxml')
                        break  # 解析成功，跳出重试循环
                    except Exception:
                        try:
                            tables = pd.read_html(response.text)
                            break  # 解析成功，跳出重试循环
                        except Exception as e:
                            if attempt < max_retries - 1:
                                continue
                            # 截断过长的一大坨 HTML 报错代码
                            err_msg = str(e)[:150] + "..." if len(str(e)) > 150 else str(e)
                            print(f"  [ERROR] 解析错误: HTML表格提取失败 - {err_msg}")
                            return None
                else:
                    if attempt < max_retries - 1:
                        continue
                    print(f"  [ERROR] 请求失败，状态码: {response.status_code}")
                    return None
            
            # ==== 修复2：纠正严重的代码缩进错误，释放被 return None 阻断的表格处理逻辑 ====
            if tables is None:
                return None
            
            # 查找包含日期和价格的表格
            target_table = None
            # 优先选择较大的表格，因为数据可能在较大的表格中
            max_rows = 0
            for i, table in enumerate(tables):
                has_date = any('日期' in str(col) for col in table.columns)
                has_price = any('价格' in str(col) for col in table.columns)
                if has_date and has_price:
                    # 选择行数最多的表格
                    if table.shape[0] > max_rows:
                        max_rows = table.shape[0]
                        target_table = table
            
            if target_table is not None:
                # 提取数据
                data = []
                
                # 处理多级列索引的情况
                if isinstance(target_table.columns, pd.MultiIndex):
                    # 查找日期和价格列
                    date_col = None
                    price_col = None
                    for col in target_table.columns:
                        if '日期' in str(col):
                            date_col = col
                        elif '价格' in str(col):
                            price_col = col
                else:
                    # 单级列索引的情况
                    date_col = '日期'
                    price_col = '价格'
                
                # 遍历表格数据，从前向后查找有效数据
                for index, row in target_table.iterrows():
                    if index < 3:
                        continue
                    
                    if isinstance(row.get(date_col), str) and row.get(date_col) == '日期':
                        continue
                    
                    date = row.get(date_col)
                    price = row.get(price_col)
                    
                    if pd.isna(date) or pd.isna(price):
                        continue
                    
                    date_str = None
                    if isinstance(date, str):
                        try:
                            if '-' in date:
                                date_obj = datetime.strptime(date, '%Y-%m-%d')
                            elif '/' in date:
                                date_obj = datetime.strptime(date, '%Y/%m/%d')
                            else:
                                date_obj = pd.to_datetime(date)
                            date_str = date_obj.strftime('%Y-%m-%d')
                        except Exception:
                            continue
                    else:
                        try:
                            date_str = date.strftime('%Y-%m-%d')
                        except Exception:
                            continue
                    
                    price_float = None
                    if isinstance(price, str):
                        price = price.replace(',', '')
                        try:
                            price_float = float(price)
                        except ValueError:
                            continue
                    else:
                        try:
                            price_float = float(price)
                        except Exception:
                            continue
                    
                    if date_str and price_float:
                        try:
                            row_date_obj = datetime.strptime(date_str, '%Y-%m-%d')
                            
                            # 🎯 根据不同市场设定安全收盘时间 (北京时间)
                            if '-JP' in symbol:
                                # 日本市场约14:00收盘，14:35数据已稳定
                                safe_close_time = row_date_obj + timedelta(hours=14, minutes=35)
                                market_name = "日本"
                            elif '-HK' in symbol:
                                # 香港市场约16:00收盘，16:35数据已稳定
                                safe_close_time = row_date_obj + timedelta(hours=16, minutes=35)
                                market_name = "香港"
                            elif '-EU' in symbol:
                                # 欧洲市场约23:30收盘，安全起见设为次日凌晨1:00
                                safe_close_time = row_date_obj + timedelta(days=1, hours=1, minutes=0)
                                market_name = "欧洲"
                            else:
                                # 默认美股，次日凌晨5:30
                                safe_close_time = row_date_obj + timedelta(days=1, hours=5, minutes=30)
                                market_name = "美股"
                                
                            if datetime.now() < safe_close_time:
                                print(f"  ⚠️  拦截: 发现尚未收盘的{market_name}实时/盘前数据 ({date_str})，已跳过以防污染历史账本")
                                continue
                        except Exception:
                            pass
                            
                        data.append({
                            '日期': date_str,
                            '价格': price_float
                        })
                        if len(data) >= max_records:
                            break
                
                if data:
                    df = pd.DataFrame(data)
                    df = df.drop_duplicates(subset=['日期'], keep='last')
                    df['日期'] = pd.to_datetime(df['日期'])
                    df = df.sort_values('日期', ascending=False)
                    df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                    
                    latest_date = df['日期'].iloc[0]
                    latest_price = df['价格'].iloc[0]
                    print(f"  [OK] 成功读取{symbol}数据，最新日期: {latest_date}，最新价格: {latest_price}")
                    
                    return df
                else:
                    print("  [ERROR] 未提取到数据")
                    return None
            else:
                print("  [ERROR] 未找到包含日期和价格的表格")
                return None
        
        except Exception as e:
            print(f"  [ERROR] 请求失败: {e}")
            return None

    def fetch_sina_historical_data(self, symbol, max_records=30):
        """从新浪财经爬取美股ETF的历史价格数据"""
        # 符号需要小写，且去掉任何特殊前缀
        clean_symbol = symbol.lower().replace('^', '')
        print(f"\n=== 新浪爬取 {symbol} 的价格数据 ===")
        url = f"https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK?symbol={clean_symbol}"
        
        try:
            response = requests.get(url, headers=self.woody_headers, timeout=15, verify=False)
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
    
    def get_lof_calibration_values(self, config):
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
                # 每次请求前等待2秒，避免被封
                import time
                time.sleep(2)
                
                response = requests.get(url, headers=self.woody_headers, timeout=15, verify=False)
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
    
