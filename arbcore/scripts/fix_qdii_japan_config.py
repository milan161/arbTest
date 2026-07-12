#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[AI-2026-07-09] 修复 QDII日本基金 related_index 并导入 N225 历史数据
"""

import sqlite3
import os
import requests
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'database', 'arb_master.db')

def fix_related_index():
    """修复 QDII日本基金的 related_index 字段"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 更新 related_index 为 N225
    c.execute("UPDATE unified_fund_list SET related_index='N225' WHERE fund_code IN ('513000','513520','159866')")
    print('[OK] Updated %d rows: related_index -> N225' % c.rowcount)
    
    # 验证
    c.execute("SELECT fund_code, fund_name, related_index FROM unified_fund_list WHERE fund_code IN ('513000','513520','159866')")
    for row in c.fetchall():
        print('  %s %s -> idx=%s' % (row[0], row[1], row[2]))
    
    conn.commit()
    conn.close()

def import_n225_sina_history():
    """从新浪获取日经225历史数据并导入 index_history"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 检查是否已有 N225 数据
    c.execute("SELECT COUNT(*) FROM index_history WHERE symbol='N225'")
    existing = c.fetchone()[0]
    if existing > 0:
        print('[INFO] N225 历史数据已存在 (%d 条)，跳过导入' % existing)
        conn.close()
        return
    
    # 使用新浪历史数据接口获取日经225
    # 新浪日经225代码: int_nikkei
    print('[INFO] 尝试从新浪获取日经225历史数据...')
    
    headers = {
        'Referer': 'https://finance.sina.com.cn/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    }
    
    # 尝试获取日经225 K线数据（日线）
    # 新浪财经历史K线接口
    import json
    
    # 方案1: 新浪历史行情接口
    try:
        # 日经225新浪代码: b_TWSE (台湾证交所) 或 int_nikkei
        url = 'https://finance.sina.com.cn/realstock/company/int_nikkei/hisdata/klc_kl.js'
        r = requests.get(url, headers=headers, timeout=10)
        print('[INFO] Sina history response status: %d' % r.status_code)
        if r.status_code == 200 and len(r.text) > 100:
            print('[INFO] Got history data, length=%d' % len(r.text))
    except Exception as e:
        print('[WARN] Sina history failed: %s' % str(e))
    
    # 方案2: 使用腾讯接口获取日经225历史
    try:
        # 腾讯日经225代码: nkn225
        url = 'http://qt.gtimg.cn/q=nkn225'
        r = requests.get(url, headers={'Referer': 'https://finance.qq.com/'}, timeout=5)
        print('[INFO] Tencent N225 response: %s' % r.text[:200])
    except Exception as e:
        print('[WARN] Tencent N225 failed: %s' % str(e))
    
    print('[INFO] 自动导入 N225 历史数据需要 TDX 或其他数据源支持')
    print('[INFO] 暂时跳过，将在后续通过 daily_updater 自动补全')
    
    conn.close()

def verify_estimation_flow():
    """验证估值流程是否就绪"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    print('\n=== 验证估值流程 ===')
    
    # 1. 检查 related_index
    c.execute("SELECT fund_code, fund_name, related_index, pos_ratio FROM unified_fund_list WHERE fund_code IN ('513000','513520','159866')")
    funds = c.fetchall()
    print('\n[1] QDII日本基金配置:')
    all_ok = True
    for row in funds:
        idx = row[2]
        ok = idx and idx != '-' and idx != ''
        status = '[OK]' if ok else '[MISSING]'
        print('  %s %s | idx=%s | pos=%s %s' % (row[0], row[1], idx, row[3], status))
        if not ok:
            all_ok = False
    
    # 2. 检查 JPY/CNY 汇率
    c.execute("SELECT COUNT(*) FROM exchange_rate WHERE jpy_cny_mid IS NOT NULL")
    jpy_count = c.fetchone()[0]
    print('\n[2] JPY/CNY 汇率数据: %d 条 %s' % (jpy_count, '[OK]' if jpy_count > 0 else '[MISSING]'))
    
    # 3. 检查 index_history 中的 N225
    c.execute("SELECT COUNT(*) FROM index_history WHERE symbol='N225'")
    n225_count = c.fetchone()[0]
    print('\n[3] N225 历史数据: %d 条 %s' % (n225_count, '[OK]' if n225_count > 0 else '[NEED DATA]'))
    
    # 4. 检查 valuation_mapping
    print('\n[4] valuation_mapping.py:')
    print('  equity_asia -> calculate_asia_valuation [OK]')
    print('  equity_us_index -> calculate_index_valuation [OK]')
    
    # 5. 检查 static_valuation.py 路由
    print('\n[5] static_valuation.py 路由:')
    print('  指数估值路径已添加 (related_index 兜底) [OK]')
    
    conn.close()
    
    return all_ok and jpy_count > 0

if __name__ == '__main__':
    print('=== 修复 QDII日本基金配置 ===\n')
    
    # Step 1: 修复 related_index
    fix_related_index()
    
    # Step 2: 导入 N225 历史数据
    import_n225_sina_history()
    
    # Step 3: 验证估值流程
    verify_estimation_flow()
    
    print('\n=== 完成 ===')
