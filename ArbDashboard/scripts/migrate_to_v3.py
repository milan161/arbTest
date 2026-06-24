# -*- coding: utf-8 -*-
"""
数据库大一统 (V3) 数据迁移脚本 - 完整全量版
------------------------------------------
此脚本实现真正的“大一统”：
1. 合并 LOFarb 和 jsl 系统中的所有基金名录到 unified_fund_list。
2. 将所有历史数据对齐并存入 unified_fund_history。
"""

import sqlite3
import os
import pandas as pd

# 数据库路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASTER_DB_PATH = os.path.join(BASE_DIR, 'database', 'arb_master.db')
JSL_DB_PATH = os.path.join(BASE_DIR, 'jsl', 'jsl_monitor.db')

def migrate_to_v3():
    print("="*50)
    print("🚀 开始执行 V3 数据库大一统迁移 (全量增强版)...")
    print("="*50)

    if not os.path.exists(MASTER_DB_PATH):
        print(f"❌ 错误：找不到主数据库 {MASTER_DB_PATH}")
        return

    # 1. 连接主数据库
    conn = sqlite3.connect(MASTER_DB_PATH)
    cursor = conn.cursor()

    # 2. 创建 V3 宽表 (如果不存在)
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS unified_fund_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        fund_code TEXT NOT NULL,
        price REAL,
        price_change REAL,
        nav REAL,
        nav_date TEXT,
        volume REAL,
        shares REAL,
        shares_added REAL,
        turnover_rate TEXT,
        static_val REAL,
        rt_val REAL,
        premium REAL,
        rt_premium REAL,
        index_close REAL,
        index_pct REAL,
        calibration REAL,
        purchase_status TEXT,
        redemption_status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(date, fund_code)
    );
    """
    cursor.execute(create_table_sql)
    print("✅ V3 新表 'unified_fund_history' 检查/创建完成。")

    # 3. 挂载 JSL 数据库
    if os.path.exists(JSL_DB_PATH):
        try:
            cursor.execute(f"ATTACH DATABASE '{JSL_DB_PATH}' AS jsl_db")
            print(f"🔗 成功挂载集思录数据库: {JSL_DB_PATH}")
        except Exception as e:
            print(f"⚠️ 挂载 JSL 数据库失败: {e}")
            return
    else:
        print("⚠️ 找不到 JSL 数据库，跳过数据融合。")
        return

    # 4. 【关键】合并基金名录
    print("📋 正在同步全量基金名录 (QDII, 亚洲, 国内LOF)...")
    # 将 JSL 数据库中的标的合并进来
    merge_funds_sql = """
    INSERT INTO unified_fund_list (fund_code, fund_name, category, related_index)
    SELECT fund_code, fund_name, category, idx_code
    FROM jsl_db.fund_info
    WHERE fund_code NOT IN (SELECT fund_code FROM unified_fund_list)
    """
    try:
        cursor.execute(merge_funds_sql)
        conn.commit()
    except Exception as e:
        print(f"⚠️ 合并基金名录失败: {e}")

    # 获取全量基金
    funds_df = pd.read_sql_query("SELECT fund_code, fund_name, category FROM unified_fund_list", conn)
    fund_codes = tuple(funds_df['fund_code'].tolist())
    print(f"✅ 发现共 {len(fund_codes)} 只监控基金。")

    # 5. 执行历史数据提取
    print("⏳ 正在跨库抽取历史数据...")
    placeholders = ','.join(['?'] * len(fund_codes))

    lof_df = pd.read_sql_query(f"SELECT date, fund_code, price, nav, premium, static_val FROM fund_data WHERE fund_code IN ({placeholders})", conn, params=fund_codes)
    jsl_df = pd.read_sql_query(f"SELECT date, fund_code, volume, shares, turnover_rate, static_valuation as jsl_static_val, estimated_premium, index_close, index_pct FROM jsl_db.fund_history WHERE fund_code IN ({placeholders})", conn, params=fund_codes)
    factor_df = pd.read_sql_query(f"SELECT date, fund_code, calibration FROM fund_daily_factors WHERE fund_code IN ({placeholders})", conn, params=fund_codes)
    status_df = pd.read_sql_query(f"SELECT fund_code, purchase_status, redemption_status FROM fund_purchase_status WHERE fund_code IN ({placeholders})", conn, params=fund_codes)

    print("📊 正在执行内存多级缝合...")
    all_dates_codes = pd.concat([lof_df[['date', 'fund_code']], jsl_df[['date', 'fund_code']]]).drop_duplicates()
    merged_df = pd.merge(all_dates_codes, lof_df, on=['date', 'fund_code'], how='left')
    merged_df = pd.merge(merged_df, jsl_df, on=['date', 'fund_code'], how='left')
    merged_df = pd.merge(merged_df, factor_df, on=['date', 'fund_code'], how='left')
    merged_df = pd.merge(merged_df, status_df, on=['fund_code'], how='left')

    merged_df = merged_df.sort_values(by=['fund_code', 'date'])
    merged_df['static_val'] = merged_df['static_val'].fillna(merged_df['jsl_static_val'])
    
    # 算涨跌幅
    merged_df['prev_price'] = merged_df.groupby('fund_code')['price'].shift(1)
    merged_df['price_change'] = (merged_df['price'] / merged_df['prev_price'] - 1) * 100
    
    # 算新增份额
    merged_df['shares'] = pd.to_numeric(merged_df['shares'], errors='coerce')
    merged_df['prev_shares'] = merged_df.groupby('fund_code')['shares'].shift(1)
    merged_df['shares_added'] = merged_df['shares'] - merged_df['prev_shares']
    
    merged_df['volume'] = pd.to_numeric(merged_df['volume'], errors='coerce') / 10000.0
    merged_df = merged_df.where(pd.notna(merged_df), None)

    print("💾 正在执行 V3 宽表写入...")
    insert_data = []
    for _, row in merged_df.iterrows():
        if (row['price'] is None or row['price'] <= 0) and (row['nav'] is None or row['nav'] <= 0):
            continue
        insert_data.append((
            row['date'], row['fund_code'], 
            row['price'], row['price_change'], row['nav'], row['date'],
            row['volume'], row['shares'], row['shares_added'], row['turnover_rate'],
            row['static_val'], None, row['premium'], None,
            row['index_close'], row['index_pct'],
            row['calibration'], row['purchase_status'], row['redemption_status']
        ))

    insert_sql = """
        INSERT INTO unified_fund_history (
            date, fund_code, price, price_change, nav, nav_date,
            volume, shares, shares_added, turnover_rate,
            static_val, rt_val, premium, rt_premium,
            index_close, index_pct, calibration, purchase_status, redemption_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, fund_code) DO UPDATE SET
            price=excluded.price, price_change=excluded.price_change, nav=excluded.nav,
            volume=excluded.volume, shares=excluded.shares, shares_added=excluded.shares_added,
            turnover_rate=excluded.turnover_rate, static_val=excluded.static_val,
            premium=excluded.premium, index_close=excluded.index_close,
            index_pct=excluded.index_pct, calibration=excluded.calibration;
    """
    
    try:
        cursor.executemany(insert_sql, insert_data)
        conn.commit()
        print(f"🎉 成功！已完成 {len(fund_codes)} 只基金的历史全量迁移。")
    except Exception as e:
        print(f"❌ 写入失败: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_to_v3()
