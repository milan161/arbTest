import os
import sys
import pandas as pd
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from arbcore.database.db_manager import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def import_basic_csv_to_db():
    # 自动定位旧的 csv 文件
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    csv_path = os.path.join(base_dir, 'database', 'GLD_USO_basic_data.csv')
    
    # 如果在 database 目录没找到，退回到老的 data 目录找
    if not os.path.exists(csv_path):
        csv_path = os.path.join(base_dir, 'LOFarb', 'data', 'GLD_USO_basic_data.csv')

    if not os.path.exists(csv_path):
        logger.error(f"未找到 basic.csv 文件，路径: {csv_path}")
        return

    logger.info(f"开始读取旧版 CSV: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str) # 全按字符串读，避免精度丢失或 NaN 错误
    
    db = DatabaseManager()
    
    # 定义需要被扁平化提取的 ETF 价格列
    etf_columns = [
        'GLD', '^GLD-EU', '^GLD-JP', 
        'USO', '^USO-EU', '^USO-JP', '^USO-HK', 
        'XOP', 'SLV', 'XBI', 'SPY', 'QQQ', 
        '.INX', '.NDX'
    ]
    
    # 定义期货历史结算价映射关系
    futures_columns = {
        'GC_settle': 'GC',
        'CL_settle': 'CL',
        'NQ_settle': 'NQ',
        'ES_settle': 'ES'
    }

    # 定义旧表格里独立成列的基金校准/对冲因子
    fund_codes = ['162411', '161127', '161125', '161130']

    success_count = 0
    for index, row in df.iterrows():
        date = str(row['日期']).strip()
        if not date or date == 'nan' or date == 'NaT':
            continue
            
        try:
            # 统一日期格式为 YYYY-MM-DD
            parsed_date = pd.to_datetime(date).strftime('%Y-%m-%d')
            
            # 1. 导入宏观绝对锚点：人民币中间价
            if '人民币中间价' in row and pd.notna(row['人民币中间价']) and str(row['人民币中间价']).strip() != 'nan':
                db.upsert_exchange_rate(parsed_date, float(row['人民币中间价']))
                
            # 导入大宗商品通用校准值（独立表 future_calibration 存储）
            gold_cal = float(row['黄金校准']) if '黄金校准' in row and pd.notna(row['黄金校准']) and str(row['黄金校准']).strip() != 'nan' else None
            oil_cal = float(row['原油校准']) if '原油校准' in row and pd.notna(row['原油校准']) and str(row['原油校准']).strip() != 'nan' else None
            
            if gold_cal is not None:
                db.upsert_futures_daily(parsed_date, 'GC', calibration=gold_cal)
            if oil_cal is not None:
                db.upsert_futures_daily(parsed_date, 'CL', calibration=oil_cal)

            # 导入历史期货结算价
            for col, symbol in futures_columns.items():
                if col in row and pd.notna(row[col]) and str(row[col]).strip() != 'nan':
                    db.upsert_futures_daily(parsed_date, symbol, settle_price=float(row[col]))

            # 2. 导入打平的 ETF 价格矩阵
            for etf in etf_columns:
                if etf in row and pd.notna(row[etf]) and str(row[etf]).strip() != 'nan':
                    db.upsert_etf_price(parsed_date, etf, float(row[etf]))

            # 3. 导入独立基金的校准和对冲值
            for code in fund_codes:
                cal_col = f"{code}校准"
                hedge_col = f"{code}对冲"
                
                if cal_col in row and pd.notna(row[cal_col]) and str(row[cal_col]).strip() != 'nan':
                    calibration = float(row[cal_col])
                    # 部分基金可能没有写入过对冲值
                    hedge = float(row[hedge_col]) if hedge_col in row and pd.notna(row[hedge_col]) and str(row[hedge_col]).strip() != 'nan' else None
                    
                    # 旧表里没有 position(仓位)和 nav，这里填 None，后续从 config 或 API 更新
                    db.upsert_fund_factor(parsed_date, code, calibration=calibration, hedge=hedge, position=None)
                    
            success_count += 1
        except Exception as e:
            logger.warning(f"处理日期 {date} 的数据时出错: {e}")
            
    logger.info(f"✅ 成功将 {success_count} 天的旧版 basic 历史数据清洗并导入 SQLite 数据库！")

if __name__ == "__main__":
    import_basic_csv_to_db()
