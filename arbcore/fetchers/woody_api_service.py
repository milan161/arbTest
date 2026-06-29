# -*- coding: utf-8 -*-
# woody_api_service.py - 统一的 Woody API 数据获取、备份与因子解析服务

import os
import json
import time  # 🌟 新增：用于重试机制的延时
from datetime import datetime
import pandas as pd
import logging

from .woody_telegram_client import FetchPalmmicroData

logger = logging.getLogger(__name__)

class WoodyAPIService:
    @staticmethod
    def fetch_and_process(db, codes: list, backup_dir: str, source_id: str):
        """
        核心共享逻辑：拉取Woody API、保存数据湖、生成CSV/JSON双备份、提纯入库
        :param db: DatabaseManager 实例
        :param codes: 基金代码列表 (如 ['162411', '513350'])
        :param backup_dir: 备份文件存放的物理绝对目录
        :param source_id: 来源标识 (用于数据湖和防刷标记，如 'woody_lof' 或 'woody_etf')
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        sync_key = f"{source_id}_batch"
        
        # 1. 防刷检查
        if db.is_access_synced_today(today_str, sync_key):
            logger.info(f"✅ 今日已成功拉取过 {source_id}，防刷机制启动，跳过网络请求...")
            raw_content = db.get_raw_api_data(today_str, source_id)
            if not raw_content:
                return None
            try:
                return json.loads(raw_content)
            except Exception:
                return None

        # 2. 拼装请求并调用 Telegram 接口
        symbols = []
        for c in codes:
            c_str = str(c).strip()
            if not c_str: continue
            prefix = 'sh' if c_str.startswith('5') else 'sz'
            symbols.append(f"{prefix}{c_str}")
        
        symbols_str = ",".join(set(symbols))
        logger.info(f"📡 正在向 Woody API 发起批量请求: {symbols_str}")
        
        # 🌟 优化：引入带指数退避的重试机制 (最多尝试 3 次)
        max_retries = 3
        result = None
        for attempt in range(1, max_retries + 1):
            try:
                result = FetchPalmmicroData(symbols_str)
                if result and 'text' in result:
                    break  # 获取成功，跳出重试循环
                else:
                    logger.warning(f"⚠️ 第 {attempt} 次请求成功，但返回数据格式异常或为空。")
            except Exception as e:
                logger.warning(f"⚠️ 第 {attempt} 次请求 Woody API 失败: {e}")
            
            if attempt < max_retries:
                sleep_time = 2 ** attempt  # 指数退避: 第1次失败等2秒，第2次等4秒
                logger.info(f"⏳ 等待 {sleep_time} 秒后进行第 {attempt + 1} 次重试...")
                time.sleep(sleep_time)

        if not result or 'text' not in result:
            logger.error("❌ Woody API 历经多次重试后依然返回为空或请求失败。")
            return None

        api_data = result['text']
        if isinstance(api_data, str):
            try: api_data = json.loads(api_data)
            except: pass
                
        # 3. 校验 API 返回数据质量：必须是 dict 且包含基金代码键
        if not isinstance(api_data, dict) or not api_data:
            logger.error(f"❌ [woody_lof] API 返回数据无效（非字典或为空），不入库。原始内容: {str(api_data)[:200]}")
            return None

        raw_json_str = json.dumps(api_data, ensure_ascii=False, indent=2)
        
        # 4. 存入原始数据湖
        db.save_raw_api_data(date=today_str, source=source_id, raw_content=raw_json_str)

        # 4. 智能生成 JSON / 动态宽表 CSV 备份
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M')
        
        try:
            # JSON
            json_path = os.path.join(backup_dir, f"Data_{source_id}_{timestamp}.json")
            with open(json_path, 'w', encoding='utf-8') as f:
                f.write(raw_json_str)
                
            # 动态 CSV (修复原有写死字段导致新ETF丢失的问题)
            if isinstance(api_data, dict):
                csv_data = []
                dynamic_cols = set(['symbol', 'type', 'CNY', 'position', 'date', 'netvalue', 'CNYholdings', 'calibration', 'hedge', 'symbol_hedge'])
                
                for sym, f_data in api_data.items():
                    if not isinstance(f_data, dict): continue
                    row = {'symbol': sym}
                    for field in ['type', 'CNY', 'position', 'date', 'netvalue', 'CNYholdings', 'calibration', 'hedge']:
                        row[field] = f_data.get(field, '')
                    
                    sh_data = f_data.get('symbol_hedge', '')
                    if isinstance(sh_data, dict):
                        for e_name, e_data in sh_data.items():
                            clean_name = e_name
                            if ('-JP' in clean_name or '-EU' in clean_name or '-HK' in clean_name) and not clean_name.startswith('^'): 
                                clean_name = f"^{clean_name}"
                            p_col, r_col = f"{clean_name}_price", f"{clean_name}_ratio"
                            dynamic_cols.update([p_col, r_col])
                            row[p_col] = e_data.get('price', '')
                            row[r_col] = e_data.get('ratio', '')
                    else:
                        row['symbol_hedge'] = str(sh_data)
                    csv_data.append(row)
                    
                if csv_data:
                    std_cols = ['symbol', 'type', 'CNY', 'position', 'date', 'netvalue', 'CNYholdings', 'calibration', 'hedge', 'symbol_hedge']
                    final_cols = std_cols + sorted(list(dynamic_cols - set(std_cols)))
                    csv_path = os.path.join(backup_dir, f"Data_{source_id}_{timestamp}.csv")
                    pd.DataFrame(csv_data, columns=final_cols).to_csv(csv_path, index=False, encoding='utf-8-sig')
        except Exception as e:
            logger.error(f"⚠️ 生成备份文件失败: {e}")

        # 5. 验证数据有效性（防止错误信息被标记为成功）
        if not isinstance(api_data, dict) or len(api_data) == 0:
            logger.error(f"❌ [{source_id}] API 返回数据无效（非字典或为空），不标记防刷。原始内容: {str(api_data)[:200]}")
            return None

        # 6. 调用提纯入库逻辑
        WoodyAPIService.process(db, api_data, source_id)

        # 7. 数据验证通过后才标记防刷（修复 bug：之前错误信息也会被标记）
        db.mark_access_synced(today_str, sync_key)
        logger.info(f"✅ [{source_id}] 因子提纯入库与双备份完毕！")
        return api_data

    @staticmethod
    def process(db, api_data: dict, source_id: str = 'woody_lof'):
        """
        核心数据提纯入库解析逻辑，支持解析最新的估值日数据 (est_date, est_price)
        """
        today_str = datetime.now().strftime('%Y-%m-%d')
        if not isinstance(api_data, dict):
            return None
            
        for sym, f_data in api_data.items():
            if not isinstance(f_data, dict): continue

            # 🌟 新增：如果是基础标的（如 GLD, USO, ^GSPC, ^NDX），则提取其校准值存入 futures_daily
            if sym in ['GLD', 'USO', '^GSPC', '^NDX']:
                future_mapping = {'GLD': 'GC', 'USO': 'CL', '^GSPC': 'ES', '^NDX': 'NQ'}
                db_sym = future_mapping.get(sym)
                api_calib = f_data.get('calibration')
                api_date = f_data.get('est_date', f_data.get('date', today_str))
                if api_calib:
                    try:
                        calib_val = float(api_calib)
                        if calib_val > 0:
                            db.upsert_futures_daily(date=api_date, symbol=db_sym, calibration=calib_val)
                            logging.info(f"✅ 从API同步全局校准值: {db_sym} = {calib_val} (日期: {api_date})")
                    except Exception as e:
                        logging.error(f"❌ 解析全局校准值 {sym} 失败: {e}")

            fund_code = sym.replace('sh', '').replace('sz', '').replace('SH', '').replace('SZ', '')
            
            raw_date = f_data.get('date', '')
            b_date = pd.to_datetime(str(raw_date).strip()).strftime('%Y-%m-%d') if raw_date else today_str
            
            # --- 解析最新的估值日 (est_date) ---
            est_date_raw = f_data.get('est_date', '')
            e_date = pd.to_datetime(str(est_date_raw).strip()).strftime('%Y-%m-%d') if est_date_raw else None
            
            pos = f_data.get('position')
            pos = float(pos)/100.0 if pos and float(pos) > 2 else (float(pos) if pos else 1.0)
            cal = float(f_data['calibration']) if 'calibration' in f_data else None
            hed = float(f_data['hedge']) if 'hedge' in f_data else None
            nav_val = float(f_data['netvalue']) if f_data.get('netvalue') else None
            
            db.upsert_fund_factor(date=b_date, fund_code=fund_code, calibration=cal, hedge=hed, position=pos, nav=nav_val)
            
            # 🌟 Woody API 返回了真实仓位时，同步更新 unified_fund_list.pos_ratio
            raw_pos = f_data.get('position')
            if raw_pos is not None:
                try:
                    clean_pos = float(raw_pos)/100.0 if float(raw_pos) > 2 else float(raw_pos)
                    db.update_fund_pos_ratio(fund_code, clean_pos)
                except (ValueError, TypeError) as e:
                    logger.warning(f"⚠️ 解析 position 失败 {fund_code}: raw={raw_pos}, err={e}")
            
            # 保存 Woody 提供的估值日汇率 (CNYest) 到汇率表 (可选的增强)
            if e_date and f_data.get('CNYest'):
                try:
                    cny_est = float(f_data['CNYest'])
                    db.upsert_exchange_rate(e_date, usd_cny_mid=cny_est)
                except Exception:
                    pass
            
            sh_data = f_data.get('symbol_hedge')
            if isinstance(sh_data, dict):
                for etf_sym, etf_info in sh_data.items():
                    clean_etf = etf_sym
                    if ('-JP' in clean_etf or '-EU' in clean_etf or '-HK' in clean_etf) and not clean_etf.startswith('^'): clean_etf = f"^{clean_etf}"
                    price = float(etf_info.get('price', 0))
                    est_price = float(etf_info.get('est_price', 0)) if etf_info.get('est_price') else 0.0
                    ratio = float(etf_info.get('ratio', 0))
                    
                    # [AI-2026-06-29] 修复：移除 clean_etf.startswith('^') 限制，
                    # 使非^符号（GLD/SLV/USO等）的 price/est_price 也能写入 usa_etf_daily_prices
                    # 这些是真实的 ETF 市场价格（区别于顶层 netvalue 是 NAV）
                    if price > 0: 
                        db.upsert_usa_etf_price(date=b_date, symbol=clean_etf, price=price)
                    
                    if est_price > 0 and e_date:
                        db.upsert_usa_etf_price(date=e_date, symbol=clean_etf, price=est_price)
                        
                    if ratio != 0: db.upsert_fund_basket_weight(date=b_date, fund_code=fund_code, underlying_symbol=clean_etf, weight=ratio)
                    
        return api_data
