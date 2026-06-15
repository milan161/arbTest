# -*- coding: utf-8 -*-
"""
测试抽取到 arbcore 的 FutuReader 是否正常工作

运行方式：
    python test_futu_reader.py
"""

import sys
import os

# 添加 arbcore 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'arbcore'))

from arbcore.fetchers.futu_reader import FutuReader


def test_futu_reader():
    """测试富途读取器"""
    print("=" * 60)
    print("测试抽取到 arbcore 的 FutuReader")
    print("=" * 60)
    
    # 初始化读取器
    futu = FutuReader()
    
    # 测试获取几个美股ETF价格
    symbols = ['GLD', 'USO', 'SPY', 'QQQ']
    print(f"\n尝试获取美股ETF价格: {', '.join(symbols)}")
    print("-" * 60)
    
    success, msg, prices = futu.get_prices(symbols)
    
    print(f"\n状态: {'✅ 成功' if success else '❌ 失败'}")
    print(f"信息: {msg}")
    print(f"\n获取到的价格:")
    
    if prices:
        for symbol, quote in prices.items():
            print(f"  {symbol:6s}: 买一={quote['bid']:.2f}, 卖一={quote['ask']:.2f}, 最新={quote['last']:.2f}")
    else:
        print("  (无数据)")
    
    # 测试单个价格获取
    print("\n" + "-" * 60)
    print("测试单个价格获取:")
    for symbol in symbols:
        price = futu.get_price(symbol)
        print(f"  {symbol:6s}: {price:.2f}")
    
    # 清理
    futu.close()
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == '__main__':
    test_futu_reader()
