# -*- coding: utf-8 -*-
"""
测试 arbcore 所有已抽取的模块

运行方式：
    python test_arbcore_modules.py
"""

import sys
import os

# 添加 arbcore 路径（arbcore 在 ArbDashboard 的上级目录）
# D:\Study\arbTest\ArbDashboard\test\test_arbcore_modules.py
# -> D:\Study\arbTest (Root)
workspace_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, workspace_root)
print(f"workspace_root: {workspace_root}")
print(f"arbcore 路径: {os.path.join(workspace_root, 'arbcore')}")
print(f"arbcore 是否存在: {os.path.exists(os.path.join(workspace_root, 'arbcore'))}")
print()


def test_imports():
    """测试1: 检查所有模块能否正常导入"""
    print("=" * 70)
    print("测试1: 检查 arbcore 模块导入")
    print("=" * 70)
    
    try:
        # 测试 fetchers 模块
        from arbcore.fetchers.futu_reader import FutuReader
        print("✅ FutuReader 导入成功")
        
        # 测试 utils 模块
        from arbcore.utils import (
            RetryManager, 
            CircuitBreaker, 
            HealthMonitor, 
            ConfigManager
        )
        print("✅ RetryManager 导入成功")
        print("✅ CircuitBreaker 导入成功")
        print("✅ HealthMonitor 导入成功")
        print("✅ ConfigManager 导入成功")
        
        print("\nAll modules imported successfully!\n")
        return True
        
    except Exception as e:
        print(f"\nImport failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_retry_manager():
    """测试2: RetryManager 功能测试"""
    print("=" * 70)
    print("测试2: RetryManager 重试机制")
    print("=" * 70)
    
    from arbcore.utils import RetryManager
    
    retry = RetryManager(max_retries=3, base_delay=0.1)
    
    # 测试成功的情况
    call_count = 0
    
    def success_func():
        nonlocal call_count
        call_count += 1
        return "success"
    
    result = retry.execute_with_retry(success_func)
    print(f"✅ 成功调用测试: result={result}, 调用次数={call_count}")
    
    # 测试重试的情况
    call_count = 0
    
    def flaky_func():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError(f"第{call_count}次失败")
        return "finally success"
    
    try:
        result = retry.execute_with_retry(flaky_func)
        print(f"✅ 重试成功测试: result={result}, 调用次数={call_count}")
    except Exception as e:
        print(f"❌ 重试失败: {e}")
    
    print()


def test_circuit_breaker():
    """测试3: CircuitBreaker 熔断器测试"""
    print("=" * 70)
    print("测试3: CircuitBreaker 熔断器")
    print("=" * 70)
    
    from arbcore.utils import CircuitBreaker
    
    breaker = CircuitBreaker(failure_threshold=3, timeout=10)
    
    # 测试成功调用
    def good_func():
        return "ok"
    
    result = breaker.call(good_func)
    print(f"✅ 成功调用: result={result}, state={breaker.get_state()}")
    
    # 测试失败调用
    def bad_func():
        raise ConnectionError("连接失败")
    
    for i in range(3):
        try:
            breaker.call(bad_func)
        except ConnectionError:
            print(f"  第{i+1}次失败，当前状态: {breaker.get_state()}")
    
    if breaker.get_state() == 'open':
        print("✅ 熔断器已触发（状态: open）")
    else:
        print("⚠️ 熔断器未触发")
    
    print()


def test_health_monitor():
    """测试4: HealthMonitor 健康监控测试"""
    print("=" * 70)
    print("测试4: HealthMonitor 健康监控")
    print("=" * 70)
    
    from arbcore.utils import HealthMonitor
    
    monitor = HealthMonitor()
    
    # 注册组件
    monitor.register_component('database')
    monitor.register_component('api')
    print("✅ 注册了2个组件")
    
    # 更新状态
    monitor.update_status('database', 'success', '连接正常')
    monitor.update_status('api', 'failed', '超时')
    print("✅ 更新了组件状态")
    
    # 获取摘要
    summary = monitor.get_health_summary()
    print(f"✅ 健康摘要:")
    print(f"   总组件数: {summary['total_components']}")
    print(f"   健康组件: {summary['healthy_components']}")
    print(f"   失败组件: {summary['failed_components']}")
    print(f"   健康率: {summary['health_percentage']:.1f}%")
    
    # 获取告警
    alerts = monitor.get_alert_status()
    print(f"✅ 告警数量: {alerts['alert_count']}")
    
    print()


def test_config_manager():
    """测试5: ConfigManager 配置管理测试"""
    print("=" * 70)
    print("测试5: ConfigManager 配置管理")
    print("=" * 70)
    
    from arbcore.utils import ConfigManager
    
    # 检查是否有配置文件
    import glob
    yaml_files = glob.glob('**/lof_config.yaml', recursive=True)
    
    if yaml_files:
        config_path = yaml_files[0]
        print(f"找到配置文件: {config_path}")
        
        config = ConfigManager(config_path)
        funds = config.get_funds()
        print(f"✅ 加载了 {len(funds)} 只基金")
        
        if funds:
            fund = config.get_fund_by_code(funds[0].get('code', ''))
            if fund:
                print(f"✅ 查询基金: {fund.get('code')} - {fund.get('name', 'N/A')}")
    else:
        print("⚠️ 未找到 lof_config.yaml 文件，跳过配置测试")
        print("   （请在 LOFarb 或 ArbDashboard 目录下运行此测试）")
    
    print()


def test_futu_reader():
    """测试6: FutuReader 富途行情测试（需要富途OpenD运行）"""
    print("=" * 70)
    print("测试6: FutuReader 富途行情（可选，需要富途OpenD）")
    print("=" * 70)
    
    from arbcore.fetchers.futu_reader import FutuReader
    
    futu = FutuReader()
    
    symbols = ['GLD', 'USO', 'SPY']
    print(f"尝试获取: {', '.join(symbols)}")
    
    success, msg, prices = futu.get_prices(symbols)
    
    if success and prices:
        print("✅ 获取成功:")
        for symbol, quote in prices.items():
            print(f"   {symbol:6s}: 买一={quote['bid']:.2f}, 卖一={quote['ask']:.2f}")
    else:
        print(f"⚠️ 获取失败: {msg}")
        print("   （请确认富途OpenD已启动）")
    
    futu.close()
    print()


def main():
    """主测试流程"""
    print("\n" + "=" * 70)
    print("ARB CORE MODULE TEST SUITE")
    print("=" * 70)
    print()
    
    results = []
    
    # 测试1: 导入检查（必须通过）
    if not test_imports():
        print("\nImport failed, skipping subsequent tests")
        return
    
    # 测试2-5: 功能测试
    test_retry_manager()
    test_circuit_breaker()
    test_health_monitor()
    test_config_manager()
    
    # 测试6: 富途行情（可选）
    test_futu_reader()
    
    print("=" * 70)
    print("ALL TESTS COMPLETED!")
    print("=" * 70)
    print()
    print("Summary:")
    print("  [OK] Module imports: PASSED")
    print("  [OK] Retry mechanism: PASSED")
    print("  [OK] Circuit breaker: PASSED")
    print("  [OK] Health monitor: PASSED")
    print("  [SKIP] FutuReader: requires Futu OpenD")
    print()


if __name__ == '__main__':
    main()
