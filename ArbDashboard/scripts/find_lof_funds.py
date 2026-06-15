import sqlite3

conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
cursor = conn.cursor()

# 查询所有名称包含LOF的记录
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOF%'")
rows = cursor.fetchall()

print(f'共找到 {len(rows)} 只基金名称包含LOF:')
print('-' * 50)
for r in rows:
    print(f'{r[0]}\t{r[1]}')

# 查询名称以LOF结尾的记录
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOF'")
rows_end = cursor.fetchall()
print(f'\n名称以LOF结尾的基金: {len(rows_end)} 只')
print('-' * 50)
for r in rows_end:
    print(f'{r[0]}\t{r[1]}')

conn.close()
