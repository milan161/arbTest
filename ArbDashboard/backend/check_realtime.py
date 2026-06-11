#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""快速检查实时估值功能"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
print(f"[检查] 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 检查API响应
import requests
try:
    res = requests.get('http://127.0.0.1:8000/api/dashboard', timeout=10)
    if res.status_code == 200:
        data = res.json()
        if data.get('status') == 'ok':
            funds = data.get('data', [])
            print("[OK] API正常，共 {} 只基金\n".format(len(funds)))
            
            # 显示前5只基金的关键数据
            for fund in funds[:5]:
                code = fund.get('fund_code', '')
                name = fund.get('fund_name', '')
                price = fund.get('price', 0)
                static_val = fund.get('static_val', 0)
                rt_val = fund.get('rt_val')
                static_premium = fund.get('static_premium', 0)
                rt_premium = fund.get('rt_premium')
                
                print(f"{code} {name}")
                print(f"  价格: {price:.4f} | 静态估值: {static_val:.4f} | 实时估值: {rt_val}")
                print(f"  静态溢价: {static_premium:.3f}% | 实时溢价: {rt_premium}%")
                
                # 检查rt_val是否有效
                if rt_val and rt_val > 0:
                    if rt_val != static_val:
                    print("  [OK] 实时估值 != 静态估值（修复成功！）")
                    else:
                        print(f"  ⚠️  实时估值 = 静态估值（可能还是用缓存数据）")
                elif price > 0:
                    print(f"  ⚠️  实时估值为空（非交易时间或计算失败）")
                print()
        else:
            print(f"❌ API返回异常: {data}")
    else:
        print(f"❌ API响应失败: {res.status_code}")
except Exception as e:
    print(f"❌ API请求失败: {e}")

print("=" * 80)
