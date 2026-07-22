import requests
import pandas as pd
from datetime import datetime, timedelta
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
import re
import sys
import os

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 导入Woody网页爬虫
try:
    try:
        from .woody_web_crawler import WoodyWebCrawler
    except (ImportError, ValueError):
        try:
            from arbcore.fetchers.woody_web_crawler import WoodyWebCrawler
        except ImportError:
            from woody_web_crawler import WoodyWebCrawler
except ImportError as e:
    logger.warning(f"⚠️ 无法导入woody_web_crawler: {e}")
    logger.warning("   网页爬虫功能将不可用，但基础数据获取功能正常")
    class WoodyWebCrawler:
        def __init__(self, *args, **kwargs):
            logger.warning("⚠️ WoodyWebCrawler未安装，相关功能不可用")
        def get_data(self, *args, **kwargs):
            return None

# 禁用urllib3的警告
requests.packages.urllib3.disable_warnings()


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
        # 初始化Woody网页爬虫
        self.woody_crawler = WoodyWebCrawler()
        self._szse_blocked = False  # 新增：深交所全局熔断标志
        self._fx_cache = None       # [V10.1] 汇率内存缓存
        self._fx_cache_time = 0     # [V10.1] 缓存时间戳
    
    def sync_akshare_fund_status(self, db_manager):
        """
        【JSL专属】全局拉取并缓存全市场基金申赎状态和手续费。
        融合了 access_sync_status 单次阻断，每天最多只调用一次 AKShare API！
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        source_key = "akshare_fund_status"
        
        if db_manager.is_access_synced_today(today_str, source_key):
            logger.info("今日已成功同步 AKShare 申赎状态，触发防刷保护，直接使用数据库缓存。")
            return
            
        try:
            import akshare as ak
            logger.info("开始从 AKShare 拉取全市场基金申赎状态 (耗时较长，请稍候)...")
            fund_info = ak.fund_purchase_em()
            
            if not fund_info.empty:
                records = []
                for _, row in fund_info.iterrows():
                    purchase_fee = str(row.get('手续费', str(row.get('申购费率', '0%'))))
                    redemption_fee = str(row.get('赎回费率', '0.50%'))
                    
                    if redemption_fee == 'nan' or redemption_fee == '0%':
                        fund_type = str(row.get('基金类型', ''))
                        if '货币' in fund_type:
                            redemption_fee = '0%'
                        elif '债券' in fund_type:
                            redemption_fee = '0.10%'
                        else:
                            redemption_fee = '0.50%'
                            
                    # 日累计限定金额：东财返回的具体限额（元），如3000=限3千
                    limit_val = row.get('日累计限定金额')
                    try:
                        purchase_limit = float(limit_val) if limit_val is not None and str(limit_val) != 'nan' else None
                    except (ValueError, TypeError):
                        purchase_limit = None

                    records.append({
                        'fund_code': str(row.get('基金代码')),
                        'purchase_status': str(row.get('申购状态', '未知')),
                        'redemption_status': str(row.get('赎回状态', '未知')),
                        'purchase_fee': purchase_fee if purchase_fee != 'nan' else '0%',
                        'redemption_fee': redemption_fee if redemption_fee != 'nan' else '0.50%',
                        'purchase_limit': purchase_limit
                    })
                
                df_records = pd.DataFrame(records)
                db_manager.batch_save_fund_purchase_status(df_records)
                
                db_manager.mark_access_synced(today_str, source_key)
                logger.info(f"成功获取并缓存了 {len(df_records)} 只基金的状态数据！")
                
        except ImportError:
            logger.warning("AKShare 未安装，无法同步全市场申赎状态。")
        except Exception as e:
            logger.error(f"AKShare 申赎状态同步失败: {e}")

    def fetch_szse_fund_shares_only(self, fund_code):
        """
        【独家封装】从深交所官方API仅获取基金的场内份额（不获取净值）。
        仅支持深交所基金（通常以15或16开头）。
        """
        import random
        # 增加随机休眠，深交所反爬极其严格，低于2秒的高频并发会直接被防火墙切断连接
        time.sleep(random.uniform(2.0, 5.0))
        
        logger.info(f"从深交所官方API仅获取基金 {fund_code} 的场内份额")
        # 增加 random 参数，完美模拟真实浏览器请求，防止被缓存或拦截
        url = f"https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=1105&TABKEY=tab1&txtZqdm={fund_code}&random={random.random()}"
        
        # 终极伪装：完全模拟真实浏览器，增加应对 WAF 防火墙的特定 Header
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.szse.cn/market/fund/list/index.html",
            "X-Request-Type": "ajax",
            "X-Requested-With": "XMLHttpRequest",
            "Connection": "keep-alive",
            "Host": "www.szse.cn"
        }
        
        try:
            # 使用 Session 模式，应对部分 WAF 会校验 TCP 连接状态的要求
            session = requests.Session()
            response = session.get(url, headers=headers, timeout=10, verify=False, proxies={"http": None, "https": None})
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 0 and 'data' in data[0]:
                    fund_list = data[0]['data']
                    if fund_list and len(fund_list) > 0:
                        fund_info = fund_list[0]
                        nav_date = fund_info.get('jzrq', '')
                        shares = fund_info.get('ltfe', '') # 流通份额（场内份额）
                        
                        # 清洗深交所返回的千分位逗号
                        if isinstance(shares, str):
                            shares = shares.replace(',', '')
                        
                        logger.info(f"✅ [SZSE] {fund_code} 场内份额: {shares} ({nav_date})")
                        return {
                            'nav_date': nav_date,
                            'shares': float(shares) if shares else None
                        }
            logger.warning(f"⚠️ [SZSE] 未能查到 {fund_code} 的信息，可能不是深交所基金。")
        except Exception as e:
            # 拦截 RemoteDisconnected 异常，不抛出崩溃，打印温和提示
            logger.warning(f"⚠️ [SZSE] 深交所防火墙拦截了请求 (连接重置)。详细原因: {e}")
            self._szse_blocked = True  # 触发全局熔断
            logger.warning("🚨 [SZSE] 触发全局熔断机制！本次运行后续所有深市基金将不再尝试深交所API。")
        return None

    def fetch_official_exchange_rate(self, date=None):
        """从国家外汇管理局获取指定日期的人民币中间价，失败时回退到Woody网页"""
        logger.info("从国家外汇管理局获取人民币中间价")
        
        # 1. 尝试从国家外汇管理局获取
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
                
                # 遍历所有记录，查找美元和港币兑人民币汇率
                res_rates = {}
                for record in records:
                    if 'vrtName' in record and 'price' in record:
                        currency_name = record['vrtName']
                        rate = record['price']
                        if '美元' in currency_name or 'USD' in currency_name:
                            res_rates['usd'] = float(rate)
                        elif '港' in currency_name or 'HKD' in currency_name:
                            res_rates['hkd'] = float(rate)

                if 'usd' in res_rates:
                    logger.info(f"国家外汇管理局 - USD: {res_rates.get('usd')}, HKD: {res_rates.get('hkd')}")
                    # 规范化日期格式为 YYYY-MM-DD
                    raw_date = date_info.split(' ')[0]
                    try:
                        dt = datetime.strptime(raw_date, '%Y-%m-%d')
                        normalized_date = dt.strftime('%Y-%m-%d')
                    except:
                        normalized_date = raw_date  # 回退

                    return {
                        '日期': normalized_date,
                        '人民币中间价': res_rates.get('usd'),
                        'usd_cny_mid': res_rates.get('usd'),
                        'hkd_cny_mid': res_rates.get('hkd'),
                        '来源': '国家外汇管理局'
                    }

            logger.error(f"国家外汇管理局获取汇率数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"国家外汇管理局获取汇率数据失败: {e}")
        
        # 2. 回退到Woody网页
        logger.info("国家外汇管理局获取失败，尝试从Woody网页获取")
        try:
            woody_rates = self.woody_crawler.get_woody_exchange_rates()
            if woody_rates and 'USCNY' in woody_rates:
                uscnny_data = woody_rates['USCNY']
                current_date = datetime.now().date().strftime('%Y-%m-%d')
                logger.info(f"Woody网页 - 人民币中间价: {uscnny_data['rate']} (时间: {uscnny_data['time']})")
                return {
                    '日期': current_date,
                    '人民币中间价': uscnny_data['rate'],
                    '来源': 'Woody网页'
                }
        except Exception as e:
            logger.error(f"Woody网页获取汇率数据失败: {e}")
        
        return None

    def fetch_cny_spot_rate(self):
        """从新浪财经获取人民币在岸价（CNY）实时汇率
        
        [V10.1] 5分钟内存缓存：汇率日内变化极小，无需频繁请求。
        优先使用API接口，失败时自动回退到网页爬取，最后回退到Woody网页
        """
        # [V10.1] 5分钟缓存：汇率一天变不了几次，300秒TTL足够
        now = time.time()
        if self._fx_cache and (now - self._fx_cache_time) < 300:
            logger.debug(f"使用缓存汇率: {self._fx_cache.get('人民币在岸价')} (age={int(now - self._fx_cache_time)}s)")
            return self._fx_cache
        
        logger.info("从新浪财经获取人民币在岸价实时汇率")
        
        # 1. 尝试使用API接口
        try:
            # 新浪财经的在岸人民币汇率接口
            url = "https://hq.sinajs.cn/list=fx_susdcny"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'  # 新浪接口必须用GBK编码
            
            if response.status_code == 200:
                text = response.text.strip()
                if 'hq_str_fx_susdcny' in text:
                    # 解析新浪返回的数据格式
                    values = text.split('"')[1].split(',')
                    if len(values) >= 18:
                        update_time = values[0]        # 更新时间
                        spot_rate = float(values[1])   # 实时在岸价（第2个字段）
                        high_rate = float(values[2])   # 最高价
                        low_rate = float(values[3])    # 最低价
                        volume = values[4]             # 成交量
                        sell_rate = float(values[5])   # 卖出价
                        buy_rate = float(values[7])    # 买入价
                        currency_pair = values[9]      # 货币对
                        date = values[17]              # 日期
                        
                        logger.debug(f"API接口 - 人民币在岸价: {spot_rate} (更新时间: {update_time})")
                        result = {
                            '日期': date,
                            '时间': update_time,
                            '人民币在岸价': spot_rate,
                            '最高价': high_rate,
                            '最低价': low_rate,
                            '买入价': buy_rate,
                            '卖出价': sell_rate,
                            '成交量': volume,
                            '货币对': currency_pair,
                            '来源': 'API接口'
                        }
                        self._fx_cache = result
                        self._fx_cache_time = time.time()
                        return result
            logger.error(f"API接口获取人民币在岸价失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"API接口获取人民币在岸价失败: {e}")
        
        # 2. API失败，回退到Selenium网页爬取
        logger.info("API接口失败，尝试使用Selenium网页爬取")
        try:
            # 配置Chrome选项
            chrome_options = Options()
            chrome_options.add_argument('--headless')  # 无头模式，不显示浏览器
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36')
            
            # 启动浏览器
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            try:
                # 打开目标网页
                url = "https://finance.sina.com.cn/money/forex/hq/USDCNY.shtml"
                logger.info(f"打开网页: {url}")
                driver.get(url)
                
                # 等待页面加载完成
                time.sleep(5)  # 等待页面完全加载
                
                # 执行JavaScript获取页面中的所有文本内容
                page_text = driver.execute_script("return document.body.innerText")
                
                # 查找符合汇率格式的数字
                matches = re.findall(r'\b6\.\d{4}\b', page_text)
                if matches:
                    # 选择第一个匹配结果
                    spot_rate = float(matches[0])
                    current_time = datetime.now().strftime('%H:%M:%S')
                    current_date = datetime.now().date().strftime('%Y-%m-%d')
                    
                    logger.info(f"Selenium网页爬取 - 人民币在岸价: {spot_rate} (爬取时间: {current_time})")
                    result = {
                        '日期': current_date,
                        '时间': current_time,
                        '人民币在岸价': spot_rate,
                        '来源': 'Selenium网页爬取'
                    }
                    self._fx_cache = result
                    self._fx_cache_time = time.time()
                    return result
                else:
                    logger.error("Selenium网页爬取未能提取在岸价")
            except Exception as e:
                logger.error(f"Selenium网页爬取失败: {e}")
            finally:
                driver.quit()
        except Exception as e:
            logger.error(f"Selenium初始化失败: {e}")
        
        # 3. Selenium失败，回退到Woody网页
        logger.info("Selenium网页爬取失败，尝试从Woody网页获取")
        try:
            woody_rates = self.woody_crawler.get_woody_exchange_rates()
            if woody_rates and 'USDCNY' in woody_rates:
                usdcny_data = woody_rates['USDCNY']
                current_date = datetime.now().date().strftime('%Y-%m-%d')
                logger.info(f"Woody网页 - 人民币在岸价: {usdcny_data['rate']} (时间: {usdcny_data['time']})")
                result = {
                    '日期': current_date,
                    '时间': usdcny_data['time'],
                    '人民币在岸价': usdcny_data['rate'],
                    '来源': 'Woody网页'
                }
                self._fx_cache = result
                self._fx_cache_time = time.time()
                return result
        except Exception as e:
            logger.error(f"Woody网页获取汇率数据失败: {e}")
        
        return None

    def fetch_cnh_offshore_rate(self):
        """从新浪财经获取离岸人民币 CNH 实时汇率（Sina fx_susdcnh）
        
        返回: dict { '日期', '离岸价', '来源' } 或 None
        """
        logger.debug("从新浪财经获取离岸人民币 CNH 汇率")
        try:
            url = "https://hq.sinajs.cn/list=fx_susdcnh"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200 and 'hq_str_fx_susdcnh' in response.text:
                values = response.text.split('"')[1].split(',')
                if len(values) >= 18:
                    spot_rate = float(values[1])  # 第2个字段 = 实时离岸价
                    date = values[17]
                    logger.info(f"离岸人民币 CNH: {spot_rate} (日期: {date})")
                    return {
                        '日期': date,
                        '离岸价': spot_rate,
                        '来源': '新浪财经 fx_susdcnh'
                    }
        except Exception as e:
            logger.error(f"获取离岸人民币 CNH 失败: {e}")
        return None
    
    def fetch_ag0_from_sina(self):
        """从新浪获取 AG0（沪银连续期货）实时数据
        
        新浪 nf_AG0 返回格式 (44 fields):
        ar[0]=名称 ar[1]=今开 ar[2]=最高 ar[3]=最低 ar[4]=最新 ar[5]=昨收
        ar[6]=昨结1 ar[7]=昨结2 ar[8]=现价 ar[9]=结算价 ar[10]=昨结算
        ar[11]=涨跌1 ar[12]=涨跌2 ar[13]=成交量1 ar[14]=成交量2
        ar[15]=市场 ar[16]=品种 ar[17]=日期 ar[18]=时间
        ar[27]=VWAP ar[28]=均价 ar[29]=持仓量
        
        返回: dict { 'date', 'price', 'prev_settle', 'settle', 'vwap', 'volume', '持仓量', '来源' } 或 None
        """
        logger.debug("从新浪获取 AG0 期货实时数据")
        try:
            url = "http://hq.sinajs.cn/list=nf_AG0"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200 and 'hq_str_nf_AG0' in response.text:
                parts = response.text.split('"')[1].split(',')
                if len(parts) >= 30:
                    result = {
                        'date': parts[17],
                        'price': float(parts[8]),       # 最新价
                        'prev_settle': float(parts[10]), # 昨结算
                        'settle': float(parts[9]),       # 结算价
                        'vwap': float(parts[27]) if parts[27] else 0.0,  # VWAP
                        'volume': int(float(parts[14])) if parts[14] else 0,  # 成交量
                        'open_interest': int(float(parts[29])) if len(parts) > 29 and parts[29] else 0,  # 持仓量
                        '来源': '新浪 nf_AG0'
                    }
                    return result
        except Exception as e:
            logger.error(f"获取 AG0 失败: {e}")
        return None
    
    def fetch_si_from_sina(self):
        """从新浪获取 SI（COMEX 白银期货）实时数据
        
        新浪 hf_SI 返回格式:
        ar[0]=最新价 ar[7]=昨收 ar[12]=日期
        
        返回: dict { 'date', 'price', 'prev_close', '来源' } 或 None
        """
        logger.debug("从新浪获取 SI 期货实时数据")
        try:
            url = "http://hq.sinajs.cn/list=hf_SI"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200 and 'hq_str_hf_SI' in response.text:
                parts = response.text.split('"')[1].split(',')
                if len(parts) >= 13:
                    return {
                        'date': parts[12],
                        'price': float(parts[0]),       # 最新价（美元/盎司）
                        'prev_close': float(parts[7]),  # 昨收
                        '来源': '新浪 hf_SI'
                    }
        except Exception as e:
            logger.error(f"获取 SI 失败: {e}")
        return None
    
    def fetch_cnh_from_sina(self):
        """从新浪获取 CNH 实时汇率（备用，和 fetch_cnh_offshore_rate 相同）
        
        返回: dict { 'date', 'rate', '来源' } 或 None
        """
        logger.debug("从新浪获取 CNH 汇率实时数据")
        try:
            url = "http://hq.sinajs.cn/list=fx_susdcnh"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200 and 'hq_str_fx_susdcnh' in response.text:
                parts = response.text.split('"')[1].split(',')
                if len(parts) >= 18:
                    return {
                        'date': parts[17],
                        'rate': float(parts[1]),  # 实时离岸价
                        '来源': '新浪 fx_susdcnh'
                    }
        except Exception as e:
            logger.error(f"获取 CNH 失败: {e}")
        return None
    
    def fetch_jpy_cny_rate(self):
        """从新浪财经获取 JPY/CNY 日元兑人民币实时汇率
        
        [AI-2026-07-21] 修复：Sina 返回每1日元汇率（如 0.0416），
        乘以100转换为每100日元单位（如 4.16），与 VPS 数据和 DB 惯例一致。
        
        Returns:
            dict { '日期', '日元汇率', '来源' } 或 None
        """
        logger.info("从新浪财经获取 JPY/CNY 日元汇率")
        try:
            url = "https://hq.sinajs.cn/list=fx_sjpycny"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/"
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200 and 'hq_str_fx_sjpycny' in response.text:
                values = response.text.split('"')[1].split(',')
                if len(values) >= 18:
                    rate = float(values[1]) * 100  # [AI-2026-07-21] ×100 转为每100日元单位
                    date = values[17]
                    logger.info(f"JPY/CNY 日元汇率: {rate} (每100日元, 日期: {date})")
                    return {
                        '日期': date,
                        'jpy_cny_rate': rate,
                        '来源': '新浪财经 fx_sjpycny'
                    }
        except Exception as e:
            logger.error(f"获取 JPY/CNY 汇率失败: {e}")
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

            # [修复] 循环获取所有页面的数据，确保获取最新净值
            page = 1
            while True:
                nav_url = f"http://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex={page}&pageSize=100"
                try:
                    nav_response = requests.get(nav_url, headers=nav_headers, timeout=10, verify=False, proxies={"http": None, "https": None})
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

                        # [修复] 如果这一页数据少于100条，说明已经是最后一页
                        if len(nav_list) < 100:
                            break
                    else:
                        break

                    page += 1  # 继续获取下一页
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
        exchange_prefix = 'sh' if fund_code.startswith('5') else 'sz'
        sina_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={exchange_prefix}{fund_code}&scale=240&ma=no&datalen={days_to_fetch}"
        logger.info(f"新浪API获取 {days_to_fetch} 天的数据")
        
        # 发送请求，添加重试机制
        max_retries = 3
        retry_count = 0
        
        sina_data = None
        while retry_count < max_retries:
            try:
                response = requests.get(sina_url, headers=self.headers, timeout=15, verify=False, proxies={"http": None, "https": None})
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
                volume = item.get('volume', 0)  # 成交量
                
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
                    volume = float(volume) # 成交量
                except ValueError:
                    continue
                
                lof_data.append({
                    '日期': date,
                    'LOF交易价格': close,  # 历史收盘价
                    '成交量': volume       # 历史成交量
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
                    response = requests.get(url, headers=sina_headers, timeout=15, verify=False, proxies={"http": None, "https": None})
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
        """从新浪获取期货结算价数据（美股期货 + 内盘 AG0 沪银）"""
        logger.info("从新浪获取期货结算价数据")
        
        futures_data = []
        headers = {
            'Referer': 'https://finance.sina.com.cn/'
        }
        
        # [AI-2026-07-02] 美股期货 + 内盘期货（AG0 沪银）分开请求
        # 美股期货 URL
        url = "http://hq.sinajs.cn/list=hf_MGC,hf_GC,hf_CL,hf_NQ,hf_ES,hf_SI"
        try:
            response = requests.get(url, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response.encoding = 'gbk'
            if response.status_code == 200:
                for line in response.text.strip().split('\n'):
                    if not line: continue
                    try:
                        symbol = line.split('=')[0].split('_')[-1]
                        parts = line.split('"')[1].split(',')
                        if len(parts) >= 14:
                            close_price = float(parts[0])
                            settle_price = float(parts[7])
                            logger.info(f"{symbol} 收盘价: {close_price}, 结算价: {settle_price}")
                            futures_data.append({"symbol": symbol, "settle": settle_price, "close": close_price})
                    except Exception as e:
                        logger.error(f"解析期货行失败 {line}: {e}")
            else:
                logger.error(f"请求期货数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取期货数据失败: {e}")
        
        # [AI-2026-07-02] 内盘期货 AG0 沪银（新浪 nf_ 格式）
        try:
            url_cn = "http://hq.sinajs.cn/list=nf_AG0"
            response_cn = requests.get(url_cn, headers=headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            response_cn.encoding = 'gbk'
            if response_cn.status_code == 200:
                for line in response_cn.text.strip().split('\n'):
                    if not line: continue
                    try:
                        symbol = line.split('=')[0].split('_')[-1]
                        parts = line.split('"')[1].split(',')
                        if len(parts) >= 11:
                            # [AI-2026-07-03] 修复：parts[9]=今日结算价(VWAP/动态均价)，parts[10]=昨结算
                            # 昨结算(parts[10])是前一天的结算价，不能作为今日的 settle_price 存入
                            close_price = float(parts[8]) if len(parts) > 8 else None
                            settle_price = float(parts[9]) if len(parts) > 9 and parts[9] else None
                            volume = int(float(parts[14])) if len(parts) > 14 and parts[14] else None
                            if close_price or settle_price:
                                logger.info(f"{symbol} 收盘价: {close_price}, 结算价: {settle_price}")
                                futures_data.append({"symbol": symbol, "settle": settle_price, "close": close_price, "volume": volume})
                    except Exception as e:
                        logger.error(f"解析内盘期货行失败 {line}: {e}")
        except Exception as e:
            logger.error(f"获取内盘期货数据失败: {e}")
        
        return futures_data
    
    def fetch_sina_us_stock_historical_data(self, symbol, start_date, end_date):
        """从新浪美股API获取标准ETF和指数历史数据"""
        logger.info(f"从新浪获取美股历史数据: {symbol}")
        
        # 兼容处理：确保指数符号以点开头且为小写 (如 .inx)
        symbol_lower = str(symbol).lower()
        if symbol_lower.startswith('inx') or symbol_lower.startswith('ndx'):
            symbol_lower = f".{symbol_lower}"
            
        # 抛弃 JSONP 接口，改用稳定纯 JSON 日线接口
        url = f"https://stock.finance.sina.com.cn/usstock/api/json_v2.php/US_MinKService.getDailyK?symbol={symbol_lower}"
        
        try:
            # 核心修复：单独为这个请求补充新浪强校验的 Referer 头，突破防盗链拦截
            req_headers = self.headers.copy()
            req_headers['Referer'] = 'https://finance.sina.com.cn/'
            
            # 核心修复：强制忽略系统代理，直连新浪，彻底解决 WinError 10061 代理拒绝报错
            response = requests.get(url, headers=req_headers, timeout=15, verify=False, proxies={"http": None, "https": None})
            if response.status_code == 200:
                text = response.text.strip()
                if not text or text == 'null':
                    logger.error(f"获取 {symbol} 数据为空 (返回 null 或空字符串)")
                    return None
                
                # 解析数据
                import json
                data = json.loads(text)
                
                if not data:
                    logger.error(f"获取 {symbol} 返回空数组")
                    return None
                
                # 转换为DataFrame，适配新浪纯JSON接口的字段 (d, o, h, l, c, v)
                df = pd.DataFrame(data)
                df = df.rename(columns={'d': 'date', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'})
                
                df['date'] = pd.to_datetime(df['date'])
                
                # 在内存中按传入的起止日期进行过滤
                if start_date:
                    df = df[df['date'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['date'] <= pd.to_datetime(end_date)]
                    
                df = df.sort_values('date')
                
                # 转换价格列为浮点数
                price_columns = ['open', 'high', 'low', 'close']
                for col in price_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                logger.info(f"成功获取 {symbol} 历史数据，共 {len(df)} 条")
                return df
            else:
                logger.error(f"请求 {symbol} 历史数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取 {symbol} 历史数据失败: {e}")
        
        return None
    
    def fetch_sina_hk_stock_historical_data(self, symbol, start_date, end_date):
        """从腾讯港股API获取港股历史数据"""
        logger.info(f"从腾讯获取港股历史数据: {symbol}")

        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var=kline_dayqfq&param=hk{symbol},day,,,320,qfq&r=0.1"

        try:
            response = requests.get(url, timeout=15, verify=False, proxies={"http": None, "https": None})
            if response.status_code == 200:
                text = response.text.strip()

                if not text:
                    logger.error(f"获取港股 {symbol} 数据为空")
                    return None

                if text.startswith('kline_dayqfq='):
                    text = text[len('kline_dayqfq='):]

                import json
                data = json.loads(text)

                if data.get('code') != 0:
                    logger.error(f"获取港股 {symbol} 失败: {data.get('msg', 'Unknown error')}")
                    return None

                hk_data = data.get('data', {}).get(f'hk{symbol}', {})
                day_data = hk_data.get('day', [])

                if not day_data:
                    logger.error(f"获取港股 {symbol} 返回空数据")
                    return None

                # 修复：API返回的数据中有些行有7列（第7列是字典），需要统一为6列
                day_data = [row[:6] for row in day_data]
                
                df = pd.DataFrame(day_data)
                df.columns = ['date', 'open', 'high', 'low', 'close', 'volume']

                df['date'] = pd.to_datetime(df['date'])

                if start_date:
                    df = df[df['date'] >= pd.to_datetime(start_date)]
                if end_date:
                    df = df[df['date'] <= pd.to_datetime(end_date)]

                df = df.sort_values('date')

                price_columns = ['open', 'high', 'low', 'close', 'volume']
                for col in price_columns:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                logger.info(f"成功获取港股 {symbol} 历史数据，共 {len(df)} 条")
                return df
            else:
                logger.error(f"请求港股 {symbol} 历史数据失败，状态码: {response.status_code}")
        except Exception as e:
            logger.error(f"获取港股 {symbol} 历史数据失败: {e}")

        return None


# 创建全局实例
data_fetcher = DataFetcher()
