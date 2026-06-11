# -*- coding: utf-8 -*-
"""
测试A股多数据源功能（TDX + 银河QMT + 国金QMT）
"""

from core.arbcore.config.symbol_source_map import get_cn_stock_source, get_symbol_source

print("=" * 80)
print("测试A股多数据源功能")
print("=" * 80)

# 测试A股数据源选择
print("\n1. 便捷函数 get_cn_stock_source():")
print("-" * 80)
print(f"  get_cn_stock_source()          → {get_cn_stock_source()}（默认）")
print(f"  get_cn_stock_source('TDX')     → {get_cn_stock_source('TDX')}（通达信）")
print(f"  get_cn_stock_source('YH')      → {get_cn_stock_source('YH')}（银河QMT）")
print(f"  get_cn_stock_source('GJ')      → {get_cn_stock_source('GJ')}（国金QMT）")

# 测试标的查询（A股标的默认返回TDX）
print("\n2. 标的查询（默认用TDX）:")
print("-" * 80)
cn_symbols = ['510050', '159560', '00700', 'CU2409']
for symbol in cn_symbols:
    source = get_symbol_source(symbol)
    print(f"  {symbol:10s} → {source}")

print("\n3. 数据源切换逻辑示例:")
print("-" * 80)
print("  # 在 dynamic_valuation.py 或 fund_service.py 中")
print("  from core.arpbcore.config.symbol_source_map import get_cn_stock_source")
print("  ")
print("  # 用户配置：使用银河QMT")
print("  user_config = {'qmt_type': 'YH'}")
print("  cn_source = get_cn_stock_source(user_config.get('qmt_type'))")
print("  # 结果: cn_source = 'QMT_YH'")
print("  ")
print("  # 用户配置：使用国金QMT")
print("  user_config = {'qmt_type': 'GJ'}")
print("  cn_source = get_cn_stock_source(user_config.get('qmt_type'))")
print("  # 结果: cn_source = 'QMT_GJ'")
print("  ")
print("  # 用户配置：使用通达信（默认）")
print("  user_config = {}")
print("  cn_source = get_cn_stock_source(user_config.get('qmt_type'))")
print("  # 结果: cn_source = 'TDX'")

print("\n" + "=" * 80)
print("测试完成！")
print("=" * 80)
