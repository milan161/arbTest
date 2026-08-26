# -*- coding: utf-8 -*-
"""
[AI-2026-08-25] 事件循环卡死自曝 watchdog（纯诊断，零业务逻辑）

背景：IB/银河QMT 手动重连成功后 ~25s，asyncio 事件循环被某处同步阻塞调用堵死
（8000 在监听但所有 HTTP 超时；后台线程仍在写日志），数分钟后进程无声崩溃。
2026-08-25 复现 2 次（logs/2026-08-25_132113.log / _132911.log）。py-spy 无法附加，
故内置 watchdog 在卡死瞬间自动把全部线程栈落盘，供事后定位阻塞行号。

机制（零依赖，stdlib only，本地/ARM 同一套代码）：
- watchdog 守护线程每 2s 通过 loop.call_soon_threadsafe 投递心跳回调；
  心跳回调在事件循环上执行并刷新时间戳。
- 事件循环健康 → 时间戳始终新鲜，什么都不发生（开销：一次回调/2s）。
- 事件循环被阻塞 → 心跳回调进不了循环，时间戳变陈旧；超过 STALL_THRESHOLD(15s)
  → faulthandler.dump_traceback 全线程栈写入 logs/watchdog_stall_*.txt
  + 主日志 CRITICAL 记录卡死时长。
- 同一次卡死期内每 60s 最多补 dump 一次（阻塞点可能移动）；心跳恢复后复位。
"""

import os
import time
import threading
import logging
import faulthandler
from datetime import datetime

_CHECK_INTERVAL = 2.0     # 心跳投递间隔（秒）
_STALL_THRESHOLD = 15.0   # 超过该时长无心跳 → 判定事件循环卡死（秒）
_RE_DUMP_INTERVAL = 60.0  # 同一次卡死期内，补 dump 的最小间隔（秒）


class _LoopWatchdog:
    """单例。start() 幂等，重复调用无副作用。"""

    def __init__(self):
        self._thread = None
        self._lock = threading.Lock()
        self._last_beat = 0.0
        self._loop = None
        self._logger = None
        self._logs_dir = "."
        self._last_dump_ts = 0.0

    def _touch(self):
        """心跳回调：跑在事件循环线程上。"""
        self._last_beat = time.time()

    def _dump_stacks(self, stall_secs: float):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(self._logs_dir, f"watchdog_stall_{ts}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"[loop-watchdog] 事件循环无响应 {stall_secs:.1f}s @ {datetime.now()}\n")
                f.write(f"[loop-watchdog] 以下为全部线程调用栈（阻塞点=事件循环/MainThread 当前栈）\n")
                f.write("=" * 80 + "\n")
                faulthandler.dump_traceback(file=f, all_threads=True)
            self._logger.critical(
                f"🔴 [loop-watchdog] 事件循环已无响应 {stall_secs:.1f}s！全线程栈已写入 {path}"
            )
        except Exception as e:  # dump 本身绝不允许抛异常
            try:
                self._logger.error(f"[loop-watchdog] dump 失败: {e}")
            except Exception:
                pass

    def _run(self):
        while True:
            time.sleep(_CHECK_INTERVAL)
            loop = self._loop
            if loop is None:
                continue
            try:
                loop.call_soon_threadsafe(self._touch)
            except RuntimeError:
                # loop 已关闭（进程退出中），安静退出
                return
            except Exception:
                continue

            now = time.time()
            stall = now - self._last_beat
            if stall < _STALL_THRESHOLD:
                continue
            # 卡死：限频 dump（60s 一次），恢复由 _touch 天然复位（last_beat 刷新后 stall 归零）
            if now - self._last_dump_ts < _RE_DUMP_INTERVAL:
                continue
            self._last_dump_ts = now
            self._dump_stacks(stall)

    def start(self, loop, logger: logging.Logger, logs_dir: str):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop = loop
            self._logger = logger
            self._logs_dir = logs_dir
            self._last_beat = time.time()
            self._last_dump_ts = 0.0
            self._thread = threading.Thread(
                target=self._run, name="loop-watchdog", daemon=True
            )
            self._thread.start()
            logger.info(
                f"🛡️ [loop-watchdog] 已启动（阈值 {_STALL_THRESHOLD:.0f}s，"
                f"卡死时全线程栈自动落盘 logs/watchdog_stall_*.txt）"
            )


loop_watchdog = _LoopWatchdog()
