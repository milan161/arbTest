import asyncio
import json
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


# 【AI-2026-07-20】分类优先级管理：改为从 app_settings 读取暂停列表
# HIGH_FREQ_CATEGORIES 是系统支持的全部分类（每分类独立 3s 快照循环）
ALL_CATEGORIES = ["黄金原油", "QDII欧美", "QDII日本", "白银", "QDII亚洲", "国内LOF", "现金管理"]
# 默认暂停（用户不关心的分类）
DEFAULT_PAUSED = ["QDII亚洲", "国内LOF", "现金管理"]


class DashboardSnapshotService:
    """Background dashboard cache.

    API handlers should read this service instead of calculating dashboard data
    inline. If a refresh fails, the last successful snapshot is kept.

    [AI-2026-07-20] 分类优先级管理：
    - 只有「未暂停」的分类才会启动独立快照循环（3s 刷新）
    - 暂停的分类完全不生成快照、不抓指数、无日志噪音
    - 支持运行时修改暂停列表（sync_paused_categories）
    """

    def __init__(
        self,
        fund_service,
        market_data_service=None,
        high_interval: float = 3.0,
        normal_interval: float = 30.0,
    ):
        self.fund_service = fund_service
        self.market_data_service = market_data_service
        self.high_interval = high_interval
        self.normal_interval = normal_interval
        self._lock = threading.RLock()
        self._snapshots: Dict[str, Dict[str, Any]] = {}
        self._last_errors: Dict[str, str] = {}
        self._running = False
        self._tasks: List[asyncio.Task] = []
        # [AI-2026-07-20] 从 db 读取暂停分类列表
        self._paused_categories: set = set()

    def _load_paused(self) -> set:
        """从 app_settings 读取暂停分类列表"""
        try:
            db = getattr(self.fund_service, 'db', None)
            if db:
                raw = db.get_app_setting('paused_categories', None)
                if raw:
                    return set(json.loads(raw))
        except Exception:
            pass
        return set(DEFAULT_PAUSED)

    def _is_paused(self, category: Optional[str]) -> bool:
        """检查分类是否已暂停"""
        if not category:
            return False
        return category in self._paused_categories

    def sync_paused_categories(self, paused_list: List[str]):
        """运行时重新加载暂停分类列表（由 API 调用）"""
        self._paused_categories = set(paused_list)
        logger.info(f"[SNAPSHOT] 暂停分类已更新: {paused_list}")

    async def start(self):
        if self._running:
            return
        self._running = True
        self._paused_categories = self._load_paused()
        logger.info(f"[SNAPSHOT] 暂停分类: {sorted(self._paused_categories)}")

        # 只对「未暂停」的分类启动独立快照循环（3s 刷新）
        active_categories = [c for c in ALL_CATEGORIES if c not in self._paused_categories]
        logger.info(f"[SNAPSHOT] 活跃分类: {active_categories}")

        # 启动时先刷新一次所有活跃分类
        for cat in active_categories:
            await self.refresh_once(cat, None, cat)

        # watchlist 始终运行
        self._tasks = [
            asyncio.create_task(self._loop("watchlist", self.high_interval, True, None)),
        ]
        # 每个未暂停的分类启动独立循环
        for cat in active_categories:
            self._tasks.append(
                asyncio.create_task(self._loop(cat, self.high_interval, False, cat))
            )
        logger.info(f"Dashboard snapshot service started ({len(active_categories)} active categories)")

    async def stop(self):
        self._running = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Dashboard snapshot service stopped")

    async def _loop(self, key: str, interval: float, use_db_watchlist: bool, category: Optional[str]):
        while self._running:
            # [AI-2026-07-20] 运行时检查：如果分类被暂停，跳过本轮
            if self._is_paused(category):
                await asyncio.sleep(5.0)
                continue
            started = time.monotonic()
            try:
                await self.refresh_once(key, None, category, use_db_watchlist=use_db_watchlist)
            except Exception as exc:
                logger.warning("Dashboard snapshot loop failed for %s: %s", key, exc)
            await asyncio.sleep(max(0.2, interval - (time.monotonic() - started)))

    def _source_status(self) -> Dict[str, Any]:
        if not self.market_data_service:
            return {}
        realtime = getattr(self.market_data_service, "realtime_manager", None)
        return {
            "active_sources": self.market_data_service.get_active_source_names(),
            "ib_connected": bool(getattr(getattr(self.market_data_service, "ib_reader", None), "connected", False)),
            "futu_disabled": bool(getattr(getattr(self.market_data_service, "futu_reader", None), "disabled", True)),
            "realtime_symbols": len(getattr(realtime, "symbols", []) or []),
        }

    def _read_watchlist_from_db(self) -> List[str]:
        try:
            return self.fund_service.get_my_watchlist()
        except Exception as exc:
            logger.warning("Failed to read dashboard watchlist: %s", exc)
            return []

    async def refresh_once(
        self,
        key: str,
        watchlist: Optional[List[str]],
        category: Optional[str],
        use_db_watchlist: bool = False,
    ) -> Dict[str, Any]:
        started = time.monotonic()

        def _compute():
            effective_watchlist = self._read_watchlist_from_db() if use_db_watchlist else watchlist
            return self.fund_service.get_unified_dashboard_data(
                watchlist=effective_watchlist,
                category=category,
            )

        try:
            data = await asyncio.to_thread(_compute)
            compute_ms = int((time.monotonic() - started) * 1000)
            snapshot = {
                "data": data,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "stale": False,
                "source_status": self._source_status(),
                "compute_ms": compute_ms,
                "error": None,
                "key": key,
            }
            with self._lock:
                self._snapshots[key] = snapshot
                self._last_errors.pop(key, None)
            return snapshot
        except Exception as exc:
            compute_ms = int((time.monotonic() - started) * 1000)
            with self._lock:
                self._last_errors[key] = str(exc)
                previous = self._snapshots.get(key)
                if previous:
                    stale = dict(previous)
                    stale.update({"stale": True, "error": str(exc), "compute_ms": compute_ms})
                    self._snapshots[key] = stale
                    return stale
            logger.exception("Dashboard snapshot refresh failed for %s", key)
            raise

    def _snapshot_key(self, watchlist: Optional[List[str]], category: Optional[str]) -> str:
        if watchlist:
            return "watchlist"
        if category:
            return category
        # [AI-2026-07-20] 不再生成"all"全量快照，改由合并各分类快照
        return "_combined"

    def get_snapshot(self, watchlist: Optional[List[str]] = None, category: Optional[str] = None) -> Dict[str, Any]:
        key = self._snapshot_key(watchlist, category)
        with self._lock:
            if category:
                # 请求特定分类
                snapshot = self._snapshots.get(category)
                if snapshot:
                    return dict(snapshot)
            elif watchlist:
                snapshot = self._snapshots.get("watchlist")
                if snapshot:
                    result = dict(snapshot)
                    allowed = set(watchlist)
                    result["data"] = [item for item in result.get("data", []) if item.get("fund_code") in allowed]
                    result["key"] = "watchlist_request"
                    return result
            else:
                # 无分类/无 watchlist → 合并所有非暂停分类的快照数据
                combined_data = []
                latest_updated = None
                for cat in ALL_CATEGORIES:
                    snap = self._snapshots.get(cat)
                    if snap and snap.get("data"):
                        combined_data.extend(snap["data"])
                        if snap.get("updated_at") and (not latest_updated or snap["updated_at"] > latest_updated):
                            latest_updated = snap["updated_at"]
                if combined_data:
                    return {
                        "data": combined_data,
                        "updated_at": latest_updated,
                        "stale": False,
                        "source_status": self._source_status(),
                        "compute_ms": None,
                        "error": None,
                        "key": "_combined",
                    }
        return {
            "data": [],
            "updated_at": None,
            "stale": True,
            "source_status": self._source_status(),
            "compute_ms": 0,
            "error": "dashboard snapshot not ready",
            "key": key,
        }

    def get_runtime_health(self) -> Dict[str, Any]:
        now = datetime.now()
        with self._lock:
            snapshots = {}
            for key, snap in self._snapshots.items():
                updated_at = snap.get("updated_at")
                age_seconds = None
                if updated_at:
                    try:
                        age_seconds = (now - datetime.fromisoformat(updated_at)).total_seconds()
                    except Exception:
                        age_seconds = None
                snapshots[key] = {
                    "updated_at": updated_at,
                    "age_seconds": age_seconds,
                    "stale": snap.get("stale", False),
                    "compute_ms": snap.get("compute_ms", 0),
                    "rows": len(snap.get("data") or []),
                    "error": snap.get("error"),
                }
            return {
                "running": self._running,
                "snapshots": snapshots,
                "last_errors": dict(self._last_errors),
                "source_status": self._source_status(),
            }
