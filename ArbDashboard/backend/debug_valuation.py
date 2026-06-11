#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""调试实时估值计算"""
import sys
import os
import builtins
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"D:\Study\arbTest")

# Windows GBK encoding safe print helper
def print(*args, **kwargs):
    try:
        builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        try:
            encoding = sys.stdout.encoding or 'gbk'
            safe_args = [str(arg).encode(encoding, errors='replace').decode(encoding) for arg in args]
            builtins.print(*safe_args, **kwargs)
        except:
            pass

from datetime import datetime
import sqlite3
import pandas as pd

print(f"[调试] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. 连接数据库与初始化基座
from arbcore.database.db_manager import DatabaseManager
db_manager = DatabaseManager(db_path=r'D:\Study\arbTest\database\arb_master.db')
conn = db_manager._get_conn()

# 2. 获取基金配置
from services.config_service import ConfigService
config_service = ConfigService(db_manager)
fund_config = config_service.get_full_config().get('funds', [])

print(f"\n[1] 基金配置数量: {len(fund_config)}")

# 3. 获取第一只基金（如 164824 印度基金）
target_code = '164824'
fund_cfg = None
for f in fund_config:
    if str(f.get('code')) == target_code:
        fund_cfg = f
        break

if fund_cfg:
    print(f"\n[2] 找到基金: {fund_cfg.get('name')} ({target_code})")
    print(f"  估值组合: {fund_cfg.get('valuation_portfolio', [])}")
    
    # 4. 获取汇率
    fx_df = pd.read_sql(
        "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1",
        conn
    )
    current_fx = fx_df.iloc[0]['usd_cny_mid'] if not fx_df.empty else None
    print(f"\n[3] 汇率: {current_fx}")
    
    # 5. 获取实时 ETF 价格
    from services.market_data_service import MarketDataService
    market_data = MarketDataService(db_manager)
    
    current_etfs = {}
    portfolio = fund_cfg.get('valuation_portfolio', []) or fund_cfg.get('hedging_portfolio', [])
    print(f"\n[4] 获取ETF实时价格:")
    for item in portfolio:
        symbol = item.get('symbol', '')
        q = market_data.get_realtime_quote(symbol)
        if q and q.get('price'):
            current_etfs[symbol] = q['price']
            print(f"  {symbol} = {q['price']}")
        else:
            print(f"  {symbol} = 无价格")
    
    print(f"\n[5] current_etfs 字典: {current_etfs}")
    
    # 6. 计算实时估值
    from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
    calculator = DynamicValuationCalculator(db_manager)
    
    print(f"\n[6] 计算实时估值...")
    res = calculator.calculate(fund_cfg, current_fx, current_etfs)
    print(f"  返回结果: {res}")
    
    val_res = res.get('rt_val') if res else None
    if val_res and val_res > 0:
        print(f"  [OK] 实时估值: {val_res}")
    else:
        print(f"  [Error] 实时估值计算失败")

# 7. 检查采样表
print(f"\n[7] 采样表最新数据:")
sample_df = pd.read_sql(
    "SELECT rt_val, premium, time FROM fund_intraday_quotes WHERE fund_code=? ORDER BY time DESC LIMIT 1",
    conn,
    params=(target_code,)
)
if not sample_df.empty:
    print(f"  rt_val: {sample_df.iloc[0]['rt_val']}")
    print(f"  premium: {sample_df.iloc[0]['premium']}")
    print(f"  time: {sample_df.iloc[0]['time']}")
else:
    print(f"  无数据")

conn.close()
print("\n" + "=" * 80)
