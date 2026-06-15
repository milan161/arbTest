import sqlite3
import sys

db_path = r'D:\Study\arbTest\database\arb_master.db'

print("=" * 60)
print("数据库测试：arb_master.db")
print("=" * 60)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. 检查表列表
    print("\n【1】数据库表列表：")
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    for table in tables:
        print(f"  - {table[0]}")
    
    # 2. 检查 unified_fund_history 表结构
    print("\n【2】unified_fund_history 表结构：")
    cursor.execute("PRAGMA table_info(unified_fund_history)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    # 3. 检查 unified_fund_list 表结构
    print("\n【3】unified_fund_list 表结构：")
    cursor.execute("PRAGMA table_info(unified_fund_list)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    # 4. 检查数据量
    print("\n【4】数据量统计：")
    cursor.execute("SELECT COUNT(*) FROM unified_fund_list")
    print(f"  unified_fund_list: {cursor.fetchone()[0]} 条记录")
    
    cursor.execute("SELECT COUNT(*) FROM unified_fund_history")
    print(f"  unified_fund_history: {cursor.fetchone()[0]} 条记录")
    
    cursor.execute("SELECT COUNT(*) FROM exchange_rate")
    print(f"  exchange_rate: {cursor.fetchone()[0]} 条记录")
    
    # 5. 检查关键字段是否存在
    print("\n【5】关键字段检查：")
    required_fields = ['static_val', 'premium', 'valuation_error', 'premium_error']
    cursor.execute("PRAGMA table_info(unified_fund_history)")
    existing_fields = [col[1] for col in cursor.fetchall()]
    
    for field in required_fields:
        status = "✓ 存在" if field in existing_fields else "✗ 缺失"
        print(f"  {field}: {status}")
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
    
    conn.close()
    
except Exception as e:
    print(f"\n错误: {e}")
    sys.exit(1)
