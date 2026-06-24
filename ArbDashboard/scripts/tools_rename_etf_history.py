# -*- coding: utf-8 -*-
# 独立工具脚本：将混入 lof_history 体系的 A股 ETF 历史对账表重命名为 etf_history

import os
import sqlite3

def rename_tables():
    # 定位数据库路径
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base_dir, "database", "arb_master.db")
    
    if not os.path.exists(db_path):
        print(f"❌ 找不到数据库文件: {db_path}")
        return

    etf_codes = ['159502', '159518', '513350']
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("开始重命名 ETF 历史对账表...\n")
    for code in etf_codes:
        old_name = f"lof_history_{code}"
        new_name = f"etf_history_{code}"
        
        # 检查旧表是否存在
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{old_name}'")
        if cursor.fetchone():
            try:
                cursor.execute(f"ALTER TABLE {old_name} RENAME TO {new_name}")
                print(f"✅ 成功: {old_name} -> {new_name}")
            except Exception as e:
                print(f"❌ 失败: 重命名 {old_name} 时发生错误: {e}")
        else:
            print(f"⚠️ 跳过: 数据库中不存在表 {old_name}")
            
    conn.close()
    print("\n操作完成！")

if __name__ == "__main__":
    rename_tables()