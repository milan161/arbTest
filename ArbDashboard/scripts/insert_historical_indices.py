# -*- coding: utf-8 -*-
# insert_historical_indices.py - 手动导入历史指数数据

import sqlite3
import os

def insert_historical_indices():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, "database", "arb_master.db")
    
    if not os.path.exists(db_path):
        print(f"❌ 找不到数据库文件: {db_path}")
        return

    # 格式化用户提供的历史数据 (.NDX = 纳斯达克100, .INX = 标普500)
    data = [
        ("2026-04-29", ".NDX", 27186.99), ("2026-04-29", ".INX", 7135.95),
        ("2026-04-28", ".NDX", 27029.01), ("2026-04-28", ".INX", 7138.80),
        ("2026-04-27", ".NDX", 27305.68), ("2026-04-27", ".INX", 7173.91),
        ("2026-04-24", ".NDX", 27303.67), ("2026-04-24", ".INX", 7165.08),
        ("2026-04-23", ".NDX", 26782.63), ("2026-04-23", ".INX", 7108.40),
        ("2026-04-22", ".NDX", 26937.28), ("2026-04-22", ".INX", 7137.90),
        ("2026-04-21", ".NDX", 26479.47), ("2026-04-21", ".INX", 7064.01),
        ("2026-04-20", ".NDX", 26590.34), ("2026-04-20", ".INX", 7109.14),
        ("2026-04-19", ".NDX", 26672.43), ("2026-04-19", ".INX", 7126.06),
        ("2026-04-17", ".NDX", 26333.00), ("2026-04-17", ".INX", 7041.28),
    ]

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        count = 0
        for date, symbol, price in data:
            # 先执行删除，确保不会因为多次运行产生重复的冗余数据
            cursor.execute("DELETE FROM index_daily WHERE date = ? AND symbol = ?", (date, symbol))
            cursor.execute("INSERT INTO index_daily (date, symbol, price) VALUES (?, ?, ?)", (date, symbol, price))
            count += 1
            
        conn.commit()
        print(f"✅ 成功将 {count} 条历史指数数据写入 index_daily 表！")
    except Exception as e:
        print(f"❌ 写入数据时发生错误: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    insert_historical_indices()
