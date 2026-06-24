# clean_duplicate_history.py - SQLite 重复历史数据清理工具
import sqlite3
import os

def clean_duplicates():
    # 获取数据库路径 (上一级目录下的 database/arb_master.db)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, "database", "arb_master.db")
    
    if not os.path.exists(db_path):
        print(f"❌ 找不到数据库文件: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # 0. 清理 usa_etf_daily_prices 中误存的期货和指数脏数据（如高露洁股票 CL，或者 .INX）
        garbage_symbols = ['GC', 'CL', 'NQ', 'ES', 'AG0', 'MGC', 'MCL', 'MES', 'MNQ', 
                           'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle',
                           'INX', 'NDX', 'DJI', '.INX', '.NDX', '.DJI']
        placeholders = ','.join(['?'] * len(garbage_symbols))
        cursor.execute(f"DELETE FROM usa_etf_daily_prices WHERE symbol IN ({placeholders})", garbage_symbols)
        garbage_deleted = cursor.rowcount
        if garbage_deleted > 0:
            print(f"🗑️ 已从 usa_etf_daily_prices 中清洗掉 {garbage_deleted} 条误存的期货/指数脏数据。")

        # 1. 查找所有需要按日期去重的数据表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        all_tables = cursor.fetchall()
        
        # 定义哪些表适用按 'date' 字段去重
        target_tables = []
        for (table_name,) in all_tables:
            if table_name.startswith('fund_history_') or table_name in [
                'fund_data', 'exchange_rate', 'usa_etf_daily_prices', 
                'futures_daily', 'fund_daily_factors', 'index_daily'
            ]:
                target_tables.append(table_name)
        
        total_deleted = 0
        for table_name in target_tables:
            # 2. 针对多维表(带有 fund_code 或 symbol 的表)，需按日期+标识符联合去重
            group_by_clause = "date"
            if table_name in ['fund_data', 'fund_daily_factors']:
                group_by_clause = "date, fund_code"
            elif table_name in ['usa_etf_daily_prices', 'futures_daily', 'index_daily']:
                group_by_clause = "date, symbol"
                
            cursor.execute(f"DELETE FROM {table_name} WHERE rowid NOT IN (SELECT MAX(rowid) FROM {table_name} GROUP BY {group_by_clause})")
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"✅ 清理表 {table_name}: 删除了 {deleted} 条重复数据")
                total_deleted += deleted
                
        conn.commit()
        
        if total_deleted == 0:
            print("🎉 扫描完毕：数据库很干净，没有发现重复数据。")
        else:
            print(f"🧹 清理完成！全库共删除了 {total_deleted} 条重复的冗余数据。")
            
    except Exception as e:
        print(f"清理过程中发生错误: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    clean_duplicates()
