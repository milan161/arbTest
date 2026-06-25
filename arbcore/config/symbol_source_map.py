# -*- coding: utf-8 -*-
"""
symbol_source_map.py - 标的代码与数据源映射配置

核心设计原则：
1. 所有标的的数据源固定写在映射表中，不需要每次询问
2. 美股ETF支持双数据源：IB（主）+ 富途（备），无IB账户用户可用富途
3. A股支持多数据源：TDX（主）+ 银河QMT（备1）+ 国金QMT（备2）
4. 数据源选择逻辑在 dynamic_valuation.py 或 fund_service.py 中根据用户配置切换

数据源类型：
- IB: Interactive Brokers（美股实时价格，主数据源）
- FUTU: 富途（港股/美股，备用数据源，无IB账户用户可用）
- TDX: 通达信/新浪（A股/期货/指数，主数据源）
- QMT_YH: 银河QMT（A股/期货，备用数据源1）
- QMT_GJ: 国金QMT（A股/期货，备用数据源2）
- WOODY: Woody数据源（QDII估值）
- SINA: 新浪财经（A股/指数）

美股ETF双数据源说明：
- 默认从 IB 获取实时价格（IBReader）
- 无 IB 账户用户可配置从富途获取（FutuReader）
- 数据源选择逻辑：
  if user_config.get('use_ib', True):
      source = 'IB'
  else:
      source = 'FUTU'  # 美股用富途替代

A股多数据源说明：
- 默认从 TDX 获取实时价格（TDXFetcher）
- TDX不可用时可切换到银河QMT或国金QMT
- 数据源选择逻辑：
  if user_config.get('qmt_type') == 'YH':
      source = 'QMT_YH'  # 银河QMT
  elif user_config.get('qmt_type') == 'GJ':
      source = 'QMT_GJ'  # 国金QMT
  else:
      source = 'TDX'  # 默认通达信
- 以下所有美股ETF都可以从富途读取，只需在配置中切换即可
"""

# ============================================================
# 核心映射表：标的代码 → 数据源
# ============================================================

# 美股 ETF 映射表（支持 IB 和 富途 双数据源）
US_ETF_MAP = {
    # 宽基指数 ETF（IB/富途均可）
    'SPY': 'IB',      # 标普500（IB/富途均可）
    'QQQ': 'IB',      # 纳斯达克100（IB/富途均可）
    'IWM': 'IB',      # 罗素2000（IB/富途均可）
    'DIA': 'IB',      # 道琼斯（IB/富途均可）
    
    # 行业/主题 ETF（IB/富途均可）
    'XLK': 'IB',      # 科技（IB/富途均可）
    'XLF': 'IB',      # 金融（IB/富途均可）
    'XLE': 'IB',      # 能源（IB/富途均可）
    'XLV': 'IB',      # 医疗（IB/富途均可）
    'XLI': 'IB',      # 工业（IB/富途均可）
    'XLP': 'IB',      # 消费必需品（IB/富途均可）
    'XLY': 'IB',      # 可选消费（IB/富途均可）
    'XLU': 'IB',      # 公用事业（IB/富途均可）
    'XLRE': 'IB',     # 房地产（IB/富途均可）
    'XLB': 'IB',      # 材料（IB/富途均可）
    
    # 半导体/科技（IB/富途均可）
    'SOXX': 'IB',     # 半导体ETF（IB/富途均可）
    'SMH': 'IB',      # 半导体ETF（IB/富途均可）
    'ARKK': 'IB',     # 颠覆性创新（IB/富途均可）
    'ARKG': 'IB',     # 基因重组（IB/富途均可）
    'ARKQ': 'IB',     # 自动化/机器人（IB/富途均可）
    'AIQ': 'IB',      # 人工智能（IB/富途均可）
    'BOTZ': 'IB',     # 机器人/自动化（IB/富途均可）
    'FINX': 'IB',     # 金融科技（IB/富途均可）
    
    # 黄金/贵金属（IB/富途均可）
    'GLD': 'IB',      # 黄金ETF（IB/富途均可）
    'SLV': 'IB',      # 白银ETF（IB/富途均可）
    'IAU': 'IB',      # 黄金ETF（IB/富途均可）
    'GDX': 'IB',      # 黄金矿业（IB/富途均可）
    'GDXJ': 'IB',     # 中小黄金矿业（IB/富途均可）
    
    # 原油/能源（IB/富途均可）
    'USO': 'IB',      # 原油ETF（IB/富途均可）
    'XOP': 'IB',      # 油气开采（IB/富途均可）
    'OIL': 'IB',      # 原油（IB/富途均可）
    'BNO': 'IB',      # 布伦特原油（IB/富途均可）
    
    # 大宗商品/资源（IB/富途均可）
    'CPER': 'IB',     # 大宗商品（IB/富途均可）
    'DBC': 'IB',      # 大宗商品（IB/富途均可）
    'PDBC': 'IB',     # 大宗商品（IB/富途均可）
    
    # 国际/区域（IB/富途均可）
    'EWA': 'IB',      # 澳大利亚（IB/富途均可）
    'EWC': 'IB',      # 加拿大（IB/富途均可）
    'EWJ': 'IB',      # 日本（IB/富途均可）
    'EWZ': 'IB',      # 巴西（IB/富途均可）
    'EWY': 'IB',      # 墨西哥（IB/富途均可）
    'EWH': 'IB',      # 香港（IB/富途均可）
    'EWI': 'IB',      # 意大利（IB/富途均可）
    'EWG': 'IB',      # 德国（IB/富途均可）
    'EWU': 'IB',      # 英国（IB/富途均可）
    'FXI': 'IB',      # 中证500（港股）（IB/富途均可）
    'MCHI': 'IB',     # 中国（IB/富途均可）
    'KWEB': 'IB',     # 中概互联（IB/富途均可）
    'INDA': 'IB',     # 印度（IB/富途均可）
    
    # 其他（IB/富途均可）
    'VIX': 'IB',      # 恐慌指数（IB/富途均可）
}

# A 股 ETF 映射表（从通达信/新浪获取）
CN_ETF_MAP = {
    # 宽基指数
    '510050': 'TDX',  # 上证50
    '510300': 'TDX',  # 沪深300
    '510500': 'TDX',  # 中证500
    '159919': 'TDX',  # 沪深300
    '510100': 'TDX',  # 上证180
    '510310': 'TDX',  # 沪深300增强
    
    # 行业/主题
    '515000': 'TDX',  # 中证医疗
    '515880': 'TDX',  # 新能源车
    '516160': 'TDX',  # 新能源车
    '516150': 'TDX',  # 新能源
    '515790': 'TDX',  # 新能源ETF
    '516110': 'TDX',  # 稀土
    '516180': 'TDX',  # 光伏
    '516400': 'TDX',  # 钢铁
    '516580': 'TDX',  # 化工
    '516950': 'TDX',  # 煤炭
    '159985': 'TDX',  # 中小板
    '159560': 'TDX',  # 芯片
    
    # 债券
    '127001': 'TDX',  # 国债
    '127003': 'TDX',  # 国债
    
    # 其他
    '513100': 'TDX',  # 纳指ETF（境内）
    '513500': 'TDX',  # 标普500（境内）
    '510900': 'TDX',  # 创业板
    '159915': 'TDX',  # 创业板
}

# 港股映射表（从富途/通达信获取）
HK_STOCK_MAP = {
    '00700': 'FUTU',   # 腾讯
    '09988': 'FUTU',   # 阿里巴巴
    '01810': 'FUTU',   # 小米
    '09618': 'FUTU',   # 京东
    '00941': 'FUTU',   # 中国移动
    '01398': 'FUTU',   # 工商银行
    '02318': 'FUTU',   # 中国平安
    '00883': 'FUTU',   # 中国海洋石油
}

# [V7.2] 混合基金成分股（美股）强制走富途分流
# 减轻 IB 负担，IB 仅处理核心套利标的 (GLD, USO, XOP, SLV, INDA, QQQ, SPY)
US_STOCK_FUTU_MAP = {
    'TSM': 'FUTU',    # 台积电
    'NVDA': 'FUTU',   # 英伟达
    'SNDK': 'FUTU',   # 闪迪
    'MU': 'FUTU',     # 美光科技
    'GOOGL': 'FUTU',  # 谷歌
    'AVGO': 'FUTU',   # 博通
    'ASML': 'FUTU',   # 阿斯麦
    'AAPL': 'FUTU',   # 苹果
    'MSFT': 'FUTU',   # 微软
    'AMZN': 'FUTU',   # 亚马逊
    'META': 'FUTU',   # Meta
    'TSLA': 'FUTU',   # 特斯拉
}

# ============================================================
# IB 核心套利标的白名单（默认 7 只）
# ============================================================
# 只有在这个列表中的美股 ETF 才会走 IB 数据源
# 其余美股 ETF 自动走 FUTU（富途）或放弃
IB_CORE_ARBITRAGE_SYMBOLS = ['XOP', 'GLD', 'USO', 'SLV', 'INDA', 'QQQ', 'SPY']

# 期货映射表（从通达信获取）
FUTURES_MAP = {
    # 上期所
    'CU': 'TDX',  # 铜
    'AL': 'TDX',  # 铝
    'ZN': 'TDX',  # 锌
    'PB': 'TDX',  # 铅
    'NI': 'TDX',  # 镍
    'AU': 'TDX',  # 黄金
    'AG': 'TDX',  # 白银
    'SI': 'TDX',  # 白银
    'RB': 'TDX',  # 螺纹钢
    'HC': 'TDX',  # 热卷
    
    # 大商所
    'I': 'TDX',   # 铁矿石
    'J': 'TDX',   # 焦炭
    'JM': 'TDX',  # 焦煤
    'PP': 'TDX',  # 聚丙烯
    'EG': 'TDX',  # 乙二醇
    'L': 'TDX',   # 塑料
    'V': 'TDX',   # PVC
    'D': 'TDX',   # 豆油
    'B': 'TDX',   # 豆粕
    'Y': 'TDX',   # 棕榈油
    'C': 'TDX',   # 玉米
    'CS': 'TDX',  # 玉米淀粉
    
    # 郑商所
    'TA': 'TDX',  # PTA
    'MA': 'TDX',  # 甲醇
    'CF': 'TDX',  # 棉花
    'SR': 'TDX',  # 白糖
    'OI': 'TDX',  # 菜油
    'FG': 'TDX',  # 玻璃
    'SA': 'TDX',  # 纯碱
    
    # 能源/中金所
    'SC': 'TDX',  # 原油
    'RU': 'TDX',  # 橡胶
    'NR': 'TDX',  # 20号胶
    'PG': 'TDX',  # 液化气
    
    # 股指期货
    'IF': 'TDX',  # 沪深300
    'IC': 'TDX',  # 中证500
    'IH': 'TDX',  # 上证50
    'IM': 'TDX',  # 中证1000
    
    # 国际期货（新浪延时数据兜底）
    'GC': 'SINA',  # COMEX黄金
    'CL': 'SINA',  # 纽约原油
    'HG': 'SINA',  # COMEX铜
    'SI': 'SINA',  # COMEX白银
}

# 指数映射表（从新浪获取）
INDEX_MAP = {
    '.INX': 'SINA',   # 标普500指数
    '.NDX': 'SINA',   # 纳斯达克100
    '.DJI': 'SINA',   # 道琼斯
    '.IXIC': 'SINA',  # 纳斯达克综合
    '.HSI': 'SINA',   # 恒生指数（带.前缀）
    'HSI': 'SINA',    # 恒生指数（基金related_index存的格式，无.前缀）
    'HSTECH': 'SINA', # 恒生科技指数
    'HSCEI': 'SINA',  # 恒生中国企业指数
    'CES300.HI': 'SINA', # 恒生沪深300指数（数据库存储格式，新浪用rt_hkCES300）
    '.SSEC': 'SINA',  # 上证指数
    '.SZSC': 'SINA',  # 深证成指
    '.CSI300': 'SINA',  # 沪深300
    '.SH000300': 'SINA',  # 沪深300
}

# Woody 数据源映射表（特定市场收盘时刻的虚拟符号）
# 格式：^代码-区域 = 该 ETF 在区域市场收盘时刻的价格
# 重要规则：所有 ^前缀 + EU/JP/HK 后缀的符号，只能从 Woody API 获取数据
# - EU: 欧洲交易所（European Exchange）
# - JP: 日本交易所（Japan Exchange）
# - HK: 香港交易所（Hong Kong Exchange）
WOODY_MAP = {
    # 原油指数（欧洲/日本/香港交易所收盘时刻）
    '^USO-EU': 'WOODY',  # 原油在欧洲交易所收盘时刻的价格
    '^USO-JP': 'WOODY',  # 原油在日本交易所收盘时刻的价格
    '^USO-HK': 'WOODY',  # 原油在香港交易所收盘时刻的价格
    # 印度指数（欧洲/日本/香港交易所收盘时刻）
    '^INDA-EU': 'WOODY',  # 印度 ETF 在欧洲交易所收盘时刻的价格
    '^INDA-HK': 'WOODY',  # 印度 ETF 在香港交易所收盘时刻的价格
    '^INDA-JP': 'WOODY',  # 印度 ETF 在日本交易所收盘时刻的价格
}

# ============================================================
# 自动合并映射表
# ============================================================

# 全局映射表：标的代码 → 数据源
SYMBOL_SOURCE_MAP = {}
SYMBOL_SOURCE_MAP.update(US_ETF_MAP)
SYMBOL_SOURCE_MAP.update(CN_ETF_MAP)
SYMBOL_SOURCE_MAP.update(HK_STOCK_MAP)
SYMBOL_SOURCE_MAP.update(US_STOCK_FUTU_MAP) # 添加富途美股专属分流
SYMBOL_SOURCE_MAP.update(FUTURES_MAP)
SYMBOL_SOURCE_MAP.update(INDEX_MAP)
SYMBOL_SOURCE_MAP.update(WOODY_MAP)  # 添加 Woody 映射表

# 反向映射：数据源 → 标的列表
SOURCE_SYMBOL_MAP = {
    'IB': [],
    'IB_CORE_ONLY': list(IB_CORE_ARBITRAGE_SYMBOLS),  # 核心套利标的白名单
    'FUTU': [],
    'TDX': [],
    'QMT_YH': [],  # 银河QMT（A股备用）
    'QMT_GJ': [],  # 国金QMT（A股备用）
    'SINA': [],
    'WOODY': [],
}

# IB 只包含核心套利标的白名单，其余美股 ETF 走 FUTU
SOURCE_SYMBOL_MAP['IB'] = list(IB_CORE_ARBITRAGE_SYMBOLS)

for symbol, source in SYMBOL_SOURCE_MAP.items():
    if source in SOURCE_SYMBOL_MAP and source != 'IB':
        SOURCE_SYMBOL_MAP[source].append(symbol)
    elif source == 'IB' and symbol not in IB_CORE_ARBITRAGE_SYMBOLS:
        # 非核心套利标的从 IB 分流到 FUTU
        SOURCE_SYMBOL_MAP['FUTU'].append(symbol)

# 按数据源排序
for source in SOURCE_SYMBOL_MAP:
    SOURCE_SYMBOL_MAP[source] = sorted(set(SOURCE_SYMBOL_MAP[source]))


# ============================================================
# 查询函数
# ============================================================

def get_symbol_source(symbol: str, use_ib: bool = True) -> str:
    """
    根据标的代码获取数据源
    
    Args:
        symbol: 标的代码，如 'GLD', '510050', '00700', '.INX', '^USO-EU'
        use_ib: 是否使用 IB 数据源（仅对美股 ETF 有效）
    
    Returns:
        数据源: 'IB', 'FUTU', 'TDX', 'SINA', 'WOODY'
    
    后缀处理规则：
    - ^USO-EU, ^USO-JP, ^USO-HK → USO（原油 ETF 实时价格）
    - ^GLD-EU, ^GLD-JP, ^GLD-HK → GLD（黄金 ETF 实时价格）
    - 去掉 -EU, -JP, -HK 后缀后，查找基础标的
    
    Examples:
        >>> get_symbol_source('GLD')              # 默认用 IB
        'IB'
        >>> get_symbol_source('GLD', use_ib=False)  # 美股用富途
        'FUTU'
        >>> get_symbol_source('510050')
        'TDX'
        >>> get_symbol_source('00700')
        'FUTU'
        >>> get_symbol_source('^USO-EU')         # USO 实时价格
        'IB'
        >>> get_symbol_source('^GLD-JP')         # GLD 实时价格
        'IB'
    """
    symbol = symbol.upper().strip()
    
    # 移除地区后缀：-EU, -JP, -HK 等（如 ^USO-EU → ^USO, ^INDA-EU → ^INDA）
    # 注意：先去掉 ^ 前缀再处理后缀
    base_symbol = symbol.lstrip('^')
    for suffix in ['-EU', '-JP', '-HK']:
        if base_symbol.endswith(suffix):
            base_symbol = base_symbol[:-len(suffix)]
            break
    
    # 精确匹配（带后缀的完整代码）
    if symbol in SYMBOL_SOURCE_MAP:
        base_source = SYMBOL_SOURCE_MAP[symbol]
        
        # 美股 ETF 特殊处理：根据 use_ib 参数切换数据源
        if base_source == 'IB' and not use_ib:
            # 检查是否为美股 ETF（在 US_ETF_MAP 中）
            if symbol in US_ETF_MAP:
                return 'FUTU'  # 美股 ETF 从 IB 切换到富途
        
        return base_source
    
    # 模糊匹配：尝试去掉后缀
    if '.' in symbol:
        base = symbol.split('.')[0]
        if base in SYMBOL_SOURCE_MAP:
            base_source = SYMBOL_SOURCE_MAP[base]
            
            # 美股 ETF 特殊处理
            if base_source == 'IB' and not use_ib:
                if base in US_ETF_MAP:
                    return 'FUTU'
            
            return base_source
    
    # 尝试匹配去掉后缀的基础标的（如 USO-EU → USO, INDA-EU → INDA）
    if base_symbol in SYMBOL_SOURCE_MAP:
        base_source = SYMBOL_SOURCE_MAP[base_symbol]
        
        # 美股 ETF 特殊处理
        if base_source == 'IB' and not use_ib:
            if base_symbol in US_ETF_MAP:
                return 'FUTU'
        
        return base_source
    
    # 自动分类（兜底逻辑）
    classified = auto_classify_symbol(symbol)
    
    # 美股 ETF 特殊处理
    if classified == 'IB' and not use_ib:
        import re
        if re.match(r'^[A-Z]{2,6}$', symbol):
            return 'FUTU'
    
    return classified


def get_us_stock_source(use_ib: bool = True) -> str:
    """
    获取美股股票的数据源（便捷函数）
    
    Args:
        use_ib: 是否使用 IB 数据源
    
    Returns:
        'IB' 或 'FUTU'
    
    使用场景：
        # 在 dynamic_valuation.py 或 fund_service.py 中
        from core.arpbcore.config.symbol_source_map import get_us_stock_source
        
        us_source = get_us_stock_source(use_ib=True)  # 'IB'
        us_source = get_us_stock_source(use_ib=False) # 'FUTU'
    """
    return 'IB' if use_ib else 'FUTU'


def get_cn_stock_source(qmt_type: str = None) -> str:
    """
    获取A股股票的数据源（便捷函数）
    
    Args:
        qmt_type: QMT类型，可选值：
            - None 或 'TDX': 通达信（默认）
            - 'YH': 银河QMT
            - 'GJ': 国金QMT
    
    Returns:
        'TDX', 'QMT_YH', 或 'QMT_GJ'
    
    使用场景：
        # 在 dynamic_valuation.py 或 fund_service.py 中
        from core.arpbcore.config.symbol_source_map import get_cn_stock_source
        
        cn_source = get_cn_stock_source()          # 'TDX'（默认）
        cn_source = get_cn_stock_source('YH')      # 'QMT_YH'（银河QMT）
        cn_source = get_cn_stock_source('GJ')      # 'QMT_GJ'（国金QMT）
    """
    if qmt_type == 'YH':
        return 'QMT_YH'
    elif qmt_type == 'GJ':
        return 'QMT_GJ'
    else:
        return 'TDX'


def auto_classify_symbol(symbol: str) -> str:
    """
    自动分类标的代码（当映射表中没有时）
    
    Returns:
        默认数据源
    """
    import re
    s = symbol.upper().strip()
    
    # 移除前缀 (SH, SZ)
    if s.startswith(('SH', 'SZ')):
        s = s[2:]
    
    # 指数（以 . 或 ^ 开头）
    if s.startswith(('.', '^')):
        return 'SINA'
    
    # 美股 ETF（纯字母 2-6 位）
    if re.match(r'^[A-Z]{2,6}$', s):
        return 'IB'
    
    # 港股（5 位数字）
    if re.match(r'^[0-9]{5}$', s):
        return 'FUTU'
    
    # 期货（2 字母 + 数字）
    if re.match(r'^[A-Z]{2}[0-9]{4,6}$', s):
        return 'TDX'
    
    # A 股（6 位数字）
    if re.match(r'^[0-9]{6}$', s):
        return 'TDX'
    
    # 默认返回 A 股数据源
    return 'TDX'


def get_symbols_by_source(source: str) -> list:
    """
    根据数据源获取所有标的列表
    
    Args:
        source: 数据源 'IB', 'FUTU', 'TDX', 'SINA'
    
    Returns:
        标的代码列表
    """
    return SOURCE_SYMBOL_MAP.get(source, [])


def add_custom_mapping(symbol: str, source: str):
    """
    添加自定义映射（运行时动态添加）
    
    Args:
        symbol: 标的代码
        source: 数据源
    """
    SYMBOL_SOURCE_MAP[symbol.upper()] = source
    
    # 更新反向映射
    if source in SOURCE_SYMBOL_MAP:
        if symbol not in SOURCE_SYMBOL_MAP[source]:
            SOURCE_SYMBOL_MAP[source].append(symbol)
            SOURCE_SYMBOL_MAP[source].sort()


def print_mapping_summary():
    """打印映射表摘要"""
    print("=" * 80)
    print("标的代码与数据源映射表摘要")
    print("=" * 80)
    
    for source, symbols in SOURCE_SYMBOL_MAP.items():
        print(f"\n{source} ({len(symbols)} 个标的):")
        for i, symbol in enumerate(symbols, 1):
            print(f"  {i:3d}. {symbol}")
    
    print(f"\n总计: {len(SYMBOL_SOURCE_MAP)} 个标的映射")
    print("=" * 80)


# ============================================================
# 初始化
# ============================================================

if __name__ == '__main__':
    print_mapping_summary()
    
    # 测试查询
    print("\n测试查询:")
    test_symbols = ['GLD', 'SPY', '510050', '00700', '.INX', 'CU2409', 'UNKNOWN']
    for sym in test_symbols:
        source = get_symbol_source(sym)
        print(f"  {sym:15s} → {source}")
