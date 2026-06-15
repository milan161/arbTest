# -*- coding: utf-8 -*-
"""
测试 arbcore 模块（简化版，兼容 Windows PowerShell）
"""

import sys
import os

# 添加 workspace 路径
workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, workspace_root)

print("=" * 60)
print("Testing arbcore modules")
print("=" * 60)
print(f"Workspace: {workspace_root}")
print()

# 测试1: 导入
print("[TEST 1] Importing modules...")
try:
    from arbcore.fetchers.futu_reader import FutuReader
    print("[OK] FutuReader")
    
    from arbcore.utils import RetryManager, CircuitBreaker, HealthMonitor, ConfigManager
    print("[OK] RetryManager")
    print("[OK] CircuitBreaker")
    print("[OK] HealthMonitor")
    print("[OK] ConfigManager")
    print("\n[SUCCESS] All imports passed!\n")
except Exception as e:
    print(f"\n[FAILED] Import error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试2: RetryManager
print("[TEST 2] Testing RetryManager...")
try:
    retry = RetryManager(max_retries=3, base_delay=0.1)
    
    def test_func():
        return "ok"
    
    result = retry.execute_with_retry(test_func)
    assert result == "ok", "Result should be 'ok'"
    print("[OK] RetryManager works correctly")
except Exception as e:
    print(f"[FAILED] RetryManager error: {e}")

# 测试3: CircuitBreaker
print("[TEST 3] Testing CircuitBreaker...")
try:
    breaker = CircuitBreaker(failure_threshold=3, timeout=10)
    
    def good_func():
        return "ok"
    
    result = breaker.call(good_func)
    assert result == "ok", "Result should be 'ok'"
    print(f"[OK] CircuitBreaker state: {breaker.get_state()}")
except Exception as e:
    print(f"[FAILED] CircuitBreaker error: {e}")

# 测试4: HealthMonitor
print("[TEST 4] Testing HealthMonitor...")
try:
    monitor = HealthMonitor()
    monitor.register_component('test_db')
    monitor.update_status('test_db', 'success', 'working')
    summary = monitor.get_health_summary()
    print(f"[OK] Health summary: {summary['healthy_components']}/{summary['total_components']} healthy")
except Exception as e:
    print(f"[FAILED] HealthMonitor error: {e}")

# 测试5: FutuReader（需要富途OpenD）
print()
print("[TEST 5] Testing FutuReader (optional, requires Futu OpenD)...")
try:
    futu = FutuReader()
    success, msg, prices = futu.get_prices(['GLD'])
    if success and prices:
        print(f"[OK] FutuReader got prices: {list(prices.keys())}")
    else:
        print(f"[WARN] FutuReader failed: {msg}")
        print("       (This is OK if Futu OpenD is not running)")
    futu.close()
except Exception as e:
    print(f"[WARN] FutuReader error: {e}")

print()
print("=" * 60)
print("ALL TESTS COMPLETED!")
print("=" * 60)
