#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[2026-08-27] 从 ARM 同步当日分时数据到本地数据库。

背景（东哥口径）：
- 分时价格数据全部由 ARM / AMD 采集，回传到本地；本地程序不采分时。
- 本地库在下午才开机时，当日上午分时缺失 → 分时图上午空白。
- 因此：页面启动 / 当日首次分时请求时，从 ARM SCP 全库并合并当日关注基金的分时。

仅同步关注基金（与 H5 一致）：162411 / 164701 / 161116。
其它基金不在此同步范围（东哥 2026-08-27：其它基金不需要）。

设计原则（第一性原理，非打补丁）：
- SCP 拉 ARM 全库到临时文件 → 合并当日关注基金行到本地；本地不向 ARM 回推。
- 幂等：按 (fund_code, date, time) 存在则 UPDATE、不存在则 INSERT。
- 当天只同步一次（ensure_synced_today 用 _synced_date 守护），失败才重试。
- 所有异常就地捕获返回 dict，绝不抛给调用方（不阻塞 API / 启动）。
"""

import os
import sqlite3
import subprocess
import threading
from datetime import datetime

# 与 scripts/sync_arm_intraday.py 保持一致
LOCAL_DB = 'D:/Study/arbTest/database/arb_master.db'
ARM_SCP_DB = 'arm:/home/ubuntu/arbtest/database/arb_master.db'
TEMP_DB = 'D:/Study/arbTest/database/arb_master_sync.db'

# 关注基金：仅这 3 只做分时同步（与 H5 intradayCodes 一致）
ARM_SYNC_FUNDS = ['162411', '164701', '161116']

_sync_lock = threading.Lock()
_synced_date = None  # 当天是否已成功同步


def sync_arm_intraday_to_local(fund_codes=None, date=None):
    """执行一次同步：SCP ARM 全库 → 合并当日关注基金分时到本地。
    返回 dict(status, updated, message)。失败不抛异常。"""
    fund_codes = fund_codes or ARM_SYNC_FUNDS
    date = date or datetime.now().strftime('%Y-%m-%d')
    try:
        result = subprocess.run(
            ['scp', ARM_SCP_DB, TEMP_DB],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {'status': 'error', 'message': f'SCP失败: {result.stderr.strip()}'}

        local_conn = sqlite3.connect(LOCAL_DB)
        sync_conn = sqlite3.connect(TEMP_DB)
        local_cur = local_conn.cursor()
        sync_cur = sync_conn.cursor()

        placeholders = ','.join('?' * len(fund_codes))
        records = sync_cur.execute(f'''
            SELECT fund_code, date, time, price, rt_val, premium, open_premium, close_premium,
                   lof_bid1, lof_ask1, etf_bid1, etf_ask1
            FROM fund_intraday_quotes
            WHERE date=? AND fund_code IN ({placeholders})
            ORDER BY rowid
        ''', (date, *fund_codes)).fetchall()

        # ARM 无当日数据时不删本地（避免误清空），直接返回
        if not records:
            local_conn.close()
            sync_conn.close()
            if os.path.exists(TEMP_DB):
                try:
                    os.remove(TEMP_DB)
                except Exception:
                    pass
            return {'status': 'ok', 'updated': 0, 'message': 'ARM 无当日数据，跳过'}

        # [2026-08-27] 以 ARM 为准：先删本地当日关注基金行，再整批写入，保证本地与 ARM 完全一致
        # （仅当 ARM 已拉到数据才执行删除，ARM 不可达时绝不清空本地）
        local_cur.execute(
            f'DELETE FROM fund_intraday_quotes WHERE date=? AND fund_code IN ({placeholders})',
            (date, *fund_codes)
        )
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for rec in records:
            local_cur.execute('''
                INSERT INTO fund_intraday_quotes
                (fund_code, date, time, price, rt_val, premium, open_premium, close_premium,
                 lof_bid1, lof_ask1, etf_bid1, etf_ask1, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (*rec, now))
        updated = len(records)

        local_conn.commit()
        local_conn.close()
        sync_conn.close()

        # 清理临时文件：失败不影响同步结果（数据已 commit）
        if os.path.exists(TEMP_DB):
            try:
                os.remove(TEMP_DB)
            except Exception:
                pass

        return {'status': 'ok', 'updated': updated, 'message': f'同步 {updated} 条'}
    except Exception as e:
        if os.path.exists(TEMP_DB):
            try:
                os.remove(TEMP_DB)
            except Exception:
                pass
        return {'status': 'error', 'message': str(e)}


def ensure_synced_today():
    """当天首次调用时同步一次（幂等）。线程安全；失败才允许重试。"""
    global _synced_date
    today = datetime.now().strftime('%Y-%m-%d')
    if _synced_date == today:
        return {'status': 'skipped', 'message': '今日已同步'}
    with _sync_lock:
        if _synced_date == today:
            return {'status': 'skipped', 'message': '今日已同步'}
        res = sync_arm_intraday_to_local()
        if res.get('status') == 'ok':
            _synced_date = today
        return res


def trigger_sync_async(fund_codes=None):
    """后台线程触发同步，不阻塞调用方。供启动钩子 / 路由内 fire-and-forget 使用。"""
    def _run():
        sync_arm_intraday_to_local(fund_codes)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
