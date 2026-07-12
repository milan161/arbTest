import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


HIGH_FREQ_CATEGORIES = ["黄金原油", "QDII欧美", "QDII日本", "白银"]
NORMAL_FREQ_CATEGORIES = ["QDII亚洲", "国内LOF", "现金管理"]


class DashboardSnapshotService:
    """Background dashboard cache.

    API handlers should read this service instead of calculating dashboard data
    inline. If a refresh fails, the last successful snapshot is kept.
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

    async def start(self):
        if self._running:
            return
        self._running = True
        # [AI-2026-07-03] 启动时仅刷新高优先级分类，低优先级延迟120s再启动
        await self.refresh_once("黄金原油", None, "黄金原油")
        await self.refresh_once("QDII欧美", None, "QDII欧美")
        await self.refresh_once("QDII日本", None, "QDII日本")
        await self.refresh_once("白银", None, "白银")
        self._tasks = [
            asyncio.create_task(self._loop("watchlist", self.high_interval, True, None)),
            asyncio.create_task(self._loop("黄金原油", self.high_interval, False, "黄金原油")),
            asyncio.create_task(self._loop("QDII欧美", self.high_interval, False, "QDII欧美")),
            asyncio.create_task(self._loop("QDII日本", self.high_interval, False, "QDII日本")),
            asyncio.create_task(self._loop("白银", self.high_interval, False, "白银")),
            asyncio.create_task(self._delayed_start_low_priority()),
        ]
        logger.info("Dashboard snapshot service started")

    async def _delayed_start_low_priority(self, delay: float = 120.0):
        """延迟启动低优先级分类（QDII亚洲/国内LOF/白银/现金管理）和全量快照，
        给 daily_updater 留出完成时间，避免网络/CPU竞争。"""
        await asyncio.sleep(delay)
        await self.refresh_once("all", None, None)
        await self._normal_loop()

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
            started = time.monotonic()
            try:
                await self.refresh_once(key, None, category, use_db_watchlist=use_db_watchlist)
            except Exception as exc:
                logger.warning("Dashboard snapshot loop failed for %s: %s", key, exc)
            await asyncio.sleep(max(0.2, interval - (time.monotonic() - started)))

    async def _normal_loop(self):
        while self._running:
            started = time.monotonic()
            for category in NORMAL_FREQ_CATEGORIES:
                try:
                    await self.refresh_once(category, None, category)
                except Exception as exc:
                    logger.warning("Dashboard normal snapshot failed for %s: %s", category, exc)
            await asyncio.sleep(max(1.0, self.normal_interval - (time.monotonic() - started)))

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
        return "all"

    def get_snapshot(self, watchlist: Optional[List[str]] = None, category: Optional[str] = None) -> Dict[str, Any]:
        key = self._snapshot_key(watchlist, category)
        with self._lock:
            snapshot = self._snapshots.get(key) or self._snapshots.get("all")
            if snapshot:
                result = dict(snapshot)
                if watchlist:
                    allowed = set(watchlist)
                    result["data"] = [item for item in result.get("data", []) if item.get("fund_code") in allowed]
                    result["key"] = "watchlist_request"
                return result
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
