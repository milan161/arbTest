import sqlite3

conn = sqlite3.connect('backend/core/database/arb_master.db')
cursor = conn.cursor()

# 查询所有名称包含LOF的基金
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOF'")
rows = cursor.fetchall()

print(f'共找到 {len(rows)} 只基金名称包含LOF:')
print('-' * 50)
for r in rows:
    print(f'{r[0]}\t{r[1]}')

conn.close()
