"""
穿透分析服务 - 从季报持仓 + yaml规则计算期货合约分布
"""
import sqlite3
import yaml
import os
from typing import Dict, List, Any
from collections import defaultdict

# 路径配置：从 services/ 往上5层到项目根，再到 database/
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(BACKEND_DIR))))
DB_PATH = os.path.join(PROJECT_ROOT, "database", "arb_master.db")
YAML_PATH = os.path.join(PROJECT_ROOT, "src", "arbcore", "config", "lof_config.yaml")


def get_fund_holdings(fund_code: str, period: str) -> List[Dict[str, Any]]:
    """从DB读取指定基金的季报持仓"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute(
        "SELECT symbol, weight FROM fund_report_holdings WHERE fund_code=? AND report_period=?",
        (fund_code, period)
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    
    # 按权重降序排列
    return sorted(rows, key=lambda x: x['weight'], reverse=True)


def load_penetration_rules() -> Dict[str, Any]:
    """从yaml加载穿透规则"""
    with open(YAML_PATH, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)
    return cfg.get('penetration_rules', {})


def calculate_penetration(fund_code: str, period: str) -> Dict[str, Any]:
    """
    计算穿透分析结果
    
    Returns:
        {
            'holdings': [...],  # 季报持仓列表
            'penetrated': [...],  # 穿透后的期货合约列表
            'summary': {...},  # 汇总数据
            'metadata': {...}  # 元数据
        }
    """
    # 读取季报持仓
    holdings = get_fund_holdings(fund_code, period)
    if not holdings:
        return {'error': f'未找到 {fund_code} {period} 的持仓数据'}
    
    # 加载穿透规则
    rules = load_penetration_rules()
    
    # 计算归一化权重
    total_weight = sum(h['weight'] for h in holdings)
    for h in holdings:
        h['normalized_weight'] = h['weight'] / total_weight if total_weight > 0 else 0
    
    # 品种映射
    variety_map = {
        'CRUD': 'WTI', 'USO': 'WTI', 'OILK': 'WTI',
        'BNO': 'Brent', 'BRNT': 'Brent', 'BRNG': 'Brent'
    }
    
    # 穿透计算
    penetrated = []
    for h in holdings:
        sym = h['symbol']
        if sym not in rules:
            continue
        
        rule = rules[sym]
        etf_ratio = rule.get('期货占比', 0) or rule.get('Swaps占比', 0)
        contracts = rule.get('期货合约', [])
        variety = variety_map.get(sym, '')
        
        for c in contracts:
            penetrated.append({
                'product': sym,
                'quarter_weight': round(h['weight'] * 100, 2),
                'normalized_weight': round(h['normalized_weight'] * 100, 2),
                'etf_ratio': round(etf_ratio, 4),
                'contract_code': c.get('代码', ''),
                'contract_name': c.get('名称', ''),
                'contract_pct': round(c.get('比例', 0) * 100, 2),
                'final_pct': round(etf_ratio * c.get('比例', 0) * h['normalized_weight'] * 100, 4),
                'variety': variety
            })
    
    # 汇总
    summary = {
        'total_quarter': round(total_weight * 100, 2),
        'by_variety': {}
    }
    
    variety_totals = defaultdict(float)
    for p in penetrated:
        variety_totals[p['variety']] += p['final_pct']
    
    summary['by_variety'] = dict(variety_totals)
    summary['total_penetrated'] = round(sum(variety_totals.values()), 2)
    
    # 按合约年月聚合
    month_agg = defaultdict(lambda: {'total': 0, 'variety': ''})
    for p in penetrated:
        month = p['contract_code']
        month_agg[month]['total'] += p['final_pct']
        month_agg[month]['variety'] = p['variety']
    
    summary['by_month'] = dict(month_agg)
    
    return {
        'fund_code': fund_code,
        'period': period,
        'holdings': holdings,
        'penetrated': penetrated,
        'summary': summary,
        'metadata': {
            'calc_time': '2026-09-05',
            'data_source': 'ETF官网 + Bloomberg指数方法论'
        }
    }


if __name__ == '__main__':
    # 测试运行
    result = calculate_penetration('160723', '2026Q2')
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
