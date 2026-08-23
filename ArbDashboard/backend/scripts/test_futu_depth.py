# -*- coding: utf-8 -*-
"""
[2026-08-21] 测试脚本：验证富途实时盘口数据
目的：获取 GLD/XOP 买卖一价，计算真实开仓/平仓溢价率
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'arbcore'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'ArbDashboard', 'backend'))

from fetchers.futu_reader import FutuReader
from services.market_data_service import MarketDataService
import sqlite3
from datetime import datetime

def main():
    print("=" * 60)
    print("富途盘口数据测试")
    print("=" * 60)

    # 1. 连接富途
    reader = FutuReader()
    reader.disabled = False
    reader._try_connect_silent()

    if not reader.connected:
        print("❌ 富途连接失败")
        return

    print("✅ 富途已连接")

    # 2. 获取实时行情（含盘口）
    success, msg, prices = reader.get_prices(['GLD', 'XOP', '162411'])
    print(f"\n实时行情: {msg}")
    for sym, data in prices.items():
        print(f"  {sym}: bid={data['bid']:.2f}, ask={data['ask']:.2f}, last={data['last']:.2f}")

    # 3. 测试计算溢价率
    print("\n" + "=" * 60)
    print("溢价率计算测试（以 162411 为例）")
    print("=" * 60)

    # 需要后端估值服务
    from services.fund_service import FundService
    from infrastructure.db_manager import DatabaseManager

    db = DatabaseManager('D:/Study/arbTest/database/arb_master.db')
    svc = FundService(db)

    # 获取 162411 的估值元数据
    meta = svc.get_valuation_meta('162411')
    if meta.get('status') == 'error':
        print(f"❌ 估值计算失败: {meta.get('msg')}")
        return

    rt_val = meta.get('rt_val')
    print(f"162411 实时估值: {rt_val:.4f}")

    # 从富途获取 162411 盘口
    lof_code = '162411'
    lof_quote = reader.get_realtime_quote(lof_code)
    if lof_quote:
        lof_bid = lof_quote.get('bid', 0)
        lof_ask = lof_quote.get('ask', 0)
        print(f"162411 盘口: bid={lof_bid:.4f}, ask={lof_ask:.4f}")

        # 计算真实溢价率
        open_premium = (lof_ask / rt_val - 1) * 100
        close_premium = (lof_bid / rt_val - 1) * 100
        print(f"\n真实溢价率:")
        print(f"  开仓溢价率 (买LOF吃卖一): {open_premium:.3f}%")
        print(f"  平仓溢价率 (卖LOF吃买一): {close_premium:.3f}%")
    else:
        print(f"❌ 未获取到 {lof_code} 盘口数据")

    # 4. 验证历史数据
    print("\n" + "=" * 60)
    print("历史数据验证")
    print("=" * 60)

    conn = db._get_conn()
    cursor = conn.cursor()

    # 检查今天的数据
    cursor.execute("""
        SELECT date, time, fund_code, price, rt_val, premium,
               open_premium, close_premium, lof_bid1, lof_ask1, etf_bid1, etf_ask1
        FROM fund_intraday_quotes
        WHERE date = '2026-08-21' AND fund_code = '162411'
        ORDER BY time
        LIMIT 5
    """)
    rows = cursor.fetchall()
    print(f"\n今日 162411 数据（前5条）:")
    for row in rows:
        print(f"  {row[1]}: price={row[3]}, rt_val={row[4]}, prem={row[5]:.3f}%, "
              f"open={row[6]}, close={row[7]}, lof_bid={row[8]}, lof_ask={row[9]}")

    conn.close()
    reader.close()
    print("\n✅ 测试完成")

if __name__ == '__main__':
    main()
