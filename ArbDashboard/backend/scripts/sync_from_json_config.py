"""
从统一基金分类配置文件 (fund_categories.json) 同步到数据库
支持程序1/2/3共享配置
"""
import json
import os
import sys

# 添加路径
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(backend_dir)

# arbcore 路径
arbcore_config_dir = os.path.abspath(os.path.join(backend_dir, '..', '..', 'arbcore', 'config'))
if not os.path.exists(arbcore_config_dir):
    arbcore_config_dir = os.path.join(os.path.dirname(__file__), '..', 'core', 'arbcore', 'config')

# 数据库路径
root_db_path = os.path.abspath(os.path.join(backend_dir, '..', '..', 'database', 'arb_master.db'))

def sync_json_to_db():
    """从 JSON 配置同步到数据库"""
    json_path = os.path.join(arbcore_config_dir, 'fund_categories.json')
    
    if not os.path.exists(json_path):
        print(f"错误: 配置文件不存在: {json_path}")
        return
    
    # 读取 JSON 配置
    with open(json_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # 构建基金列表
    fund_list = []
    categories = config.get('categories', {})
    
    for cat_name, cat_data in categories.items():
        funds = cat_data.get('funds', [])
        for fund in funds:
            fund_list.append({
                'category': fund.get('category', cat_name),
                'code': str(fund.get('code')),
                'name': fund.get('name'),
                'related_index': fund.get('trade_etf', '-'),
                'target_type': fund.get('target_type', 'ETF')  # 默认ETF，指数基金标记为INDEX
            })
    
    print(f"从 JSON 读取到 {len(fund_list)} 只基金")
    
    # 导入数据库管理器
    sys.path.insert(0, os.path.join(backend_dir, '..', '..', 'arbcore'))
    from database.db_manager import DatabaseManager
    
    # 同步到数据库
    db = DatabaseManager(db_path=root_db_path)
    db.sync_unified_fund_list(fund_list)
    
    print(f"成功同步 {len(fund_list)} 只基金到 unified_fund_list 表")
    
    # 打印分类统计
    print("\n分类统计:")
    for cat_name, cat_data in categories.items():
        fund_count = len(cat_data.get('funds', []))
        print(f"  {cat_name}: {fund_count} 只")


if __name__ == "__main__":
    sync_json_to_db()
