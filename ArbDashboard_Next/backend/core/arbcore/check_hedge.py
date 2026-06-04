# -*- coding: utf-8 -*-
import sqlite3
import os

# 检查两个可能的数据库路径
paths = [
    'database/arb_master.db',
    'arbcore/database/arb_master.db'
]

for db_path in paths:
    print(f"\n{'='*50}")
    print(f"检查: {db_path}")
    print(f"存在: {os.path.exists(db_path)}, 大小: {os.path.getsize(db_path) if os.path.exists(db_path) else 0}")
    
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0:
        conn = sqlite3.connect(db_path)
        
        # 查看所有表
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        print(f"表数量: {len(tables)}")
        for t in tables[:10]:
            print(f"  {t[0]}")
        if len(tables) > 10:
            print(f"  ... 还有 {len(tables)-10} 个表")
        
        # 查看fund_daily_factors表
        print("\n=== fund_daily_factors 表 ===")
        try:
            cols = conn.execute("PRAGMA table_info(fund_daily_factors)").fetchall()
            for c in cols:
                print(f"  {c[1]}: {c[2]}")
            
            # 检查纯ETF的hedge
            print("\n=== 纯ETF的hedge因子 ===")
            for code in ['162411', '162415']:
                rows = conn.execute(
                    'SELECT fund_code, date, position, hedge FROM fund_daily_factors WHERE fund_code = ? ORDER BY date DESC LIMIT 3',
                    (code,)
                ).fetchall()
                print(f"\n--- {code} ---")
                for r in rows:
                    print(f"  {r[1]} | position={r[2]}, hedge={r[3]}")
                if not rows:
                    print("  (无数据)")
        except Exception as e:
            print(f"  错误: {e}")
        
        conn.close()
