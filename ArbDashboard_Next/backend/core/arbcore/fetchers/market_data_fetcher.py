# -*- coding: utf-8 -*-
# market_data_fetcher.py - 市场数据获取公共函数
# 版本: 1.0.0
# 最后修改时间: 2026-05-21

import os
import sqlite3
import pandas as pd

# 共享数据库路径 - 可通过环境变量覆盖
_SHARED_DB_PATH = os.environ.get('ARB_MASTER_DB', r"D:\Study\arbTest\database\arb_master.db")


def get_exchange_rate():
    """获取当天的汇率"""
    today_exchange_rate = "无"
    try:
        conn = sqlite3.connect(_SHARED_DB_PATH)
        df = pd.read_sql("SELECT date, usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
        conn.close()
        if not df.empty:
            rate = df.iloc[0]['usd_cny_mid']
            today_exchange_rate = f"汇率 - 中间价: {rate:.4f}"
    except Exception as e:
        print(f"获取汇率失败: {e}")
    return today_exchange_rate


def get_ib_night_prices():
    """获取IB夜盘价格"""
    ib_night_prices = {}
    ib_prev_closes = {}
    ib_status_message = ""
    try:
        import requests
        url = "http://localhost:5000/api/ib_prices"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if data.get('status') == 'error':
                ib_status_message = data.get('message', 'IB未连接')
                ib_prev_closes = data.get('prev_closes', {})
                print(f"IB状态: {ib_status_message}")
            else:
                ib_night_prices = data.get('prices', {})
                ib_prev_closes = data.get('prev_closes', {})
                ib_status_message = "IB夜盘价格已获取"

                price_strs = []
                for sym, p in ib_night_prices.items():
                    if isinstance(p, dict) and p.get('bid'):
                        price_strs.append(f"{sym}=${p.get('bid'):.2f}")
                prices_log = ", ".join(price_strs) if price_strs else "无数据"
                print(f"IB夜盘价格: {prices_log}")
        else:
            ib_status_message = f"后台服务响应异常: {response.status_code}"
            print(ib_status_message)
    except Exception as e:
        ib_status_message = "后台服务(端口5000)未启动"
        print(f"无法连接到后台服务获取IB数据: {e}")
    return ib_night_prices, ib_prev_closes, ib_status_message