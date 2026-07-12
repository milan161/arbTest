"""
指数数据修复服务 (Index Repair Service)

提供两种方式补采 index_history 数据：
1. repair_with_tdx() - 需要通达信客户端已打开
2. repair_with_sina() - 纯 HTTP API，无需通达信（数据质量可能不如通达信）

两种方式都会在补采后自动重算所有受影响的 static_val。
"""
import os
import sys
import json
import logging
import subprocess
import requests
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional

logger = logging.getLogger(__name__)

# ============================================================
# 路径配置
# ============================================================
BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(BACKEND_DIR, '..', '..', '..'))
DB_PATH = os.path.join(PROJECT_ROOT, 'database', 'arb_master.db')

# 同主码表：和 backfill_tdx_index.py 保持一致
A_SHARE_SZ_PREFIX = {'399300','399001','399997','399989','399330','399441','399707',
                     '399803','399807','399809','399987','399998','399417','399011',
                     '399303','399968','399986','399363','399975','399322','399988',
                     '399990','399993','399005','399006'}
A_SHARE_SH_PREFIX = {'000905','000869','000852'}

# 港股指数
HK_INDICES = {'HSI','HSCEI','HSCCI','HSTECH','HSCI','HSSI','HSMI','HSSCNE'}


# ============================================================
# TDX 方式
# ============================================================

def repair_with_tdx(days_back: int = 30) -> dict:
    """
    通过通达信 tqcenter 补采指数数据。
    需要通达信客户端已打开。
    
    Args:
        days_back: 补采最近多少天的数据（默认 30 天）
    
    Returns:
        {"status": "ok"|"error", "message": "...", "new_records": int}
    """
    # [AI-2026-07-01] 路径：BACKEND_DIR=backend/services/ -> scripts/ 需上一层
    script_path = os.path.normpath(os.path.join(
        BACKEND_DIR, '..', 'scripts', 'backfill_tdx_index.py'))
    
    if not os.path.exists(script_path):
        return {"status": "error", "message": f"backfill_tdx_index.py 不存在: {script_path}"}
    
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')
    
    try:
        result = subprocess.run(
            [sys.executable, script_path, '--start', start_date],
            capture_output=True, text=True, timeout=300,
            cwd=PROJECT_ROOT
        )
        output = result.stdout + result.stderr
        
        if result.returncode != 0:
            return {"status": "error", "message": f"脚本异常退出 (code={result.returncode})", "output": output[-2000:]}
        
        # 解析输出中的新增条数
        new_records = 0
        for line in output.split('\n'):
            if '完成！新增' in line:
                import re
                m = re.search(r'新增\s*(\d+)', line)
                if m:
                    new_records = int(m.group(1))
        
        # 补采成功后重算 static_val
        recalc_result = _recalc_all_static_val()
        
        return {
            "status": "ok",
            "message": f"TDX 补采完成，新增 {new_records} 条记录",
            "new_records": new_records,
            "recalc": recalc_result,
            "output": output[-1000:]
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "补采超时（>5分钟）"}
    except Exception as e:
        return {"status": "error", "message": f"补采失败: {e}"}


# ============================================================
# Sina/腾讯 API 方式（无需通达信）
# ============================================================

def _get_all_related_indices() -> List[tuple]:
    """
    从 unified_fund_list 获取所有需要补采的指数代码。
    Returns: [(symbol, category_type), ...]
        category_type: 'a_share_sz' | 'a_share_sh' | 'hk' | 'skip'
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT related_index FROM unified_fund_list 
        WHERE related_index IS NOT NULL AND related_index != '-' AND related_index != ''
    """)
    raw = [r[0] for r in c.fetchall()]
    conn.close()
    
    result = []
    seen = set()
    for code in raw:
        clean = code.strip().upper()
        if clean in seen:
            continue
        seen.add(clean)
        
        # 去 .CSI 后缀
        if clean.endswith('.CSI'):
            clean = clean[:-4]
        
        # 美股 → 跳过
        if clean in ('GLD','USO','XOP','QQQ','XLY','XBI','INDA','SOXX',
                     'AGG','VNQ','RSPH','SPY','KWEB','XLE'):
            result.append((code, 'skip'))
            continue
            
        # 6位纯数字CSI指数 (如 930917.CSI, 000922.CSI)
        if len(clean) == 6 and clean.isdigit():
            if clean.startswith('9'):
                result.append((code, 'a_share_sz'))  # 深圳
            else:  # 以0开头
                result.append((code, 'a_share_sh'))  # 上海
            continue
        # A股深圳指数
        if clean in A_SHARE_SZ_PREFIX or (clean.startswith('399') and len(clean) == 6):
            result.append((code, 'a_share_sz'))
        # A股上海指数
        elif clean in A_SHARE_SH_PREFIX or (clean.startswith('000') and len(clean) == 6) or (clean.startswith('001') and len(clean) == 6):
            result.append((code, 'a_share_sh'))
        # 港股指数
        elif clean in HK_INDICES:
            result.append((code, 'hk'))
        # 带 .HI 后缀的港股指数
        elif clean.endswith('.HI'):
            result.append((code, 'hk'))
        # 美股指数
        elif clean in ('.INX', '.NDX'):
            result.append((code, 'us_index'))
        else:
            result.append((code, 'skip'))
    
    return result


def _fetch_sina_a_share(symbol: str, market: str, days: int = 30) -> list:
    """
    从新浪财经获取 A 股指数日线数据。
    
    Args:
        symbol: 指数代码，如 '399300'
        market: 'sz' 或 'sh'
        days: 获取最近多少天
    
    Returns: [(date_str, close_price), ...] 按日期升序
    """
    url = (f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={market}{symbol}&scale=240&ma=no&datalen={days}")
    try:
        resp = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'
        }, timeout=15)
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not data or not isinstance(data, list):
            return []
        result = []
        for d in data:
            day = d.get('day', '')
            close = d.get('close', '')
            if day and close:
                try:
                    result.append((day, float(close)))
                except ValueError:
                    pass
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        logger.warning(f"[Sina] 获取 {market}{symbol} 失败: {e}")
        return []


def _fetch_qq_hk_index(symbol: str, days: int = 30) -> list:
    """
    从腾讯财经获取港股指数日线数据。
    
    Args:
        symbol: 港股指数代码，如 'HSI'
        days: 获取最近多少天
    
    Returns: [(date_str, close_price), ...] 按日期升序
    """
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"_var=kline_dayqfq&param=hk{symbol},day,,,{days},qfq")
    try:
        resp = requests.get(url, timeout=15)
        text = resp.text
        if 'kline_dayqfq=' not in text:
            return []
        json_str = text.split('kline_dayqfq=')[-1]
        data = json.loads(json_str)
        day_data = data.get('data', {}).get(f'hk{symbol}', {}).get('day', [])
        if not day_data:
            return []
        result = []
        for item in day_data:
            if len(item) >= 5:
                date_str = item[0]
                close = item[4]
                try:
                    result.append((date_str, float(close)))
                except (ValueError, IndexError):
                    pass
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        logger.warning(f"[QQ] 获取 hk{symbol} 失败: {e}")
        return []


def _fetch_qq_a_share(symbol: str, market: str, days: int = 30) -> list:
    """
    从腾讯财经获取 A 股指数日线数据（备用，Sina 失败时使用）。
    """
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
           f"_var=kline_dayqfq&param={market}{symbol},day,,,{days},qfq")
    try:
        resp = requests.get(url, timeout=15)
        text = resp.text
        if 'kline_dayqfq=' not in text:
            return []
        json_str = text.split('kline_dayqfq=')[-1]
        data = json.loads(json_str)
        day_data = data.get('data', {}).get(f'{market}{symbol}', {}).get('day', [])
        if not day_data:
            return []
        result = []
        for item in day_data:
            if len(item) >= 5:
                date_str = item[0]
                close = item[4]
                try:
                    result.append((date_str, float(close)))
                except (ValueError, IndexError):
                    pass
        return sorted(result, key=lambda x: x[0])
    except Exception as e:
        logger.warning(f"[QQ] 获取 {market}{symbol} 失败: {e}")
        return []


def _get_existing_dates(symbol: str) -> set:
    """获取数据库中已有的日期"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT date FROM index_history WHERE symbol=?", (symbol,))
    dates = {r[0] for r in c.fetchall()}
    conn.close()
    return dates


def _upsert_index_history(symbol: str, date: str, close: float, source: str = 'sina'):
    """写入一条 index_history"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO index_history (symbol, date, close, source) VALUES (?, ?, ?, ?)",
        (symbol, date, close, source)
    )
    conn.commit()
    conn.close()


def _recalc_all_static_val() -> dict:
    """
    重新计算全部基金的 static_val（复用 step11 逻辑的简化版）。
    通过直接调用 repair 端点逻辑对每只基金重算。
    此处直接复用 daily_updater 的 step11 方法。
    """
    # 导入 daily_updater 并执行 step11
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, 'ArbDashboard', 'backend'))
        from scheduler.daily_updater import DailyUpdater
        
        du = DailyUpdater()
        # 只跑 step11（跟踪指数公式），不跑完整 pipeline
        du.step11_simple_static_valuation()
        return {"status": "ok", "detail": "static_val 已全部重算"}
    except Exception as e:
        logger.error(f"重算 static_val 失败: {e}")
        return {"status": "error", "message": f"重算 static_val 失败: {e}"}


def repair_with_sina(days_back: int = 30) -> dict:
    """
    使用 Sina/腾讯 API 补采指数数据（无需通达信）。
    
    流程：
    1. 遍历所有 related_index
    2. A股指数 → Sina API（优先）→ QQ API（兜底）
    3. 港股指数 → QQ API
    4. 写入 index_history
    5. 重算 static_val
    """
    indices = _get_all_related_indices()
    
    total_new = 0
    total_skip = 0
    total_fail = 0
    details = []
    
    for raw_code, category in indices:
        clean = raw_code.strip().upper()
        if clean.endswith('.CSI'):
            clean = clean[:-4]
        if clean.endswith('.HI'):
            clean = clean[:-3]
        
        if category == 'skip':
            details.append(f"  {raw_code} → 跳过（无需补采）")
            total_skip += 1
            continue
        
        existing = _get_existing_dates(clean)
        rows = []
        
        if category == 'a_share_sz':
            rows = _fetch_sina_a_share(clean, 'sz', days_back)
            if not rows:
                rows = _fetch_qq_a_share(clean, 'sz', days_back)
        elif category == 'a_share_sh':
            rows = _fetch_sina_a_share(clean, 'sh', days_back)
            if not rows:
                rows = _fetch_qq_a_share(clean, 'sh', days_back)
        elif category == 'hk':
            rows = _fetch_qq_hk_index(clean, days_back)
            if not rows:
                # 也试试不带 hk 前缀
                rows = _fetch_qq_hk_index(clean, days_back)
        
        if not rows:
            details.append(f"  {raw_code} → 无数据")
            total_fail += 1
            continue
        
        inserted = 0
        skipped = 0
        for date_str, close in rows:
            if date_str in existing:
                skipped += 1
                continue
            _upsert_index_history(clean, date_str, close, 'sina')
            inserted += 1
        
        total_new += inserted
        total_skip += skipped
        if inserted > 0:
            details.append(f"  {raw_code} → 新增 {inserted} 天, 跳过 {skipped} 天")
        else:
            details.append(f"  {raw_code} → 跳过 {skipped} 天（已存在）")
    
    summary = f"Sina 补采完成：新增 {total_new} 条, 跳过 {total_skip} 条, 失败 {total_fail} 个"
    logger.info(summary)
    
    # 重算 static_val
    recalc_result = _recalc_all_static_val()
    
    return {
        "status": "ok",
        "message": summary,
        "new_records": total_new,
        "skipped": total_skip,
        "failed": total_fail,
        "details": details,
        "recalc": recalc_result
    }
