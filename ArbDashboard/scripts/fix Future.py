import pandas as pd
import os

basic_path = 'data/GLD_USO_basic_data.csv'
df = pd.read_csv(basic_path)
print("修复前 4-10 和 4-9 的期货数据：")
print(df[['日期', 'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle']].head(2))

# 找出期货相关的列
cols_to_shift = ['GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle', '.INX', '.NDX']

# 将这些列的数据向上移动一行（即将4-10的数据移给4-9）
for col in cols_to_shift:
    if col in df.columns:
        df[col] = df[col].shift(-1)

print("\n修复后 4-10 和 4-9 的期货数据：")
print(df[['日期', 'GC_settle', 'CL_settle', 'NQ_settle', 'ES_settle']].head(2))

df.to_csv(basic_path, index=False, encoding='utf-8-sig')
print(f"\n修复完成！已保存至 {basic_path}")
