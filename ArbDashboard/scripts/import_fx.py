# -*- coding: utf-8 -*-
import os
import sys
import pandas as pd

# 将项目根目录添加到 Python 路径，以便导入 arbcore 的数据库管理器
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from arbcore.database.db_manager import DatabaseManager

def import_exchange_rate_from_excel(excel_path):
    print(f"正在读取 Excel 文件: {excel_path}")
    if not os.path.exists(excel_path):
        print("❌ 文件不存在！请检查路径。")
        return
        
    try:
        # 外汇交易中心下载的 xls 有时是标准 Excel，有时是伪装的 HTML 表格
        # 这里做双重兼容处理
        try:
            df = pd.read_excel(excel_path)
        except Exception as e:
            print("⚠️ read_excel 解析失败，可能文件实际上是 HTML 格式，尝试 pd.read_html...")
            tables = pd.read_html(excel_path, encoding='utf-8')
            df = tables[0]

        print(f"✅ 成功读取文件，共 {len(df)} 行数据。表头包含: {df.columns.tolist()}")
        
        # 智能寻找日期列
        date_col = next((col for col in ['日期', 'Date', '时间', '交易日'] if col in df.columns), None)
        
        # 智能寻找汇率列（美元对人民币中间价）
        rate_col = next((col for col in ['美元', 'USD', '人民币中间价', '中间价', 'USD/CNY', '汇率'] if col in df.columns), None)
                
        if not date_col or not rate_col:
            # 极端情况：如果没找到标准列名，默认第一列为日期，第二列为汇率
            date_col = df.columns[0]
            rate_col = df.columns[1]
            print(f"⚠️ 未找到标准的'日期'和'美元'列名，尝试使用第一列[{date_col}]作日期，第二列[{rate_col}]作汇率。")
        else:
            print(f"🔍 识别到日期列: [{date_col}], 汇率列: [{rate_col}]")

        db = DatabaseManager()
        success_count = 0
        
        for index, row in df.iterrows():
            date_val = str(row[date_col]).strip()
            rate_val = row[rate_col]
            
            if pd.isna(date_val) or date_val in ['nan', 'NaT', '']:
                continue
                
            try:
                parsed_date = pd.to_datetime(date_val).strftime('%Y-%m-%d')
                parsed_rate = float(rate_val)
                if parsed_rate > 0:
                    db.upsert_exchange_rate(parsed_date, parsed_rate)
                    success_count += 1
            except Exception:
                pass # 忽略表尾说明等非数据行
                
        print(f"🎉 导入完成！成功将 {success_count} 天的汇率数据写入数据库 exchange_rate 表。")
        
    except Exception as e:
        print(f"❌ 处理失败: {e}")

if __name__ == "__main__":
    excel_file = r"D:\Study\arbTest\test_read_data\人民币汇率中间价 0506.xls"
    import_exchange_rate_from_excel(excel_file)