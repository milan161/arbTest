import requests
import pandas as pd
from datetime import datetime, timedelta
import logging

# 禁用urllib3的警告
requests.packages.urllib3.disable_warnings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataFetcher:
    """数据获取器，用于从各种来源获取数据"""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "X-Requested-With": "XMLHttpRequest",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }
    
    def fetch_official_exchange_rate(self, date=None):
        """从国家外汇管理局获取指定日期的人民币中间价"""
        url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"
        try:
            response = requests.get(url, headers=self.headers, proxies={}, timeout=30, verify=False)
            response.encoding = 'utf-8'
            if response.status_code == 200:
                data = response.json()
                date_info = ""
                if 'data' in data and 'lastDate' in data['data']:
                    date_info = data['data']['lastDate']
                logger.info(f"汇率数据日期: {date_info}")
                
                # 检查数据结构
                records = []
                if 'records' in data:
                    records = data['records']
                elif 'data' in data and 'records' in data['data']:
                    records = data['data']['records']
                
                logger.info(f"找到 {len(records)} 条汇率记录")
                
                # 遍历所有记录，查找美元兑人民币汇率
                for record in records:
                    if 'vrtName' in record and 'price' in record:
                        currency_name = record['vrtName']
                        rate = record['price']
                        if '美元' in currency_name or 'USD' in currency_name:
                            logger.info(f"{currency_name}: {rate}")
                            return {'日期': date_info.split(' ')[0], '人民币中间价': float(rate)}
            logger.error(f"获取汇率数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取汇率数据失败: {e}")
        return None
    
    def fetch_lof_nav_data(self, fund_code, existing_data=None):
        """从东财获取LOF基金历史净值数据
        
        Args:
            fund_code: LOF基金代码
            existing_data: 现有的数据，用于检查是否需要爬取
        
        Returns:
            dict: 包含日期和净值的字典
        """
        logger.info(f"从东财获取LOF基金 {fund_code} 历史净值数据")
        
        # 检查是否需要爬取
        if existing_data is not None:
            # 检查是否有最新数据
            today = datetime.now().date().strftime('%Y-%m-%d')
            if not existing_data.empty:
                latest_date = existing_data['日期'].max()
                if latest_date == today:
                    logger.info(f"已有最新数据，跳过爬取")
                    # 从现有数据中提取净值字典
                    nav_dict = {}
                    for idx, row in existing_data.iterrows():
                        if pd.notna(row.get('LOF净值')):
                            nav_dict[row['日期']] = row['LOF净值']
                    return nav_dict
        
        # 构建净值字典
        nav_dict = {}
        
        try:
            nav_headers = {'Referer': 'http://fundf10.eastmoney.com/'}
            nav_count = 0
            
            # 只需获取第1页(最近100个交易日)，足够覆盖30天的日更需求
            for page in range(1, 2):
                nav_url = f"http://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex={page}&pageSize=100"
                try:
                    nav_response = requests.get(nav_url, headers=nav_headers, timeout=10, verify=False)
                    nav_data = nav_response.json()
                    
                    if nav_data.get('Data') and nav_data['Data'].get('LSJZList'):
                        nav_list = nav_data['Data']['LSJZList']
                        if not nav_list:
                            break  # 数据已取完
                            
                        for item in nav_list:
                            date = item.get('FSRQ')
                            nav = item.get('DWJZ')
                            if date and nav:
                                nav_dict[date] = float(nav)
                                nav_count += 1
                    else:
                        break
                except Exception as e:
                    logger.error(f"第 {page} 页获取净值失败: {e}")
                    break
                    
            logger.info(f"成功获取到 {nav_count} 条净值记录！")
        except Exception as e:
            logger.error(f"获取净值数据时出错: {e}")
        
        return nav_dict
    
    def fetch_lof_price_data(self, fund_code, existing_data=None):
        """从新浪获取LOF基金历史收盘价格数据
        
        Args:
            fund_code: LOF基金代码
            existing_data: 现有的数据，用于检查是否需要爬取
        
        Returns:
            DataFrame: 包含LOF基金历史数据的DataFrame
        """
        logger.info(f"从新浪获取LOF基金 {fund_code} 历史收盘价格数据")
        
        # 检查是否需要爬取
        if existing_data is not None:
            # 检查是否有最新数据
            today = datetime.now().date().strftime('%Y-%m-%d')
            if not existing_data.empty:
                latest_date = existing_data['日期'].max()
                if latest_date == today:
                    logger.info(f"已有最新数据，跳过爬取")
                    return existing_data
        
        # 计算日期范围
        end_date = datetime.now().date()
        start_date = (datetime.now() - timedelta(days=30)).date()
        days_to_fetch = (end_date - start_date).days + 1
        days_to_fetch = max(days_to_fetch, 30)
        
        # 根据基金代码前缀确定交易所（50开头为上交所，16开头为深交所）
        exchange_prefix = 'sh' if fund_code.startswith('50') else 'sz'
        sina_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={exchange_prefix}{fund_code}&scale=240&ma=no&datalen={days_to_fetch}"
        logger.info(f"新浪API获取 {days_to_fetch} 天的数据")
        
        # 发送请求，添加重试机制
        max_retries = 3
        retry_count = 0
        
        sina_data = None
        while retry_count < max_retries:
            try:
                response = requests.get(sina_url, headers=self.headers, timeout=15, verify=False)
                logger.info(f"新浪API响应状态码: {response.status_code}")
                response.raise_for_status()  # 检查请求是否成功
                
                # 解析响应
                import json
                sina_data = response.json()
                break  # 请求成功，退出重试循环
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                retry_count += 1
                logger.error(f"获取新浪历史数据失败，正在重试 ({retry_count}/{max_retries}): {e}")
                time.sleep(3)  # 等待3秒后重试
            except Exception as e:
                logger.error(f"获取新浪历史数据失败: {e}")
                # 继续重试
                retry_count += 1
                if retry_count < max_retries:
                    logger.info(f"正在重试 ({retry_count}/{max_retries})")
                    time.sleep(3)
                else:
                    # 所有重试失败，无法获取数据
                    logger.error("所有重试失败，无法获取新浪的LOF历史收盘价格数据")
                    # 即使新浪失败，也继续处理，使用现有数据
                    sina_data = []
        
        if isinstance(sina_data, list):
            logger.info(f"找到 {len(sina_data)} 条新浪历史交易记录")
            
            # 解析新浪历史数据
            lof_data = []
            date_set = set()  # 用于跟踪已处理的日期
            
            # 获取今天的日期字符串
            today_str = datetime.now().date().strftime('%Y-%m-%d')
            
            for item in sina_data:
                date = item.get('day')  # 日期
                close = item.get('close')  # 收盘价
                
                if not date or not close:
                    continue
                
                # 检查是否为今天的数据，如果是，根据时间决定是否处理
                if date == today_str:
                    # 获取当前时间
                    now = datetime.now()
                    # 如果当前时间超过15:01，处理今天的数据作为收盘价
                    if now.hour > 15 or (now.hour == 15 and now.minute >= 1):
                        logger.info(f"处理今天({today_str})的收盘价数据")
                    else:
                        logger.info(f"跳过今天({today_str})的数据，由02模块处理")
                        continue
                
                # 跳过已经处理过的日期
                if date in date_set:
                    continue
                date_set.add(date)
                
                try:
                    close = float(close)  # 收盘价（历史数据）
                except ValueError:
                    continue
                
                lof_data.append({
                    '日期': date,
                    'LOF交易价格': close  # 历史收盘价
                })
            
            if lof_data:
                # 转换为DataFrame
                df = pd.DataFrame(lof_data)
                # 按日期排序（降序）
                df['日期'] = pd.to_datetime(df['日期'], format='%Y-%m-%d')
                df = df.sort_values('日期', ascending=False)
                # 保留完整的日期格式，包含年份
                df['日期'] = df['日期'].dt.strftime('%Y-%m-%d')
                
                logger.info(f"成功获取LOF基金 {fund_code} 历史收盘价格数据，共{len(df)}条记录")
                return df
            else:
                logger.warning("新浪返回的数据为空")
                return None
        else:
            logger.error("新浪返回的数据格式不正确")
            return None
    
    def fetch_index_data(self, indices=None):
        """从新浪获取指数数据
        
        Args:
            indices: 指数列表，默认为['.INX', '.NDX']
        
        Returns:
            dict: 包含指数数据的字典
        """
        logger.info("从新浪获取指数数据")
        
        if indices is None:
            indices = ['.INX', '.NDX']
        
        index_data = {}
        
        # 构建指数URL映射
        index_url_map = {
            '.INX': 'https://stock.finance.sina.com.cn/usstock/quotes/.INX.html',  # 标普500指数
            '.NDX': 'https://stock.finance.sina.com.cn/usstock/quotes/.NDX.html'  # 纳斯达克100指数
        }
        
        # 使用专门的新浪请求头
        sina_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        
        for idx in indices:
            if idx in index_url_map:
                url = index_url_map[idx]
                
                try:
                    response = requests.get(url, headers=sina_headers, timeout=15, verify=False)
                    response.encoding = 'utf-8'
                    if response.status_code == 200:
                        data_str = response.text
                        if data_str:
                            # 使用正则表达式提取指数价格
                            import re
                            # 匹配类似 "6616.85(0.08%)" 的模式
                            match = re.search(r'"([\d,]+\.\d+)\([^)]+\)"', data_str)
                            if match:
                                # 移除逗号，转换为浮点数
                                close_price_str = match.group(1).replace(',', '')
                                close_price = float(close_price_str)
                                index_data[idx] = close_price
                                logger.info(f"{idx} 指数价格: {close_price}")
                    else:
                        logger.error(f"请求 {idx} 指数数据失败，状态码: {response.status_code}")
                except Exception as e:
                    logger.error(f"获取 {idx} 指数数据失败: {e}")
        
        return index_data
    
    def get_futures_settlement_data(self):
        """从新浪获取期货结算价数据"""
        logger.info("从新浪获取期货结算价数据")
        
        futures_data = []
        headers = {
            'Referer': 'https://finance.sina.com.cn/'
        }
        
        # 使用新浪API获取期货数据
        url = "http://hq.sinajs.cn/list=hf_GC,hf_CL,hf_NQ,hf_ES"
        try:
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            response.encoding = 'gbk'
            if response.status_code == 200:
                for line in response.text.strip().split('\n'):
                    if 'hf_GC' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            yesterday_settlement = float(v[7])
                            logger.info(f"GC 结算价: {yesterday_settlement}")
                            futures_data.append({"symbol": "GC", "settle": yesterday_settlement})
                    elif 'hf_CL' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            yesterday_settlement = float(v[7])
                            logger.info(f"CL 结算价: {yesterday_settlement}")
                            futures_data.append({"symbol": "CL", "settle": yesterday_settlement})
                    elif 'hf_NQ' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            yesterday_settlement = float(v[7])
                            logger.info(f"NQ 结算价: {yesterday_settlement}")
                            futures_data.append({"symbol": "NQ", "settle": yesterday_settlement})
                    elif 'hf_ES' in line:
                        v = line.split('"')[1].split(',')
                        if len(v) >= 14:
                            yesterday_settlement = float(v[7])
                            logger.info(f"ES 结算价: {yesterday_settlement}")
                            futures_data.append({"symbol": "ES", "settle": yesterday_settlement})
            else:
                logger.error(f"请求期货数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取期货结算价失败: {e}")
        
        return futures_data
    
    def fetch_sina_us_stock_historical_data(self, symbol, start_date, end_date):
        """从新浪美股API获取标准ETF历史数据"""
        logger.info(f"从新浪获取美股历史数据: {symbol}")
        
        # 构建URL
        url = f"https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_{symbol}=/US_CalendarService.getMonthlyKLine?symbol={symbol}&start={start_date}&end={end_date}"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=15, verify=False)
            if response.status_code == 200:
                # 处理JSONP响应
                data_str = response.text
                data_str = data_str.split('=')[1].strip().rstrip(';')
                
                # 解析数据
                import json
                data = json.loads(data_str)
                
                # 转换为DataFrame
                df = pd.DataFrame(data, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                
                # 转换价格列为浮点数
                price_columns = ['open', 'high', 'low', 'close']
                for col in price_columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                logger.info(f"成功获取 {symbol} 历史数据，共 {len(df)} 条")
                return df
            else:
                logger.error(f"请求 {symbol} 历史数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取 {symbol} 历史数据失败: {e}")
        
        return None


# 创建全局实例
data_fetcher = DataFetcher()
