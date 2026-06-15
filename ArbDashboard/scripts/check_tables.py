import sqlite3

conn = sqlite3.connect('backend/core/database/arb_master.db')
cursor = conn.cursor()

# 查询所有表
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

print('数据库中的所有表:')
print('-' * 50)
for t in tables:
    print(t[0])
    # 查询每个表的记录数
    cursor.execute(f"SELECT COUNT(*) FROM {t[0]}")
    count = cursor.fetchone()[0]
    print(f'  记录数: {count}')

conn.close()
