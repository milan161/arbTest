import os
import pandas as pd

def clean_history_files():
    """清理LOF历史文件中错误增加的列"""
    data_dir = os.path.join(os.path.dirname(__file__), 'data')
    
    # 找出所有LOF历史文件
    lof_files = [f for f in os.listdir(data_dir) if f.startswith('LOF_') and f.endswith('_history.csv')]
    
    for file in lof_files:
        file_path = os.path.join(data_dir, file)
        print(f"清理文件: {file}")
        
        try:
            # 读取文件
            df = pd.read_csv(file_path, encoding='utf-8-sig')
            
            # 找出需要保留的列
            required_columns = ['日期', '人民币中间价', '仓位', '收盘价', '净值', '变化比例', 
                              'ETF静态估值', 'ETF静态估值误差', 'ETF静态溢价']
            
            # 保留原始列
            original_columns = [col for col in df.columns if col not in ['黄金校准', '原油校准', 
                                                                      '162411校准', '162411对冲', 
                                                                      '161127校准', '161127对冲', 
                                                                      '161125校准', '161125对冲', 
                                                                      '161130校准', '161130对冲',
                                                                      '校准', '对冲']]
            
            # 重新保存文件
            df = df[original_columns]
            df.to_csv(file_path, index=False, encoding='utf-8-sig')
            print(f"  已清理: {file}")
            
        except Exception as e:
            print(f"  清理文件 {file} 时出错: {e}")

if __name__ == "__main__":
    clean_history_files()
    print("清理完成！")
