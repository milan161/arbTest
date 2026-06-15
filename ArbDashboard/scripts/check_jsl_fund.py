import sqlite3

conn = sqlite3.connect('backend/core/database/arb_master.db')
cursor = conn.cursor()

# 查询jsl_fund_list表的所有数据
cursor.execute("SELECT * FROM jsl_fund_list")
rows = cursor.fetchall()

# 获取列名
columns = [description[0] for description in cursor.description]
print('jsl_fund_list 表的列名:')
print(columns)
print('-' * 50)
print(f'共 {len(rows)} 条记录:')
print('-' * 50)
for r in rows[:20]:  # 只显示前20条
    print(dict(zip(columns, r)))

conn.close()
