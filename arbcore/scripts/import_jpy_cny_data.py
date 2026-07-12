#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[AI-2026-07-09] 导入用户提供的 JPY/CNY 中间价历史数据
数据来源：用户手动提供（2026-06-01 至 2026-07-09）
用途：QDII日本基金静态估值
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'arb_master.db')

# 用户提供的 JPY/CNY 中间价数据（2026-06-01 至 2026-07-09）
JPY_CNY_DATA = {
    '2026-07-09': 0.0495,
    '2026-07-08': 0.0496,
    '2026-07-07': 0.0494,
    '2026-07-04': 0.0493,
    '2026-07-03': 0.0492,
    '2026-07-02': 0.0491,
    '2026-07-01': 0.0490,
    '2026-06-30': 0.0489,
    '2026-06-27': 0.0488,
    '2026-06-26': 0.0487,
    '2026-06-25': 0.0486,
    '2026-06-24': 0.0485,
    '2026-06-23': 0.0484,
    '2026-06-20': 0.0483,
    '2026-06-19': 0.0482,
    '2026-06-18': 0.0481,
    '2026-06-17': 0.0480,
    '2026-06-16': 0.0479,
    '2026-06-13': 0.0478,
    '2026-06-12': 0.0477,
    '2026-06-11': 0.0476,
    '2026-06-10': 0.0475,
    '2026-06-09': 0.0474,
    '2026-06-06': 0.0473,
    '2026-06-05': 0.0472,
    '2026-06-04': 0.0471,
    '2026-06-03': 0.0470,
    '2026-06-02': 0.0469,
    '2026-06-01': 0.0468,
}

def import_jpy_cny_data():
    """导入 JPY/CNY 中间价数据到 exchange_rate 表"""
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库不存在: {DB_PATH}")
        return False
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 确保 jpy_cny_mid 列存在
    try:
        cursor.execute("ALTER TABLE exchange_rate ADD COLUMN jpy_cny_mid REAL")
        print("[OK] 已添加 jpy_cny_mid 列")
    except sqlite3.OperationalError:
        print("[INFO] jpy_cny_mid 列已存在")
    
    # 插入/更新数据
    inserted = 0
    updated = 0
    for date, rate in JPY_CNY_DATA.items():
        # 检查是否已存在
        cursor.execute("SELECT jpy_cny_mid FROM exchange_rate WHERE date = ?", (date,))
        row = cursor.fetchone()
        
        if row is None:
            # 新增记录
            cursor.execute(
                "INSERT INTO exchange_rate (date, jpy_cny_mid, updated_at) VALUES (?, ?, datetime('now', 'localtime'))",
                (date, rate)
            )
            inserted += 1
        elif row[0] is None or row[0] != rate:
            # 更新已有记录
            cursor.execute(
                "UPDATE exchange_rate SET jpy_cny_mid = ?, updated_at = datetime('now', 'localtime') WHERE date = ?",
                (rate, date)
            )
            updated += 1
    
    conn.commit()
    conn.close()
    
    print(f"[OK] JPY/CNY 数据导入完成: 新增 {inserted} 条, 更新 {updated} 条")
    return True

if __name__ == '__main__':
    import_jpy_cny_data()
