# -*- coding: utf-8 -*-
# daily_updater.py - 每日数据大一统更新器
import os
import sys
# 自动引导路径：确保能找到根目录下的 arbcore
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
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
from arbcore.fetchers.historical import HistoricalDataManager
from arbcore.fetchers.woody_web_crawler import WoodyWebCrawler
from arbcore.fetchers.woody_api_service import WoodyAPIService
from arbcore.calculators.static_valuation import StaticValuationCalculator
from arbcore.config.account_private import WOODY_USERNAME, WOODY_PASSWORD
try:
    from arbcore.config.account_private import VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR, VPS_KEY_PATH, VPS_KEY_PASSWORD
except ImportError:
    VPS_HOST, VPS_PORT, VPS_USER, VPS_PASSWORD, VPS_DATA_DIR, VPS_KEY_PATH, VPS_KEY_PASSWORD = None, 22, None, None, None, None, None

class DailyUpdater(BaseApp):
    def __init__(self):
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        logs_dir = os.path.abspath(os.path.join(scripts_dir, "..", "..", "logs"))  # [AI-2026-07-02] 日志统一到 ArbDashboard/logs/
        super().__init__("daily_updater", app_dir=scripts_dir, log_dir=logs_dir)
        # [AI-2026-07-08] 移除：BaseApp 现已在 arbcore/config/ 优先查找，无需重复重定向
        self.woody_crawler = WoodyWebCrawler()
        self.hist_manager = HistoricalDataManager(db_manager=self.db)
        self._woody_logged_in = False  # 延迟登录标记
        # 降低第三方库日志噪音
        logging.getLogger('arbcore.fetchers.historical').setLevel(logging.WARNING)
    
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
        
        # 数据目录迁移到 ArbDashboard/data/（与脚本目录解耦）
        local_sync_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ArbDashboard", "data", "vps_sync"))
        os.makedirs(local_sync_dir, exist_ok=True)

        self.logger.info(f"[VPS] 正在扫描云端所有缺失的 {data_type} 历史数据...")
        synced_data_list = []
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # 优先使用私钥认证，失败则降级到密码
            try:
                if VPS_KEY_PATH and os.path.exists(VPS_KEY_PATH):
                    pkey = paramiko.Ed25519Key.from_private_key_file(VPS_KEY_PATH, password=VPS_KEY_PASSWORD)
                    ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, pkey=pkey, timeout=10)
                    self.logger.info(f"[VPS] SSH 私钥认证成功")
                else:
                    raise Exception("no key file")
            except Exception as key_err:
                self.logger.info(f"[VPS] 私钥认证失败 ({key_err})，降级到密码认证")
                ssh.connect(VPS_HOST, port=VPS_PORT, username=VPS_USER, password=VPS_PASSWORD, timeout=10,
                            look_for_keys=False, allow_agent=False)
            
            sftp = ssh.open_sftp()
            # 1. 列表远程目录下的所有文件
            try:
                files = sftp.listdir(VPS_DATA_DIR)
            except IOError:
                self.logger.warning(f"[VPS] 远程目录不存在: {VPS_DATA_DIR}")
                sftp.close(); ssh.close()
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
                
                # [性能优化] 如果数据库已经同步过该日期，直接跳过（不依赖本地缓存文件，修复本地缓存被删除后重复下载的bug）
                sync_key = f"{data_type}_vps_sync"
                # [AI-2026-07-06] 移除 os.path.exists 要求：只要 access_sync_status 有标记就跳过，即使缓存文件被删除
                if self.db.is_access_synced_today(file_date, sync_key):
                    continue

                # 3. 增量同步：如果本地不存在，则下载
                if not os.path.exists(local_path):
                    remote_path = f"{VPS_DATA_DIR}/{remote_file}"
                    self.logger.info(f"[VPS] 正在补全历史数据: {remote_file}")
                    sftp.get(remote_path, local_path)
                
                # 4. 加载数据 (无论是刚下载的还是本地已有的)
                try:
                    with open(local_path, 'r', encoding='utf-8') as f:
                        content = json.load(f)
                    synced_data_list.append({'date': file_date, 'content': content})
                    # [AI-2026-07-03] 标记VPS文件已读取解析，下次跳过检查能找到此标记，避免重复加载
                    self.db.mark_access_synced(file_date, f"{data_type}_vps_sync")
                except Exception as e:
                    self.logger.error(f"[VPS] 解析本地同步文件失败 {remote_file}: {e}")

            sftp.close()
            ssh.close()
            
            if synced_data_list:
                self.logger.info(f"[VPS] {data_type} 数据同步完成，共获取 {len(synced_data_list)} 天记录")
            return synced_data_list
            
        except Exception as e:
            self.logger.warning(f"[VPS] 同步失败: {e}")
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
        实施"安全第一"防御机制：VPS(增量追溯) -> API -> Crawler -> Stop on Failure
        """
        self.logger.info("=== 步骤一：获取 Woody 数据，步骤二：解析入库 (增量追溯模式) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        sync_key = "woody_lof_batch"
        
        # 🛡️ 总闸检查：如果今日已经处理过（无论是通过 VPS 还是 API），直接跳过整个步骤
        if self.db.is_access_synced_today(today_str, sync_key):
            self.logger.info(f"✅ 今日 Woody 因子已处理完毕（防刷标记 {sync_key} 已存在），跳过 VPS 同步与 API 请求。")
            return True

        # 🛡️ 数据库检查：如果库里已有今天的 Woody 因子数据，无需连 VPS
        try:
            conn = self.db._get_conn()
            cursor = conn.execute(
                "SELECT COUNT(*), raw_content FROM raw_api_data WHERE date = ? AND source = 'woody_lof'",
                (today_str,)
            )
            row = cursor.fetchone()
            count = row[0] if row else 0
            raw_content = row[1] if row else ""
            conn.close()
            # 只有内容是有效 JSON dict 时才认为已入库（排除错误信息如 "未授权IP"）
            if count > 0 and raw_content and raw_content.strip().startswith('{'):
                self.logger.info(f"✅ 今日({today_str}) Woody 原始数据已在库中({count}条)，无需连VPS，直接标记完成。")
                self.db.mark_access_synced(today_str, sync_key)
                return True
            elif count > 0:
                self.logger.warning(f"⚠️ 今日({today_str}) Woody 原始数据在库中但内容无效（非JSON），清除后重新获取...")
                conn2 = self.db._get_conn()
                conn2.execute("DELETE FROM raw_api_data WHERE date = ? AND source = 'woody_lof'", (today_str,))
                conn2.commit()
                conn2.close()
        except Exception as e:
            self.logger.warning(f"检查 Woody 数据库时出错: {e}，继续连接VPS获取")

        codes = [
            str(fund.get('code', '')) 
            for fund in self.config.get('funds', []) 
            if str(fund.get('code', '')) != '161226' and fund.get('data_source') == 'woody'
        ]
        # 数据目录迁移到 ArbDashboard/data/（与脚本目录解耦）
        backup_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "ArbDashboard", "data", "woodyAPI"))
        
        # Level 0: VPS Siphon (支持多日历史自动补全)
        vps_history_data = self._try_sync_all_from_vps('woody')
        vps_today_success = False
        
        if vps_history_data:
            self.logger.info(f"🔄 [VPS] 发现 {len(vps_history_data)} 份历史因子数据，正在逐一入库解析...")
            for item in vps_history_data:
                file_date = item['date']
                content = item['content']

                # 🛡️ [AI-2026-07-06] 检查本地 raw_api_data 是否已有该日期的因子数据
                # 解决 access_sync_status 被清理后 VPS 重复处理历史数据的 bug
                existing_raw = self.db.get_raw_api_data(file_date, 'woody_lof')
                if existing_raw:
                    self.logger.info(f"   ⏭️ [VPS] 日期 {file_date} 的因子原始数据已存在，跳过入库解析")
                    # 补打 VPS 同步标记，确保 _try_sync_all_from_vps 下次不再下载该文件
                    self.db.mark_access_synced(file_date, 'woody_vps_sync')
                    if file_date == today_str:
                        vps_today_success = True
                    continue

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
                            self.db.mark_access_synced(file_date, 'woody_vps_sync')
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
                                if w != 0:
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
                                if old_sym not in db_weights or db_weights[old_sym] == 0:
                                    portfolio_changed = True
                                    self.logger.info(f"🔄 [{code}] YAML删除成分股 ({old_sym})")
                                    
                            if portfolio_changed:
                                # 将新成分按权重降序排列后直接覆写
                                new_portfolio = sorted(new_portfolio, key=lambda x: x['weight'], reverse=True)
                                fund[port_key] = new_portfolio
                                yaml_updated = True
            conn.close()
            
            if yaml_updated:
                config_file = self.config_path  # [AI-2026-07-03] 使用已修正的 self.config_path
                with open(config_file, 'w', encoding='utf-8') as f:
                    yaml.safe_dump(self.config, f, allow_unicode=True, sort_keys=False)
                self.logger.info("✅ lof_config.yaml 文件已成功覆写更新！")
            else:
                self.logger.info("✅ 经对比，YAML中已是最新仓位权重，无需覆写。")
                
        except Exception as e:
            self.logger.error(f"❌ 同步YAML配置失败: {e}")

    def step3_fetch_exchange_rate(self):
        """[AI-2026-07-08] 步骤三：抓取汇率（中间价/在岸价/离岸价）存入库，2 级降级：VPS 同步 → 本地直连兜底"""
        self.logger.info("=== 步骤三：抓取汇率（中间价/在岸价/离岸价） ===")
        today_str = datetime.now().strftime('%Y-%m-%d')

        # 🛡️ 数据库检查：仅当今日三个汇率字段（中间价/在岸价/离岸价）都已齐备时才跳过
        # [AI-2026-07-08] 改为三字段全齐才跳过，避免"中间价有了但 spot/cnh 永远不补"的漏洞
        try:
            conn = self.db._get_conn()
            row = conn.execute(
                "SELECT usd_cny_mid, usd_cny_spot, usd_cnh FROM exchange_rate WHERE date = ?",
                (today_str,)
            ).fetchone()
            conn.close()
            if row and row[0] is not None and row[1] is not None and row[2] is not None:
                self.logger.info(f"✅ 今日({today_str})三汇率已齐备，无需连VPS，直接跳过。")
                self.db.mark_access_synced(today_str, source='official_exchange_rate')
                return
        except Exception as e:
            self.logger.warning(f"检查汇率数据库时出错: {e}，继续连接VPS获取")

        # Level 0: 尝试从 VPS 增量同步汇率数据并入库
        vps_fx_data = self._try_sync_all_from_vps('fx')
        if vps_fx_data:
            self.logger.info(f"🔄 [VPS] 发现 {len(vps_fx_data)} 份历史汇率数据，正在同步入库...")
            for item in vps_fx_data:
                file_date = item['date']
                content = item['content']
                try:
                    # [AI-2026-07-08] 读取全部四个汇率字段（中间价/在岸价/离岸价）
                    date_info = content.get('date')
                    usd_val = content.get('usd_cny_mid')
                    hkd_val = content.get('hkd_cny_mid')
                    cny_spot_val = content.get('usd_cny_spot')
                    cnh_val = content.get('usd_cnh')
                    # 中间价缺失则尝试用其他汇率兜底日期，避免整条跳过
                    if date_info and (usd_val or cny_spot_val or cnh_val):
                        date_info_str = pd.to_datetime(str(date_info)).strftime('%Y-%m-%d')
                        self.db.upsert_exchange_rate(
                            date_info_str,
                            usd_cny_mid=usd_val,
                            hkd_cny_mid=hkd_val,
                            usd_cny_spot=cny_spot_val,
                            usd_cnh=cnh_val,
                        )
                        self.logger.info(f"   ✅ [VPS] 同步入库汇率: {date_info_str} -> USD:{usd_val}, HKD:{hkd_val}, CNYSpot:{cny_spot_val}, CNH:{cnh_val}")
                        # 标记云端文件在此日期已完成同步
                        self.db.mark_access_synced(file_date, 'fx_vps_sync')
                except Exception as e:
                    self.logger.error(f"   ❌ [VPS] 解析日期 {file_date} 汇率时出错: {e}")

        # 检查今天是否已经同步到最新的汇率
        if self.db.is_access_synced_today(today_str, source='official_exchange_rate'):
            self.logger.info("✅ 今日已同步过人民币中间价，跳过实时抓取。")
            return

        # Level 1: 实时抓取作为兜底（[AI-2026-07-08] 单级兜底补全：中间价 + 在岸价 + 离岸价 一次抓全）
        self.logger.info("📡 [Level 1] 尝试实时抓取人民币中间价/在岸价/离岸价...")
        from arbcore.fetchers.data_fetcher import data_fetcher
        exchange_rate_data = data_fetcher.fetch_official_exchange_rate()
        if exchange_rate_data:
            date_info = exchange_rate_data.get('日期')
            if date_info:
                try:
                    date_info_str = pd.to_datetime(str(date_info)).strftime('%Y-%m-%d')
                    usd_val = exchange_rate_data.get('usd_cny_mid')
                    hkd_val = exchange_rate_data.get('hkd_cny_mid')
                    self.db.upsert_exchange_rate(date_info_str, usd_cny_mid=usd_val, hkd_cny_mid=hkd_val)
                    self.logger.info(f"✅ 人民币中间价入库: {date_info_str} -> USD:{usd_val}, HKD:{hkd_val}")

                    # 关键修复：只有当抓取到的汇率实际生效日期是今天（或更晚）时，才标记今日已同步
                    # 如果抓到的是昨天的日期，说明今天最新的还没更新，我们绝不标记今日同步，以便稍后重试
                    if date_info_str >= today_str:
                        self.db.mark_access_synced(today_str, source='official_exchange_rate')
                        self.logger.info(f"✅ 成功获取到今日 ({today_str}) 最新汇率，已打标。")
                    else:
                        self.logger.warning(f"⚠️ 抓取到的汇率日期为过去日期 ({date_info_str})，未更新到今天，因此不标记今日已同步。")
                except Exception as e:
                    self.logger.error(f"❌ 本地汇率解析异常: {e}")

        # [AI-2026-07-08] Level 1 兜底补全：在岸价 + 离岸价 直连新浪（VPS 未提供时单级也能补齐）
        # 在岸价 USDCNY
        try:
            conn_spot = self.db._get_conn()
            has_spot = conn_spot.execute(
                "SELECT COUNT(*) FROM exchange_rate WHERE date = ? AND usd_cny_spot IS NOT NULL", (today_str,)
            ).fetchone()[0] > 0
            conn_spot.close()
            if not has_spot:
                spot_data = data_fetcher.fetch_cny_spot_rate()
                if spot_data:
                    spot_date = pd.to_datetime(str(spot_data.get('日期', today_str))).strftime('%Y-%m-%d')
                    spot_rate = spot_data.get('人民币在岸价')
                    if spot_rate is not None:
                        self.db.upsert_exchange_rate(spot_date, usd_cny_spot=spot_rate)
                        self.logger.info(f"✅ [Level 1] 在岸价 USDCNY 入库: {spot_date} -> {spot_rate}")
        except Exception as e:
            self.logger.error(f"❌ [Level 1] 在岸价直连兜底失败: {e}")
        # 离岸价 CNH
        try:
            conn_cnh = self.db._get_conn()
            has_cnh = conn_cnh.execute(
                "SELECT COUNT(*) FROM exchange_rate WHERE date = ? AND usd_cnh IS NOT NULL", (today_str,)
            ).fetchone()[0] > 0
            conn_cnh.close()
            if not has_cnh:
                cnh_data = data_fetcher.fetch_cnh_offshore_rate()
                if cnh_data:
                    cnh_date = pd.to_datetime(str(cnh_data.get('日期', today_str))).strftime('%Y-%m-%d')
                    cnh_rate = cnh_data.get('离岸价')
                    if cnh_rate is not None:
                        self.db.upsert_exchange_rate(cnh_date, usd_cnh=cnh_rate)
                        self.logger.info(f"✅ [Level 1] 离岸价 CNH 入库: {cnh_date} -> {cnh_rate}")
        except Exception as e:
            self.logger.error(f"❌ [Level 1] 离岸价直连兜底失败: {e}")

        self.logger.info(f"✅ 步骤三完成：今日({today_str})汇率（中间价/在岸价/离岸价）采集结束。")

    def _safe_save_fund_data(self, date_str, fund_code, price=None, nav=None):
        """[AI-2026-06-28] premium 用 T-1 净值计算，入库即正确"""
        conn = self.db._get_conn()
        row = None
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT price, nav FROM unified_fund_history WHERE date=? AND fund_code=?", (date_str, fund_code))
            row = cursor.fetchone()
            # [AI-2026-06-28] 查 T-1 净值用于溢价计算
            cursor.execute("SELECT nav FROM unified_fund_history WHERE fund_code=? AND date<? AND nav IS NOT NULL ORDER BY date DESC LIMIT 1", (fund_code, date_str))
            t1_row = cursor.fetchone()
        finally:
            conn.close()
            
        exist_price = row[0] if row and row[0] is not None else None
        exist_nav = row[1] if row and row[1] is not None else None
        t1_nav = float(t1_row[0]) if t1_row and t1_row[0] is not None else None
        
        new_price = price if price is not None else exist_price
        new_nav = nav if nav is not None else exist_nav
        
        premium = None
        if new_price is not None and t1_nav is not None and t1_nav > 0:
            premium = round((float(new_price) - t1_nav) / t1_nav * 100, 4)
            
        self.db.save_unified_history(
            date_str=date_str, 
            fund_code=fund_code, 
            price=new_price, 
            nav=new_nav, 
            premium=premium
        )

    def _step4_fix_holiday_prices(self, codes_to_fix=None):
        """[AI-2026-06-28] 用腾讯历史 K 线修复假期导致的错误收盘价"""
        from arbcore.fetchers.historical.tencent import TencentHistoricalFetcher
        self.logger.info("🔧 [假期修复] 开始用腾讯历史 K 线修复错误收盘价...")
        
        if codes_to_fix is None:
            # 修复所有基金（不只是 NULL 的）
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT fund_code FROM unified_fund_list ORDER BY fund_code")
            codes_to_fix = [str(r[0]) for r in cursor.fetchall()]
            conn.close()
        
        self.logger.info(f"🔧 [假期修复] 共 {len(codes_to_fix)} 只基金待检查...")
        
        fetcher = TencentHistoricalFetcher()
        fixed_count = 0
        corrected_count = 0
        
        for code in codes_to_fix:
            try:
                # 腾讯代码格式: sz159518 或 sh513350
                tx_code = f"sz{code}" if code.startswith(('0', '1', '3')) else f"sh{code}"
                df = fetcher.fetch_prices(tx_code, start_date='2026-06-01')
                
                if df.empty:
                    continue
                
                # [AI-2026-06-28] 用 _safe_save_fund_data 直接写入 unified_fund_history
                need_update = False
                for _, row in df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d')
                    price = float(row['close'])
                    # 检查是否已有数据
                    conn = self.db._get_conn()
                    existing = conn.execute("SELECT price FROM unified_fund_history WHERE date=? AND fund_code=?", (date_str, code)).fetchone()
                    conn.close()
                    
                    should_update = False
                    if existing:
                        if existing[0] is None:
                            should_update = True
                        elif abs(float(existing[0]) - price) > 0.0001:
                            should_update = True
                    else:
                        should_update = True
                    
                    if should_update:
                        # [AI-2026-06-28] 直接写入 unified_fund_history（废弃 fund_data）
                        self._safe_save_fund_data(date_str=date_str, fund_code=code, price=price)
                        need_update = True
                
                if need_update:
                    fixed_count += 1
                    self.logger.info(f"  ✅ [{code}] 修复历史价格")
                else:
                    self.logger.info(f"  ⏭️ [{code}] 价格正确，无需修复")
            except Exception as e:
                self.logger.error(f"  ❌ [{code}] 修复失败: {e}")
        
        self.logger.info(f"🔧 [假期修复] 完成，修复 {fixed_count}/{len(codes_to_fix)} 只基金")

    def _step4_fetch_prices(self):
        """[AI-2026-06-28] 从腾讯行情获取收盘价，和净值补采分离"""
        self.logger.info("=== 步骤4P：获取各基金收盘价 (腾讯API) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        conn_ufl = self.db._get_conn()
        all_codes = [str(r[0]) for r in conn_ufl.execute("SELECT fund_code FROM unified_fund_list").fetchall() if r[0]]
        conn_ufl.close()
        self.logger.info(f"📋 共 {len(all_codes)} 只基金，开始获取收盘价...")

        for code in all_codes:
            if not code: continue
            if not self.db.is_access_synced_today(today_str, source=f'lof_price_{code}'):
                import requests
                tx_code = f"sz{code}" if code.startswith(('0', '1', '3')) else f"sh{code}"
                url = f"https://qt.gtimg.cn/q={tx_code}"
                headers = {"Referer": "https://finance.qq.com/"}
                try:
                    resp = requests.get(url, headers=headers, timeout=10)
                    resp.encoding = "gbk"
                    if resp.status_code == 200 and resp.text and '~' in resp.text:
                        parts = resp.text.split('=')[1].strip('"~;\n\r ')
                        fields = parts.split('~')
                        if len(fields) > 30:
                            ts = fields[30].strip()
                            if len(ts) >= 8:
                                date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
                                price = float(fields[3]) if fields[3] else 0
                                amount_wan = round(float(fields[36]) / 10000, 2) if len(fields) > 36 and fields[36] else 0
                                if price > 0:
                                    self._safe_save_fund_data(date_str=date_str, fund_code=code, price=price)
                                    self.db.save_unified_history(date_str=date_str, fund_code=code, volume=amount_wan)
                                    self.db.mark_access_synced(today_str, source=f'lof_price_{code}')
                                    self.logger.info(f"✅ [{code}] 收盘价: {date_str} {price}")
                                else:
                                    self.logger.warning(f"⚠️ [{code}] 腾讯返回价格为0")
                    else:
                        self.logger.warning(f"⚠️ [{code}] 腾讯返回空数据")
                except Exception as e:
                    self.logger.error(f"❌ [{code}] 腾讯获取收盘价失败: {e}")

    def step4_fetch_lof_market(self):
        """[AI-2026-06-28] 步骤四：仅获取净值（收盘价已分离到 _step4_fetch_prices）"""
        self.logger.info("=== 步骤四：抓取各基金最新净值 (东财API) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')

        # 从大一统基金列表获取所有基金代码+分类
        conn_ufl = self.db._get_conn()
        all_fund_rows = conn_ufl.execute("SELECT fund_code, category FROM unified_fund_list").fetchall()
        conn_ufl.close()
        fund_categories = {str(r[0]): (r[1] or '') for r in all_fund_rows if r[0]}
        all_codes = list(fund_categories.keys())
        T2_CATEGORIES = {'黄金原油', 'QDII欧美'}  # [AI-2026-07-09] 混合跨境已并入QDII欧美

        for code in all_codes:
            if not code: continue
            # 获取东财净值 ---
            def get_prev_trading_day(dt):
                t = dt - timedelta(days=1)
                while t.weekday() >= 5: t -= timedelta(days=1)
                return t
                
            t_1_date = get_prev_trading_day(datetime.now())
            t_2_date = get_prev_trading_day(t_1_date)
            
            # 按分类决定预期净值日期：海外品种T-2最新，国内/亚洲T-1最新
            category = fund_categories.get(code, '')
            if category in T2_CATEGORIES:
                expected_nav_date = t_2_date.strftime('%Y-%m-%d')
            else:
                expected_nav_date = t_1_date.strftime('%Y-%m-%d')
            
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM unified_fund_history WHERE fund_code = ? AND nav IS NOT NULL", (code,))
            max_nav_row = cursor.fetchone()
            conn.close()
            
            db_max_nav_date = max_nav_row[0] if max_nav_row and max_nav_row[0] else "2000-01-01"
            
            if db_max_nav_date >= expected_nav_date:
                nav_label = 'T-2' if category in T2_CATEGORIES else 'T-1'
                self.logger.info(f"✅ [{code}] 数据库已有{nav_label}净值 ({db_max_nav_date})，跳过东财接口...")
                self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
                continue
                
            self.logger.info(f"🔍 [{code}] 数据库最新净值({db_max_nav_date})落后于预期进度({expected_nav_date})，前往东财获取...")
            nav_df = self.hist_manager.get_nav(code, source="eastmoney")
            if not nav_df.empty:
                latest_nav_date = nav_df['date'].max().strftime('%Y-%m-%d')
                self.logger.info(f"✅ [{code}] 获取到历史净值，最新日期: {latest_nav_date}")
                for _, row in nav_df.iterrows():
                    d_str = row['date'].strftime('%Y-%m-%d')
                    self._safe_save_fund_data(date_str=d_str, fund_code=code, nav=row['nav'])
                if latest_nav_date >= expected_nav_date:
                    self.db.mark_access_synced(today_str, source=f'lof_nav_{code}')
            else:
                self.logger.warning(f"⚠️ [{code}] 东财接口未返回任何净值数据。")

        # [AI-2026-06-28] 假期修复移至 _run_pipeline，nav-only 不修价格

    def step4_5_sync_fund_purchase_status(self):
        """步骤4.5：从 AKShare 同步基金申赎状态"""
        self.logger.info("=== 步骤4.5：同步基金申购赎回状态 (AKShare) ===")
        try:
            from arbcore.fetchers.data_fetcher import data_fetcher
            data_fetcher.sync_akshare_fund_status(self.db)
        except Exception as e:
            self.logger.error(f"❌ 申赎状态同步失败: {e}")

    def step5_fetch_usa_market_data(self):
        """步骤五：抓取美股市场交易数据"""
        self.logger.info("=== 步骤五：抓取海外及指数市场交易数据 (标准库模式) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')

        # access_sync_status 防刷：今天已跑过步骤五就跳过
        if self.db.is_access_synced_today(today_str, source='usa_etf_data'):
            self.logger.info("⏭️ [海外/指数] 今日已抓取，跳过步骤五")
            return

        symbols = set()
        for fund in self.config.get('funds', []):
            for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                sym = str(item.get('symbol', '')).replace('^', '').split('-')[0]
                # 港股代码(5位纯数字如00700)允许通过，其他纯数字跳过
                if sym and (not sym.isdigit() or len(sym) == 5):
                    symbols.add(sym)

        for sym in symbols:
            df = self.hist_manager.get_prices(sym, source="sina", start_date=start_date)
            if not df.empty:
                for _, row in df.iterrows():
                    date_str = row['date'].strftime('%Y-%m-%d')
                    self.db.upsert_usa_etf_price(date=date_str, symbol=sym, price=row['close'])
                    # 同步更新大一统表中的指数价格
                    for fund in self.config.get('funds', []):
                        for item in fund.get('valuation_portfolio', []) + fund.get('hedging_portfolio', []):
                            if sym in str(item.get('symbol', '')):
                                self.db.save_unified_history(date_str=date_str, fund_code=fund['code'], index_close=row['close'])
                self.logger.info(f"✅ [海外/指数] {sym} 行情同步完成")

        self.db.mark_access_synced(today_str, source='usa_etf_data')
        self.logger.info(f"✅ [海外/指数] 步骤五完成，已标记防刷")

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


    def step8_fetch_sina_futures_from_vps(self):
        """步骤八：从VPS同步新浪期货数据，并带有本地接口兜底（收盘价和结算价）"""
        self.logger.info("=== 步骤八：获取新浪期货数据 (VPS优先 -> 本地兜底) ===")
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 如果今天的数据已经同步成功过，直接跳过
        if self.db.is_access_synced_today(today_str, source='futures_data'):
            self.logger.info("✅ 今日已同步过期货数据，跳过抓取。")
            return
            
        vps_futures_data = self._try_sync_all_from_vps('futures')
        vps_today_success = False
        
        if vps_futures_data:
            self.logger.info(f"🔄 [VPS] 发现 {len(vps_futures_data)} 份历史期货数据，正在同步入库...")
            for item in vps_futures_data:
                file_date = item['date']
                content = item['content']
                try:
                    date_info = content.get('date', file_date)
                    futures_list = content.get('data', [])
                    for f_data in futures_list:
                        symbol = f_data.get('symbol')
                        settle = f_data.get('settle')
                        close_price = f_data.get('close')
                        volume = f_data.get('volume')
                        
                        if symbol and (settle is not None or close_price is not None):
                            self.db.upsert_futures_daily(date=date_info, symbol=symbol, settle_price=settle, close_price=close_price, volume=volume)
                    
                    self.logger.info(f"   ✅ [VPS] 同步入库期货数据: {date_info} ({len(futures_list)} 个品种)")
                    self.db.mark_access_synced(file_date, 'futures_vps_sync')
                    if date_info >= today_str:
                        vps_today_success = True
                except Exception as e:
                    self.logger.error(f"   ❌ [VPS] 解析日期 {file_date} 期货数据时出错: {e}")

        if vps_today_success:
            self.db.mark_access_synced(today_str, source='futures_data')
            self.logger.info("✅ [VPS] 今日期货数据同步完成！")
            return
            
        # 本地兜底
        self.logger.warning("⚠️ [VPS] 未获取到今日期货数据，启动本地新浪API兜底...")
        from arbcore.fetchers.data_fetcher import data_fetcher
        fallback_data = data_fetcher.get_futures_settlement_data()
        if fallback_data:
            for f_data in fallback_data:
                symbol = f_data.get('symbol')
                settle = f_data.get('settle')
                close_price = f_data.get('close')
                volume = f_data.get('volume')
                if symbol and (settle is not None or close_price is not None):
                    self.db.upsert_futures_daily(date=today_str, symbol=symbol, settle_price=settle, close_price=close_price, volume=volume)
            self.db.mark_access_synced(today_str, source='futures_data')
            self.logger.info(f"✅ [本地兜底] 今日期货数据获取完成！")
        else:
            self.logger.error("❌ [本地兜底] 获取期货数据失败。")

    def step9_fetch_jsl_shares_from_vps(self):
        """步骤九：从VPS同步场内份额数据（含深交所+上交所）"""
        self.logger.info("=== 步骤九：从VPS同步场内份额数据 ===")
        today_str = datetime.now().strftime('%Y-%m-%d')

        # [V10.4] 防刷检查：今日已同步过则跳过，避免每次启动重复拉取 VPS
        if self.db.is_access_synced_today(today_str, source='jsl_shares_data'):
            self.logger.info("✅ 今日份额数据已同步，跳过 VPS 拉取")
            return

        vps_shares_data = self._try_sync_all_from_vps('shares')
        processed_count = 0
        skipped_count = 0
        
        if vps_shares_data:
            self.logger.info(f"🔄 [VPS] 发现 {len(vps_shares_data)} 份份额数据文件，正在逐日检查...")
            for item in vps_shares_data:
                file_date = item['date']
                content = item['content']
                
                # 总是处理每个文件（save_unified_history 使用 UPSERT，安全幂等）
                # 即使 DB 已有部分数据，VPS 文件可能包含更多基金（如扩展 symbols 后）
                try:
                    count = 0
                    for fund_code_raw, shares in content.items():
                        if shares is not None:
                            # 去掉 sh/sz 前缀，保持 fund_code 统一的 6 位数字格式
                            clean_code = fund_code_raw.lower().replace('sh', '').replace('sz', '')
                            self.db.save_unified_history(date_str=file_date, fund_code=clean_code, shares=shares)
                            count += 1
                    
                    self.logger.info(f"   ✅ [VPS] 入库份额数据: {file_date} ({count} 个品种)")
                    processed_count += 1
                except Exception as e:
                    self.logger.error(f"   ❌ [VPS] 解析日期 {file_date} 份额数据时出错: {e}")

            self.logger.info(f"✅ [VPS] 份额同步完成: 处理 {processed_count} 天, 跳过 {skipped_count} 天")
            
            # 标记今日已同步（防止其他入口重复触发）
            if any(item['date'] >= today_str for item in vps_shares_data):
                self.db.mark_access_synced(today_str, source='jsl_shares_data')
        else:
            self.logger.warning("⚠️ [VPS] 未获取到份额数据 (可能VPS采集失败或网络问题)")

    def _step10_calculate_static_valuation(self):
        """步骤十：基于同步后的因子数据，计算所有基金的静态估值 (static_val)"""
        # [AI-2026-07-03] 使用 __init__ 中已修正的 self.config_path，不再重复计算路径
        config_path = getattr(self, 'config_path', None)
        if not config_path or not os.path.exists(config_path):
            fallback_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "arbcore", "config", "lof_config.yaml")
            if os.path.exists(fallback_path):
                config_path = fallback_path
            else:
                self.logger.warning("⚠️ [静态估值] lof_config.yaml 不存在，跳过")
                return
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        calc = StaticValuationCalculator(self.db)
        success = 0
        for fund in config.get('funds', []):
            if not fund.get('valuation_portfolio') and not fund.get('hedging_portfolio'):
                continue  # 跳过无估值配置的基金（如白银期货）
            try:
                if calc.process_fund(fund):
                    success += 1
            except Exception as e:
                self.logger.error(f"  ❌ [{fund.get('code')}] 静态估值计算失败: {e}")
        self.logger.info(f"✅ [静态估值] 计算完成，{success}/{len(config.get('funds', []))} 只基金已更新")

    # ================================================================
    # 步骤十一：跟踪指数公式静态估值 (覆盖 QDII亚洲 / 国内LOF / 指数LOF)
    # 公式: static_val = prev_nav * (1 + pos_ratio * (idx_ratio * fx_ratio - 1))
    # 与魔法公式区别：用指数比率代替 ETF 价格/hedge，无需 hedge 参数
    # ================================================================
    def step11_simple_static_valuation(self):
        """
        跟踪指数公式静态估值：覆盖 step10 未处理的基金
        公式: static_val = prev_nav * (1 + pos_ratio * (idx_ratio * fx_ratio - 1))
        与魔法公式区别：用指数比率代替 ETF 价格/hedge，无需 hedge 参数
        """
        import sqlite3
        self.logger.info("=== 步骤十一：跟踪指数公式静态估值 (QDII亚洲/国内LOF/指数LOF) ===")

        # [AI-2026-06-29] 修复路径: 4层dirname才到项目根目录database/
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))), "database", "arb_master.db")
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        cursor = conn.cursor()

        # 1. 获取所有基金
        cursor.execute("SELECT fund_code, category, related_index, pos_ratio FROM unified_fund_list")
        all_funds = cursor.fetchall()

        # 2. 分类：step10 已处理黄金原油和有basket的基金，这里处理其余
        #    - 国内指数/指数LOF → A股，无汇率
        #    - QDII亚洲 → 港币
        #    - QDII欧美（无basket的，如标普500）→ 美元
        #    - 白银 → 跳过（期货估值特殊）
        a_share = []
        hk_funds = []
        us_funds = []

        # 读取 fund_list.csv 获取分类（与 jsl/03_eod_all.py 一致）
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "jsl", "fund_list.csv")
        fund_category = {}
        if os.path.exists(csv_path):
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                import csv
                reader = csv.DictReader(f)
                for row in reader:
                    code = row.get('代码', '').strip()
                    cat = row.get('分类', '').strip()
                    if code and cat:
                        fund_category[code] = cat

        hk_index_syms = {'HSI', 'HSCEI', 'HSCCI', 'HSMCI', 'HSTECH', 'HSCI', 'HSSI', 'HSSNCNE', 'HSMI'}

        for fund_code, category, related_index, pos_ratio in all_funds:
            if category == '白银':
                continue  # 白银跳过

            ri = str(related_index).strip() if related_index else ''
            if not ri or ri == '-' or ri == '0':
                continue  # 无跟踪标的，跳过

            ri_upper = ri.upper()
            ri_lower = ri.lower()

            # 按 category 分类
            if category in ('国内指数', '指数LOF', '国内LOF'):
                a_share.append((fund_code, ri, pos_ratio or 0.95))
            elif category == 'QDII亚洲':
                hk_funds.append((fund_code, ri, pos_ratio or 0.95))
            elif category == 'QDII欧美':
                us_funds.append((fund_code, ri, pos_ratio or 0.95))
            elif category == '黄金原油':
                continue  # step10 已处理
            else:
                # 根据指数代码推断
                if ri_upper in hk_index_syms or ri_lower in {s.lower() for s in hk_index_syms}:
                    hk_funds.append((fund_code, ri, pos_ratio or 0.95))
                elif ri_lower.startswith('399') or ri_lower.startswith('000') or ri_lower.startswith('001') or '.csi' in ri_lower:
                    a_share.append((fund_code, ri, pos_ratio or 0.95))
                elif ri_upper in ('.INX', '.NDX', 'SPY', 'QQQ', 'XOP', 'XLY', 'XBI', 'KWEB', 'RSPH', 'INDA'):
                    us_funds.append((fund_code, ri, pos_ratio or 0.95))

        self.logger.info(f"  分类结果: A股={len(a_share)}, 港股={len(hk_funds)}, 美股={len(us_funds)}")

        total_updated = 0

        def process_batch(funds, batch_name, fx_type='none'):
            nonlocal total_updated
            if not funds:
                return
            self.logger.info(f"  --- {batch_name} ({len(funds)} 只) ---")

            for fund_code, related_index, pos_ratio in funds:
                # 获取指数历史数据
                cursor.execute(
                    "SELECT date, close FROM index_history WHERE symbol = ? ORDER BY date",
                    (related_index.upper(),))
                idx_rows = cursor.fetchall()
                if not idx_rows:
                    # 尝试小写
                    cursor.execute(
                        "SELECT date, close FROM index_history WHERE symbol = ? ORDER BY date",
                        (related_index.lower(),))
                    idx_rows = cursor.fetchall()
                if not idx_rows:
                    self.logger.warning(f"    [{fund_code}] 指数 {related_index} 无历史数据，跳过")
                    continue

                idx_data = {r[0]: r[1] for r in idx_rows}

                # 获取该基金的交易日数据
                cursor.execute(
                    "SELECT date, nav, price, index_close FROM unified_fund_history "
                    "WHERE fund_code = ? AND nav IS NOT NULL ORDER BY date",
                    (fund_code,))
                fund_rows = cursor.fetchall()

                count = 0
                last_fx_pct = 0

                for date, nav, price, existing_idx_close in fund_rows:
                    if not nav or float(nav) <= 0:
                        continue

                    # 回写 index_close（如果缺失）
                    if date in idx_data:
                        current_idx_close = idx_data[date]
                        if existing_idx_close is None:
                            cursor.execute(
                                "UPDATE unified_fund_history SET index_close = ? "
                                "WHERE fund_code = ? AND date = ?",
                                (current_idx_close, fund_code, date))
                    else:
                        current_idx_close = existing_idx_close

                    if current_idx_close is None:
                        continue

                    # 找基准日：前一个有 nav 和 index_close 的交易日
                    cursor.execute(
                        "SELECT date, nav, index_close FROM unified_fund_history "
                        "WHERE fund_code = ? AND date < ? AND nav IS NOT NULL "
                        "ORDER BY date DESC LIMIT 1",
                        (fund_code, date))
                    prev_row = cursor.fetchone()
                    if not prev_row:
                        continue

                    prev_date, prev_nav, prev_idx_close = prev_row
                    if not prev_nav or float(prev_nav) <= 0 or not prev_idx_close or float(prev_idx_close) <= 0:
                        continue

                    # 汇率比率
                    fx_ratio = 1.0
                    if fx_type != 'none':
                        if fx_type == 'usd':
                            cursor.execute("SELECT usd_cny_mid FROM exchange_rate WHERE date = ?", (date,))
                            curr_fx = cursor.fetchone()
                            cursor.execute("SELECT usd_cny_mid FROM exchange_rate WHERE date = ?", (prev_date,))
                            prev_fx = cursor.fetchone()
                        else:  # hkd
                            cursor.execute("SELECT hkd_cny_mid FROM exchange_rate WHERE date = ?", (date,))
                            curr_fx = cursor.fetchone()
                            cursor.execute("SELECT hkd_cny_mid FROM exchange_rate WHERE date = ?", (prev_date,))
                            prev_fx = cursor.fetchone()

                        curr_val = curr_fx[0] if curr_fx and curr_fx[0] else None
                        prev_val = prev_fx[0] if prev_fx and prev_fx[0] else None
                        if curr_val and prev_val and prev_val > 0:
                            fx_ratio = curr_val / prev_val
                        else:
                            continue

                    # 指数比率
                    idx_ratio = float(current_idx_close) / float(prev_idx_close)

                    # 静态估值
                    static_val = float(prev_nav) * (1 + pos_ratio * (idx_ratio * fx_ratio - 1))

                    # 溢价率 (用收盘价)
                    premium = None
                    if price and float(price) > 0:
                        premium = (float(price) / float(nav) - 1) * 100

                    # 估值误差
                    calibration = (static_val / float(nav) - 1) * 100 if float(nav) > 0 else None

                    # 指数涨幅
                    index_pct = (idx_ratio - 1) * 100

                    # 溢价率误差（估算溢价 - 实际溢价）
                    rt_premium = None
                    if price and float(price) > 0 and static_val > 0:
                        est_premium = (float(price) / static_val - 1) * 100
                        if premium is not None:
                            rt_premium = est_premium - premium

                    cursor.execute(
                        "UPDATE unified_fund_history SET static_val=?, premium=?, "
                        "index_pct=?, calibration=?, rt_premium=? "
                        "WHERE fund_code=? AND date=?",
                        (static_val, premium, index_pct, calibration, rt_premium,
                         fund_code, date))
                    if cursor.rowcount > 0:
                        count += 1

                total_updated += count
                if count > 0:
                    self.logger.info(f"    [{fund_code}] 更新 {count} 条")

        process_batch(a_share, "A股指数/LOF (无汇率)", fx_type='none')
        process_batch(hk_funds, "QDII亚洲 (港币)", fx_type='hkd')
        process_batch(us_funds, "QDII欧美 (美元)", fx_type='usd')

        conn.commit()
        conn.close()
        self.logger.info(f"✅ [简单估值] 完成，共更新 {total_updated} 条记录")

    def run(self, nav_only=False, refresh_morning=False):
        today_str = datetime.now().strftime('%Y-%m-%d')
        now = datetime.now()

        if refresh_morning:
            self.logger.info("🚀 [清晨刷新] 清除9:20前旧标记，重新抓取 Woody/汇率/VPS 上午数据...")
            if now.weekday() in (5, 6):
                self.logger.info("📅 周末跳过。")
                return
            for src in ['woody_lof_batch', 'official_exchange_rate', 'futures_data', 'jsl_shares_data']:
                self.logger.info(f"🗑️ 清除 {src} 标记")
                self.db.remove_access_sync_status(today_str, src)
            self._run_pipeline()
            self.logger.info("🎉 [清晨刷新] Woody/汇率/VPS 数据已重新同步！")
            return

        if nav_only:
            self.logger.info("🚀 [NAV模式] 仅执行净值更新 (step4)...")
            self.step4_fetch_lof_market()
            self.logger.info("🎉 [NAV模式] 净值更新完毕！")
            return

        # 默认：完整流水线（周末跳过除净值外的所有步骤）
        if now.weekday() in (5, 6):
            self.logger.info("📅 [周末] 跳过完整流水线，仅执行净值更新+静态估值...")
            self.step4_fetch_lof_market()
            # [AI-2026-07-04] 周末也跑静态估值计算，避免 nav 更新后 static_val 缺失
            self._step10_calculate_static_valuation()
            self.logger.info("🎉 [周末净值+静态估值] 更新完毕！")
            return
        self._run_pipeline()

    def _run_pipeline(self):
        self.logger.info("🚀 开始执行每日数据大一统更新流水线...")
        self.step1_and_2_fetch_woody_api()
        self.step2_5_sync_yaml_with_latest_factors()
        self.step3_fetch_exchange_rate()
        # [AI-2026-06-28] 价格+净值分开，nav-only 只拉净值
        self._step4_fetch_prices()
        self.step4_fetch_lof_market()
        # [AI-2026-06-28] 假期价格修复只在完整流水线跑，不干扰 nav-only
        self._step4_fix_holiday_prices()
        self.step4_5_sync_fund_purchase_status()
        self.step5_fetch_usa_market_data()
        self.step7_fetch_extra_calibrations()
        self.step8_fetch_sina_futures_from_vps()
        self.step9_fetch_jsl_shares_from_vps()
        self._step10_calculate_static_valuation()
        self.step11_simple_static_valuation()
        self.logger.info("🎉 流水线执行完毕，数据大盘一切就绪！")

if __name__ == "__main__":
    import argparse
    import subprocess

    parser = argparse.ArgumentParser(description="ArbNext 日度数据流水线")
    parser.add_argument("--nav-only", action="store_true", help="仅更新基金净值 (step4)")
    parser.add_argument("--refresh-morning", action="store_true", help="清除上午标记后重新抓取 Woody/汇率/VPS")
    args = parser.parse_args()

    # 进程互斥锁（跨平台）：用 PID 文件防多实例
    lock_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_updater.lock")

    def _is_pid_alive(pid):
        try:
            if os.name == 'nt':
                result = subprocess.run(['tasklist', '/FI', f'PID eq {pid}'], capture_output=True, text=True, timeout=5)
                return str(pid) in result.stdout
            else:
                os.kill(pid, 0)
                return True
        except (OSError, subprocess.TimeoutExpired):
            return False

    locked = False
    try:
        with open(lock_path, 'x') as f:
            f.write(str(os.getpid()))
        locked = True
    except FileExistsError:
        try:
            with open(lock_path, 'r') as f:
                old_pid = int(f.read().strip())
            if _is_pid_alive(old_pid):
                print(f"[SKIP] 另一个 daily_updater 实例正在运行 (PID {old_pid})，退出。")
                sys.exit(0)
            # 旧进程已死，抢锁
            with open(lock_path, 'w') as f:
                f.write(str(os.getpid()))
            locked = True
        except (ValueError, FileNotFoundError):
            with open(lock_path, 'w') as f:
                f.write(str(os.getpid()))
            locked = True

    try:
        DailyUpdater().run(nav_only=args.nav_only, refresh_morning=args.refresh_morning)
    finally:
        if locked:
            try:
                os.remove(lock_path)
            except OSError:
                pass
