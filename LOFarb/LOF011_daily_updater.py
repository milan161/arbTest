# -*- coding: utf-8 -*-
# LOF01_daily_updater.py - 每日数据大一统更新器 (替代原011和部分012)
import os
import sys
import json
import yaml
import logging
from datetime import datetime, timedelta
import pandas as pd
import re

# 引入公共基座
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from arbcore.database.db_manager import DatabaseManager
from arbcore.fetchers.data_fetcher import data_fetcher
from arbcore.fetchers.woody_web_crawler import WoodyWebCrawler
from arbcore.fetchers.woody_api_service import WoodyAPIService

# 配置日志目录与双路输出（文件 + 终端）
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"LOF01_daily_updater_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True,  # 强制覆盖底层模块(如db_manager)被动生成的默认日志配置，让双路输出生效
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8-sig'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# 降低底层爬虫组件的日志输出级别，防止终端被大量细节刷屏
logging.getLogger('arbcore.fetchers.data_fetcher').setLevel(logging.WARNING)

class DailyUpdater:
    def __init__(self):
        self.db = DatabaseManager()
        self.config = self._load_config()
        self.woody_crawler = WoodyWebCrawler()
        
    def _load_config(self):
        config_file = os.path.join(os.path.dirname(__file__), "lof_config.yaml")
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def step1_and_2_fetch_woody_api(self):
        """步骤一：通过通用基座拉取Woody API，并生成JSON/CSV备份、步骤二：解析入库"""
        logger.info("=== 步骤一：获取 Woody API 数据，步骤二：解析入库 ===")
        codes = [str(fund.get('code', '')) for fund in self.config.get('funds', []) if str(fund.get('code', '')) != '161226']
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "woodyAPI")
        
        # 调用统一接口进行获取和解析
        return WoodyAPIService.fetch_and_process(self.db, codes, backup_dir, source_id='woody_lof')

    def step2_5_sync_yaml_with_latest_factors(self):
        """步骤2.5：将数据库中最新的真实仓位和权重同步反写回 lof_config.yaml"""
        logger.info("=== 步骤2.5：同步最新因子到 lof_config.yaml ===")
        try:
            conn = self.db._get_conn()
            yaml_updated = False
            
            for fund in self.config.get('funds', []):
                code = str(fund.get('code', ''))
                if not code: continue
                
                # 1. 查询最新仓位
                pos_df = pd.read_sql("SELECT position FROM fund_daily_factors WHERE fund_code=? ORDER BY date DESC LIMIT 1", conn, params=(code,))
                if not pos_df.empty and pd.notna(pos_df.iloc[0]['position']):
                    new_pos = float(pos_df.iloc[0]['position'])
                    if new_pos <= 1.5: new_pos = new_pos * 100  # 转换为百分比(防呆设计)
                    
                    old_pos = fund.get('holdings', {}).get('equity_ratio', 0)
                    if abs(new_pos - old_pos) > 0.01:
                        if 'holdings' not in fund: fund['holdings'] = {}
                        fund['holdings']['equity_ratio'] = round(new_pos, 2)
                        fund['holdings']['cash_ratio'] = round(100 - new_pos, 2)
                        fund['position'] = round(new_pos, 2)
                        yaml_updated = True
                        logger.info(f"🔄 [{code}] YAML仓位已同步: {old_pos}% -> {new_pos:.2f}%")
                
                # 2. 查询最新权重
                weight_df = pd.read_sql("SELECT underlying_symbol, weight FROM fund_basket_weights WHERE fund_code=? AND date=(SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)", conn, params=(code, code))
                if not weight_df.empty:
                    db_weights = {row['underlying_symbol'].replace('^', ''): float(row['weight']) for _, row in weight_df.iterrows() if pd.notna(row['weight'])}
                    
                    for port_key in ['valuation_portfolio', 'hedging_portfolio']:
                        for item in fund.get(port_key, []):
                            sym = item.get('symbol', '').replace('^', '')
                            if sym in db_weights:
                                new_w = db_weights[sym]
                                old_w = item.get('weight', 0)
                                if abs(new_w - old_w) > 0.01:
                                    item['weight'] = round(new_w, 2)
                                    yaml_updated = True
                                    logger.info(f"🔄 [{code}] YAML权重已同步 ({sym}): {old_w}% -> {new_w:.2f}%")
            conn.close()
            
            if yaml_updated:
                config_file = os.path.join(os.path.dirname(__file__), "lof_config.yaml")
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
                logger.info("✅ lof_config.yaml 文件已成功覆写更新！")
            else:
                logger.info("✅ 经对比，YAML中已是最新仓位权重，无需覆写。")
                
        except Exception as e:
            logger.error(f"❌ 同步YAML配置失败: {e}")

    def step3_fetch_exchange_rate(self):
        """步骤三：抓取汇率（人民币中间价）存入库"""
        logger.info("=== 步骤三：抓取汇率（人民币中间价） ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 1. 抓取汇率
        if self.db.is_access_synced_today(today_str, source='official_exchange_rate'):
            logger.info("✅ 今日已获取过人民币中间价，为防封号从本地缓存跳过...")
        else:
            exchange_rate_data = data_fetcher.fetch_official_exchange_rate()
            if exchange_rate_data:
                date_info = exchange_rate_data.get('日期')
                try:
                    # 统一日期格式
                    date_info = pd.to_datetime(str(date_info)).strftime('%Y-%m-%d')
                except:
                    date_info = today_str
                    
                rate = exchange_rate_data.get('人民币中间价')
                if rate:
                    self.db.upsert_exchange_rate(date_info, float(rate))
                    self.db.mark_access_synced(today_str, source='official_exchange_rate')
                    logger.info(f"✅ 人民币中间价入库: {date_info} -> {rate}")
                else:
                    logger.error("❌ 严重告警：获取人民币中间价为空，估值将无法计算！")

    def _safe_save_fund_data(self, date_str, fund_code, price=None, nav=None):
        """安全合并保存 fund 数据，防止 price 和 nav 互相覆盖导致对方变成 NULL"""
        conn = self.db._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT price, nav FROM fund_data WHERE date=? AND fund_code=?", (date_str, fund_code))
            row = cursor.fetchone()
            
            exist_price = row[0] if row and row[0] is not None else None
            exist_nav = row[1] if row and row[1] is not None else None
            
            new_price = price if price is not None else exist_price
            new_nav = nav if nav is not None else exist_nav
            
            premium = None
            if new_price is not None and new_nav is not None and float(new_nav) > 0:
                premium = (float(new_price) - float(new_nav)) / float(new_nav) * 100
                
            self.db.save_fund_data(date=date_str, fund_code=fund_code, price=new_price, nav=new_nav, premium=premium)
        finally:
            conn.close()

    def step4_fetch_lof_market(self):
        """步骤四：抓取各基金的净值和收盘价"""
        logger.info("=== 步骤四：抓取各基金最新净值和收盘价 ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        current_hour = datetime.now().hour

        # 澄清：净值(NAV)来自东财，收盘价(price)来自新浪
        for fund in self.config.get('funds', []):
            code = str(fund.get('code', ''))
            if not code:
                continue
                
            # --- 1. 获取新浪收盘价 ---
            latest_date = None
            t_minus_1_date = None
            if self.db.is_access_synced_today(today_str, source=f'lof_price_{code}'):
                logger.info(f"✅ [{code}] 今日已获取过历史收盘价，跳过新浪接口...")
                conn = self.db._get_conn()
                cursor = conn.cursor()
                cursor.execute("SELECT date FROM fund_data WHERE fund_code = ? AND price IS NOT NULL ORDER BY date DESC LIMIT 2", (code,))
                rows = cursor.fetchall()
                if rows and len(rows) > 0:
                    latest_date = rows[0][0]
                if rows and len(rows) > 1:
                    t_minus_1_date = rows[1][0]
                conn.close()
            else:
                price_df = data_fetcher.fetch_lof_price_data(code)
                if price_df is not None and not price_df.empty:
                    latest_row = price_df.iloc[0]
                    latest_date = pd.to_datetime(latest_row['日期']).strftime('%Y-%m-%d')
                    if len(price_df) > 1:
                        t_minus_1_date = pd.to_datetime(price_df.iloc[1]['日期']).strftime('%Y-%m-%d')
                    latest_price = latest_row['LOF交易价格']
                    logger.info(f"✅ [{code}] 最新收盘价: {latest_date} -> {latest_price}")
                    for _, row in price_df.iterrows():
                        d_str = pd.to_datetime(row['日期']).strftime('%Y-%m-%d')
                        self._safe_save_fund_data(date_str=d_str, fund_code=code, price=row['LOF交易价格'])
                    self.db.mark_access_synced(today_str, source=f'lof_price_{code}')
                else:
                    logger.warning(f"⚠️ [{code}] 未获取到历史收盘价数据 (新浪接口异常)。")

            # --- 2. 获取东财净值 ---
            def get_prev_trading_day(dt):
                t = dt - timedelta(days=1)
                while t.weekday() >= 5: t -= timedelta(days=1)
                return t
                
            t_1_date = get_prev_trading_day(datetime.now())
            t_2_date = get_prev_trading_day(t_1_date)
            
            target_nav_date = t_1_date.strftime('%Y-%m-%d')
            # 15:00之前预期只有T-2的净值，15:00之后预期会有T-1的净值
            expected_nav_date = t_2_date.strftime('%Y-%m-%d') if current_hour < 15 else t_1_date.strftime('%Y-%m-%d')
            
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM fund_data WHERE fund_code = ? AND nav IS NOT NULL", (code,))
            max_nav_row = cursor.fetchone()
            conn.close()
            
            db_max_nav_date = max_nav_row[0] if max_nav_row and max_nav_row[0] else "2000-01-01"
            
            if db_max_nav_date >= expected_nav_date:
                if current_hour < 15:
                    logger.info(f"⏳ [{code}] 当前未到15:00，T-1净值未发。本地已拥有T-2及之前最新净值({db_max_nav_date})，暂不请求东财。")
                else:
                    logger.info(f"✅ [{code}] 数据库已存在预期最新净值 ({db_max_nav_date})，跳过东财接口...")
                self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
                continue
                
            logger.info(f"🔍 [{code}] 数据库最新净值({db_max_nav_date})落后于预期进度({expected_nav_date})，前往东财获取...")
            nav_dict = data_fetcher.fetch_lof_nav_data(code)
            if nav_dict:
                latest_nav_date = sorted(nav_dict.keys(), reverse=True)[0]
                latest_nav = nav_dict[latest_nav_date]
                logger.info(f"✅ [{code}] 获取到净值: {latest_nav_date} -> {latest_nav}")
                
                for d_str, nav_val in nav_dict.items():
                    self._safe_save_fund_data(date_str=d_str, fund_code=code, nav=nav_val)
                
                if latest_nav_date >= expected_nav_date:
                    self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
            else:
                logger.warning(f"⚠️ [{code}] 东财接口未返回任何净值数据。")

    def step5_fetch_usa_market_data(self):
        """步骤五：抓取美股市场交易数据（标准ETF、期货、指数）"""
        logger.info("=== 步骤五：抓取美股市场交易数据（标准ETF、期货、指数） ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 智能检查：如果 index_daily 表里根本没数据，说明之前被 access_sync 拦截漏抓了，强制解除今日防封号限制
        conn = self.db._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM index_daily")
        index_count = cursor.fetchone()[0]
        conn.close()
        
        if self.db.is_access_synced_today(today_str, source='usa_market_data_sina') and index_count > 0:
            logger.info("✅ 今日已获取过新浪美股市场数据，为防封号跳过...")
            return

        standard_etf_symbols = set()
        index_symbols = set()
        
        # 预定义非ETF名单，防止误当做美股ETF爬取（拦截 _settle 后缀污染）
        future_tickers = {'GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ', 'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle'}
        index_tickers = {'INX', 'NDX', 'DJI', '.INX', '.NDX', '.DJI'}
        
        # 智能提取所有底层 ETF (过滤掉带后缀的衍生品，只取 GLD, USO, SPY 等根资产)
        for fund in self.config.get('funds', []):
            for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                sym = item.get('symbol', '').replace('^', '').split('-')[0]
                if not sym: continue
                if sym in future_tickers:
                    continue  # 期货行情由专门的结算价接口获取，不走美股API
                elif sym in index_tickers or sym.startswith('.'):
                    clean_sym = f".{sym.replace('.', '')}"
                    index_symbols.add(clean_sym)
                else:
                    standard_etf_symbols.add(sym)
                    
            if fund.get('trade_etf'):
                for s in str(fund.get('trade_etf')).replace('，', ',').split(','):
                    s = s.strip().upper()
                    if s and s not in future_tickers and s not in index_tickers and not s.startswith('.'):
                        standard_etf_symbols.add(s)
            # 提取纯净指数
            idx_url = fund.get('sina_index_url', '')
            idx_sym = None
            if idx_url:
                # 兼容新浪各种指数链接格式 (如 quotes/.INX.html)
                m = re.search(r'(?:symbol=|list=gb_|quotes/)([.a-zA-Z0-9]+)', idx_url, re.IGNORECASE)
                if m:
                    raw_sym = m.group(1).upper().replace('.HTML', '')
                    idx_sym = f".{raw_sym}" if not raw_sym.startswith('.') else raw_sym
                    
            if not idx_sym and fund.get('category', '') == '指数':
                trade_etf = str(fund.get('trade_etf', '')).upper()
                if 'QQQ' in trade_etf: idx_sym = '.NDX'
                elif 'SPY' in trade_etf: idx_sym = '.INX'
                
            if idx_sym:
                index_symbols.add(idx_sym)
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')
        
        # --- 1. 抓取标准ETF ---
        missing_etfs = []
        for sym in standard_etf_symbols:
            import time
            df = None
            # 增加 3 次网络防抖重试机制，防止 USO 偶发的 Response ended prematurely
            for attempt in range(3):
                df = data_fetcher.fetch_sina_us_stock_historical_data(sym, start_date=start_date, end_date=today_str)
                if df is not None and not df.empty:
                    break
                if attempt < 2:
                    logger.warning(f"⏳ [ETF] {sym} 第 {attempt+1} 次抓取失败，2秒后准备重试...")
                    time.sleep(2)
                    
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d')
                    price = row['close']
                    if price > 0: self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=price)
                logger.info(f"✅ [ETF] {sym} 历史行情入库完成。")
            else:
                missing_etfs.append(sym)
        if missing_etfs:
            logger.error(f"🚨 健壮性告警：以上标准 ETF 数据缺失，将会导致 012 算不出最新估值：{', '.join(missing_etfs)}")
            
        # --- 2. 抓取指数 ---
        missing_indices = []
        # 极简模式：只取最近几天的记录以确保能拿到上一个交易日，不浪费资源请求长线历史
        index_start_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        for sym in index_symbols:
            import time
            df = None
            # 恢复原生模式：直接使用带小数点的符号 (如 .NDX) 获取，剔除自作多情的轮询
            for attempt in range(3):
                df = data_fetcher.fetch_sina_us_stock_historical_data(sym, start_date=index_start_date, end_date=today_str)
                if df is not None and not df.empty:
                    break
                if attempt < 2:
                    time.sleep(1)
                
            if df is not None and not df.empty:
                # 精准提取上一个交易日最新收盘价
                latest_row = df.sort_values('date', ascending=True).iloc[-1]
                date_str = latest_row['date'].strftime('%Y-%m-%d')
                price = latest_row['close']
                if price > 0: 
                    self.db.upsert_index_price(date=date_str, symbol=sym, price=price)
                logger.info(f"✅ [指数] {sym} 极简入库完成 ({date_str} 收盘价 -> {price})。")
            else:
                missing_indices.append(sym)
        if missing_indices:
            logger.error(f"🚨 健壮性告警：以上纯净指数数据缺失，将会导致 012 算不出最新估值：{', '.join(missing_indices)}")
            
        # --- 3. 抓取期货结算价 ---
        futures_data = data_fetcher.get_futures_settlement_data()
        t_minus_1 = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        for fut in futures_data:
            sym, settle = fut.get('symbol'), fut.get('settle')
            if sym and settle:
                self.db.upsert_futures_daily(date=t_minus_1, symbol=sym, settle_price=float(settle))
                logger.info(f"✅ [期货] {t_minus_1} {sym} 结算价 -> {settle} 入库完成。")
        
        # 统一标记
        self.db.mark_access_synced(today_str, source='usa_market_data_sina')

    def step6_fetch_woody_regional_etfs(self):
        """步骤六：抓取 Woody 特有的区域变种虚拟 ETF (如 ^GLD-EU) 历史行情"""
        logger.info("=== 步骤六：抓取 Woody 区域变种虚拟 ETF 历史行情 ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        if self.db.is_access_synced_today(today_str, source='regional_etf'):
            logger.info("✅ 今日已获取过 Woody 区域变种 ETF 行情，为防封号跳过...")
            return

        regional_etfs = set()
        
        # 智能提取所有带有 ^ 前缀的区域虚拟 ETF
        for fund in self.config.get('funds', []):
            for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                sym = item.get('symbol', '')
                if sym.startswith('^'):
                    regional_etfs.add(sym)
                    
        # 兜底：如果没提取到，给个默认集
        if not regional_etfs:
            regional_etfs = {'^GLD-EU', '^GLD-JP', '^USO-EU', '^USO-JP', '^USO-HK'}

        missing_etfs = []
        for sym in regional_etfs:
            # 每次爬取最近 10 天的历史数据，覆盖假期停机的缺口
            df = self.woody_crawler.fetch_woody_historical_data(sym, max_records=10)
            if df is not None and not df.empty:
                saved_count = 0
                for _, row in df.iterrows():
                    date_str = row['日期']
                    price = row['价格']
                    if price > 0:
                        self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=price)
                        saved_count += 1
                logger.info(f"✅ 区域变种 [{sym}] 历史行情入库完成，共更新 {saved_count} 天。")
            else:
                missing_etfs.append(sym)
                
        if missing_etfs:
            logger.error(f"🚨 健壮性告警：以下 Woody 区域变种 ETF 数据抓取失败：{', '.join(missing_etfs)}")
        else:
            self.db.mark_access_synced(today_str, source='regional_etf')

    def run(self):
        logger.info("🚀 开始执行每日数据大一统更新流水线...")
        self.step1_and_2_fetch_woody_api()
        self.step2_5_sync_yaml_with_latest_factors()
            
        self.step3_fetch_exchange_rate()
        self.step4_fetch_lof_market()
        self.step5_fetch_usa_market_data()
        self.step6_fetch_woody_regional_etfs()
        logger.info("🎉 流水线执行完毕，数据大盘一切就绪！")

if __name__ == "__main__":
    DailyUpdater().run()
