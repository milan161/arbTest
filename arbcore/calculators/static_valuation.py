# -*- coding: utf-8 -*-
# static_valuation.py - 静态估值核心计算引擎

import pandas as pd
from datetime import datetime
import logging
from .valuation_math import calculate_magic_valuation

logger = logging.getLogger(__name__)

class StaticValuationCalculator:
    def __init__(self, db_manager):
        """
        传入 DatabaseManager 实例以复用 SQLite 连接
        """
        self.db = db_manager
        
    def process_fund(self, fund):
        fund_code = str(fund.get('code', ''))
        if not fund_code: return
        
        name = fund.get('name', '')
        category = fund.get('category', '')
        logger.info(f"=== 开始计算 {name} ({fund_code}) 静态估值 ===")
        
        conn = self.db._get_conn()
        
        # 1. & 2. 使用 Outer Join 联合 A股行情与汇率，构建全集日期基座
        lof_df = pd.read_sql("SELECT date, price as close, nav FROM fund_data WHERE fund_code = ?", conn, params=(fund_code,))
        fx_df = pd.read_sql("SELECT date, usd_cny_mid as exchange_rate FROM exchange_rate", conn)
        df = pd.merge(lof_df, fx_df, on='date', how='outer')
        
        # 剔除未来的脏数据，并过滤掉啥都没有的幽灵行
        today_str = datetime.now().strftime('%Y-%m-%d')
        df = df[df['date'] <= today_str]
        df.dropna(subset=['close', 'nav', 'exchange_rate'], how='all', inplace=True)
        
        # 3. 匹配基金因子常数
        factors_df = pd.read_sql("SELECT date, position as 仓位, hedge, calibration FROM fund_daily_factors WHERE fund_code = ?", conn, params=(fund_code,))
        df = pd.merge(df, factors_df, on='date', how='left')
        
        # 4. 匹配海外底层 ETF 行情
        portfolio = fund.get('valuation_portfolio', [])
        if not portfolio:
            portfolio = fund.get('hedging_portfolio', [])
            
        # 提取核心主锚点 (用于常量折叠极简魔法)
        primary_sym = None
        if portfolio:
            first_sym = portfolio[0].get('symbol', '').replace('^', '').split('-')[0]
            base_syms = ['GLD', 'USO', 'XOP', 'XBI', 'SLV', 'SPY', 'QQQ']
            for bs in base_syms:
                if bs in first_sym:
                    primary_sym = bs
                    break
            if not primary_sym:
                primary_sym = first_sym
            
        etf_symbols = []
        for item in portfolio:
            sym = item.get('symbol', '').replace('^', '')
            if sym in ['GLD-JP', 'GLD-EU', 'USO-JP', 'USO-EU', 'USO-HK']:
                sym = f"^{sym}"
            etf_symbols.append(sym)
            
            # 匹配价格
            etf_df = pd.read_sql(f'SELECT date, price as "{sym}" FROM usa_etf_daily_prices WHERE symbol = ?', conn, params=(sym,))
            df = pd.merge(df, etf_df, on='date', how='left')
            
            # 匹配每日动态变化的真实仓位权重
            weight_df = pd.read_sql(f'SELECT date, weight as "{sym}权重" FROM fund_basket_weights WHERE fund_code = ? AND underlying_symbol = ?', conn, params=(fund_code, sym))
            df = pd.merge(df, weight_df, on='date', how='left')
            
        # 确保魔法锚点 ETF 也被拉入计算基座
        if primary_sym and primary_sym not in df.columns:
            primary_df = pd.read_sql(f'SELECT date, price as "{primary_sym}" FROM usa_etf_daily_prices WHERE symbol = ?', conn, params=(primary_sym,))
            df = pd.merge(df, primary_df, on='date', how='left')

        # 5. 匹配大宗期货结算价行情
        future_sym = None
        f_list = fund.get('future_hedging', [])
        if f_list:
            raw_sym = f_list[0].get('symbol', '').upper()
            mapping = {'MGC': 'GC', 'MCL': 'CL', '沪银AG': 'AG0', 'MES': 'ES', 'MNQ': 'NQ', 'CL': 'CL', 'GC': 'GC', 'NQ': 'NQ', 'ES': 'ES'}
            future_sym = mapping.get(raw_sym, raw_sym)
        else:
            if category == '黄金': future_sym = 'GC'
            elif category == '原油' and fund_code != '162411': future_sym = 'CL'
            elif category == '指数':
                if fund_code in ['161130', '161128']: future_sym = 'NQ'
                elif fund_code in ['161125', '161127']: future_sym = 'ES'
                
        if future_sym:
            fut_df = pd.read_sql(f'SELECT date, settle_price as "{future_sym}_settle", calibration as "{future_sym}_calib" FROM futures_daily WHERE symbol = ?', conn, params=(future_sym,))
            df = pd.merge(df, fut_df, on='date', how='left')
            df['期货结算价'] = df[f"{future_sym}_settle"]
            
            if category == '黄金':
                df.rename(columns={f"{future_sym}_calib": '黄金期货校准'}, inplace=True)
            elif category == '原油':
                df.rename(columns={f"{future_sym}_calib": '原油期货校准'}, inplace=True)

        # 6. 匹配纯净指数行情 (如果有)
        idx_url = fund.get('sina_index_url', '')
        idx_sym = None
        if idx_url:
            import re
            m = re.search(r'\.(INX|NDX|DJI)', idx_url, re.IGNORECASE)
            idx_sym = f".{m.group(1).upper()}" if m else None
        if idx_sym:
            idx_df = pd.read_sql(f'SELECT date, price as "{idx_sym}" FROM index_daily WHERE symbol = ?', conn, params=(idx_sym,))
            df = pd.merge(df, idx_df, on='date', how='left')
        
        conn.close()
        
        # ================= 极速矩阵运算核心 =================
        df['date'] = pd.to_datetime(df['date'])
        df.sort_values('date', ascending=False, inplace=True)
        df.reset_index(drop=True, inplace=True)
        
        # === 核心修复：向下兼容 (bfill)，继承最近一个交易日的真实API因子 ===
        # 1. 宏观期货校准继承 (注：严禁穿透继承 仓位、hedge 和 calibration)
        for col in ['黄金期货校准', '原油期货校准']:
            if col in df.columns:
                df[col] = df[col].bfill()
                
        # 2. ETF权重继承与兜底
        for item in portfolio:
            sym = item.get('symbol', '').replace('^', '')
            if sym in ['GLD-JP', 'GLD-EU', 'USO-JP', 'USO-EU', 'USO-HK']:
                sym = f"^{sym}"
            w_col = f"{sym}权重"
            if w_col in df.columns:
                df[w_col] = df[w_col].bfill().fillna(item.get('weight', 0))
                
        # 3. 仓位终极兜底转换 (仅在连历史最老一天都没有API数据时才触发)
        default_pos = fund.get('holdings', {}).get('equity_ratio', 100)
        if default_pos > 1: default_pos = default_pos / 100.0
        if '仓位' in df.columns:
            df['仓位'] = df['仓位'].fillna(default_pos)
            df['仓位'] = df['仓位'].apply(lambda x: x / 100.0 if x > 1 else x)
        
        # 初始化计算列占位符
        df['static_valuation'] = None
        df['变化比例'] = None
        df['ETF静态估值误差'] = None
        df['ETF静态溢价'] = None
        if future_sym:
            df['期货静态估值'] = None
            df['期货静态估值误差'] = None
            df['期货静态估值溢价'] = None
        if idx_sym:
            df['index_valuation'] = None
            df['指数静态估值误差'] = None
        
        # 历史滑动窗口计算
        for i in range(len(df)):
            row = df.loc[i]
            
            base_idx = -1
            for k in range(i + 1, min(i + 15, len(df))):
                b_row = df.loc[k]
                if pd.isna(b_row['nav']) or b_row['nav'] <= 0: continue
                if pd.isna(b_row['exchange_rate']) or b_row['exchange_rate'] <= 0: continue
                has_all_etfs = True
                for sym in etf_symbols:
                    if pd.isna(b_row.get(sym)) or b_row.get(sym) <= 0:
                        has_all_etfs = False
                        break
                if not has_all_etfs: continue
                base_idx = k
                break
                
            if base_idx == -1: continue
            b_row = df.loc[base_idx]
            
            base_nav, base_fx = b_row['nav'], b_row['exchange_rate']
            b_hedge = b_row.get('hedge')
            cur_fx = row['exchange_rate']
            if pd.isna(cur_fx) or cur_fx <= 0: continue
                
            fx_change = cur_fx / base_fx
            # 核心修正：估值推演必须且只能使用基准日(T-1)的仓位，绝不能使用估值日(T)的仓位！
            position = b_row['仓位']
            
            # 1. 计算【ETF 静态官方估值】
            val = None
            net_ratio = None
            
            # 🌟 魔法捷径：Woody 常量折叠极简推演
            # 逻辑：仅限单一纯净ETF(如XOP/SPY)使用单一代入。多区域组合(黄金/原油)必须强制走矩阵兜底。
            if pd.notna(b_hedge) and b_hedge > 0 and primary_sym and primary_sym in row and len(portfolio) == 1:
                c_price = row.get(primary_sym)
                if pd.notna(c_price) and c_price > 0:
                    val = calculate_magic_valuation(base_nav, position, c_price, cur_fx, b_hedge)
                    if val is not None:
                        net_ratio = (val / base_nav) - 1
            
            # 🌟 降级兜底：传统的矩阵推演
            # 逻辑：万一昨天的 Woody API 挂了没抓到因子，自动退回“一篮子ETF+权重”的安全矩阵算法
            if val is None:
                etf_factor, has_cur_etfs, valid_weight = 0.0, True, 0.0
                for sym in etf_symbols:
                    weight = row.get(f"{sym}权重", 0.0)
                    c_price = row.get(sym)
                    b_price = b_row.get(sym)
                    if pd.isna(c_price) or c_price <= 0 or pd.isna(b_price) or b_price <= 0:
                        has_cur_etfs = False
                        break
                    etf_factor += (c_price / b_price) * (weight / 100.0)
                    valid_weight += (weight / 100.0)
                    
                if has_cur_etfs and valid_weight > 0:
                    if valid_weight < 0.98 or valid_weight > 1.02: 
                        etf_factor = etf_factor / valid_weight # 归一化防偏离
                    net_ratio = position * (etf_factor * fx_change - 1)
                    val = base_nav * (1 + net_ratio)
            
            if val is not None:
                df.at[i, 'static_valuation'] = round(val, 4)
                df.at[i, '变化比例'] = f"{net_ratio * 100:.4f}%"
                
                nav = row['nav']
                if pd.notna(nav) and nav > 0:
                    df.at[i, 'ETF静态估值误差'] = f"{(val - nav) / nav:.2%}"
                    
                close = row['close']
                if pd.notna(close) and close > 0:
                    df.at[i, 'ETF静态溢价'] = f"{(close - val) / val:.2%}"
                    
            # 2. 计算【大宗期货 静态估值】
            if future_sym:
                c_fut, b_fut = row.get('期货结算价'), b_row.get('期货结算价')
                if pd.notna(c_fut) and c_fut > 0 and pd.notna(b_fut) and b_fut > 0:
                    fut_ratio = position * ((c_fut / b_fut) * fx_change - 1)
                    f_val = base_nav * (1 + fut_ratio)
                    df.at[i, '期货静态估值'] = round(f_val, 4)
                    nav = row['nav']
                    if pd.notna(nav) and nav > 0:
                        df.at[i, '期货静态估值误差'] = f"{(f_val - nav) / nav:.2%}"
                    close = row['close']
                    if pd.notna(close) and close > 0:
                        df.at[i, '期货静态估值溢价'] = f"{(close - f_val) / f_val:.2%}"
                        
            # 3. 计算【纯净指数 静态估值】
            if idx_sym:
                c_idx, b_idx = row.get(idx_sym), b_row.get(idx_sym)
                if pd.notna(c_idx) and c_idx > 0 and pd.notna(b_idx) and b_idx > 0:
                    idx_ratio = position * ((c_idx / b_idx) * fx_change - 1)
                    i_val = base_nav * (1 + idx_ratio)
                    df.at[i, 'index_valuation'] = round(i_val, 4)
                    nav = row['nav']
                    if pd.notna(nav) and nav > 0:
                        df.at[i, '指数静态估值误差'] = f"{(i_val - nav) / nav:.2%}"

        # 清洗最终格式，保存回 SQLite 独立对账表，完美兼容旧版前端提取规范
        df['date'] = df['date'].dt.strftime('%Y-%m-%d')
        
        base_cols = ['date', 'exchange_rate', '仓位', 'close', 'nav']
        etf_price_cols = [col for sym in etf_symbols for col in (sym, f"{sym}权重")]
        etf_val_cols = ['变化比例', 'static_valuation', 'ETF静态估值误差', 'ETF静态溢价']
        
        fut_basic_cols, fut_val_cols = [], []
        if future_sym:
            fut_basic_cols = [f"{future_sym}_settle", f"{future_sym}_calib", '期货结算价', '黄金期货校准', '原油期货校准']
            fut_val_cols = ['期货静态估值', '期货静态估值误差', '期货静态估值溢价']
            
        idx_basic_cols = [idx_sym] if idx_sym else []
        idx_val_cols = ['index_valuation', '指数静态估值误差'] if idx_sym else []
        
        ordered_cols = base_cols + etf_price_cols + etf_val_cols + fut_basic_cols + fut_val_cols + idx_basic_cols + idx_val_cols
        final_cols = [c for c in ordered_cols if c in df.columns]
        
        for c in df.columns:
            if c not in final_cols:
                final_cols.append(c)
                
        df = df[final_cols]

        table_name = f"fund_history_{fund_code}"
        
        conn = self.db._get_conn()
        df.to_sql(table_name, conn, if_exists='replace', index=False)
        conn.close()
        
        # 提取最新一天的有效估值用于日志打印
        valid_df = df[df['static_valuation'].notna()]
        if not valid_df.empty:
            latest = valid_df.iloc[0]
            val = latest['static_valuation']
            dt = latest['date']
            err = latest.get('ETF静态估值误差', '未知')
            logger.info(f"✅ {name} ({fund_code}) 计算完成! [最新 {dt}] 官方估值: {val}, 误差: {err}")
        else:
            logger.warning(f"⚠️ {name} ({fund_code}) 计算完成! 但未算出任何有效估值 (可能缺失底层ETF或汇率数据)。")
