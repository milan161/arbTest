"""
[2026-07-31] 收盘后冻结实时估值快照 + 最后有效估值缓存

背景：A股 15:00 收盘后，LOF 价格已冻结；之后海外标的（NK 期货 / 美股夜盘）继续波动，
对实时估值已无套利意义（LOF 不能交易）。故把当时算好的 rt_val/rt_premium 冻下来，
主看板收盘后直接显示冻结值，不再显示 "-"。

设计铁律（东哥拍板）：
- 统一对所有基金（国内LOF / QDII香港 / QDII日本 / QDII欧美）拍快照，不分市场；
  绝不搞「按市场分别冻结」的复杂方案（港股16:00 / 美股盘前等）。
- 这是主程序功能，快照文件落在 database/ 目录（非 deploy）。

两个持久化文件（都在 database/）：
1) rt_freeze.json   —— 每日 15:00:05 由 APScheduler 拍的"官方收盘锚点"（优先用）。
2) rt_cache.json    —— 盘中每次算出有效 rt_val 就持续缓存「最后有效值」（改用）。
   解决"用户不常驻、15:00 没拍到 → 盘后全空白"的问题：只要盘中开过后端，
   盘后/重启即显示最后一次有效实时估值 + 「最后有效 HH:MM」标签。

回退优先级（apply_freeze_to_dashboard）：
  盘中(<15:00)            → 显示实时 live（有行情）
  盘后 + 今日有15:00冻结  → 覆盖为 15:00 冻结值（标签「15:00冻结」）
  盘后 + 无15:00冻结      → rt_val 仍为 None 的，回退用最后有效缓存（标签「最后有效 HH:MM」）
"""
import os
import json
import time
import logging
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# realtime_freeze.py 位于 ArbDashboard/backend/services/ → 上溯 3 级到项目根 arbTest/
_HERE = os.path.dirname(os.path.abspath(__file__))
# [AI-2026-08-16] 活库移出仓库根到 D:\Study\arbTest\database（物理隔离防泄漏）；项目根父目录/database
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
FREEZE_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), 'database', 'rt_freeze.json')
RT_CACHE_PATH = os.path.join(os.path.dirname(PROJECT_ROOT), 'database', 'rt_cache.json')

# 进程内串行化：避免同一进程多线程同时替换同一缓存文件（启动期并发调用 update_rt_cache 的根因）
_write_lock = threading.Lock()


def _atomic_write_json(path: str, payload: dict) -> bool:
    """原子写 JSON 到 path。
    做法：写唯一临时文件 → os.replace 原子替换。Windows 下并发/被杀进程残留句柄会
    导致 os.replace 抛 PermissionError / WinError 32(文件被占用) / 5(拒绝访问)，这里用
    「唯一临时名 + 重试保护」彻底消除启动期 '更新估值缓存失败' 警告。返回是否成功。"""
    d = os.path.dirname(path)
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        return False
    # 唯一临时名（含 pid + 线程 id），多进程/多线程不会互相覆盖同一个 .tmp
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except OSError:
                pass
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    # 进程内串行替换（_write_lock 由调用方持有时更安全，这里再保一层）
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return True
        except OSError:
            if attempt < 5:
                time.sleep(0.1 * (attempt + 1))
                continue
            # 最终仍失败：放弃原子性，直接覆盖目标（缓存非关键，至少不丢文件）
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                    try:
                        f.flush()
                        os.fsync(f.fileno())
                    except OSError:
                        pass
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return True
            except Exception:
                pass
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
    return False


def _today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def should_apply_freeze() -> bool:
    """是否已过 A股收盘（15:00）。之后才用冻结/缓存值。"""
    return datetime.now().hour >= 15


def load_realtime_freeze() -> Optional[dict]:
    """读取 15:00 冻结文件；不存在/损坏返回 None。"""
    try:
        if not os.path.exists(FREEZE_PATH):
            return None
        with open(FREEZE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[FREEZE] 读取冻结文件失败: {e}")
        return None


def load_rt_cache() -> Optional[dict]:
    """读取最后有效估值缓存；不存在/损坏返回 None。"""
    try:
        if not os.path.exists(RT_CACHE_PATH):
            return None
        with open(RT_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[FREEZE] 读取估值缓存失败: {e}")
        return None


def snapshot_realtime_freeze(fund_service) -> bool:
    """在 15:00:05 调用：快照当前全量基金的 rt_val/rt_premium → database/rt_freeze.json。"""
    try:
        data = fund_service.get_unified_dashboard_data()
        if not data:
            logger.warning("[FREEZE] 快照失败：get_unified_dashboard_data 返回空")
            return False
        funds: dict = {}
        for r in data:
            code = r.get('fund_code')
            if not code:
                continue
            rt_val = r.get('rt_val')
            rt_premium = r.get('rt_premium')
            # 只冻结有效估值，避免把 None 冻成空（导致收盘后反而变 "-"）
            if rt_val is None and rt_premium is None:
                continue
            funds[code] = {
                'rt_val': rt_val,
                'rt_premium': rt_premium,
                'price': r.get('price'),
            }
        payload = {
            'date': _today_str(),
            'frozen_at': datetime.now().strftime('%H:%M:%S'),
            'funds': funds,
        }
        ok = _atomic_write_json(FREEZE_PATH, payload)
        if not ok:
            logger.warning("[FREEZE] 快照写入失败(文件被占用)，跳过本次冻结")
            return False
        logger.info(f"[FREEZE] 已快照 {len(funds)} 只基金实时估值 → {FREEZE_PATH}")
        return True
    except Exception as e:
        logger.error(f"[FREEZE] 快照异常: {e}")
        return False


def update_rt_cache(data: list) -> None:
    """盘中每次算出有效 rt_val 即合并写入 database/rt_cache.json（最后有效值）。
    合并式：只更新本次有效的基金，保留之前有效但本次缺失的，避免网络抖动丢缓存。
    [AI-2026-08-06] 进程内锁 + 唯一临时文件 + 跨进程重试，消除 Windows 下 os.replace
    并发/被杀进程残留句柄导致的 WinError 5/13/32 警告。
    [AI-2026-08-15] 盘中守卫：盘后(≥15:00)不再写缓存。原因——QDII亚洲/国内LOF 盘后
    走指数极速估值（nav×最近两日指数涨跌幅）照样算出非 None 的 rt_val，若盘后也写，
    会把"最后有效实时值"污染成盘后估算值（rt_cache.json updated_at 变成 21:5x）。
    缓存只保留盘中(<15:00)最后有效实时值，供盘后定格显示（与"15:00 后 LOF 不能交易、
    估值无意义应定格"的套利口径一致）。"""
    try:
        if should_apply_freeze():
            return
        with _write_lock:
            cache = load_rt_cache() or {'updated_at': None, 'funds': {}}
            funds = cache.get('funds', {})
            touched = False
            for r in data:
                code = r.get('fund_code')
                if not code:
                    continue
                rt_val = r.get('rt_val')
                rt_premium = r.get('rt_premium')
                if rt_val is None and rt_premium is None:
                    continue
                funds[code] = {
                    'rt_val': rt_val,
                    'rt_premium': rt_premium,
                    'price': r.get('price'),
                }
                touched = True
            if not touched:
                return
            payload = {
                'updated_at': datetime.now().strftime('%H:%M:%S'),
                'funds': funds,
            }
            ok = _atomic_write_json(RT_CACHE_PATH, payload)
        if not ok:
            # 瞬时文件占用，缓存非关键路径，静默跳过避免刷屏 WARNING
            logger.debug("[FREEZE] 估值缓存写入被跳过(瞬时文件占用)，不影响实时估值主流程")
    except Exception as e:
        logger.debug(f"[FREEZE] 更新估值缓存失败(已静默): {e}")


def apply_freeze_to_dashboard(result: list) -> None:
    """在 get_unified_dashboard_data() 末尾调用：
    - 盘中：直接返回（显示实时 live）。
    - 盘后：优先用当日 15:00 冻结值；rt_val 仍 None 的，回退用最后有效缓存。
      二者都标记 rt_frozen=True，并附 rt_frozen_note 说明来源。
    """
    # 盘中：显示实时 live（有行情），不回退，避免误导
    if not should_apply_freeze():
        return

    today = _today_str()

    # 1) 15:00 冻结优先（官方收盘锚点）
    freeze = load_realtime_freeze()
    if freeze and freeze.get('date') == today and freeze.get('funds'):
        for item in result:
            code = item.get('fund_code')
            fz = freeze['funds'].get(code)
            if fz and fz.get('rt_val') is not None:
                item['rt_val'] = fz['rt_val']
                item['rt_premium'] = fz['rt_premium']
                item['rt_frozen'] = True
                item['rt_frozen_note'] = '15:00冻结'

    # 2) 回退：rt_val 仍为 None 的，或指数极速类(QDII亚洲/国内LOF，盘后用指数外推
    #    算出估算值、同样应定格)未冻的，用最后有效缓存（解决不常驻导致 15:00 没拍到）。
    #    [AI-2026-08-15] 已由第 1 步"15:00冻结"覆盖的基金跳过，保持快照锚点优先。
    cache = load_rt_cache()
    if cache and cache.get('funds'):
        updated_at = cache.get('updated_at') or ''
        for item in result:
            if item.get('rt_frozen'):
                continue
            cat = item.get('category')
            est_class = cat in ('QDII亚洲', '国内LOF')
            if item.get('rt_val') is not None and not est_class:
                continue
            code = item.get('fund_code')
            c = cache['funds'].get(code)
            if c and c.get('rt_val') is not None:
                item['rt_val'] = c['rt_val']
                item['rt_premium'] = c['rt_premium']
                item['rt_frozen'] = True
                item['rt_frozen_note'] = f'最后有效 {updated_at}'
