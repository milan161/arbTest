import sqlite3

conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
cursor = conn.cursor()

# 搜索所有名称包含LOF的记录
cursor.execute("SELECT fund_code, fund_name, category FROM unified_fund_list WHERE fund_name LIKE '%LOF%'")
rows = cursor.fetchall()

print(f'找到 {len(rows)} 条记录包含LOF:\n')
for row in rows:
    print(f'{row[0]}\t{row[1]}\t({row[2]})')

conn.close()
