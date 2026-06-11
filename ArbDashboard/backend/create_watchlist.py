#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
创建"我的自选"基金表
"""

import sqlite3
import os

DB_PATH = r"D:\Study\arbTest\database\arb_master.db"

def create_watchlist_table():
    """创建自选基金表"""
    print(f"[INFO] 连接数据库: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 创建自选基金表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fund_watchlist (
                fund_code TEXT PRIMARY KEY,
                fund_name TEXT,
                category TEXT,
                added_date TEXT DEFAULT (date('now')),
                notes TEXT
            )
        ''')
        
        # 从 unified_fund_list 中插入所有基金作为初始自选（可选）
        # 这里先不插入，让用户手动添加感兴趣的基金
        
        conn.commit()
        
        # 验证表是否创建成功
        cursor.execute("SELECT COUNT(*) FROM fund_watchlist")
        count = cursor.fetchone()[0]
        
        print(f"\n[OK] 自选基金表创建成功!")
        print(f"[INFO] 当前自选基金数量: {count} 只")
        print(f"[INFO] 使用方式: 通过API添加/删除自选基金")
        
    except Exception as e:
        print(f"\n[ERROR] 创建表失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("="*60)
    print("创建自选基金表")
    print("="*60)
    create_watchlist_table()
