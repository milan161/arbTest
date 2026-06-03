import os
import re

file_path = "jsl/00_web_server.py"
with open(file_path, "r", encoding="utf-8-sig") as f:
    content = f.read()

# I will use a robust regular expression to find the start of load_jsl_data and inject the mapping.
pattern = r"    try:\s*df_funds = pd\.read_csv\(csv_file, dtype=str\)\s*except:\s*return \{\}"

new_code = """    try:
        df_funds = pd.read_csv(csv_file, dtype=str)
        col_map = {
            '代码': 'code', '基金代码': 'code',
            '名称': 'name', '基金名称': 'name',
            '分类': 'category', '类别': 'category',
            '指数代码': 'idx_code', '相关指数代码': 'idx_code',
            '仓位': 'pos_ratio', '仓位比例': 'pos_ratio'
        }
        df_funds.rename(columns={k:v for k,v in col_map.items() if k in df_funds.columns}, inplace=True)
    except:
        return {}"""

content = re.sub(pattern, new_code, content)

# I also need to make sure the physical sync is called.
# It seems the previous replace also missed the _sync_complex_funds_from_master call
sync_call_pattern = r"        _ensure_quotes_table\(conn\)\n\n        for _, row in df_funds\.iterrows\(\):"
sync_call_code = """        _ensure_quotes_table(conn)
        
        # 物理同步
        if 'category' in df_funds.columns and 'code' in df_funds.columns:
            complex_df = df_funds[df_funds['category'].isin(['黄金原油', '混合跨境'])]
            complex_codes = complex_df['code'].tolist()
            if 'idx_code' in complex_df.columns:
                index_map = complex_df.set_index('code')['idx_code'].to_dict()
            else:
                index_map = {}
            if complex_codes: _sync_complex_funds_from_master(conn, complex_codes, index_map)

        for _, row in df_funds.iterrows():"""

content = re.sub(sync_call_pattern, sync_call_code, content)

with open(file_path, "w", encoding="utf-8-sig") as f:
    f.write(content)

print("SUCCESS: Injected CSV column mapping and physical sync call.")
