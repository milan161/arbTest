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
2) rt_cache.json    —— 盘中每次算出有效 rt_val 就持续缓存「最后有效值」（兜底用）。
   解决"用户不常驻、15:00 没拍到 → 盘后全空白"的问题：只要盘中开过后端，
   盘后/重启即显示最后一次有效实时估值 + 「最后有效 HH:MM」标签。

回退优先级（apply_freeze_to_dashboard）：
  盘中(<15:00)            → 显示实时 live（有行情）
  盘后 + 今日有15:00冻结  → 覆盖为 15:00 冻结值（标签「15:00冻结」）
  盘后 + 无15:00冻结      → rt_val 仍为 None 的，回退用最后有效缓存（标签「最后有效 HH:MM」）
"""
import os
import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# realtime_freeze.py 位于 ArbDashboard/backend/services/ → 上溯 3 级到项目根 arbTest/
_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
FREEZE_PATH = os.path.join(PROJECT_ROOT, 'database', 'rt_freeze.json')
RT_CACHE_PATH = os.path.join(PROJECT_ROOT, 'database', 'rt_cache.json')


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
        os.makedirs(os.path.dirname(FREEZE_PATH), exist_ok=True)
        tmp = FREEZE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, FREEZE_PATH)
        logger.info(f"[FREEZE] 已快照 {len(funds)} 只基金实时估值 → {FREEZE_PATH}")
        return True
    except Exception as e:
        logger.error(f"[FREEZE] 快照异常: {e}")
        return False


def update_rt_cache(data: list) -> None:
    """盘中每次算出有效 rt_val 即合并写入 database/rt_cache.json（最后有效值）。
    合并式：只更新本次有效的基金，保留之前有效但本次缺失的，避免网络抖动丢缓存。"""
    try:
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
        os.makedirs(os.path.dirname(RT_CACHE_PATH), exist_ok=True)
        tmp = RT_CACHE_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, RT_CACHE_PATH)
    except Exception as e:
        logger.warning(f"[FREEZE] 更新估值缓存失败: {e}")


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

    # 2) 回退：仍有 rt_val=None 的，用最后有效缓存（解决不常驻导致 15:00 没拍到）
    cache = load_rt_cache()
    if cache and cache.get('funds'):
        updated_at = cache.get('updated_at') or ''
        for item in result:
            if item.get('rt_val') is not None:
                continue
            code = item.get('fund_code')
            c = cache['funds'].get(code)
            if c and c.get('rt_val') is not None:
                item['rt_val'] = c['rt_val']
                item['rt_premium'] = c['rt_premium']
                item['rt_frozen'] = True
                item['rt_frozen_note'] = f'最后有效 {updated_at}'
