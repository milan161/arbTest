#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[AI-2026-07-09] 检查数据库中 N225 历史数据和 QDII日本基金配置状态
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'arb_master.db')

def check_db_state():
    """检查数据库状态"""
    if not os.path.exists(DB_PATH):
        print('[ERROR] 数据库不存在: %s' % DB_PATH)
        return
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. 检查 index_history 中的 N225 数据
    print('=== index_history 中的 N225 数据 ===')
    c.execute("SELECT COUNT(*) FROM index_history WHERE symbol LIKE '%N225%' OR symbol LIKE '%nikkei%' OR symbol LIKE '%NIKKEI%'")
    count = c.fetchone()[0]
    print('N225 相关记录数: %d' % count)
    
    if count == 0:
        print('[WARNING] N225 历史数据不存在！需要导入日经225指数历史数据')
    else:
        c.execute("SELECT symbol, date, close FROM index_history WHERE symbol LIKE '%N225%' ORDER BY date DESC LIMIT 5")
        print('\n最近 N225 数据:')
        for row in c.fetchall():
            print('  %s | %s | close=%s' % (row[0], row[1], row[2]))
    
    # 2. 检查 index_history 中的 symbol 列表
    print('\n=== index_history symbol 列表 ===')
    c.execute("SELECT symbol, COUNT(*) as cnt FROM index_history GROUP BY symbol ORDER BY cnt DESC LIMIT 20")
    print('前 20 个 symbol:')
    for row in c.fetchall():
        print('  %s: %d 行' % (row[0], row[1]))
    
    # 3. 检查 QDII日本基金配置
    print('\n=== QDII日本基金配置 ===')
    c.execute("SELECT fund_code, fund_name, category, related_index, pos_ratio FROM unified_fund_list WHERE category='QDII日本' OR fund_code IN ('513000','513520','159866')")
    rows = c.fetchall()
    if rows:
        for row in rows:
            print('  %s %s | cat=%s | idx=%s | pos=%s' % (row[0], row[1], row[2], row[3], row[4]))
    else:
        print('[WARNING] QDII日本基金未配置！')
    
    # 4. 检查 exchange_rate 中的 JPY/CNY 数据
    print('\n=== exchange_rate 中的 JPY/CNY 数据 ===')
    c.execute("SELECT date, jpy_cny_mid FROM exchange_rate WHERE jpy_cny_mid IS NOT NULL ORDER BY date DESC LIMIT 5")
    rows = c.fetchall()
    if rows:
        print('最近 JPY/CNY 汇率:')
        for row in rows:
            print('  %s: %s' % (row[0], row[1]))
    else:
        print('[WARNING] JPY/CNY 汇率数据不存在！')
    
    # 5. 检查 valuation_mapping 中的 equity_asia 配置
    print('\n=== valuation_mapping 检查 ===')
    print('需要检查 valuation_mapping.py 中是否正确配置了 equity_asia')
    
    conn.close()

if __name__ == '__main__':
    check_db_state()
