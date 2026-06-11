#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
更新数据库中的基金分类，统一为5个分类：
- 黄金原油
- QDII欧美
- QDII亚洲
- 国内LOF
- 白银
"""

import sqlite3
import os

# 数据库路径
DB_PATH = r"D:\Study\arbTest\database\arb_master.db"

def update_categories():
    """更新数据库分类"""
    print(f"[INFO] 连接数据库: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] 数据库文件不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. 查看当前有哪些分类
        cursor.execute("SELECT category, COUNT(*) as count FROM unified_fund_list GROUP BY category")
        current_categories = cursor.fetchall()
        print("\n[INFO] 当前数据库分类统计:")
        for cat, count in current_categories:
            print(f"   - {cat}: {count} 只基金")
        
        # 2. 执行更新
        updates = [
            ("QDII 欧美", "QDII欧美", "更新有空格到无空格"),
            ("QDII 亚洲", "QDII亚洲", "更新有空格到无空格"),
            ("指数LOF", "国内LOF", "重命名为国内LOF"),
            ("混合跨境", "QDII欧美", "合并到QDII欧美"),
            ("我的自选", "QDII欧美", "合并到QDII欧美"),
        ]
        
        total_updated = 0
        for old_cat, new_cat, reason in updates:
            cursor.execute(
                "UPDATE unified_fund_list SET category = ? WHERE category = ?",
                (new_cat, old_cat)
            )
            rows_updated = cursor.rowcount
            if rows_updated > 0:
                print(f"\n[OK] 已更新: '{old_cat}' -> '{new_cat}' ({reason})")
                print(f"     影响 {rows_updated} 只基金")
                total_updated += rows_updated
        
        conn.commit()
        
        # 3. 验证更新结果
        cursor.execute("SELECT category, COUNT(*) as count FROM unified_fund_list GROUP BY category")
        new_categories = cursor.fetchall()
        
        print("\n" + "="*60)
        print("[OK] 更新后的分类统计:")
        for cat, count in new_categories:
            print(f"   - {cat}: {count} 只基金")
        print(f"\n总计: {sum(count for _, count in new_categories)} 只基金")
        print(f"共更新 {total_updated} 只基金的分类")
        print("="*60)
        
    except Exception as e:
        print(f"\n[ERROR] 更新失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    print("="*60)
    print("基金分类统一更新工具")
    print("="*60)
    update_categories()
