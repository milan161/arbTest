import sqlite3

conn = sqlite3.connect('D:/Study/arbTest/ArbDashboard/frontend/src/layouts/MainLayout.vue')
cursor = conn.cursor()

# Read the file
with open('D:/Study/arbTest/ArbDashboard/frontend/src/layouts/MainLayout.vue', 'r', encoding='utf-8') as f:
    content = f.read()
    
# Find the line with .time-box-sidebar .time
lines = content.split('\n')
for i, line in enumerate(lines[175:185], start=176):
    print(f'{i}: {line}')
