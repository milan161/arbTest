# LOF032_data_processor.py - 数据处理模块
import os
import re
from datetime import datetime
import pandas as pd
import sqlite3

# 全局共享数据库路径 (动态获取项目根目录下的 database/arb_master.db)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARED_DB_PATH = os.path.join(BASE_DIR, "database", "arb_master.db")

class DataProcessor:
    """数据处理类"""
    
    def __init__(self, data_dir):
        """初始化数据处理器"""
        self.data_dir = data_dir

    def _infer_year(self, series):
        """从日期列推断年份（优先使用已有完整年份，否则使用当前年份）"""
        try:
            for v in series.dropna().astype(str):
                m = re.match(r'^(\d{4})[-/]', v.strip())
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return datetime.now().year

    def _normalize_date_column(self, df, col_name='date'):
        """统一日期列格式，兼容YYYY-MM-DD与MM-DD"""
        if col_name not in df.columns:
            return df
        series = df[col_name].astype(str).str.strip()
        inferred_year = self._infer_year(series)
        # 对MM-DD补全年份
        def _fix_date(x):
            if len(x) == 5 and x[2] == '-':
                return f"{inferred_year}-{x}"
            return x
        series = series.apply(_fix_date)
        df[col_name] = pd.to_datetime(series, errors='coerce')
        return df
    
    def read_lof_data(self, fund_code):
        """
        读取基金历史数据 (大一统版本)
        从核心宽表 fund_data 中提取该基金的所有历史记录
        """
        df = pd.DataFrame()
        try:
            conn = sqlite3.connect(SHARED_DB_PATH)
            # 核心 SQL：从 fund_data 提取数据，并进行字段名映射以保持 UI 兼容
            sql = f"""
                SELECT 
                    date, 
                    nav, 
                    price as close, 
                    static_val as static_valuation, 
                    static_premium as premium,
                    val_error
                FROM fund_data 
                WHERE fund_code = '{fund_code}'
                ORDER BY date DESC
            """
            df = pd.read_sql(sql, conn)
            conn.close()
            
            if not df.empty:
                df = self._normalize_date_column(df, 'date')
                # 过滤掉日期为空的行
                df = df[df['date'].notna()]
                return df.reset_index(drop=True)
            
        except Exception as e:
            print(f"❌ [DataProcessor] 读取基金 {fund_code} 历史数据失败: {e}")
            
        return pd.DataFrame()
    
    def read_basic_data(self):
        """读取基础数据（从 SQLite 并行读取后合并输出，兼容旧版 CSV 结构）"""
        df = pd.DataFrame()
        try:
            conn = sqlite3.connect(SHARED_DB_PATH)
            # 1. 读取汇率
            fx_df = pd.read_sql("SELECT date, usd_cny_mid as 人民币中间价 FROM exchange_rate", conn)
            if not fx_df.empty:
                df = fx_df
            
            # 2. 读取校准常量
            calib_df = pd.read_sql("SELECT date, symbol, calibration FROM futures_daily WHERE calibration IS NOT NULL", conn)
            if not calib_df.empty:
                calib_pivot = calib_df.pivot(index='date', columns='symbol', values='calibration').reset_index()
                calib_pivot.rename(columns={'GC': '黄金校准', 'CL': '原油校准'}, inplace=True)
                if df.empty:
                    df = calib_pivot
                else:
                    df = pd.merge(df, calib_pivot, on='date', how='outer')

            # 3. 读取期货结算价
            fut_df = pd.read_sql("SELECT date, symbol, settle_price FROM futures_daily WHERE settle_price IS NOT NULL", conn)
            if not fut_df.empty:
                fut_pivot = fut_df.pivot(index='date', columns='symbol', values='settle_price').reset_index()
                rename_map = {c: f"{c}_settle" for c in fut_pivot.columns if c != 'date'}
                fut_pivot.rename(columns=rename_map, inplace=True)
                if df.empty:
                    df = fut_pivot
                else:
                    df = pd.merge(df, fut_pivot, on='date', how='outer')

            # 4. 读取 ETF 价格
            etf_df = pd.read_sql("SELECT date, symbol, price FROM usa_etf_daily_prices", conn)
            if not etf_df.empty:
                etf_pivot = etf_df.pivot(index='date', columns='symbol', values='price').reset_index()
                if df.empty:
                    df = etf_pivot
                else:
                    df = pd.merge(df, etf_pivot, on='date', how='outer')

            conn.close()
            
            if not df.empty:
                df = self._normalize_date_column(df, 'date')
                return df.sort_values('date', ascending=False).reset_index(drop=True)
        except Exception as e:
            print(f"读取 SQLite 基础数据表失败: {e}")
            
        return pd.DataFrame()
    
    def get_base_date_info(self, historical_data):
        """获取基准日期信息
        
        Args:
            historical_data: 历史数据
            
        Returns:
            tuple: (base_date, base_nav, base_row) 如果没有找到有效的基准日期，返回(None, None, None)
        """
        if historical_data is None or len(historical_data) == 0:
            return None, None, None
        
        # 找到有净值的最新日期（优先使用标准化列名）
        date_col = 'date' if 'date' in historical_data.columns else ('日期' if '日期' in historical_data.columns else None)
        nav_col = 'nav' if 'nav' in historical_data.columns else ('LOF净值' if 'LOF净值' in historical_data.columns else '净值')
        if date_col is None or nav_col not in historical_data.columns:
            return None, None, None
        for _, row in historical_data.iterrows():
            nav_val = row.get(nav_col, None)
            if nav_val and not pd.isna(nav_val):
                base_date = row.get(date_col)
                base_nav = nav_val
                base_row = row
                return base_date, base_nav, base_row
        
        return None, None, None
