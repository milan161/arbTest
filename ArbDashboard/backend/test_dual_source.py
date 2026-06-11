# -*- coding: utf-8 -*-
"""
测试美股ETF双数据源功能
"""

import sys
sys.path.insert(0, '.')

from core.arbcore.config.symbol_source_map import get_symbol_source, get_us_stock_source

print("=" * 80)
print("测试美股ETF双数据源功能")
print("=" * 80)

# 测试美股ETF
us_etfs = ['GLD', 'SPY', 'QQQ', 'ARKK', 'XBI', 'SOXX']

print("\n1. 使用 IB 数据源 (默认):")
print("-" * 80)
for symbol in us_etfs:
    source = get_symbol_source(symbol, use_ib=True)
    print(f"  {symbol:10s} → {source}")

print("\n2. 使用 富途 数据源 (无IB账户):")
print("-" * 80)
for symbol in us_etfs:
    source = get_symbol_source(symbol, use_ib=False)
    print(f"  {symbol:10s} → {source}")

print("\n3. 便捷函数 get_us_stock_source():")
print("-" * 80)
print(f"  get_us_stock_source(use_ib=True)  → {get_us_stock_source(use_ib=True)}")
print(f"  get_us_stock_source(use_ib=False) → {get_us_stock_source(use_ib=False)}")

print("\n4. 其他标的不受影响:")
print("-" * 80)
other_symbols = [
    ('510050', 'TDX'),   # A股ETF
    ('00700', 'FUTU'),   # 港股
    ('.INX', 'SINA'),    # 指数
    ('CU2409', 'TDX'),   # 期货
]
for symbol, expected in other_symbols:
    source = get_symbol_source(symbol, use_ib=False)
    status = "OK" if source == expected else "FAIL"
    print(f"  [{status}] {symbol:10s} → {source:6s} (期望: {expected})")

print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
