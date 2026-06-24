# -*- coding: utf-8 -*-
# 清空特定日期的估值数据，以触发 012 程序的重新计算

import os
import glob
import pandas as pd

def clear_valuations():
    data_dir = r"D:\Study\codexTest\CodexLOFarb\data"
    lof_files = glob.glob(os.path.join(data_dir, "LOF_*_history.csv"))
    
    # 锁定需要重新计算的区间
    start_date = '2026-04-01'
    end_date = '2026-04-09'
    
    # 需要清空的所有静态估值与溢价字段
    val_cols = [
        '变化比例', 'ETF静态估值', 'ETF静态估值误差', 'ETF静态溢价',
        '指数静态估值', '指数静态估值误差',
        '期货静态估值', '期货静态估值误差', '期货静态估值溢价'
    ]
    
    for filepath in lof_files:
        try:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
            if '日期' not in df.columns:
                continue
                
            df['日期'] = pd.to_datetime(df['日期']).dt.strftime('%Y-%m-%d')
            # 找到 4-1 到 4-9 之间的行
            mask = (df['日期'] >= start_date) & (df['日期'] <= end_date)
            
            cleared = False
            for col in val_cols:
                if col in df.columns:
                    df.loc[mask, col] = pd.NA
                    cleared = True
                    
            if cleared:
                df.to_csv(filepath, index=False, encoding='utf-8-sig')
                print(f"  [OK] 已成功清空旧估值: {os.path.basename(filepath)}")
                
        except PermissionError:
            print(f"  [ERROR] 文件被占用，请先关闭 Excel: {os.path.basename(filepath)}")
        except Exception as e:
            print(f"  [ERROR] 处理 {os.path.basename(filepath)} 时出错: {e}")

if __name__ == "__main__":
    print("开始清空 4-1 至 4-9 之间的已有静态估值，以便 012 重新计算...")
    clear_valuations()
    print("清空完成！")
