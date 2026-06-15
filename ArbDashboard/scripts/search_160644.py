import sqlite3

conn = sqlite3.connect('D:/Study/arbTest/database/arb_master.db')
cursor = conn.cursor()

# 搜索所有包含160644的记录
cursor.execute("SELECT * FROM unified_fund_list WHERE fund_code = '160644' OR fund_name LIKE '%160644%' OR fund_name LIKE '%港美%' OR fund_name LIKE '%港股%'")
rows = cursor.fetchall()

print(f'找到 {len(rows)} 条记录:\n')
for row in rows:
    print(f'基金代码: {row[0]}')
    print(f'基金名称: {row[1]}')
    print(f'分类: {row[2]}')
    print(f'跟踪标的: {row[3]}')
    print('-' * 50)

conn.close()
