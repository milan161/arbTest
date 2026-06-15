import sqlite3

conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
cursor = conn.cursor()

# 查看表结构
cursor.execute("PRAGMA table_info(unified_fund_list)")
columns = cursor.fetchall()
print("表结构:")
for col in columns:
    print(f'  {col}')

print("\n" + "="*50 + "\n")

# 查询前5条记录
cursor.execute("SELECT * FROM unified_fund_list LIMIT 5")
rows = cursor.fetchall()
print("前5条记录:")
for row in rows:
    print(row)

conn.close()
