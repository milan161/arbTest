# -*- coding: utf-8 -*-
# woody_api_service.py - 统一的 Woody API 数据获取、备份与因子解析服务

import os
import os # 确保 os 模块被导入
import json
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
        
        force_update = os.environ.get("FORCE_WOODY_UPDATE", "0") == "1"

        # 1. 防刷检查
        if force_update:
            logger.warning(f"⚠️ FORCE_WOODY_UPDATE 环境变量已设置，强制重新拉取 {source_id} 数据...")
            # 强制更新前，先移除旧的同步状态，确保新的成功同步能被记录
            db.remove_access_sync_status(today_str, sync_key)
        elif db.is_access_synced_today(today_str, sync_key):
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
        
        try:
            result = FetchPalmmicroData(symbols_str)
        except Exception as e:
            logger.error(f"❌ 调用 FetchPalmmicroData 崩溃: {e}")
            return None

        if not result or 'text' not in result:
            logger.error("❌ Woody API 返回为空或不包含 text 节点。")
            return None

        api_data = result['text']
        if isinstance(api_data, str):
            try: api_data = json.loads(api_data)
            except: pass
                
        raw_json_str = json.dumps(api_data, ensure_ascii=False, indent=2) if isinstance(api_data, dict) else str(api_data)
        
        # 3. 存入原始数据湖
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

        # 5. 调用之前 011 中的提纯入库逻辑 (代码过长，复用了原处理大一统因子及ETF变种权重的逻辑，直接集成于后台)
        # == 此处省略提取 fund_daily_factors 和 etf_prices 的纯享逻辑实现，详见完整代码 ==
        if isinstance(api_data, dict):
            for sym, f_data in api_data.items():
                if not isinstance(f_data, dict): continue
                fund_code = sym.replace('sh', '').replace('sz', '').replace('SH', '').replace('SZ', '')
                
                raw_date = f_data.get('date', '')
                b_date = pd.to_datetime(str(raw_date).strip()).strftime('%Y-%m-%d') if raw_date else today_str
                pos = f_data.get('position')
                pos = float(pos)/100.0 if pos and float(pos) > 1 else (float(pos) if pos else 1.0)
                cal = float(f_data['calibration']) if 'calibration' in f_data else None
                hed = float(f_data['hedge']) if 'hedge' in f_data else None
                nav_val = float(f_data['netvalue']) if f_data.get('netvalue') else None
                
                db.upsert_fund_factor(date=b_date, fund_code=fund_code, calibration=cal, hedge=hed, position=pos, nav=nav_val)
                
                sh_data = f_data.get('symbol_hedge')
                if isinstance(sh_data, dict):
                    for etf_sym, etf_info in sh_data.items():
                        clean_etf = etf_sym
                        if ('-JP' in clean_etf or '-EU' in clean_etf or '-HK' in clean_etf) and not clean_etf.startswith('^'): clean_etf = f"^{clean_etf}"
                        price = float(etf_info.get('price', 0))
                        ratio = float(etf_info.get('ratio', 0))
                        
                        if price > 0 and clean_etf.startswith('^'): db.upsert_usa_etf_price(date=b_date, symbol=clean_etf, price=price)
                        if ratio > 0: db.upsert_fund_basket_weight(date=b_date, fund_code=fund_code, underlying_symbol=clean_etf, weight=ratio)

        db.mark_access_synced(today_str, sync_key)
        logger.info(f"✅ [{source_id}] 因子提纯入库与双备份完毕！")
        return api_data
