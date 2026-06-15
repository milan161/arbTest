import sqlite3

conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
cursor = conn.cursor()

# 查询unified_fund_list表的所有数据
cursor.execute("SELECT * FROM unified_fund_list")
rows = cursor.fetchall()

# 获取列名
columns = [description[0] for description in cursor.description]
print('unified_fund_list 表的列名:')
print(columns)
print('-' * 50)
print(f'共 {len(rows)} 条记录')
print('-' * 50)

# 显示前30条记录
for r in rows[:30]:
    print(dict(zip(columns, r)))

conn.close()
