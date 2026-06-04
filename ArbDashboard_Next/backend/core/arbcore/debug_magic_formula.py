# -*- coding: utf-8 -*-
"""调试脚本：检查纯ETF静态估值计算是否使用了魔法公式"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('database/arb_master.db')

# 检查纯ETF 162411(华宝油气)的历史计算结果
fund_code = '162411'
table_name = f'fund_history_{fund_code}'

print(f"=== 检查 {fund_code} 的静态估值计算结果 ===")

try:
    df = pd.read_sql(f"SELECT date, nav, static_valuation, ETF静态估值误差, ETF静态溢价 FROM {table_name} ORDER BY date DESC LIMIT 5", conn)
    print(df.to_string(index=False))
except Exception as e:
    print(f"错误: {e}")

# 检查fund_daily_factors中的hedge值
print(f"\n=== {fund_code} 的 hedge因子 ===")
factors = pd.read_sql("SELECT date, position, hedge FROM fund_daily_factors WHERE fund_code = ? ORDER BY date DESC LIMIT 5", conn, params=(fund_code,))
print(factors.to_string(index=False))

# 检查XOP的价格
print(f"\n=== XOP 最近价格 ===")
xop = pd.read_sql("SELECT date, price, netvalue FROM usa_etf_daily_prices WHERE symbol = 'XOP' ORDER BY date DESC LIMIT 5", conn)
print(xop.to_string(index=False))

conn.close()

# 手动计算魔法公式验证
print(f"\n=== 手动验证魔法公式 ===")
# 假设基准日是 T-1，估值日是 T
# 魔法公式: 估值 = T-1净值 * (1 - 仓位) + (T日价格 * T日汇率) / Hedge
base_nav = 1.0241  # 假设的T-1净值
position = 0.95
xop_price = 41.0   # 假设的T日XOP价格
fx = 6.8431        # 假设的T日汇率
hedge = 1356.551701

magic_val = base_nav * (1.0 - position) + (xop_price * fx) / hedge
print(f"魔法公式计算: {base_nav} * (1 - {position}) + ({xop_price} * {fx}) / {hedge}")
print(f"结果: {magic_val:.4f}")
