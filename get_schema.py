import sqlite3
import os
import sys

def get_schema(db_path, table):
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'")
        row = cursor.fetchone()
        if row:
            print(f"Schema for {table}:")
            print(row[0])
        else:
            # Check if it's a view
            cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='view' AND name='{table}'")
            row = cursor.fetchone()
            if row:
                print(f"Schema for VIEW {table}:")
                print(row[0])
            else:
                print(f"Table/View {table} not found")
        conn.close()
    else:
        print(f"{db_path} not found")

if __name__ == "__main__":
    if len(sys.argv) > 2:
        get_schema(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python get_schema.py <db_path> <table>")
