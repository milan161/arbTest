import os
import pandas as pd

def clean_calibration_columns():
    """清理LOF历史文件中所有校准相关列"""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    # 找出所有LOF历史文件
    lof_files = [f for f in os.listdir(data_dir) if f.startswith('LOF_') and f.endswith('_history.csv')]
    
    for file in lof_files:
        file_path = os.path.join(data_dir, file)
        print(f"清理文件: {file}")
        
        try:
            # 读取文件
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            
            # 找出需要删除的校准相关列
            # 包括所有包含校准、对冲的列，不管有没有后缀
            cols_to_drop = []
            for col in df.columns:
                if '校准' in col or '对冲' in col:
                    cols_to_drop.append(col)
            
            # 删除校准相关列
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
                print(f"  已删除列: {', '.join(cols_to_drop)}")
            else:
                print(f"  无校准列需要删除")
            
            # 重新保存文件
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            print(f"  已清理: {file}")
            
        except Exception as e:
            print(f"  清理文件 {file} 时出错: {e}")

if __name__ == "__main__":
    clean_calibration_columns()
    print("清理完成！")
