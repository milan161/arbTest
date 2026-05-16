import sqlite3
import os
import re

db_path = 'D:/Study/arbTest/database/arb_master.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

def migrate():
    print("🚀 开始执行数据库大迁徙...")
    
    # 1. 为 fund_data 补充字段 (增加静态溢价率字段)
    try:
        c.execute("ALTER TABLE fund_data ADD COLUMN static_premium REAL")
        print("✅ fund_data 补充字段: static_premium")
    except sqlite3.OperationalError:
        print("ℹ️ fund_data 已存在 static_premium 字段")

    # 2. 获取所有历史碎片表
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'fund_history_%'")
    hist_tables = [r[0] for r in c.fetchall()]
    print(f"📦 发现 {len(hist_tables)} 个历史碎片表")

    for table in hist_tables:
        fund_code = table.replace('fund_history_', '')
        print(f"🚚 正在搬迁 [{fund_code}] 的数据...")
        
        # 获取该表的列名，处理中文乱码风险
        c.execute(f"PRAGMA table_info({table})")
        cols = {col[1]: col[1] for col in c.fetchall()}
        
        # 映射字段 (根据之前检查的结果)
        # static_valuation -> static_val
        # ETF静态估值误差 -> val_error
        # ETF静态溢价 -> static_premium
        
        # 寻找对应的列名 (由于乱码，我们通过索引或者部分匹配)
        val_col = 'static_valuation'
        error_col = next((c for c in cols if '误差' in c or '璇敓' in c), None)
        premium_col = next((c for c in cols if '溢价' in c or '婧环' in c), None)

        select_cols = ['date', val_col]
        if error_col: select_cols.append(error_col)
        if premium_col: select_cols.append(premium_col)

        c.execute(f"SELECT {', '.join(select_cols)} FROM {table}")
        rows = c.fetchall()
        
        update_count = 0
        insert_count = 0
        
        for row in rows:
            date = row[0]
            val = row[1]
            err = row[2] if error_col else None
            prem = row[3] if premium_col else None
            
            # 尝试更新 fund_data
            c.execute("""
                UPDATE fund_data 
                SET static_val = ?, val_error = ?, static_premium = ? 
                WHERE date = ? AND fund_code = ?
            """, (val, err, prem, date, fund_code))
            
            if c.rowcount == 0:
                # 如果主表没这行，说明是纯历史数据，插入新行
                c.execute("""
                    INSERT INTO fund_data (date, fund_code, static_val, val_error, static_premium) 
                    VALUES (?, ?, ?, ?, ?)
                """, (date, fund_code, val, err, prem))
                insert_count += 1
            else:
                update_count += 1
        
        print(f"   - 完成: 更新 {update_count} 条，补充 {insert_count} 条")

    # 3. 提交更改
    conn.commit()
    print("🎉 数据大迁徙完成！")

    # 4. 销毁旧表 (可选，建议先执行迁移再手动销毁，或者这里直接干掉)
    for table in hist_tables:
        c.execute(f"DROP TABLE {table}")
    print(f"🧹 已清理 {len(hist_tables)} 个碎片表。")
    conn.commit()

if __name__ == "__main__":
    try:
        migrate()
    finally:
        conn.close()
