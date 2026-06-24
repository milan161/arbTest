# -*- coding: utf-8 -*-
"""
指数数据源测试脚本
测试新浪、腾讯、通达信 对不同类型指数的支持情况
"""
import requests
import time
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 测试用例：各类指数
TEST_INDICES = {
    # A股指数（6位数字）
    'A股指数': [
        ('399300', '沪深300'),
        ('399001', '深证成指'),
        ('000905', '中证500'),
        ('399997', '中证白酒'),
        ('399989', '中证TMT'),
    ],
    # 港股指数
    '港股指数': [
        ('HSI', '恒生指数'),
        ('HSTECH', '恒生科技'),
        ('HSCEI', '国企指数'),
    ],
    # 非标CSI代码（需要映射）
    'CSI非标代码': [
        ('H30094', '中证1000'),
        ('930713', '创业板指'),
        ('930720', '中小板指'),
        ('950090', '中证1000别名'),
        ('000922', '深证红利'),
        ('000961', '深证300'),
        ('000979', '深证信息'),
    ],
    # 中文名（需要映射）
    '中文名': [
        ('中小100', '中小100'),
        ('移动互联', '移动互联'),
        ('中证500', '中证500'),
        ('证券公司', '证券公司'),
    ],
}

def test_tencent(code):
    """测试腾讯接口"""
    headers = {'Referer': 'https://finance.qq.com/', 'User-Agent': 'Mozilla/5.0'}
    
    # 判断前缀
    if code.isdigit() and len(code) == 6:
        if code.startswith('399') or code.startswith('159') or code.startswith('3999'):
            tc_code = f"sz{code}"
        else:
            tc_code = f"sh{code}"
    elif code in ['HSI', 'HSTECH', 'HSCEI']:
        tc_code = f"hk{code}"
    else:
        return None, "非标准代码，跳过"
    
    url = f"http://qt.gtimg.cn/q={tc_code}"
    try:
        r = requests.get(url, headers=headers, timeout=3.0)
        if r.status_code == 200 and 'v_' in r.text and '=' in r.text:
            data_str = r.text.split('=')[1].strip(' "')
            parts = data_str.split('~')
            if len(parts) >= 33:
                return {
                    'price': float(parts[3]),
                    'pct': float(parts[32]),
                    'name': parts[1],
                    'code': parts[2],
                }, "OK"
        return None, "无数据"
    except Exception as e:
        return None, f"异常: {e}"

def test_sina(code):
    """测试新浪接口"""
    headers = {'Referer': 'https://finance.sina.com.cn/', 'Accept': 'text/event-stream'}
    
    if code.isdigit() and len(code) == 6:
        if code.startswith('399') or code.startswith('159') or code.startswith('3999'):
            sina_code = f"s_sz{code}"
        else:
            sina_code = f"s_sh{code}"
    elif code in ['HSI', 'HSTECH', 'HSCEI']:
        sina_code = f"rt_hk{code}"
    else:
        return None, "非标准代码，跳过"
    
    url = f"http://hq.sinajs.cn/list={sina_code}"
    try:
        r = requests.get(url, headers=headers, timeout=3.0)
        if r.status_code == 200 and '="' in r.text:
            data_str = r.text.split('="')[1].rstrip('";')
            parts = data_str.split(',')
            if len(parts) >= 2:
                return {
                    'price': float(parts[1]),
                    'pct': float(parts[2]) if len(parts) > 2 else 0,
                    'name': parts[0],
                }, "OK"
        return None, "无数据"
    except Exception as e:
        return None, f"异常: {e}"

def test_tdx(code):
    """测试通达信接口（需要tqcenter模块）"""
    try:
        from tqcenter import TqCenter
        tq = TqCenter()
        if code.isdigit() and len(code) == 6:
            market = 1 if code.startswith(('6', '5', '9')) else 0
            result = tq.get_security_quote(market, code)
            if result:
                return {
                    'price': result.last_price,
                    'pct': result.price_change_pct,
                    'name': result.name,
                }, "OK"
        return None, "不支持该类型代码"
    except ImportError:
        return None, "tqcenter未安装"
    except Exception as e:
        return None, f"异常: {e}"

def main():
    print("=" * 80)
    print("指数数据源测试报告")
    print("=" * 80)
    
    results = {}
    
    for category, indices in TEST_INDICES.items():
        print(f"\n{'=' * 60}")
        print(f"【{category}】")
        print(f"{'=' * 60}")
        
        for code, name in indices:
            print(f"\n  {code} ({name}):")
            
            # 测试腾讯
            data, status = test_tencent(code)
            tc_status = "✅" if data else "❌"
            tc_price = f"{data['price']:.3f}" if data else "-"
            tc_pct = f"{data['pct']:.2f}%" if data else "-"
            print(f"    腾讯: {tc_status} 价格={tc_price} 涨跌幅={tc_pct} [{status}]")
            
            # 测试新浪
            data, status = test_sina(code)
            sina_status = "✅" if data else "❌"
            sina_price = f"{data['price']:.3f}" if data else "-"
            sina_pct = f"{data['pct']:.2f}%" if data else "-"
            print(f"    新浪: {sina_status} 价格={sina_price} 涨跌幅={sina_pct} [{status}]")
            
            # 测试通达信
            data, status = test_tdx(code)
            tdx_status = "✅" if data else "❌"
            tdx_price = f"{data['price']:.3f}" if data else "-"
            tdx_pct = f"{data['pct']:.2f}%" if data else "-"
            print(f"    通达信: {tdx_status} 价格={tdx_price} 涨跌幅={tdx_pct} [{status}]")
            
            time.sleep(0.1)
    
    # 总结
    print(f"\n{'=' * 80}")
    print("【总结】")
    print(f"{'=' * 80}")
    print("""
    数据源特性：
    ┌─────────┬────────────┬────────────┬────────────┐
    │ 数据源  │ A股指数    │ 港股指数   │ 历史数据   │
    ├─────────┼────────────┼────────────┼────────────┤
    │ 腾讯    │ ✅ 实时    │ ✅ 实时    │ ❌ 无      │
    │ 新浪    │ ✅ 实时    │ ✅ 实时    │ ❌ 无      │
    │ 通达信  │ ✅ 实时    │ ❌ 不支持  │ ✅ 历史K线 │
    │ Tushare │ ✅ 历史    │ ✅ 历史    │ ✅ 全部    │
    └─────────┴────────────┴────────────┴────────────┘
    
    推荐方案：
    1. 实时价格：腾讯优先（速度快、数据全）
    2. 历史价格：通达信（本地有K线数据）
    3. 港股指数：腾讯/新浪
    4. 非标CSI代码：需要映射到标准6位代码
    """)

if __name__ == '__main__':
    main()
