import sqlite3

conn = sqlite3.connect('backend/core/database/arb_master.db')
cursor = conn.cursor()

# 查询unified_fund_list表的所有数据
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list LIMIT 20")
rows = cursor.fetchall()

print('unified_fund_list 表前20条数据:')
print('-' * 50)
for r in rows:
    print(f'{r[0]}\t{r[1]}')

print(f'\n总记录数:')
cursor.execute("SELECT COUNT(*) FROM unified_fund_list")
print(f'共 {cursor.fetchone()[0]} 条记录')

conn.close()
