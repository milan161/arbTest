import sqlite3

conn = sqlite3.connect(r'D:\Study\arbTest\database\arb_master.db')
cursor = conn.cursor()

# 查询unified_fund_list表的所有数据
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOF'")
rows = cursor.fetchall()

print(f'共找到 {len(rows)} 只基金名称包含LOF:')
print('-' * 50)
for r in rows:
    print(f'{r[0]}\t{r[1]}')

print('\n' + '=' * 50)
print('更新前总计:', len(rows))

# 执行更新：删除名称最后的LOF
cursor.execute("""
    UPDATE unified_fund_list 
    SET fund_name = REPLACE(fund_name, 'LOF', '') 
    WHERE fund_name LIKE '%LOF'
""")
conn.commit()

print(f'已更新 {cursor.rowcount} 条记录')

# 验证更新结果
cursor.execute("SELECT fund_code, fund_name FROM unified_fund_list WHERE fund_name LIKE '%LOF'")
remaining = cursor.fetchall()
print(f'更新后剩余: {len(remaining)} 只')

conn.close()
print('\n[OK] 更新完成！')
