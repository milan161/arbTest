"""
基金估值方法映射表

前端 TAB 分类 (用户可见):
- 黄金原油: 商品期货/现货价格计算
- QDII欧美: 股票/指数标的 (包含原纯ETF、美股指数、混合跨境)
- QDII亚洲: 亚洲市场指数
- 国内LOF: LOF特有折溢价算法
- 白银: 上海期货交易所标的

内部估值方法分类 (程序使用):
- commodity: 商品型 (黄金原油、白银)
- equity_us: 欧美股票型 (美股指数、纯ETF)
- equity_jp: 日本股票型 (QDII日本)
- equity_asia: 亚洲股票型 (QDII亚洲)
- hybrid_cross: 混合跨境型
- lof: 国内LOF型
"""

# 基金代码到估值方法的映射
FUND_VALUATION_MAP = {
    # 商品型 - 黄金原油
    '162411': 'commodity_gold_oil',
    '162415': 'commodity_gold_oil',
    
    # 商品型 - 白银 (上海期货交易所)
    '161116': 'commodity_silver',
    
    # 欧美股票型 - 纯ETF
    '161126': 'equity_us_etf',
    '161127': 'equity_us_etf',
    '164906': 'equity_us_etf',
    
    # 欧美股票型 - 美股指数
    '161125': 'equity_us_index',
    '161130': 'equity_us_index',
    
    # 欧美股票型 - 混合跨境
    '160225': 'hybrid_cross',
    
    # 亚洲股票型 - QDII亚洲
    '161725': 'equity_asia',
    '161726': 'equity_asia',
    
    # 国内LOF型
    '501018': 'lof_domestic',
    '501025': 'lof_domestic',
    '501043': 'lof_domestic',
    '501050': 'lof_domestic',
    '501057': 'lof_domestic',
    '501058': 'lof_domestic',
    '501089': 'lof_domestic',
    '501225': 'lof_domestic',
    '501227': 'lof_domestic',
    '501300': 'lof_domestic',
    '501301': 'lof_domestic',
    '501302': 'lof_domestic',
    '501303': 'lof_domestic',
    '501305': 'lof_domestic',
    '501306': 'lof_domestic',
    '501307': 'lof_domestic',
    '501310': 'lof_domestic',
    '501311': 'lof_domestic',
    '501312': 'lof_domestic',
    
    # 日本股票型 - QDII日本
    '513000': 'equity_jp',
    '159866': 'equity_jp',
    '513520': 'equity_jp',
}

# 估值方法到前端 TAB 的映射
VALUATION_TO_TAB = {
    'commodity_gold_oil': '黄金原油',
    'commodity_silver': '白银',
    'equity_us_etf': 'QDII欧美',
    'equity_us_index': 'QDII欧美',
    'hybrid_cross': 'QDII欧美',
    'equity_jp': 'QDII日本',
    'equity_asia': 'QDII亚洲',
    'lof_domestic': '国内LOF',
}

# 估值方法到计算函数的映射
VALUATION_CALCULATOR_MAP = {
    'commodity_gold_oil': 'calculate_commodity_valuation',  # 商品期货/现货
    'commodity_silver': 'calculate_silver_valuation',       # 白银 (上期所)
    'equity_us_etf': 'calculate_etf_valuation',             # ETF标的
    'equity_us_index': 'calculate_index_valuation',         # 指数标的
    'hybrid_cross': 'calculate_basket_valuation',           # 一篮子资产
    'equity_asia': 'calculate_asia_valuation',           # 亚洲市场
    'equity_jp': 'calculate_asia_valuation',               # 日本市场（复用亚洲方法）
    'lof_domestic': 'calculate_lof_premium',                # LOF折溢价
}


def get_fund_valuation_method(fund_code: str) -> str:
    """获取基金的估值方法"""
    return FUND_VALUATION_MAP.get(fund_code, 'default')


def get_fund_tab(fund_code: str) -> str:
    """根据基金代码获取对应的前端 TAB"""
    method = get_fund_valuation_method(fund_code)
    return VALUATION_TO_TAB.get(method, 'QDII欧美')


def get_valuation_calculator(method: str) -> str:
    """获取估值方法对应的计算函数名"""
    return VALUATION_CALCULATOR_MAP.get(method, 'calculate_default_valuation')
