# LOF032_data_processor.py - 数据处理模块
import os
import re
from datetime import datetime
import pandas as pd

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
        """读取LOF基金数据"""
        # 尝试读取扩展后的LOF历史数据文件（包含静态官方估值）
        filename = f"LOF_{fund_code}_history.csv"
        file_path = os.path.join(self.data_dir, filename)
        
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path, encoding='utf-8-sig')
                
                # 确保日期列存在
                if 'date' not in df.columns:
                    # 尝试其他可能的日期列名
                    for col in ['Date', '日期']:
                        if col in df.columns:
                            df.rename(columns={col: 'date'}, inplace=True)
                            break
                
                if 'date' in df.columns:
                    df = self._normalize_date_column(df, 'date')
                    
                    # 确保必要的列存在
                    if 'nav' not in df.columns:
                        for col in ['NAV', '净值', 'LOF净值']:
                            if col in df.columns:
                                df.rename(columns={col: 'nav'}, inplace=True)
                                break
                    
                    if 'close' not in df.columns:
                        for col in ['Close', '收盘价', 'LOF交易价格', 'LOF交易价']:
                            if col in df.columns:
                                df.rename(columns={col: 'close'}, inplace=True)
                                break
                    
                    if 'static_valuation' not in df.columns:
                        # 兼容新旧版字段命名
                        for col in ['ETF静态估值', '静态官方估值']:
                            if col in df.columns:
                                df.rename(columns={col: 'static_valuation'}, inplace=True)
                                break
                    
                    # 提取纯指数估值数据
                    if 'index_valuation' not in df.columns:
                        for col in ['指数静态估值']:
                            if col in df.columns:
                                df.rename(columns={col: 'index_valuation'}, inplace=True)
                                break
                                
                    # 处理纯指数估值列中的无效值
                    if 'index_valuation' in df.columns:
                        df['index_valuation'] = df['index_valuation'].replace(['n', '无', 'N/A', 'NA'], pd.NA)
                    
                    # 处理静态官方估值列中的无效值
                    if 'static_valuation' in df.columns:
                        # 将'n'和'无'等无效值转换为NaN
                        df['static_valuation'] = df['static_valuation'].replace(['n', '无', 'N/A', 'NA'], pd.NA)
                        # 尝试将列转换为数值类型
                        try:
                            df['static_valuation'] = pd.to_numeric(df['static_valuation'], errors='coerce')
                        except Exception as e:
                            pass
                    
                    if 'exchange_rate' not in df.columns:
                        for col in ['人民币中间价']:
                            if col in df.columns:
                                df.rename(columns={col: 'exchange_rate'}, inplace=True)
                                break
                    
                    # 过滤掉日期为空的行
                    df = df[df['date'].notna()]
                    
                    if len(df) > 0:
                        return df.sort_values('date', ascending=False).reset_index(drop=True)
            except Exception as e:
                print(f"读取文件 {filename} 失败: {e}")
        else:
            print(f"警告: 找不到LOF历史数据文件: {file_path}")
        return pd.DataFrame()
    
    def read_basic_data(self):
        """读取基础数据（包含汇率和ETF数据）"""
        filename = "GLD_USO_basic_data.csv"
        file_path = os.path.join(self.data_dir, filename)
        
        if os.path.exists(file_path):
            try:
                df = pd.read_csv(file_path)
                # 确保日期列存在
                if 'date' not in df.columns:
                    # 尝试其他可能的日期列名
                    for col in ['Date', '日期']:
                        if col in df.columns:
                            df.rename(columns={col: 'date'}, inplace=True)
                            break
                if 'date' in df.columns:
                    df = self._normalize_date_column(df, 'date')
                    return df.sort_values('date', ascending=False).reset_index(drop=True)
                else:
                    print(f"文件 {filename} 没有日期列")
            except Exception as e:
                print(f"读取文件 {filename} 失败: {e}")
        else:
            print(f"基础数据文件不存在: {file_path}")
        return pd.DataFrame()
    
    def get_v(self, df, date, col):
        """获取指定日期的值"""
        if df is None or date not in df.index:
            return 0.0
        val = df.loc[date].get(col, 0.0)
        return float(val) if pd.notnull(val) and val != "" else 0.0
    
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
    
    def calculate_future_estimated_value(self, fund, historical_data, gc_price, cl_price, gold_calibration, oil_calibration):
        """计算基于期货的实时估值
        
        Args:
            fund: 基金配置
            historical_data: 历史数据
            gc_price: 黄金期货价格
            cl_price: 石油期货价格
            gold_calibration: 黄金期货校准值
            oil_calibration: 原油期货校准值
            
        Returns:
            float: 实时期货估值
        """
        # 1. 检查是否有足够的历史数据
        if historical_data is None or len(historical_data) == 0:
            print(f"基金 {fund.get('code')} 无历史数据")
            return None
        
        # 2. 提取对冲组合和仓位
        hedging_portfolio = fund.get('hedging_portfolio', [])
        position = fund.get('holdings', {}).get('equity_ratio', 0)
        
        # 确保权重为小数
        hedging_portfolio = [(item['symbol'], item['weight'] / 100) for item in hedging_portfolio]
        
        # 3. 找到基准日期的净值和汇率
        base_date, base_nav, base_row = self.get_base_date_info(historical_data)
        
        if not base_date or not base_nav:
            print(f"基金 {fund.get('code')} 无法找到基准日期")
            return None
        
        # 4. 计算加权平均期货变化率（转换为校准ETF）
        weighted_future_change_rate = 0
        valid_weights = 0
        
        print(f"\n基金 {fund.get('code')} - 期货实时估值计算:")
        print(f"1. 基准日期: {base_date}")
        print(f"2. 基准净值: {base_nav}")
        print(f"3. 仓位: {position}%")
        print(f"4. 黄金期货价格: {gc_price}")
        print(f"5. 原油期货价格: {cl_price}")
        print(f"6. 黄金校准值: {gold_calibration}")
        print(f"7. 原油校准值: {oil_calibration}")
        print(f"8. 对冲组合:")
        
        # 遍历对冲组合，计算加权平均期货变化率
        for symbol, weight in hedging_portfolio:
            if weight <= 0:
                continue
            
            # 获取基准日期的ETF价格
            base_price = base_row.get(symbol, None)
            if base_price is None or pd.isna(base_price):
                print(f"  - {symbol}: 无基准价格")
                continue
            
            # 获取当前校准ETF价格（使用期货价格和校准值）
            current_price = 0
            if symbol == 'GLD' and gc_price > 0 and gold_calibration > 0:
                # 黄金期货转换为校准GLD
                current_price = gc_price / gold_calibration
                print(f"  - {symbol}: 基准价格={base_price}, 校准价格={current_price:.4f}, 权重={weight:.4f}")
            elif symbol == 'USO' and cl_price > 0 and oil_calibration > 0:
                # 石油期货转换为校准USO
                current_price = cl_price / oil_calibration
                print(f"  - {symbol}: 基准价格={base_price}, 校准价格={current_price:.4f}, 权重={weight:.4f}")
            else:
                print(f"  - {symbol}: 无法计算校准价格")
                continue
            
            if current_price <= 0:
                continue
            
            # 计算期货变化率（转换为校准ETF后的变化率）
            future_change_rate = (current_price - base_price) / base_price
            
            # 计算加权变化率
            weighted_future_change_rate += future_change_rate * weight
            valid_weights += weight
        
        if valid_weights <= 0:
            print(f"基金 {fund.get('code')} 无有效权重")
            return None
        
        print(f"9. 加权平均期货变化率: {weighted_future_change_rate:.4f}")
        print(f"10. 有效权重: {valid_weights:.4f}")
        
        # 5. 计算基金估值
        # 应用仓位
        estimated_value = base_nav * (1 + weighted_future_change_rate * position / 100)
        
        print(f"11. 计算结果: {estimated_value:.4f}")
        
        return estimated_value
