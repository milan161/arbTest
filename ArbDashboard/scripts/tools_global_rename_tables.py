# -*- coding: utf-8 -*-
# 数据库全局正名工具：完成 etf_daily_prices -> usa_etf_daily_prices, lof_data -> fund_data 以及历史表的彻底统一

import os
import sqlite3

def migrate_db():
    # 智能定位数据库路径
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if os.path.basename(base_dir) in ['LOFarb', 'ETFRotate', 'arbcore']:
        base_dir = os.path.dirname(base_dir)
    db_path = os.path.join(base_dir, "database", "arb_master.db")
    
    if not os.path.exists(db_path):
        print(f"❌ 找不到数据库文件: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    print("🚀 开始全局数据库正名重构...")

    # 1. 改名基础大表
    renames = {"lof_data": "fund_data", "etf_daily_prices": "usa_etf_daily_prices"}
    for old, new in renames.items():
        cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{old}'")
        if cursor.fetchone():
            cursor.execute(f"ALTER TABLE {old} RENAME TO {new}")
            print(f"✅ 成功: {old} -> {new}")

    # 2. 改名所有的 lof_history_xxx 和 etf_history_xxx 为 fund_history_xxx
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE 'lof_history_%' OR name LIKE 'etf_history_%')")
    for (tname,) in cursor.fetchall():
        new_tname = f"fund_history_{tname.split('_')[-1]}"
        cursor.execute(f"ALTER TABLE {tname} RENAME TO {new_tname}")
        print(f"✅ 成功: {tname} -> {new_tname}")

    conn.commit()
    conn.close()
    print("\n🎉 全局数据库重命名操作完成！您可以继续实施代码替换了。")

if __name__ == "__main__":
    migrate_db()