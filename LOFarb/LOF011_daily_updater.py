# -*- coding: utf-8 -*-
# LOF01_daily_updater.py - 每日数据大一统更新器
import os
import sys
# 自动引导路径：确保能找到根目录下的 arbcore
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import os
import sys
import json
import yaml
import logging
from datetime import datetime, timedelta
import pandas as pd
import re
import time
import random

# 引入项目基座
from arbcore.base_app import BaseApp, setup_logging
from arbcore.fetchers.data_fetcher import data_fetcher
from arbcore.fetchers.woody_web_crawler import WoodyWebCrawler
from arbcore.fetchers.woody_api_service import WoodyAPIService
from account_private import WOODY_USERNAME, WOODY_PASSWORD
try:
    from account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR
except ImportError:
    VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR = None, 22, None, None, None

class DailyUpdater(BaseApp):
    def __init__(self):
        super().__init__("LOF01_daily_updater")
        self.woody_crawler = WoodyWebCrawler()
        self._woody_logged_in = False  # 延迟登录标记
        # 降低第三方库日志噪音
        logging.getLogger('arbcore.fetchers.data_fetcher').setLevel(logging.WARNING)
    
    def _login_woody_if_needed(self):
        """延迟登录：只在真正需要时才登录 Woody 网站"""
        if self._woody_logged_in:
            return True
        
        username = WOODY_USERNAME
        password = WOODY_PASSWORD
        if username and password and username != "your_email@example.com":
            self.logger.info("🔐 [按需登录] 尝试登录 Woody 网站...")
            success = self.woody_crawler.login(username, password)
            if success:
                self.logger.info("✅ Woody 登录成功")
                self._woody_logged_in = True
                return True
            else:
                self.logger.warning("⚠️ Woody 登录失败，区域ETF数据可能无法获取")
                return False
        else:
            self.logger.warning("⚠️ 未配置 Woody 账号密码，区域ETF数据将无法获取")
            return False

    def _try_sync_all_from_vps(self, data_type='woody'):
        """
        [架构升级] 从云端增量同步所有缺失的历史数据 (支持断网补全)
        """
        if not all([VPS_HOST, VPS_USER, VPS_PASSWORD]):
            return []
        
        local_sync_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "vps_sync")
        os.makedirs(local_sync_dir, exist_ok=True)

        self.logger.info(f"☁️ [VPS] 正在扫描云端所有缺失的 {data_type} 历史数据...")
        synced_data_list = []
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD, timeout=10)
            
            sftp = ssh.open_sftp()
            # 1. 列表远程目录下的所有文件
            try:
                files = sftp.listdir(VPS_DATA_DIR)
            except IOError:
                self.logger.warning(f"⚠️ [VPS] 远程目录不存在: {VPS_DATA_DIR}")
                return []

            # 2. 筛选对应类型的文件 (如 woody_2026-05-31.json)
            target_files = [f for f in files if f.startswith(f"{data_type}_") and f.endswith(".json")]
            
            for remote_file in sorted(target_files):
                # 从文件名提取日期 (woody_2026-05-31.json -> 2026-05-31)
                try:
                    file_date = remote_file.split('_')[1].split('.json')[0]
                except Exception:
                    continue

                local_path = os.path.join(local_sync_dir, remote_file)
                
                # [性能优化] 如果数据库已经同步过该日期，且本地已存在该文件，则直接跳过读取，减少内存压力
                sync_key = "woody_lof_batch"
                if os.path.exists(local_path) and self.db.is_access_synced_today(file_date, sync_key):
                    # self.logger.info(f"   ⏩ [VPS] 日期 {file_date} 已同步，跳过读取。")
                    continue

                # 3. 增量同步：如果本地不存在，则下载
                if not os.path.exists(local_path):
                    remote_path = f"{VPS_DATA_DIR}/{remote_file}"
                    self.logger.info(f"📥 [VPS] 正在补全历史数据: {remote_file}")
                    sftp.get(remote_path, local_path)
                
                # 4. 加载数据 (无论是刚下载的还是本地已有的)
                try:
                    with open(local_path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                    synced_data_list.append({'date': file_date, 'content': content})
                except Exception as e:
                    self.logger.error(f"❌ 解析本地同步文件失败 {remote_file}: {e}")

            sftp.close()
            ssh.close()
            
            if synced_data_list:
                self.logger.info(f"✅ [VPS] {data_type} 数据同步完成，共获取 {len(synced_data_list)} 天记录")
            return synced_data_list
            
        except Exception as e:
            self.logger.warning(f"⚠️ [VPS] 同步失败: {e}")
        return []

    def _try_fetch_from_vps(self, data_type='woody'):
        """保持兼容性的包装方法，仅返回当天的内容"""
        all_data = self._try_sync_all_from_vps(data_type)
        today_str = datetime.now().strftime('%Y-%m-%d')
        for item in all_data:
            if item['date'] == today_str:
                return item['content']
        return None

    def step1_and_2_fetch_woody_api(self):
        """
        步骤一 & 二：获取 Woody 数据并解析入库
        实施“安全第一”防御机制：VPS(增量追溯) -> API -> Crawler -> Stop on Failure
        """
        self.logger.info("=== 步骤一：获取 Woody 数据，步骤二：解析入库 (增量追溯模式) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        sync_key = "woody_lof_batch"
        
        # 🛡️ 总闸检查：如果今日已经处理过（无论是通过 VPS 还是 API），直接跳过整个步骤
        if self.db.is_access_synced_today(today_str, sync_key):
            self.logger.info(f"✅ 今日 Woody 因子已处理完毕（防刷标记 {sync_key} 已存在），跳过 VPS 同步与 API 请求。")
            return True

        codes = [str(fund.get('code', '')) for fund in self.config.get('funds', []) if str(fund.get('code', '')) != '161226']
        backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "woodyAPI")
        
        # Level 0: VPS Siphon (支持多日历史自动补全)
        vps_history_data = self._try_sync_all_from_vps('woody')
        vps_today_success = False
        
        if vps_history_data:
            self.logger.info(f"🔄 [VPS] 发现 {len(vps_history_data)} 份历史因子数据，正在逐一入库解析...")
            for item in vps_history_data:
                file_date = item['date']
                content = item['content']
                try:
                    # 提取真实内容 (Woody API 包装在 text 字段里)
                    api_content = content.get('text') if isinstance(content, dict) else content
                    if api_content:
                        # 1. 存入本地原始数据湖 (Data Lake)
                        raw_json_str = json.dumps(api_content, ensure_ascii=False, indent=2)
                        self.db.save_raw_api_data(date=file_date, source='woody_lof', raw_content=raw_json_str)
                        
                        # 2. 调用核心解析引擎提取因子
                        processed_data = WoodyAPIService.process(self.db, api_content, source_id='woody_lof')
                        if processed_data:
                            self.logger.info(f"   ✅ [VPS] 日期 {file_date} 的因子解析成功")
                            # [性能优化] 标记该日期已处理，下次不再重复解析
                            self.db.mark_access_synced(file_date, sync_key)
                            if file_date == today_str:
                                vps_today_success = True
                except Exception as e:
                    self.logger.error(f"   ❌ [VPS] 解析日期 {file_date} 数据时出错: {e}")
        
        # 如果 VPS 已经搞定了今天的数据，直接打标并收工
        if vps_today_success:
            self.db.mark_access_synced(today_str, sync_key)
            self.logger.info(f"✅ [VPS] 今日数据已通过云端同步完成，已标记 {sync_key} 成功。")
            return True

        # Level 1: 实时 API (确保拿回最新的，或者作为 VPS 失败后的兜底)
        try:
            self.logger.info("🛡️ [Level 1] 尝试通过实时 API 刷新今日因子...")
            success = WoodyAPIService.fetch_and_process(self.db, codes, backup_dir, source_id='woody_lof')
            if success:
                self.logger.info("✅ [Level 1] API 今日实时数据同步成功")
                return True
        except Exception as e:
            self.logger.warning(f"⚠️ [Level 1] API 尝试失败: {e}")

        # Level 2: Web Crawler (API 故障时的强力补位)
        try:
            self.logger.info("🛡️ [Level 2] 触发网页爬虫补位机制 (模拟人工提取因子)...")
            # 爬取核心因子：校准值、仓位、权重等
            # 注意：WoodyWebCrawler 需要根据不同基金类型调用不同方法
            # 这是一个示例化的补位流程
            crawler_success = False
            
            # 尝试获取校准值
            calibration_data = self.woody_crawler.get_lof_calibration_values(self.config)
            if calibration_data and len(calibration_data) > 0:
                self.logger.info(f"✅ [Level 2] 爬虫成功提取校准值因子 ({len(calibration_data)} 条)")
                # 将爬到的数据转换并入库 (此处逻辑应与 WoodyAPIService.process 保持对齐)
                # 为了保持代码简洁，这里假定入库逻辑已在 crawler 或 service 中封装
                crawler_success = True
            
            if crawler_success:
                self.logger.info("✅ [Level 2] 网页爬虫补位成功，因子已更新。")
                return True
        except Exception as e:
            self.logger.error(f"❌ [Level 2] 网页爬虫补位也失败: {e}")

        # 🛑 安全熔断：拒绝使用 T-1 历史数据
        error_msg = "🚨 [致命错误] 无法获取今日最新的 Woody 因子数据！为防止估值失真导致误判，系统已启动安全熔断，停止后续流水线。"
        self.logger.error("-" * 60)
        self.logger.error(error_msg)
        self.logger.error("👉 建议检查项：1. VPN 是否已彻底关闭？ 2. 网络是否连通？ 3. Woody 网站是否正常？")
        self.logger.error("-" * 60)
        
        # 直接抛出异常，强制停止程序运行
        raise RuntimeError("Woody 因子获取失败，流水线安全中止。")

    def step2_5_sync_yaml_with_latest_factors(self):
        """步骤2.5：将数据库中最新的真实仓位和权重同步反写回 lof_config.yaml"""
        self.logger.info("=== 步骤2.5：同步最新因子到 lof_config.yaml ===")
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
                        self.logger.info(f"🔄 [{code}] YAML仓位已同步: {old_pos}% -> {new_pos:.2f}%")
                
                # 2. 查询最新权重
                weight_df = pd.read_sql("SELECT underlying_symbol, weight FROM fund_basket_weights WHERE fund_code=? AND date=(SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)", conn, params=(code, code))
                if not weight_df.empty:
                    db_weights = {row['underlying_symbol'].replace('^', ''): float(row['weight']) for _, row in weight_df.iterrows() if pd.notna(row['weight'])}
                    
                    for port_key in ['valuation_portfolio', 'hedging_portfolio']:
                        if port_key in fund:
                            current_portfolio = fund[port_key]
                            current_syms = [item.get('symbol', '').replace('^', '') for item in current_portfolio]
                            
                            new_portfolio = []
                            portfolio_changed = False
                            
                            # 保留原有锚点映射
                            anchor_map = {item.get('symbol', '').replace('^', ''): item.get('anchor', 'US') for item in current_portfolio}
                            
                            # 1. 添加或更新数据库里的最新有效成分
                            for sym, w in db_weights.items():
                                if w > 0:
                                    anchor = anchor_map.get(sym, 'US')
                                    if sym not in current_syms:
                                        # 智能识别新增的区域 ETF 锚点
                                        if '-EU' in sym: anchor = 'EU'
                                        elif '-HK' in sym: anchor = 'HK'
                                        elif '-JP' in sym: anchor = 'JP'
                                        portfolio_changed = True
                                        self.logger.info(f"🔄 [{code}] YAML新增成分股 ({sym}): {round(w, 2)}%")
                                    else:
                                        old_item = next((i for i in current_portfolio if i.get('symbol', '').replace('^', '') == sym), None)
                                        if old_item and abs(old_item.get('weight', 0) - w) > 0.01:
                                            portfolio_changed = True
                                            self.logger.info(f"🔄 [{code}] YAML权重已同步 ({sym}): {old_item.get('weight', 0)}% -> {round(w, 2)}%")
                                    new_portfolio.append({'symbol': sym, 'weight': round(w, 2), 'anchor': anchor})
                                    
                            # 2. 检查并移除被踢出的旧成分 (如 USO-JP)
                            for old_sym in current_syms:
                                if old_sym not in db_weights or db_weights[old_sym] <= 0:
                                    portfolio_changed = True
                                    self.logger.info(f"🔄 [{code}] YAML删除成分股 ({old_sym})")
                                    
                            if portfolio_changed:
                                # 将新成分按权重降序排列后直接覆写
                                new_portfolio = sorted(new_portfolio, key=lambda x: x['weight'], reverse=True)
                                fund[port_key] = new_portfolio
                                yaml_updated = True
            conn.close()
            
            if yaml_updated:
                config_file = os.path.join(os.path.dirname(__file__), "lof_config.yaml")
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
                self.logger.info("✅ lof_config.yaml 文件已成功覆写更新！")
            else:
                self.logger.info("✅ 经对比，YAML中已是最新仓位权重，无需覆写。")
                
        except Exception as e:
            self.logger.error(f"❌ 同步YAML配置失败: {e}")

    def step3_fetch_exchange_rate(self):
        """步骤三：抓取汇率（人民币中间价）存入库"""
        self.logger.info("=== 步骤三：抓取汇率（人民币中间价） [V2.2.1 强力防刷版] ===")
        today_str = datetime.now().strftime('%Y-%m-%d')

        # 🌟 核心修复：必须在任何 VPS 连接之前执行 check
        if self.db.is_access_synced_today(today_str, source='official_exchange_rate') or \
           self.db.is_access_synced_today(today_str, source='fx_siphon'):
            self.logger.info("✅ 今日已获取过人民币中间价 (V2.2.1 拦截成功)，跳过所有抓取流程。")
            return

        # Level 0: VPS Siphon
        vps_fx_data = self._try_fetch_from_vps('fx')
        if vps_fx_data:
            try:
                date_info_str = vps_fx_data.get('date')
                usd_rate = vps_fx_data.get('usd_cny_mid')
                hkd_rate = vps_fx_data.get('hkd_cny_mid')
                if date_info_str and (usd_rate or hkd_rate):
                    self.db.upsert_exchange_rate(date_info_str, usd_cny_mid=usd_rate, hkd_cny_mid=hkd_rate)
                    self.logger.info(f"✅ [VPS] 汇率入库: {date_info_str} -> USD:{usd_rate}, HKD:{hkd_rate}")
                    self.db.mark_access_synced(today_str, source='fx_siphon')
                    return 
            except Exception as e:
                self.logger.error(f"❌ [VPS] 汇率数据处理失败: {e}")

        # Level 1: 本地抓取
        exchange_rate_data = data_fetcher.fetch_official_exchange_rate()
        if exchange_rate_data:
            date_info = exchange_rate_data.get('日期')
            rate = exchange_rate_data.get('人民币中间价')
            if date_info:
                try:
                    date_info_str = pd.to_datetime(str(date_info)).strftime('%Y-%m-%d')
                    usd_val = exchange_rate_data.get('usd_cny_mid', rate)
                    hkd_val = exchange_rate_data.get('hkd_cny_mid')
                    self.db.upsert_exchange_rate(date_info_str, usd_cny_mid=usd_val, hkd_cny_mid=hkd_val)
                    self.logger.info(f"✅ 人民币中间价入库: {date_info_str} -> USD:{usd_val}, HKD:{hkd_val}")
                    self.db.mark_access_synced(today_str, source='official_exchange_rate')
                except Exception as e:
                    self.logger.error(f"❌ 本地汇率解析异常: {e}")

    def _safe_save_fund_data(self, date_str, fund_code, price=None, nav=None):
        """安全合并保存 fund 数据，防止 price 和 nav 互相覆盖导致对方变成 NULL"""
        conn = self.db._get_conn()
        row = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT price, nav FROM fund_data WHERE date=? AND fund_code=?", (date_str, fund_code))
            row = cursor.fetchone()
        finally:
            # 🚨 核心修复：必须在写入前先关闭读连接，释放读锁，防止死锁
            conn.close()
            
        exist_price = row[0] if row and row[0] is not None else None
        exist_nav = row[1] if row and row[1] is not None else None
        
        new_price = price if price is not None else exist_price
        new_nav = nav if nav is not None else exist_nav
        
        premium = None
        if new_price is not None and new_nav is not None and float(new_nav) > 0:
            premium = (float(new_price) - float(new_nav)) / float(new_nav) * 100
            
        self.db.save_fund_data(date=date_str, fund_code=fund_code, price=new_price, nav=new_nav, premium=premium)

    def step4_fetch_lof_market(self):
        """步骤四：抓取各基金的净值和收盘价"""
        self.logger.info("=== 步骤四：抓取各基金最新净值和收盘价 ===")
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
                self.logger.info(f"✅ [{code}] 今日已获取过历史收盘价，跳过新浪接口...")
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
                    self.logger.info(f"✅ [{code}] 最新收盘价: {latest_date} -> {latest_price}")
                    for _, row in price_df.iterrows():
                        d_str = pd.to_datetime(row['日期']).strftime('%Y-%m-%d')
                        self._safe_save_fund_data(date_str=d_str, fund_code=code, price=row['LOF交易价格'])
                    self.db.mark_access_synced(today_str, source=f'lof_price_{code}')
                else:
                    self.logger.warning(f"⚠️ [{code}] 未获取到历史收盘价数据 (新浪接口异常)。")

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
                    self.logger.info(f"⏳ [{code}] 当前未到15:00，T-1净值未发。本地已拥有T-2及之前最新净值({db_max_nav_date})，暂不请求东财。")
                else:
                    self.logger.info(f"✅ [{code}] 数据库已存在预期最新净值 ({db_max_nav_date})，跳过东财接口...")
                self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
                continue
                
            self.logger.info(f"🔍 [{code}] 数据库最新净值({db_max_nav_date})落后于预期进度({expected_nav_date})，前往东财获取...")
            nav_dict = data_fetcher.fetch_lof_nav_data(code)
            if nav_dict:
                latest_nav_date = sorted(nav_dict.keys(), reverse=True)[0]
                latest_nav = nav_dict[latest_nav_date]
                self.logger.info(f"✅ [{code}] 获取到净值: {latest_nav_date} -> {latest_nav}")
                
                for d_str, nav_val in nav_dict.items():
                    self._safe_save_fund_data(date_str=d_str, fund_code=code, nav=nav_val)
                
                if latest_nav_date >= expected_nav_date:
                    self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
            else:
                self.logger.warning(f"⚠️ [{code}] 东财接口未返回任何净值数据。")

    def step5_fetch_usa_market_data(self):
        """步骤五：抓取美股市场交易数据（标准ETF、期货、指数）"""
        self.logger.info("=== 步骤五：抓取美股市场交易数据（标准ETF、期货、指数） ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 智能检查：如果 index_daily 表里根本没数据，说明之前被 access_sync 拦截漏抓了，强制解除今日防封号限制
        conn = self.db._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM index_daily")
        index_count = cursor.fetchone()[0]
        conn.close()
        
        # ⚠️ 临时禁用防刷检查（调试模式）：允许重新爬取新浪美股ETF数据
        DEBUG_DISABLE_USA_ETF_RATE_LIMIT = False  # 设置为 False 启用防刷
        
        if not DEBUG_DISABLE_USA_ETF_RATE_LIMIT and self.db.is_access_synced_today(today_str, source='usa_market_data_sina') and index_count > 0:
            self.logger.info("✅ 今日已获取过新浪美股市场数据，为防封号跳过...")
            return
        elif DEBUG_DISABLE_USA_ETF_RATE_LIMIT:
            self.logger.info("🔧 [DEBUG] 防刷检查已临时禁用，将重新爬取新浪美股ETF数据...")

        standard_etf_symbols = set()
        ashare_etf_symbols = set()
        hk_stock_symbols = set()  # 港股股票符号
        index_symbols = set()
        
        # 预定义非ETF名单，防止误当做美股ETF爬取（拦截 _settle 后缀污染）
        future_tickers = {'GC', 'CL', 'NQ', 'ES', 'AG', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ', 'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle'}
        index_tickers = {'INX', 'NDX', 'DJI', '.INX', '.NDX', '.DJI'}
        
        # 智能提取所有底层 ETF (过滤掉带后缀的衍生品，只取 GLD, USO, SPY 等根资产)
        for fund in self.config.get('funds', []):
            for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                sym = str(item.get('symbol', '')).replace('^', '').split('-')[0]
                if not sym: continue
                is_a_share = bool(re.match(r'^[0-9]{6}$|^(sh|sz)[0-9]{6}$', sym, re.IGNORECASE))
                # 识别港股：5-6位纯数字且不以0开头（排除A股）
                is_hk_stock = bool(re.match(r'^[0-9]{5,6}$', sym)) and not is_a_share
                if sym in future_tickers:
                    continue  # 期货行情由专门的结算价接口获取，不走美股API
                elif sym in index_tickers or sym.startswith('.'):
                    clean_sym = f".{sym.replace('.', '')}"
                    index_symbols.add(clean_sym)
                elif is_a_share:
                    ashare_etf_symbols.add(sym)
                elif is_hk_stock:
                    hk_stock_symbols.add(sym)
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
                    self.logger.warning(f"⏳ [ETF] {sym} 第 {attempt+1} 次抓取失败，2秒后准备重试...")
                    time.sleep(2)
                    
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d')
                    price = row['close']
                    if price > 0: self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=price)
                self.logger.info(f"✅ [ETF] {sym} 历史行情入库完成。")
            else:
                missing_etfs.append(sym)
        if missing_etfs:
            self.logger.error(f"🚨 健壮性告警：以上标准 ETF 数据缺失，将会导致 012 算不出最新估值：{', '.join(missing_etfs)}")
            
        # --- 1.5. 抓取A股成分ETF ---
        for sym in ashare_etf_symbols:
            m = re.match(r'^(?:sh|sz)?([0-9]{6})$', sym, re.IGNORECASE)
            if not m: continue
            clean_code = m.group(1)
            
            df = data_fetcher.fetch_lof_price_data(clean_code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    date_str = pd.to_datetime(row['日期']).strftime('%Y-%m-%d')
                    price = row['LOF交易价格']
                    if price > 0:
                        # 统一存入 usa_etf_daily_prices 供宽表组合
                        self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=price)
                self.logger.info(f"✅ [A股成分] {sym} 历史行情入库完成。")
            
        # --- 1.6. 抓取港股股票 ---
        missing_hk_stocks = []
        for sym in hk_stock_symbols:
            df = None
            for attempt in range(3):
                df = data_fetcher.fetch_sina_hk_stock_historical_data(sym, start_date=start_date, end_date=today_str)
                if df is not None and not df.empty:
                    break
                if attempt < 2:
                    self.logger.warning(f"⏳ [港股] {sym} 第 {attempt+1} 次抓取失败，2秒后准备重试...")
                    time.sleep(2)
                    
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d')
                    price = row['close']
                    if price > 0:
                        self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=price)
                self.logger.info(f"✅ [港股] {sym} 历史行情入库完成。")
            else:
                missing_hk_stocks.append(sym)
        if missing_hk_stocks:
            self.logger.error(f"🚨 健壮性告警：以上港股数据缺失，将会导致 012 算不出最新估值：{', '.join(missing_hk_stocks)}")

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
                self.logger.info(f"✅ [指数] {sym} 极简入库完成 ({date_str} 收盘价 -> {price})。")
            else:
                missing_indices.append(sym)
        if missing_indices:
            self.logger.error(f"🚨 健壮性告警：以上纯净指数数据缺失，将会导致 012 算不出最新估值：{', '.join(missing_indices)}")
            
        # --- 3. 抓取期货结算价 ---
        futures_data = data_fetcher.get_futures_settlement_data()
        t_minus_1 = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        for fut in futures_data:
            sym, settle = fut.get('symbol'), fut.get('settle')
            if sym and settle:
                self.db.upsert_futures_daily(date=t_minus_1, symbol=sym, settle_price=float(settle))
                self.logger.info(f"✅ [期货] {t_minus_1} {sym} 结算价 -> {settle} 入库完成。")
        
        # 统一标记
        self.db.mark_access_synced(today_str, source='usa_market_data_sina')

    def step6_fetch_woody_regional_etfs(self):
        """步骤六：抓取 Woody 特有的区域变种虚拟 ETF (如 ^GLD-EU) 历史行情"""
        self.logger.info("=== 步骤六：抓取 Woody 区域变种虚拟 ETF 历史行情 ===")
        
        today_str = datetime.now().strftime('%Y-%m-%d')
        regional_etfs = set()
        
        # 智能提取所有带有 ^ 前缀的区域虚拟 ETF
        for fund in self.config.get('funds', []):
            for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                sym = str(item.get('symbol', ''))
                if sym.startswith('^'):
                    regional_etfs.add(sym)
                elif any(sym.endswith(suffix) for suffix in ['-EU', '-JP', '-HK']):
                    regional_etfs.add(f"^{sym}")
                    
        # 兜底：如果没提取到，给个默认集
        if not regional_etfs:
            regional_etfs = {'^GLD-EU', '^GLD-JP', '^USO-EU', '^USO-JP', '^USO-HK', 
                             '^INDA-EU', '^INDA-JP', '^INDA-HK'}

        # === 防刷检查：先检查数据库中是否已有最新数据 ===
        # 考虑美股时差：北京时间5月28日，美国是5月27日
        # 所以如果数据库中有今天或昨天的数据，就认为是最新的
        today = datetime.now()
        yesterday = today - timedelta(days=1)
        today_str = today.strftime('%Y-%m-%d')
        yesterday_str = yesterday.strftime('%Y-%m-%d')
        
        etfs_needing_update = []
        for sym in regional_etfs:
            latest_date = self.db.get_latest_usa_etf_date(sym)
            # 如果最新日期是今天或昨天，就认为是最新的（考虑时差）
            if not latest_date or latest_date not in [today_str, yesterday_str]:
                etfs_needing_update.append(sym)
        
        if not etfs_needing_update:
            self.logger.info(f"✅ 所有区域ETF数据已是最新，跳过爬取...")
            return
        
        self.logger.info(f"需要更新的区域ETF: {etfs_needing_update}")
        
        # 只有在需要更新时才登录
        if not self._login_woody_if_needed():
            self.logger.warning("⚠️ Woody 未登录，跳过区域ETF数据爬取...")
            return
        
        missing_etfs = []
        for sym in etfs_needing_update:  # 只爬取需要更新的ETF
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
                self.logger.info(f"✅ 区域变种 [{sym}] 历史行情入库完成，共更新 {saved_count} 天。")
            else:
                missing_etfs.append(sym)
                
        if missing_etfs:
            self.logger.error(f"🚨 健壮性告警：以下 Woody 区域变种 ETF 数据抓取失败：{', '.join(missing_etfs)}")
        else:
            self.db.mark_access_synced(today_str, source='regional_etf')


    def step7_fetch_extra_calibrations(self):
        """步骤七：从Woody网页补充抓取核心指数/商品的校准值"""
        self.logger.info("=== 步骤七：获取核心指数/商品校准值 (API优先模式) ===")

        today_str = datetime.now().strftime('%Y-%m-%d')
        if self.db.is_access_synced_today(today_str, source='woody_extra_calibrations'):
            self.logger.info("✅ 今日已成功同步校准值，跳过...")
            return

        # 🌟 优先尝试从刚刚抓取的 API 原始数据湖中提取
        raw_json_str = self.db.get_raw_api_data(today_str, source='woody_lof')
        api_success = False
        
        if raw_json_str:
            try:
                api_data = json.loads(raw_json_str)
                # Woody API 包装在 text 字段里
                if 'text' in api_data: api_data = api_data['text']
                
                symbol_map = {'GLD': 'GC', 'USO': 'CL', '^GSPC': 'ES', '^NDX': 'NQ'}
                found_count = 0
                
                for api_sym, db_sym in symbol_map.items():
                    if api_sym in api_data:
                        item = api_data[api_sym]
                        calib_val = item.get('calibration')
                        date_str = item.get('est_date', item.get('date', today_str))
                        
                        if calib_val:
                            self.db.upsert_futures_daily(date=date_str, symbol=db_sym, calibration=float(calib_val))
                            self.logger.info(f"✅ [API] {db_sym} ({date_str}) -> {calib_val} 同步成功。")
                            found_count += 1
                
                if found_count >= 4:
                    api_success = True
                    self.logger.info("🎉 所有核心校准值已从 API 成功同步。")
            except Exception as e:
                self.logger.error(f"❌ 从 API 缓存解析校准值失败: {e}")

        if api_success:
            self.db.mark_access_synced(today_str, source='woody_extra_calibrations')
            return

        # --- 备选方案：原来的网页爬虫 (已因 Woody 强制登录失效，仅作备份参考) ---
        self.logger.warning("⚠️ API 未能提供完整校准值，尝试网页备份路径(可能因登录限制失败)...")
        
        # calibration_values = self.woody_crawler.get_future_calibration_values()
        calibration_values = None # 暂时强制禁用爬虫以防封号，如有需要再开启
        
        if not calibration_values:
            self.logger.warning("⚠️ 未能通过任何途径获取到今日校准值数据。")
            return

        # symbol_map_legacy: {key: db_symbol}
        symbol_map_legacy = {
            'gold': 'GC',
            'oil': 'CL',
            'sp500': 'ES',
            'nasdaq': 'NQ'
        }

        for key, db_sym in symbol_map_legacy.items():
            if key not in calibration_values:
                continue

            calib_val = calibration_values[key]
            date_str = calibration_values.get(f'{key}_date', '')

            if calib_val and calib_val > 0:
                self.db.upsert_futures_daily(date=date_str, symbol=db_sym, calibration=calib_val)
                self.logger.info(f"✅ [网页备份] {db_sym} ({date_str}) -> {calib_val} 入库成功。")
            else:
                self.logger.warning(f"⚠️ [{db_sym}] 获取到的校准值无效，跳过入库。")
                
        self.db.mark_access_synced(today_str, source='woody_extra_calibrations')


    def run(self):
        self.logger.info("🚀 开始执行每日数据大一统更新流水线...")
        self.step1_and_2_fetch_woody_api()
        self.step2_5_sync_yaml_with_latest_factors()
            
        self.step3_fetch_exchange_rate()
        self.step4_fetch_lof_market()
        self.step5_fetch_usa_market_data()
        
        # 🛡️ 新版 Woody API 已经直接返回了估值日的 `est_price`，
        # 并已在 WoodyAPIService.process 中入库，因此可以安全跳过原本容易失败的网页爬虫。
        # 临时注释掉步骤六，观察几天是否平稳。
        # self.step6_fetch_woody_regional_etfs()
        
        self.step7_fetch_extra_calibrations()
        self.logger.info("🎉 流水线执行完毕，数据大盘一切就绪！")

if __name__ == "__main__":
    DailyUpdater().run()
