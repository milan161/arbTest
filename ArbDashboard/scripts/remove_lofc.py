import sqlite3

conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
cursor = conn.cursor()

# 查看更新前的数据
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOFC%'")
before_rows = cursor.fetchall()
print('更新前:')
for row in before_rows:
    print(f'  {row[0]}\t{row[1]}')

# 执行更新：删除"LOFC"
cursor.execute("UPDATE unified_fund_list SET fund_name = REPLACE(fund_name, 'LOFC', '') WHERE fund_name LIKE '%LOFC%'")
conn.commit()

affected = cursor.rowcount
print(f'\n[OK] 更新了 {affected} 条记录')

# 查看更新后的数据
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_code IN ('501058', '501306')")
after_rows = cursor.fetchall()
print('\n更新后:')
for row in after_rows:
    print(f'  {row[0]}\t{row[1]}')

conn.close()
