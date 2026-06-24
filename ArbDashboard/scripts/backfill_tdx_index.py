# -*- coding: utf-8 -*-
"""
TDX 指数历史数据补采脚本
使用 tqcenter（通达信客户端本地DLL）获取K线数据
⚠️ 运行前必须先打开通达信客户端

用法：
  python backfill_tdx_index.py                    # 补采所有相关指数
  python backfill_tdx_index.py --dry-run          # 只预览，不写入数据库
  python backfill_tdx_index.py --start 2025-01-01 # 指定起始日期
  python backfill_tdx_index.py --list             # 只列出指数映射表
"""
import sqlite3
import sys
import os
import io
import time
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Set

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# ============================================================
# 路径配置
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
DB_PATH = os.path.join(PROJECT_ROOT, 'database', 'arb_master.db')
FUND_LIST_CSV = os.path.join(PROJECT_ROOT, 'jsl', 'fund_list.csv')
TDX_UTILS_DIR = os.path.join(PROJECT_ROOT, 'jsl')
DEFAULT_START = '2025-01-01'

# ============================================================
# 指数映射表（CSV指数代码 → tqcenter符号）
#
# tqcenter符号格式:  code.SZ (深圳), code.SH (上海), code.HI (港股)
#
# 来源：fund_list.csv 中所有基金的"指数代码"列
# ============================================================

# 美股ETF/指数 — 不通过TDX获取，跳过
US_SYMBOLS = {
    'USO', 'GLD', 'XOP', 'QQQ', 'XLY', 'XBI', 'INDA', 'SOXX',
    'AGG', 'VNQ', 'RSPH', '.INX', '.NDX', '.SP500-45',
    '.SPACEVCP', '.SPHCMSHP', 'KWEB', 'SPY',
    'GLD,USO',  # CSV中的逗号分隔值
}

# A股交易所指数（TDX直接支持）
# 格式: CSV指数代码 → tqcenter符号
A_SHARE_INDEX = {
    # 深圳指数 (SZ)
    '399300': '399300.SZ',   # 沪深300
    '399001': '399001.SZ',   # 深证成指
    '399997': '399997.SZ',   # 中证白酒
    '399989': '399989.SZ',   # 中证医疗
    '399330': '399330.SZ',   # 深证100
    '399441': '399441.SZ',   # 生物医药
    '399707': '399707.SZ',   # CSSW证券
    '399803': '399803.SZ',   # 中证工业4.0
    '399807': '399807.SZ',   # 高铁产业
    '399809': '399809.SZ',   # 保险主题
    '399987': '399987.SZ',   # 中证酒
    '399998': '399998.SZ',   # 中证煤炭
    '399417': '399417.SZ',   # 新能源车
    '399011': '399011.SZ',   # 深证100
    '399303': '399303.SZ',   # 深证300
    '399968': '399968.SZ',   # 中证信息技术
    '399986': '399986.SZ',   # 中证银行
    '399363': '399363.SZ',   # 移动互联
    '399975': '399975.SZ',   # 证券公司
    '399322': '399322.SZ',   # 深证红利
    '399988': '399988.SZ',   # 中证500
    '399990': '399990.SZ',   # 中证TMT50
    '399993': '399993.SZ',   # 中证全指信息技术

    # 上海指数 (SH)
    '000905': '000905.SH',   # 中证500
    '000869': '000869.SH',   # HK银行
    '000852': '000852.SH',   # 中证1000
}

# 中证编制指数 → 交易所替代指数（TDX不支持中证编制代码）
# 需要用相近的交易所指数来替代
CSI_TO_EXCHANGE = {
    '930713': '399006.SZ',   # CS人工智能 → 创业板指
    '930875': '399006.SZ',   # 空天军工 → 创业板指
    '930720': '399005.SZ',   # CS互联网医疗 → 中小板指
    '930997': '399005.SZ',   # 新能源车 → 中小板指
    '950090': '000852.SH',   # 上证50优选 → 中证1000
    'H30094': '000852.SH',   # 消费红利 → 中证1000
    '000922': '399322.SZ',   # 中证红利 → 深证红利
    '000961': '399303.SZ',   # 中证上游 → 深证300
    '000979': '399968.SZ',   # 大宗商品 → 中证信息技术
    '930914': None,          # 港股通高股息 → 无交易所替代
    '930917': None,          # SHS高股息 → 无交易所替代
    'H11136': None,          # 中证海外中国互联网 → 无交易所替代
}

# 港股指数 (HI)
HK_INDEX = {
    'HSI':    'HSI.HI',      # 恒生指数
    'HSCEI':  'HSCEI.HI',    # 国企指数
    'HSCI':   'HSCI.HI',     # 恒生综指
    'HSMI':   'HSMI.HI',     # 恒生综合中型股
    'HSSI':   'HSSI.HI',     # 恒生小型股
    'HSCCI':  'HSCCI.HI',    # 恒生中国30
    'HSSCNE': 'HSSCNE.HI',   # 恒生港股通新经济
    'HSTECH': 'HSTECH.HI',   # 恒生科技
}

# 带后缀的代码 → 清理后查找
SUFFIX_MAP = {
    'CES300.HI': '399300.SZ',   # 中华沪深300 → 沪深300
}

# 中文名 → tqcenter符号
CN_NAME_MAP = {
    '中小100': '399011.SZ',
    '中证500': '000905.SH',
    '中证TMT': '399989.SZ',
    '中证银行': '399986.SZ',
    '移动互联': '399363.SZ',
    '证券公司': '399975.SZ',
    '国企改革': None,  # 无交易所替代
}

# [V10.17] 中文名/非标 → 纯数字代码（和 ArbDashboard 后端 _INDEX_CODE_MAP 严格一致）
_INDEX_CODE_MAP_FOR_DB = {
    '中小100': '399011', '移动互联': '399363', '中证500': '000905',
    '中证TMT': '399989', '中证白酒': '399997', '中证消费': '399932',
    '中证养老': '399812', '中证银行': '399986', '国证有色': '399395',
    '证券公司': '399975', '国企改革': '399974',
    'SZ399989': '399989', 'SZ399990': '399990', 'SZ399993': '399993',
    'H30094': '000852', '950090': '000852',
    '930713': '399006', '930875': '399006',
    '930720': '399005', '930997': '399005',
    '000922': '399001', '000961': '399330', '000979': '399441',
    'CES300': '399300',
    'CES300.HI': '399300',
}


def clean_index_code(raw_code: str) -> Optional[str]:
    """清理指数代码，去掉.CSI等后缀"""
    code = raw_code.strip()
    # 去掉 .CSI 后缀
    if code.endswith('.CSI'):
        code = code[:-4]
    # 去掉 SZ/SH 前缀
    if code.startswith('SZ'):
        code = code[2:]
    if code.startswith('SH'):
        code = code[2:]
    return code if code else None


def get_db_symbol(raw_code: str) -> str:
    """
    [V10.17] 获取存入 index_history 的 symbol（必须和后端 _clean_index_symbol 输出一致）
    
    后端查询路径: unified_fund_list.related_index → _clean_index_symbol() → 查 index_history.symbol
    如果两边符号不匹配（如中文名 vs 数字代码），后端就读不到数据。
    """
    if not raw_code:
        return raw_code
    code = raw_code.strip().upper()
    # Step1: 直查映射表（中文名 → 数字代码）
    if code in _INDEX_CODE_MAP_FOR_DB:
        return _INDEX_CODE_MAP_FOR_DB[code]
    # Step2: 去后缀再查
    cleaned = clean_index_code(code)
    if cleaned and cleaned in _INDEX_CODE_MAP_FOR_DB:
        return _INDEX_CODE_MAP_FOR_DB[cleaned]
    # Step3: 已是标准代码则直接返回
    if cleaned and (cleaned.startswith('399') or cleaned.startswith('000') or cleaned.startswith('001')):
        return cleaned
    if cleaned and cleaned in A_SHARE_INDEX:
        return cleaned
    if cleaned and cleaned in HK_INDEX:
        return cleaned
    if cleaned and cleaned in CSI_TO_EXCHANGE:
        return cleaned
    # 兜底
    return raw_code


def map_csv_index_to_tq(raw_code: str) -> Tuple[Optional[str], str]:
    """
    将 CSV 中的指数代码映射到 tqcenter 符号
    
    Returns: (tq_symbol, reason) 
             tq_symbol=None 表示无法映射
    """
    code = raw_code.strip()
    
    # 1. 直接跳过美股
    if code in US_SYMBOLS or code.upper() in {s.upper() for s in US_SYMBOLS}:
        return None, '美股ETF/指数(TDX不支持)'
    
    # 1b. 中文名
    if code in CN_NAME_MAP:
        result = CN_NAME_MAP[code]
        if result:
            return result, '中文名映射'
        else:
            return None, '中文名(无替代)'
    
    # 2. 带后缀的特殊代码
    if code in SUFFIX_MAP:
        return SUFFIX_MAP[code], '特殊后缀映射'
    
    # 3. 港股
    if code in HK_INDEX:
        return HK_INDEX[code], '港股指数'
    
    # 4. A股交易所指数（直接支持）
    if code in A_SHARE_INDEX:
        return A_SHARE_INDEX[code], 'A股交易所指数'
    
    # 5. 清理后缀再查
    cleaned = clean_index_code(code)
    if cleaned:
        if cleaned in A_SHARE_INDEX:
            return A_SHARE_INDEX[cleaned], 'A股(去后缀)'
        # 中证编制代码
        if cleaned in CSI_TO_EXCHANGE:
            mapped = CSI_TO_EXCHANGE[cleaned]
            if mapped:
                return mapped, '中证→交易所替代'
            else:
                return None, '中证编制(无替代)'
    
    # 6. 自动推断：399开头→SZ, 000/001开头→SH
    if cleaned:
        if cleaned.startswith('399'):
            return f'{cleaned}.SZ', '自动推断(SZ)'
        if cleaned.startswith('000') or cleaned.startswith('001'):
            return f'{cleaned}.SH', '自动推断(SH)'
    
    # 7. 未识别
    return None, f'未识别: {code}'


def parse_fund_list_csv() -> Dict[str, dict]:
    """
    解析 fund_list.csv，返回 {基金代码: {name, index_code, index_name, category}}
    """
    funds = {}
    with open(FUND_LIST_CSV, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fund_code = row.get('代码', '').strip()
            if not fund_code:
                continue
            idx_code = row.get('指数代码', '').strip()
            if not idx_code or idx_code == '-':
                continue
            funds[fund_code] = {
                'name': row.get('名称', '').strip(),
                'index_code': idx_code,
                'index_name': row.get('相关指数', '').strip(),
                'category': row.get('分类', '').strip(),
            }
    return funds


def get_all_indices_from_db() -> List[str]:
    """从数据库 unified_fund_list 获取所有 related_index"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT related_index FROM unified_fund_list "
              "WHERE related_index IS NOT NULL AND related_index != '-'")
    indices = [r[0] for r in c.fetchall()]
    conn.close()
    return indices


def get_existing_dates(symbol: str) -> Set[str]:
    """获取数据库中已有的日期"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT date FROM index_history WHERE symbol=?", (symbol,))
    dates = {r[0] for r in c.fetchall()}
    conn.close()
    return dates


def upsert_index_history(symbol: str, date: str, close: float, source: str = 'tqcenter'):
    """写入 index_history"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO index_history (symbol, date, close, source) VALUES (?, ?, ?, ?)",
        (symbol, date, close, source)
    )
    conn.commit()
    conn.close()


def init_tqcenter():
    """
    初始化 tqcenter 连接
    返回: (success, tq_instance)
    """
    try:
        # 将 jsl 目录加入 sys.path
        if TDX_UTILS_DIR not in sys.path:
            sys.path.insert(0, TDX_UTILS_DIR)
        
        from common.tqcenter import tq
        
        # 如果之前已初始化，先关闭
        if hasattr(tq, '_initialized') and tq._initialized:
            try:
                tq.close()
            except:
                pass
        
        # 使用本脚本的 __file__ 路径初始化（tqcenter 需要调用者路径定位DLL）
        tq.initialize(__file__)
        
        if hasattr(tq, '_initialized') and tq._initialized:
            return True, tq
        elif hasattr(tq, 'run_id') and tq.run_id >= 0:
            tq._initialized = True
            return True, tq
        else:
            return False, None
    except Exception as e:
        print(f"  [ERROR] tqcenter 初始化失败: {e}")
        print(f"  请确保通达信客户端已打开")
        return False, None


def fetch_kline_via_tq(tq, tq_symbol: str, start_date: str, end_date: str) -> List[Tuple[str, float]]:
    """
    通过 tqcenter 获取日K线数据
    
    Args:
        tq: tqcenter 实例
        tq_symbol: tqcenter 格式的符号，如 '399300.SZ'
        start_date: 起始日期 'YYYY-MM-DD'
        end_date: 截止日期 'YYYY-MM-DD'
    
    Returns: [(date_str, close_price), ...]
    """
    try:
        beg_tq = start_date.replace('-', '')
        end_tq = end_date.replace('-', '')
        
        df_dict = tq.get_market_data(
            field_list=[],
            stock_list=[tq_symbol],
            start_time=beg_tq,
            end_time=end_tq,
            count=5000,
            period='1d'
        )
        
        results = []
        if df_dict and 'Close' in df_dict:
            if tq_symbol in df_dict['Close']:
                series = df_dict['Close'][tq_symbol].dropna()
                for date_idx, close_val in series.items():
                    date_str = date_idx.strftime('%Y-%m-%d') if hasattr(date_idx, 'strftime') else str(date_idx)[:10]
                    if start_date <= date_str <= end_date:
                        results.append((date_str, float(close_val)))
        
        return results
    except Exception as e:
        print(f"  [ERROR] 获取K线失败 {tq_symbol}: {e}")
        return []


def migrate_symbol_names(conn, dry_run=False):
    """[V10.17] 将 index_history 中中文名/非标符号重命名为标准数字代码"""
    to_migrate = {
        '移动互联': '399363', '证券公司': '399975', '中证银行': '399986',
        '中证500': '000905', '中证TMT': '399989', '中小100': '399011',
    }
    migrated = 0
    for old_name, new_code in to_migrate.items():
        c = conn.execute("SELECT COUNT(*) FROM index_history WHERE symbol=?", (old_name,))
        cnt = c.fetchone()[0]
        if cnt == 0:
            continue
        c2 = conn.execute("SELECT COUNT(*) FROM index_history WHERE symbol=?", (new_code,))
        existing = c2.fetchone()[0]
        print(f"  {old_name:10s} → {new_code:8s} 旧{old_name}={cnt}行, 新{new_code}={existing}行", end='')
        if not dry_run:
            if existing > 0:
                # 新代码已有数据 → 删除旧的（避免重复）
                conn.execute("DELETE FROM index_history WHERE symbol=?", (old_name,))
                print(f"  [删除旧{old_name} {cnt}行]")
            else:
                conn.execute("UPDATE index_history SET symbol=? WHERE symbol=?", (new_code, old_name))
                print(f"  [迁移 {cnt}行 → {new_code}]")
        else:
            action = "删除旧" if existing > 0 else "迁移"
            print(f"  [{action} {cnt}行] (dry-run)")
        migrated += cnt
    return migrated


def main():
    import argparse
    parser = argparse.ArgumentParser(description='TDX 指数历史数据补采 (tqcenter)')
    parser.add_argument('--start', default=DEFAULT_START, help='起始日期 (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='只预览，不写入数据库')
    parser.add_argument('--list', action='store_true', help='只列出指数映射表')
    parser.add_argument('--migrate', action='store_true', help='迁移旧中文名/非标符号到标准数字代码')
    parser.add_argument('--migrate-only', action='store_true', help='只做迁移，不补采')
    args = parser.parse_args()
    
    start_date = args.start
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    
    # [V10.17] 迁移旧中文名数据
    if args.migrate or args.migrate_only:
        print("=" * 72)
        print("迁移 index_history 中文名 → 标准数字代码")
        print("=" * 72)
        conn = sqlite3.connect(DB_PATH)
        n = migrate_symbol_names(conn, dry_run=args.dry_run)
        if not args.dry_run:
            conn.commit()
        conn.close()
        print(f"\n迁移完成: {n} 条记录")
        if args.migrate_only:
            return
    
    # ========================================================
    # 收集所有需要补采的指数
    # ========================================================
    # 来源1: CSV fund_list.csv
    csv_funds = parse_fund_list_csv()
    csv_indices = {}
    for fc, info in csv_funds.items():
        idx = info['index_code']
        if idx and idx != '-':
            csv_indices[idx] = info
    
    # 来源2: 数据库 unified_fund_list
    db_indices = get_all_indices_from_db()
    
    # 合并（去重）
    all_raw_indices = set()
    for idx in csv_indices:
        all_raw_indices.add(idx)
    for idx in db_indices:
        all_raw_indices.add(idx)
    
    print("=" * 72)
    print("TDX 指数历史数据补采 (tqcenter)")
    print(f"日期范围: {start_date} ~ {end_date}")
    print("=" * 72)
    print(f"\n共发现 {len(all_raw_indices)} 个唯一指数代码（CSV + 数据库）")
    
    # ========================================================
    # 映射到 tqcenter 符号
    # ========================================================
    to_fetch = {}       # {db_symbol: tq_symbol}
    skipped = []        # [(raw_code, reason)]
    db_symbol_map = {}  # {db_symbol: raw_code} 用于数据库写入
    
    for raw_idx in sorted(all_raw_indices):
        tq_sym, reason = map_csv_index_to_tq(raw_idx)
        
        # [V10.17 FIX] db_symbol 用清洗后的代码，和后端 _clean_index_symbol 保持一致
        db_sym = get_db_symbol(raw_idx)
        
        if tq_sym is None:
            skipped.append((raw_idx, reason))
        else:
            to_fetch[db_sym] = tq_sym
            db_symbol_map[db_sym] = raw_idx
    
    # 打印映射表
    print(f"\n{'─' * 72}")
    print(f"{'CSV代码':<20} → {'tqcenter符号':<18} 来源")
    print(f"{'─' * 72}")
    for db_sym, tq_sym in sorted(to_fetch.items()):
        raw = db_symbol_map.get(db_sym, db_sym)
        print(f"  {db_sym:<18} → {tq_sym:<18}")
    
    if skipped:
        print(f"\n{'─' * 72}")
        print(f"跳过 {len(skipped)} 个:")
        for code, reason in skipped:
            print(f"  {code:<18} — {reason}")
    
    print(f"\n需要补采: {len(to_fetch)} 个指数")
    
    if args.list:
        print("\n[LIST 模式] 仅列出映射表，不执行补采")
        return
    
    if not to_fetch:
        print("\n无需补采的数据")
        return
    
    # ========================================================
    # 初始化 tqcenter
    # ========================================================
    print(f"\n正在初始化 tqcenter（请确保通达信已打开）...")
    success, tq = init_tqcenter()
    if not success:
        print("[FAIL] tqcenter 初始化失败，退出")
        return
    print("[OK] tqcenter 连接成功\n")
    
    # ========================================================
    # 逐个获取K线数据
    # ========================================================
    total_inserted = 0
    total_skipped = 0
    
    for db_sym, tq_sym in sorted(to_fetch.items()):
        # 获取已有日期
        existing = get_existing_dates(db_sym)
        
        print(f"  {db_sym} → {tq_sym} 已有{len(existing)}天 ... ", end='', flush=True)
        
        # 获取K线
        bars = fetch_kline_via_tq(tq, tq_sym, start_date, end_date)
        
        if not bars:
            print("无数据")
            continue
        
        inserted = 0
        skipped_batch = 0
        for bar_date, close in bars:
            if bar_date in existing:
                skipped_batch += 1
                continue
            if not args.dry_run:
                upsert_index_history(db_sym, bar_date, close)
            inserted += 1
        
        total_inserted += inserted
        total_skipped += skipped_batch
        print(f"新增{inserted}天, 跳过{skipped_batch}天")
        
        time.sleep(0.3)  # 避免请求过快
    
    # ========================================================
    # 完成
    # ========================================================
    print(f"\n{'=' * 72}")
    print(f"完成！新增 {total_inserted} 条, 跳过 {total_skipped} 条(已存在)")
    if args.dry_run:
        print("[DRY-RUN] 未写入数据库")
    print(f"{'=' * 72}")
    
    # 关闭 tqcenter
    try:
        tq.close()
    except:
        pass


if __name__ == '__main__':
    main()
