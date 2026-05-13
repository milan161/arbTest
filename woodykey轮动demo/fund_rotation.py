import csv
import sys
import pandas as pd
from telegram import FetchPalmmicroData
import json
import webbrowser
import os
import time
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入数据获取器
from arbcore.fetchers.data_fetcher import data_fetcher

def read_etf_list():
    """读取ETFlist.csv文件，返回两组基金代码"""
    groups = {1: set(), 2: set()}
    with open('ETFlist.csv', 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            group = int(row['组别'])
            lof_code = row['LOF基金代码']
            # 添加SZ前缀，因为API需要SZ开头的代码
            if not lof_code.startswith('SZ'):
                lof_code = f'SZ{lof_code}'
            groups[group].add(lof_code)
    # 转换为逗号分隔的字符串
    group1_codes = ','.join(groups[1])
    group2_codes = ','.join(groups[2])
    return group1_codes, group2_codes

def fetch_fund_data(codes):
    """调用API获取基金数据"""
    result = FetchPalmmicroData(codes)
    return result

def save_data_to_json(data):
    """将数据保存为带有时间戳的JSON文件"""
    # 生成时间戳
    timestamp = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f'Data_woodyAPI_{timestamp}.json'
    
    # 提取真正的基金数据
    fund_data = data.get('text', data) if isinstance(data, dict) else data
    
    # 保存到JSON文件
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(fund_data, f, ensure_ascii=False, indent=2)
    
    print(f"数据已保存到 {filename}")
    return filename

def fetch_sina_data(fund_code, etf_symbol, dates=None):
    """从新浪获取基金收盘价和ETF收盘价
    
    Args:
        fund_code: 基金代码
        etf_symbol: ETF代码
        dates: 需要获取的日期列表
    
    Returns:
        dict: 包含各日期收盘价的数据
    """
    data = {
        'fund_close_prices': {},
        'etf_close_prices': {}
    }
    
    # 获取基金收盘价
    try:
        lof_price_df = data_fetcher.fetch_lof_price_data(fund_code.lstrip('SZ'))
        if lof_price_df is not None and not lof_price_df.empty:
            # 转换日期格式
            lof_price_df['日期'] = pd.to_datetime(lof_price_df['日期']).dt.strftime('%Y-%m-%d')
            
            # 如果指定了日期，只获取这些日期的数据
            if dates:
                for date in dates:
                    date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime) else date
                    if date_str in lof_price_df['日期'].values:
                        price = lof_price_df[lof_price_df['日期'] == date_str]['LOF交易价格'].iloc[0]
                        data['fund_close_prices'][date_str] = price
                        print(f"基金 {fund_code} {date_str} 收盘价: {price}")
            else:
                # 获取最新的三个交易日的数据
                for i in range(min(3, len(lof_price_df))):
                    date = lof_price_df.iloc[i]['日期']
                    price = lof_price_df.iloc[i]['LOF交易价格']
                    data['fund_close_prices'][date] = price
                    print(f"基金 {fund_code} {date} 收盘价: {price}")
    except Exception as e:
        print(f"获取基金收盘价失败: {e}")
    
    # 获取ETF收盘价
    try:
        if etf_symbol and etf_symbol in ['QQQ', 'XOP', 'USO', 'GLD']:
            # 计算日期范围
            if dates:
                start_date = min(dates).strftime('%Y-%m-%d') if isinstance(dates[0], datetime) else min(dates)
                end_date = max(dates).strftime('%Y-%m-%d') if isinstance(dates[0], datetime) else max(dates)
            else:
                end_date = datetime.now().date().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=14)).date().strftime('%Y-%m-%d')
            
            etf_df = data_fetcher.fetch_sina_us_stock_historical_data(etf_symbol, start_date, end_date)
            if etf_df is not None and not etf_df.empty:
                # 转换日期格式
                etf_df['date'] = etf_df['date'].dt.strftime('%Y-%m-%d')
                
                # 如果指定了日期，只获取这些日期的数据
                if dates:
                    for date in dates:
                        date_str = date.strftime('%Y-%m-%d') if isinstance(date, datetime) else date
                        if date_str in etf_df['date'].values:
                            price = etf_df[etf_df['date'] == date_str]['close'].iloc[0]
                            data['etf_close_prices'][date_str] = price
                            print(f"ETF {etf_symbol} {date_str} 收盘价: {price}")
                else:
                    # 获取最新的两个交易日的数据
                    for i in range(min(2, len(etf_df))):
                        date = etf_df.iloc[-(i+1)]['date']
                        price = etf_df.iloc[-(i+1)]['close']
                        data['etf_close_prices'][date] = price
                        print(f"ETF {etf_symbol} {date} 收盘价: {price}")
    except Exception as e:
        print(f"获取ETF收盘价失败: {e}")
    
    return data

def generate_html(data, group1_codes, group2_codes):
    """生成HTML页面展示数据"""
    html = '''
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>基金轮动套利数据</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: white;
                margin: 20px;
                padding: 20px;
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .group {
                margin-bottom: 30px;
                padding: 20px;
                border: 1px solid #ddd;
                border-radius: 5px;
                background-color: #f9f9f9;
            }
            h2 {
                color: #555;
                border-bottom: 1px solid #ddd;
                padding-bottom: 10px;
            }
            .fund-table {
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
                background-color: white;
            }
            .fund-table th,
            .fund-table td {
                border: 1px solid #ddd;
                padding: 8px;
                text-align: center;
            }
            .fund-table th {
                background-color: #f2f2f2;
                font-weight: bold;
            }
            .fund-table tr:nth-child(even) {
                background-color: #f9f9f9;
            }
            .highlight {
                background-color: #fff3cd;
                font-weight: bold;
            }
        </style>
    </head>
    <body>
        <h1>基金轮动套利数据</h1>
    '''
    
    # 提取真正的基金数据
    fund_data = data.get('text', data) if isinstance(data, dict) else data
    if not isinstance(fund_data, dict):
        fund_data = {}
    
    # 处理第一组数据
    html += f'''<div class="group">
        <h2>第一组基金 (代码: {group1_codes})</h2>
    '''
    
    # 获取第一组的基金代码列表
    group1_code_list = group1_codes.split(',')
    for code in group1_code_list:
        if code in fund_data:
            fund_info = fund_data[code]
            if isinstance(fund_info, dict):
                # 获取日期
                if code == 'SZ162411':
                    # 162411的基准日固定为4-21日
                    base_date = '2026-04-21'
                else:
                    base_date = fund_info.get('date', datetime.now().date().strftime('%Y-%m-%d'))
                
                # 确保日期格式正确
                if isinstance(base_date, str):
                    base_date = base_date.replace('/', '-')
                
                # 生成三天的日期（交易日、估值日、基准日）
                dates = []
                try:
                    base_date_obj = datetime.strptime(base_date, '%Y-%m-%d')
                    # 交易日（今天）
                    today = datetime.now().date()
                    dates.append(today.strftime('%Y-%m-%d'))
                    # 估值日（今天的前一天）
                    val_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                    dates.append(val_date)
                    # 基准日（API返回的日期）
                    dates.append(base_date)
                except:
                    # 如果日期解析失败，使用今天、昨天和前天
                    today = datetime.now().date()
                    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                    day_before_yesterday = (today - timedelta(days=2)).strftime('%Y-%m-%d')
                    dates = [today.strftime('%Y-%m-%d'), yesterday, day_before_yesterday]
                
                # 获取新浪数据
                etf_symbol = fund_info.get('symbol_hedge', '')
                sina_data = fetch_sina_data(code, etf_symbol, dates)
                
                html += f'''<table class="fund-table">
                    <tr>
                        <th>项目</th>
                        <th>{code}</th>
                        <th>仓位</th>
                        <th>汇率</th>
                        <th>基金净值</th>
                        <th>对冲ETF收盘价</th>
                        <th>官方估值</th>
                        <th>基金收盘价</th>
                        <th>对冲值</th>
                    </tr>
                '''
                
                # 交易日行
                today_date = dates[0]
                today_fund_price = sina_data['fund_close_prices'].get(today_date, 'N/A')
                html += f'''
                    <tr>
                        <td>交易日</td>
                        <td>{today_date.replace('-', '/')}</td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td class="highlight">{sina_data['etf_close_prices'].get(today_date, 'N/A')}</td>
                        <td></td>
                        <td class="highlight">{today_fund_price}</td>
                        <td></td>
                    </tr>
                '''
                
                # 估值日行
                val_date = dates[1]
                val_etf_price = sina_data['etf_close_prices'].get(val_date, 'N/A')
                val_fund_price = sina_data['fund_close_prices'].get(val_date, 'N/A')
                html += f'''
                    <tr>
                        <td>估值日</td>
                        <td>{val_date.replace('-', '/')}</td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td class="highlight">{val_etf_price}</td>
                        <td></td>
                        <td class="highlight">{val_fund_price}</td>
                        <td></td>
                    </tr>
                '''
                
                # 基准日行
                base_date_str = dates[2]
                base_etf_price = sina_data['etf_close_prices'].get(base_date_str, 'N/A')
                base_fund_price = sina_data['fund_close_prices'].get(base_date_str, 'N/A')
                html += f'''
                    <tr>
                        <td>基准日</td>
                        <td>{base_date_str.replace('-', '/')}</td>
                        <td>{fund_info.get('position', 'N/A')}</td>
                        <td>{fund_info.get('CNY', 'N/A')}</td>
                        <td>{fund_info.get('netvalue', 'N/A')}</td>
                        <td class="highlight">{base_etf_price}</td>
                        <td></td>
                        <td class="highlight">{base_fund_price}</td>
                        <td>{fund_info.get('hedge', 'N/A')}</td>
                    </tr>
                '''
                
                html += '''</table>
                '''
    
    html += '''</div>'''
    
    # 处理第二组数据
    html += f'''<div class="group">
        <h2>第二组基金 (代码: {group2_codes})</h2>
    '''
    
    # 获取第二组的基金代码列表
    group2_code_list = group2_codes.split(',')
    for code in group2_code_list:
        if code in fund_data:
            fund_info = fund_data[code]
            if isinstance(fund_info, dict):
                # 获取日期
                if code == 'SZ162411':
                    # 162411的基准日固定为4-21日
                    base_date = '2026-04-21'
                else:
                    base_date = fund_info.get('date', datetime.now().date().strftime('%Y-%m-%d'))
                
                # 确保日期格式正确
                if isinstance(base_date, str):
                    base_date = base_date.replace('/', '-')
                
                # 生成三天的日期（交易日、估值日、基准日）
                dates = []
                try:
                    base_date_obj = datetime.strptime(base_date, '%Y-%m-%d')
                    # 交易日（今天）
                    today = datetime.now().date()
                    dates.append(today.strftime('%Y-%m-%d'))
                    # 估值日（今天的前一天）
                    val_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                    dates.append(val_date)
                    # 基准日（API返回的日期）
                    dates.append(base_date)
                except:
                    # 如果日期解析失败，使用今天、昨天和前天
                    today = datetime.now().date()
                    yesterday = (today - timedelta(days=1)).strftime('%Y-%m-%d')
                    day_before_yesterday = (today - timedelta(days=2)).strftime('%Y-%m-%d')
                    dates = [today.strftime('%Y-%m-%d'), yesterday, day_before_yesterday]
                
                # 获取新浪数据
                etf_symbol = fund_info.get('symbol_hedge', '')
                sina_data = fetch_sina_data(code, etf_symbol, dates)
                
                html += f'''<table class="fund-table">
                    <tr>
                        <th>项目</th>
                        <th>{code}</th>
                        <th>仓位</th>
                        <th>汇率</th>
                        <th>基金净值</th>
                        <th>对冲ETF收盘价</th>
                        <th>官方估值</th>
                        <th>基金收盘价</th>
                        <th>对冲值</th>
                    </tr>
                '''
                
                # 交易日行
                today_date = dates[0]
                today_fund_price = sina_data['fund_close_prices'].get(today_date, 'N/A')
                html += f'''
                    <tr>
                        <td>交易日</td>
                        <td>{today_date.replace('-', '/')}</td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td class="highlight">{sina_data['etf_close_prices'].get(today_date, 'N/A')}</td>
                        <td></td>
                        <td class="highlight">{today_fund_price}</td>
                        <td></td>
                    </tr>
                '''
                
                # 估值日行
                val_date = dates[1]
                val_etf_price = sina_data['etf_close_prices'].get(val_date, 'N/A')
                val_fund_price = sina_data['fund_close_prices'].get(val_date, 'N/A')
                html += f'''
                    <tr>
                        <td>估值日</td>
                        <td>{val_date.replace('-', '/')}</td>
                        <td></td>
                        <td></td>
                        <td></td>
                        <td class="highlight">{val_etf_price}</td>
                        <td></td>
                        <td class="highlight">{val_fund_price}</td>
                        <td></td>
                    </tr>
                '''
                
                # 基准日行
                base_date_str = dates[2]
                base_etf_price = sina_data['etf_close_prices'].get(base_date_str, 'N/A')
                base_fund_price = sina_data['fund_close_prices'].get(base_date_str, 'N/A')
                html += f'''
                    <tr>
                        <td>基准日</td>
                        <td>{base_date_str.replace('-', '/')}</td>
                        <td>{fund_info.get('position', 'N/A')}</td>
                        <td>{fund_info.get('CNY', 'N/A')}</td>
                        <td>{fund_info.get('netvalue', 'N/A')}</td>
                        <td class="highlight">{base_etf_price}</td>
                        <td></td>
                        <td class="highlight">{base_fund_price}</td>
                        <td>{fund_info.get('hedge', 'N/A')}</td>
                    </tr>
                '''
                
                html += '''</table>
                '''
    
    html += '''</div>
    </body>
    </html>'''
    
    return html

def main():
    # 读取ETF列表
    group1_codes, group2_codes = read_etf_list()
    print(f"第一组基金代码: {group1_codes}")
    print(f"第二组基金代码: {group2_codes}")
    
    # 合并所有代码
    all_codes = f"{group1_codes},{group2_codes}"
    print(f"所有基金代码: {all_codes}")
    
    # 获取基金数据
    print("正在获取基金数据...")
    data = fetch_fund_data(all_codes)
    
    if data:
        print("数据获取成功！")
        
        # 保存数据到JSON文件
        json_file = save_data_to_json(data)
        
        # 生成HTML页面
        html = generate_html(data, group1_codes, group2_codes)
        
        # 保存HTML文件
        html_file = 'fund_rotation_data.html'
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(html)
        
        # 打开浏览器展示
        file_path = os.path.abspath(html_file)
        webbrowser.open(f'file://{file_path}')
        print(f"数据已保存到 {html_file} 并在浏览器中打开")
    else:
        print("数据获取失败！")

if __name__ == "__main__":
    main()
