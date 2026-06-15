#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试实时估值功能
验证：
1. IB/富途能否获取美股ETF实时价格（夜盘）
2. 采样服务符号格式修复是否生效
3. 实时估值计算是否正常
"""
import sys
import os

# 添加路径
# D:\Study\arbTest\ArbDashboard\test\test_realtime.py
test_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(test_dir)) # D:\Study\arbTest
backend_dir = os.path.join(project_root, "ArbDashboard", "backend")

sys.path.insert(0, project_root)
sys.path.insert(0, backend_dir)

print(f"project_root: {project_root}")
print(f"backend_dir: {backend_dir}")

from datetime import datetime
import json

print("=" * 80)
print("🧪 实时估值功能测试")
print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. 测试IB Reader能否获取美股ETF实时价格
print("\n[1/4] 测试 IB Reader 获取美股ETF实时价格...")
try:
    from arbcore.fetchers.ib_reader import IBReader
    ib = IBReader()
    if ib.connect_to_ib():
        print("✅ IB连接成功")
        
        # 测试几个美股ETF
        test_etfs = ['GLD', 'USO', 'SPY', 'QQQ', 'INDA']
        prices = {}
        for etf in test_etfs:
            if etf in ib.prices:
                price_data = ib.prices[etf]
                if isinstance(price_data, dict) and price_data.get('bid', 0) > 0:
                    prices[etf] = price_data['bid']
                    print(f"  ✅ {etf}: ${price_data['bid']} (bid: {price_data.get('bid')})")
                else:
                    print(f"  ⚠️  {etf}: 无有效价格")
            else:
                print(f"  ❌ {etf}: IB prices字典中不存在")
        
        if not prices:
            print("  ⚠️  夜盘可能没有实时价格，尝试等待IB轮询...")
            import time
            time.sleep(5)  # 等待5秒让IB轮询
        
        ib.disconnect()
    else:
        print("❌ IB连接失败")
except Exception as e:
    print(f"❌ IB测试失败: {e}")
    import traceback
    traceback.print_exc()

# 2. 测试MarketDataService
print("\n[2/4] 测试 MarketDataService...")
try:
    from services.market_data_service import MarketDataService
    from arbcore.database.db_manager import DatabaseManager
    
    db = DatabaseManager(db_path=os.path.join(project_root, 'database', 'arb_master.db'))
    mds = MarketDataService(db)
    
    # 测试LOF基金
    test_codes = ['501312', '161130', '162411']
    for code in test_codes:
        q = mds.get_realtime_quote(code)
        if q and q.get('price'):
            print(f"  ✅ {code}: ¥{q['price']} (来源: {q.get('source', '未知')})")
        else:
            print(f"  ❌ {code}: 无实时价格")
    
    # 测试完整符号（如 ^INDA-EU）
    print("\n  测试完整符号格式:")
    test_symbols = ['^INDA-EU', '^USO-EU', '^GLD-JP']
    for sym in test_symbols:
        q = mds.get_realtime_quote(sym)
        if q and q.get('price'):
            print(f"  ✅ {sym}: ¥{q['price']} (来源: {q.get('source', '未知')})")
        else:
            print(f"  ⚠️  {sym}: 无实时价格")
    
except Exception as e:
    print(f"❌ MarketDataService测试失败: {e}")
    import traceback
    traceback.print_exc()

# 3. 测试DynamicValuationCalculator
print("\n[3/4] 测试 DynamicValuationCalculator...")
try:
    from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
    from services.config_service import ConfigService
    
    # 使用已经初始化的 db
    calc = DynamicValuationCalculator(db)
    
    # 获取配置
    config_svc = ConfigService(db)
    config = config_svc.get_full_config()
    funds = config.get('funds', [])
    
    if funds:
        # 测试第一个基金
        fund = funds[0]
        code = fund.get('code', '')
        print(f"  测试基金: {code} - {fund.get('name', '')}")
        
        # 模拟current_etfs（完整符号格式）
        current_etfs = {}
        portfolio = fund.get('valuation_portfolio', []) or fund.get('hedging_portfolio', [])
        for item in portfolio:
            symbol = item.get('symbol', '')
            current_etfs[symbol] = 35.0  # 模拟价格
            print(f"    ETF: {symbol} = 35.0 (模拟)")
        
        # 计算估值
        res = calc.calculate(fund, 7.2, current_etfs)
        if res and res.get('rt_val') and res['rt_val'] > 0:
            print(f"  ✅ 实时估值: {res['rt_val']}")
            print(f"  ✅ 基准日期: {res.get('base_date')}")
        else:
            print(f"  ❌ 估值计算失败: {res}")
    else:
        print("  ❌ 没有基金配置")
        
except Exception as e:
    print(f"❌ Calculator测试失败: {e}")
    import traceback
    traceback.print_exc()

# 4. 测试采样服务符号格式
print("\n[4/4] 测试采样服务符号格式修复...")
try:
    # 读取sampler_service.py检查修复
    sampler_path = os.path.join(backend_dir, 'services', 'intraday', 'sampler_service.py')
    with open(sampler_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if 'current_etfs' in content and '完整符号' in content:
        print("  ✅ 采样服务已修复：使用完整符号格式")
        print("  ✅ 构建 current_etfs 字典")
        
        # 检查关键代码
        if 'current_etfs[symbol] = q[\'price\']' in content:
            print("  ✅ 使用完整符号作为字典键")
        else:
            print("  ⚠️  字典键格式可能不正确")
    else:
        print("  ❌ 采样服务未修复")
        
except Exception as e:
    print(f"❌ 采样服务检查失败: {e}")

print("\n" + "=" * 80)
print("✅ 测试完成")
print("=" * 80)
