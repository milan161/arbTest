# -*- coding: utf-8 -*-
# 修复受时差映射污染的 ETF 历史数据

import os
import glob
import pandas as pd

def fix_etf_data():
    data_dir = r"D:\Study\codexTest\CodexLOFarb\data"
    correct_file = os.path.join(data_dir, "GLDUSO_0409.csv")
    basic_file = os.path.join(data_dir, "GLD_USO_basic_data.csv")
    lof_files = glob.glob(os.path.join(data_dir, "LOF_*_history.csv"))
    
    # 严格锁定的修复范围
    start_date = '2026-04-01'
    end_date = '2026-04-09'
    
    # 受污染的 7 个目标列（含变种前缀）
    target_cols = ['GLD', '^GLD-EU', '^GLD-JP', 'USO', '^USO-EU', '^USO-JP', '^USO-HK']
    
    if not os.path.exists(correct_file):
        print(f"❌ 找不到正确数据文件: {correct_file}")
        return
        
    correct_df = pd.read_csv(correct_file)
    if '日期' not in correct_df.columns:
        print("❌ 正确数据文件中没有 '日期' 列！")
        return
        
    correct_df['日期'] = pd.to_datetime(correct_df['日期']).dt.strftime('%Y-%m-%d')
    correct_df.set_index('日期', inplace=True)
    
    files_to_fix = [basic_file] + lof_files
    
    for filepath in files_to_fix:
        if not os.path.exists(filepath):
            continue
            
        print(f"正在处理: {os.path.basename(filepath)}")
        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
            if '日期' not in df.columns:
                continue
                
            df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
            
            # 步骤 1: 将指定日期区间的这 7 列清零/设为空
            mask = (df['日期'] >= start_date) & (df['日期'] <= end_date)
            for col in target_cols:
                if col in df.columns:
                    df.loc[mask, col] = pd.NA
                    
            # 步骤 2: 从正确的临时表中读取数据并精准填充
            for date in df.loc[mask, '日期']:
                if date in correct_df.index:
                    for col in target_cols:
                        # 兼容带有 '^' 或没有 '^' 的临时表列名
                        alt_col = col.replace('^', '')
                        src_col = col if col in correct_df.columns else (alt_col if alt_col in correct_df.columns else None)
                        
                        if src_col and col in df.columns:
                            val = correct_df.loc[date, src_col]
                            if pd.notna(val):
                                df.loc[df['日期'] == date, col] = float(val)
            
            # 保存修复后的文件
            df.to_csv(filepath, index=False, encoding='utf-8-sig')
            print(f"  [OK] 已成功清洗并修复: {os.path.basename(filepath)}")
            
        except PermissionError:
            print(f"  [ERROR] 文件被占用，请先关闭 Excel: {os.path.basename(filepath)}")
        except Exception as e:
            print(f"  [ERROR] 处理 {os.path.basename(filepath)} 时出错: {e}")

if __name__ == "__main__":
    print("开始执行 4-1 至 4-9 ETF 错位数据定点清洗...")
    fix_etf_data()
    print("修复完成！")