import sqlite3
import threading
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# [AI-2026-09-02] WAL 是「数据库文件级」的持久属性，设一次就永久生效，不需要每次连接都设。
# 原实现在 _get_conn() 里每个连接都执行 PRAGMA journal_mode=WAL —— 该语句在模式需要变更时
# 要拿瞬时排他锁，遇到并发写（daily_updater 子进程 / 15:00 冻结快照线程）就会把调用方死死卡住。
# 主线程（asyncio 事件循环）一旦卡在这里，整个 uvicorn 全接口超时 —— 即 loop-watchdog 抓到的 60s 卡死。
# 改为：进程内每个 db_path 首次连接时设一次，之后走集合命中直接返回（零 SQL、零锁）。
_WAL_ENSURED = set()
_WAL_LOCK = threading.Lock()


def ensure_wal_once(db_path):
    """进程内首次连接该库时确保 WAL 模式；已处理过的库直接返回（不再发任何 SQL）。"""
    if db_path in _WAL_ENSURED:      # 快路径：无锁集合命中
        return
    with _WAL_LOCK:
        if db_path in _WAL_ENSURED:  # 双检：并发首次访问只设一次
            return
        # 先标记，即使本次设置失败也不再每连接重试（避免失败时逐连接放大开销）
        _WAL_ENSURED.add(db_path)
        try:
            conn = sqlite3.connect(db_path, timeout=15.0)
            try:
                mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
                if str(mode).lower() != 'wal':
                    conn.execute('PRAGMA journal_mode=WAL;')
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to enable WAL mode: {e}")


class BaseManager:
    def __init__(self, db_path, lock=None):
        self.db_path = db_path
        self.lock = lock or threading.Lock()

    def _get_conn(self):
        try:
            ensure_wal_once(self.db_path)
            conn = sqlite3.connect(self.db_path, timeout=15.0)
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database at {self.db_path}: {e}")
            raise
