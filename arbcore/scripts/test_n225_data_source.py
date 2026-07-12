#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[AI-2026-07-09] 测试日经225(N225)数据源可用性
目标：找到可用的 N225 实时/历史数据 API
"""

import requests
import json

def test_eastmoney():
    """测试东财 API 获取 N225"""
    headers = {
        'Referer': 'https://quote.eastmoney.com/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    
    # 测试不同的 secid 格式
    test_cases = [
        '100.N225',
        '116.N225',
        '100.NKY',
        '116.NKY',
    ]
    
    for secid in test_cases:
        try:
            url = 'https://push2.eastmoney.com/api/qt/stock/get'
            params = {
                'secid': secid,
                'fields': 'f43,f58,f170',
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'fltt': '1',
            }
            r = requests.get(url, params=params, headers=headers, timeout=5.0)
            data = r.json()
            if data.get('rc') == 0 and data.get('data'):
                d = data['data']
                print('[OK] secid=%s: price=%s, name=%s, pct=%s' % (secid, d.get('f43'), d.get('f58'), d.get('f170')))
                return secid, d
            else:
                print('[FAIL] secid=%s: rc=%s' % (secid, data.get('rc')))
        except Exception as e:
            print('[ERROR] secid=%s: %s' % (secid, str(e)))
    
    return None, None

def test_sina():
    """测试新浪全球指数接口获取 N225"""
    headers = {
        'Referer': 'https://finance.sina.com.cn/',
        'Accept': 'text/event-stream',
    }
    
    # 测试不同的 symbol 格式
    test_cases = [
        'int_nikkei',
        'b_TWSE',
        'nikkei',
    ]
    
    for sym in test_cases:
        try:
            url = 'http://hq.sinajs.cn/list=%s' % sym
            r = requests.get(url, headers=headers, timeout=3.0)
            r.encoding = 'gbk'
            if '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                print('[OK] sym=%s: parts=%s' % (sym, parts[:5]))
                return sym, parts
            else:
                print('[FAIL] sym=%s: %s' % (sym, r.text[:100]))
        except Exception as e:
            print('[ERROR] sym=%s: %s' % (sym, str(e)))
    
    return None, None

def test_tencent():
    """测试腾讯接口获取 N225"""
    headers = {
        'Referer': 'https://finance.qq.com/',
        'User-Agent': 'Mozilla/5.0',
    }
    
    # 腾讯可能不支持 N225，但测试一下
    test_cases = [
        'nkn225',
        'jnx',
    ]
    
    for sym in test_cases:
        try:
            url = 'http://qt.gtimg.cn/q=%s' % sym
            r = requests.get(url, headers=headers, timeout=3.0)
            if 'v_' in r.text:
                print('[OK] sym=%s: %s' % (sym, r.text[:200]))
                return sym, r.text
            else:
                print('[FAIL] sym=%s: %s' % (sym, r.text[:100]))
        except Exception as e:
            print('[ERROR] sym=%s: %s' % (sym, str(e)))
    
    return None, None

if __name__ == '__main__':
    print('=== 测试日经225(N225)数据源 ===')
    print()
    
    print('--- 东财 API ---')
    secid, data = test_eastmoney()
    print()
    
    print('--- 新浪 API ---')
    sym, parts = test_sina()
    print()
    
    print('--- 腾讯 API ---')
    sym, text = test_tencent()
    print()
    
    print('=== 测试完成 ===')
