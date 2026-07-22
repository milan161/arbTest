import os
import sys
import json
import subprocess
import threading
import pandas as pd
import logging
from logging.handlers import RotatingFileHandler
import uvicorn
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from datetime import datetime

# Setup logging
backend_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(backend_dir, ".."))
logs_dir = os.path.join(workspace_root, "logs")  # [AI-2026-07-02] 日志集中到 ArbDashboard/logs/

if not os.path.exists(logs_dir):
    os.makedirs(logs_dir, exist_ok=True)

log_filename = datetime.now().strftime("%Y-%m-%d_%H%M%S.log")
log_filepath = os.path.join(logs_dir, log_filename)

log_format = '%(asctime)s - %(levelname)s - %(message)s - %(name)s'

class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[94m',
        'INFO': '\033[92m',       # Green
        'WARNING': '\033[93m',    # Yellow
        'ERROR': '\033[91m',      # Red
        'CRITICAL': '\033[1;91m'  # Bold Red
    }
    RESET = '\033[0m'
    
    def format(self, record):
        original_levelname = record.levelname
        color = self.COLORS.get(original_levelname, self.RESET)
        record.levelname = f"{color}{original_levelname}{self.RESET}"
        formatted = super().format(record)
        record.levelname = original_levelname
        return formatted

# Setup File Handler (no colors)
file_handler = RotatingFileHandler(
    log_filepath,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter(log_format))

# Setup Console Handler (with colors)
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter(log_format))

# Configure Root Logger
logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger("ArbNext")

# [Master-Slave] 检查主交易程序 (LOFarb) 是否运行
# 强制设为 False，防止 opencode cli 等占用 5000 端口导致误判为 Slave 只读模式
lof_is_running = False

# [V4.4] 强力补丁：全局唯一 TQ 抢占与锁定
# [V10.0] 启动时不自动连接通达信，跳过 TQ 全局初始化（用户点击"通达信"按钮时才需要）
# 用户手动重连通达信时，TdxRealtimeFetcher.connect() 会自行完成 TQ 初始化
logger.info("[V10.0] 跳过 TQ 全局初始化（通达信待用户手动连接）")

# Add project root and core/arbcore to path
# [FIX] 使用 D:\Study\arbTest\arbcore 作为核心模块目录
backend_dir = os.path.dirname(os.path.abspath(__file__))
# arbcore 在 ArbDashboard 的上级目录 (D:\Study\arbTest\arbcore)
# 需要添加 D:\Study\arbTest 到 sys.path，这样 Python 才能找到 arbcore 包
arbcore_parent = os.path.normpath(os.path.join(backend_dir, "..", ".."))
arbcore_dir = os.path.join(arbcore_parent, "arbcore")
if os.path.exists(arbcore_dir):
    sys.path.insert(0, arbcore_parent)
    logger.info(f"使用 arbcore 目录: {arbcore_dir} (父目录: {arbcore_parent})")
else:
    # 降级：尝试使用 backend/core
    fallback_dir = os.path.join(backend_dir, "core")
    if os.path.exists(fallback_dir):
        sys.path.insert(0, fallback_dir)
        logger.warning(f"arbcore 目录不存在，使用降级目录: {fallback_dir}")
    else:
        raise RuntimeError(f"既找不到 {arbcore_dir}，也找不到 {fallback_dir}")

# 1. [V3.11 统一数据库路径]
root_db_path = os.path.abspath(os.path.join(workspace_root, "..", "database", "arb_master.db"))
logger.info(f"📂 Using database at {root_db_path}")

# Define project root (ArbDashboard directory)
project_root = workspace_root
logger.info(f"📁 Project root: {project_root}")

try:
    from arbcore.database.db_manager import DatabaseManager
    from services.fund_service import FundService
    from services.config_service import ConfigService
    from services.market_data_service import MarketDataService
    from services.system_status_service import system_status
    from services.intraday.sampler_service import IntradaySamplerService
    from services.dashboard_snapshot_service import DashboardSnapshotService
    from services.trading_service import TradingService
    from services.config_manager_service import ConfigManagerService
    from services.ledger_service import LedgerService
    from services.etf_rotation_service import ETFRotationService

    # [AI-2026-07-02] 旧版信号监测引擎 (已从 private/ 移出到 services/，需要上传 GitHub)
    try:
        from services.auto_trade.engine_runner import auto_trade_runner
    except ImportError:
        class DummyRunner:
            running = False
            def start(self): pass
            def stop(self): pass
            def get_recent_logs(self): return []
        auto_trade_runner = DummyRunner()
        auto_trade_runner.engine = type("DummyEngine", (), {"rules": [], "add_rule": lambda *a: "", "update_rule": lambda *a: False, "delete_rule": lambda *a: None, "save_rules": lambda *a: None})()

    logger.info("Core modules imported successfully")
except Exception as e:
    logger.error(f"Failed to import core modules: {e}")
    raise

# 2. Initialize Database Manager FIRST
# [V3.11] 使用统一数据库路径 D:\Study\arbTest\database\arb_master.db
db = DatabaseManager(db_path=root_db_path)

def _print_data_source_banners():
    """启动后统一打印各数据源连接状态（清晰的双层提醒标志）并写入里程碑日志"""
    rt = market_data_service.realtime_manager
    active = rt.active_fetchers if rt else {}

    def _is_fetcher_connected(fetcher) -> bool:
        """检查实时行情 fetcher 是否真正已连接（不为 None、未 disabled）"""
        if fetcher is None:
            return False
        if getattr(fetcher, 'disabled', False):
            return False
        if getattr(fetcher, 'is_connected', True) is False:
            return False
        return True

    sources = [
        ("tdx",    "通达信",  _is_fetcher_connected(active.get("tdx")),
         "请点击顶部'通达信'按钮启动"),
        ("guojin", "国金QMT", _is_fetcher_connected(active.get("guojin")),
         "请点击顶部'国金QMT'按钮启动"),
        ("galaxy", "银河QMT", _is_fetcher_connected(active.get("galaxy")),
         "请点击顶部'银河QMT'按钮启动"),
        ("ib",     "IB 盈透证券",
         market_data_service.ib_reader is not None and getattr(market_data_service.ib_reader, 'connected', False),
         "请点击顶部'IB'按钮启动"),
        ("futu",   "富途 OpenD",
         market_data_service.futu_reader is not None and not getattr(market_data_service.futu_reader, 'disabled', True),
         "请点击顶部'富途'按钮启动"),
    ]

    for key, label, available, hint in sources:
        if available:
            logger.info(f"{label} 连接正常")
            system_status.add_milestone("SUCCESS", f"{label} 连接正常")
        else:
            logger.info(f"{label} 待连接")
            system_status.add_milestone("INFO", f"{label} {hint}")

# 2. Initialize Services with DB instance
config_service = ConfigService(db)
# [V4.5 紧急隔离重构] 采用主从架构动态判断交易服务
if lof_is_running:
    trading_service = None
    logger.warning("[主从架构] 已禁用交易服务(TradingService)，以避免与运行中的主程序冲突。")
else:
    try:
        # 如果主程序没运行，尝试启动交易服务 (仅供测试或单机模式)
        from services.trading_service import TradingService
        trading_service = TradingService(db)
        
        # [V4.7] 修改：放开通达信强制绑定限制，允许系统在只有 QMT 的情况下启动
        if sys.platform == "win32" and (not trading_service.trade_manager or not getattr(trading_service.trade_manager, 'tdx_available', False)):
            logger.warning("交易通道部分受限 (未检测到通达信登录)")
            print("\n提示: tdx_available = False (如果您仅使用 QMT 交易，这完全正常)。系统将继续启动...\n")
        else:
            logger.info("交易服务已就绪 (独立模式)")
    except SystemExit:
        logger.warning("交易服务初始化被中止 (SystemExit)，系统继续运行，交易功能不可用。")
        trading_service = None
    except Exception as e:
        logger.error(f"交易服务启动失败: {e}")
        trading_service = None 
_active_watchlist = []
_nav_last_updated = {"time": None, "date": None}
_nav_scheduled_today_date = ""
_morning_refreshed_today = False
_morning_refresh_time = None
market_data_service = MarketDataService(db)
fund_service = FundService(db, market_data_service=market_data_service, config_service=config_service)
sampler_service = IntradaySamplerService(db, market_data_service, config_service)
sampler_service.active_watchlist = _active_watchlist
dashboard_snapshot_service = DashboardSnapshotService(
    fund_service,
    market_data_service=market_data_service,
)
config_manager_service = ConfigManagerService(project_root)
ledger_service = LedgerService(db)
etf_rotation_service = ETFRotationService(db, market_data_service=market_data_service)

def _is_script_running(script_name: str) -> bool:
    """Best-effort process guard for background scripts."""
    try:
        import subprocess
        if sys.platform == "win32":
            output = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "Select-Object -ExpandProperty CommandLine"],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        else:
            output = subprocess.check_output(["ps", "axo", "command"], text=True, timeout=5)
        current_pid = str(os.getpid())
        for line in output.splitlines():
            if script_name in line and current_pid not in line:
                return True
    except Exception as e:
        logger.debug(f"Process guard failed for {script_name}: {e}")
    return False

def _popen_script_once(cmd, cwd, script_name: str) -> bool:
    if _is_script_running(script_name):
        logger.info(f"{script_name} is already running, skip duplicate launch")
        system_status.add_milestone("INFO", f"{script_name} 已在运行，跳过重复启动")
        return False
    subprocess.Popen(cmd, cwd=cwd)
    return True

# 3. Try to load Private Plugins
try:
    from private.export_service import PrivateExportService
    export_service = PrivateExportService(root_db_path, project_root)
    logger.info("Private export plugins loaded.")
except (ImportError, NameError) as e:
    export_service = None
    logger.info(f"Private export plugins not found or initialization failed: {e}")

try:
    from private.lazy_trader import lazy_trader_instance
    # 注入实盘驱动
    ib_reader = getattr(market_data_service, 'ib_reader', None)
    galaxy_qmt = None
    guojin_qmt = None
    if getattr(market_data_service, 'realtime_manager', None):
        rt = market_data_service.realtime_manager
        galaxy_qmt = rt.active_fetchers.get('galaxy')
        guojin_qmt = rt.active_fetchers.get('guojin')
    lazy_trader_instance.inject_drivers(ib_reader=ib_reader, galaxy_qmt=galaxy_qmt, guojin_qmt=guojin_qmt)
    # [AI-2026-07-15] 注入自动开仓所需服务
    lazy_trader_instance.inject_services(fund_service=fund_service, trading_service=trading_service)
    logger.info("✅ Lazy Trader plugin loaded.")
except (ImportError, NameError) as e:
    lazy_trader_instance = None
    logger.info(f"Lazy Trader plugin not found: {e}")

# Lazy Simulator (weekend mock data)
try:
    from private.lazy_simulator import lazy_simulator_instance
    logger.info("Lazy Simulator loaded.")
except (ImportError, NameError) as e:
    lazy_simulator_instance = None
    logger.info(f"Lazy Simulator not found: {e}")

# [AI-2026-07-01] 导入 DB 驱动规则引擎（LazyMode 自动化规则）
try:
    from private.rule_engine import rule_engine
    # 注入依赖
    rule_engine.inject(fund_service=fund_service, lazy_trader=lazy_trader_instance, trading_service=trading_service, db_path=root_db_path)
    logger.info("✅ RuleEngine (DB驱动) loaded.")
except (ImportError, NameError) as e:
    rule_engine = None
    logger.info(f"RuleEngine not found: {e}")

# [AI-2026-07-17] SmartOpenMonitor（智能开仓/平仓监控器）
try:
    from private.smart_open_monitor import start_monitor as _smart_start, stop_monitor as _smart_stop, get_monitor_status as _smart_status, update_monitor_target as _smart_update_target
    # 注入依赖的全局实例
    _smart_mds = market_data_service
    _smart_fs = fund_service
    _smart_ts = trading_service
    _smart_lt = lazy_trader_instance
    logger.info("✅ SmartOpenMonitor loaded.")
except (ImportError, NameError) as e:
    _smart_start = _smart_stop = _smart_status = None
    logger.info(f"SmartOpenMonitor not loaded: {e}")

try:
    from services.signal_detector import signal_detector
    signal_detector.inject(
        rule_engine=auto_trade_runner.engine,
        fund_service=fund_service,
    )
    logger.info("✅ SignalDetector loaded.")
except (ImportError, NameError) as e:
    signal_detector = None
    logger.info(f"SignalDetector not loaded: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ArbNext Backend lifespan...")
    try:
        import asyncio
        
        # 1. [核心策略] 启动即运行一次 011 数据更新（异步，不需要通达信）
        # 011只读取历史数据并写入数据库，与通达信实时行情不冲突
        async def run_011_first():
            if sys.platform != "win32":
                logger.info("📊 [Cloud] 云端部署环境，静默跳过 011 本地数据更新任务")
                system_status.add_milestone("INFO", "云端部署，跳过本地数据同步")
                return

            logger.info("📊 启动时自动运行 011 数据更新任务...")
            system_status.add_milestone("INFO", "启动时自动运行 011 数据更新")
            print("daily_updater 即将启动...")
            # [AI-2026-06-28] 修复：daily_updater.py 在 scheduler/ 下，不在 arbcore/scripts/
            scripts_dir = os.path.normpath(os.path.join(backend_dir, "scheduler"))
            script_path = os.path.join(scripts_dir, "daily_updater.py")
            
            # [V4.1] 尝试多种 Python 路径
            python_exe_candidates = [
                os.path.normpath(os.path.join(backend_dir, "..", "..", ".venv", "Scripts", "python.exe")),
                os.path.normpath(os.path.join(backend_dir, "..", "..", "..", ".venv", "Scripts", "python.exe")),
                os.path.normpath(os.path.join(backend_dir, "..", "..", "..", "Python311", "python.exe")),
                "python",
            ]
            
            python_exe = None
            for candidate in python_exe_candidates:
                if os.path.exists(candidate):
                    python_exe = candidate
                    logger.info(f"✅ 找到 Python: {python_exe}")
                    break
            
            if python_exe and os.path.exists(script_path):
                try:
                    if _popen_script_once([python_exe, script_path], scripts_dir, "daily_updater.py"):
                        logger.info("011 任务已在后台启动 (daily_updater)")
                        system_status.add_milestone("SUCCESS", "011 数据更新任务已启动")
                except Exception as e:
                    logger.error(f"011 任务启动失败: {e}")
                    system_status.add_milestone("ERROR", f"011 任务启动失败: {e}")
            else:
                logger.info(f"ℹ️ 未检测到 011 脚本，跳过自动更新")
                system_status.add_milestone("INFO", "未检测到 011 脚本，跳过自动更新")
        
        asyncio.create_task(run_011_first())

        # 2. 启动分时采样服务
        await sampler_service.start()
        if sampler_service.running:
            system_status.add_milestone("SUCCESS", "分时采样服务已启动")
        else:
            system_status.add_milestone("INFO", "分时采样服务未启动 (已配置禁用)")

        # 3. 启动实时行情引擎（延迟10秒，等 011 任务先跑起来）
        # 011 需要 1-2 分钟，通达信可以稍后启动
        await dashboard_snapshot_service.start()
        system_status.add_milestone("SUCCESS", "Dashboard 快照服务已启动")

        async def start_mds_later():
            await asyncio.sleep(10)
            try:
                market_data_service.realtime_manager.start()
                logger.info("实时行情引擎已在后台启动")
                system_status.add_milestone("SUCCESS", "实时行情引擎已启动")
            except Exception as e:
                logger.error(f"实时行情引擎启动失败: {e}")
                system_status.add_milestone("ERROR", f"实时行情引擎启动失败: {e}")

            # 延迟获取各数据源连接状态，确保所有异步初始化已完成
            await asyncio.sleep(2)
            _print_data_source_banners()
            
            # [V10.0] 启动完成提示：引导用户手动连接需要的券商客户端
            system_status.add_milestone("INFO", "💡 如需实时行情，请点击顶部对应按钮连接券商客户端（通达信/IB/银河QMT/国金QMT/富途）")
            
            # [AI-2026-07-07] 启动时自动检测并连接 IB Gateway（如果已在运行）
            try:
                if market_data_service.ib_reader:
                    success, msg = market_data_service.ib_reader.reconnect()
                    if success:
                        logger.info(f"✅ IB Gateway 自动连接成功")
                        system_status.add_milestone("SUCCESS", "IB Gateway 自动连接成功")
                    else:
                        logger.info(f"ℹ️ IB Gateway 自动连接跳过: {msg}")
                        system_status.add_milestone("INFO", f"IB Gateway 未检测到: {msg}")
            except Exception as e:
                logger.warning(f"IB 自动连接异常: {e}")
        
        asyncio.create_task(start_mds_later())

        # SignalDetector（信号检测引擎 — 默认不启动，用户手动开启）
        if signal_detector:
            logger.info("SignalDetector 已就绪，等待用户手动启动")
            system_status.add_milestone("INFO", "信号检测引擎就绪")
        else:
            logger.info("SignalDetector 未加载")
            system_status.add_milestone("INFO", "信号检测引擎未加载")

        # 5. 定义脚本路径和 Python 查找的公共函数
        def _get_scripts_dir():
            # [AI-2026-06-28] daily_updater.py 在 scheduler/ 下
            return os.path.normpath(os.path.join(backend_dir, "scheduler"))
        def _find_python():
            for candidate in [
                os.path.normpath(os.path.join(backend_dir, "..", "..", ".venv", "Scripts", "python.exe")),
                os.path.normpath(os.path.join(backend_dir, "..", "..", "..", ".venv", "Scripts", "python.exe")),
                "python",
            ]:
                if os.path.exists(candidate):
                    return candidate
            return None
        def _run_daily_updater(args_list):
            sd = _get_scripts_dir()
            sp = os.path.join(sd, "daily_updater.py")
            pe = _find_python()
            if pe and os.path.exists(sp):
                return _popen_script_once([pe, sp] + args_list, sd, "daily_updater.py")
            return False

        # 6. [V9.0] 9:20 清晨自动刷新 Woody/汇率/VPS
        global _morning_refreshed_today, _morning_refresh_time
        async def morning_refresh_scheduler():
            global _morning_refreshed_today, _morning_refresh_time
            while True:
                await asyncio.sleep(300)
                now = datetime.now()
                if now.weekday() in (5, 6):
                    _morning_refreshed_today = False
                    continue
                today = now.strftime("%Y-%m-%d")
                if _morning_refreshed_today and today != _morning_refresh_time:
                    _morning_refreshed_today = False  # 新的一天
                if not _morning_refreshed_today and now.hour >= 9 and (now.hour > 9 or now.minute >= 20):
                    _morning_refreshed_today = True
                    _morning_refresh_time = today
                    logger.info("⏰ [清晨刷新] 自动触发 --refresh-morning (Woody/汇率/VPS)")
                    system_status.add_milestone("INFO", "⏰ 9:20 自动清晨数据刷新")
                    if _run_daily_updater(["--refresh-morning"]):
                        logger.info("✅ [清晨刷新] 已启动 --refresh-morning")
                    else:
                        logger.warning("⚠️ [清晨刷新] 启动失败")

        asyncio.create_task(morning_refresh_scheduler())
        logger.info("⏰ [清晨刷新] 定时器已注册 (9:20 自动刷新 Woody/汇率/VPS)")

        # 7. [V9.0] 净值定时更新：下午 18:00 / 19:30 / 21:00 自动补跑 step4
        global _nav_last_updated, _nav_scheduled_today_date
        _nav_slot_done = set()
        
        async def nav_update_scheduler():
            global _nav_last_updated, _nav_scheduled_today_date
            run_at = ["18:00", "19:30", "21:00"]
            while True:
                await asyncio.sleep(300)
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                if now.weekday() in (5, 6):
                    _nav_slot_done.clear()
                    continue
                if today != _nav_scheduled_today_date:
                    _nav_scheduled_today_date = today
                    _nav_slot_done.clear()
                    _nav_last_updated = {"time": None, "date": None}
                hm = now.strftime("%H:%M")
                for slot in run_at:
                    if slot not in _nav_slot_done and hm >= slot:
                        _nav_slot_done.add(slot)
                        logger.info(f"⏰ [自动净值更新] 触发定时 {slot} 净值更新...")
                        system_status.add_milestone("INFO", f"⏰ 定时净值更新 ({slot})")
                        if _run_daily_updater(["--nav-only"]):
                            _nav_last_updated["time"] = now.strftime("%H:%M")
                            _nav_last_updated["date"] = today
                            logger.info(f"✅ [自动净值更新] 定时 {slot} 已启动 --nav-only")
                        else:
                            logger.warning(f"⚠️ [自动净值更新] 启动失败")
        
        asyncio.create_task(nav_update_scheduler())
        logger.info("⏰ [自动净值更新] 定时器已注册 (18:00 / 19:30 / 21:00)")

    except Exception as e:
        logger.error(f"❌ Failed during backend startup: {e}")
        system_status.add_milestone("ERROR", f"系统启动自检异常: {e}")

    yield

    logger.info("🛠️ Shutting down ArbNext Backend...")
    await dashboard_snapshot_service.stop()
    await sampler_service.stop()
    if signal_detector:
        signal_detector.stop()
    auto_trade_runner.stop()
    market_data_service.realtime_manager.stop()
    # [AI-2026-07-13] 先 stop_polling() 再 disconnect()，防止 polling 线程抢重连
    if market_data_service and market_data_service.ib_reader:
        market_data_service.ib_reader.stop_polling()
        market_data_service.ib_reader.disconnect_from_ib()

app = FastAPI(title="ArbNext API", version="1.0.0", lifespan=lifespan)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/health")
async def get_health():
    return {"status": "ok", "db": root_db_path}

# [V6.0] 存储前端传递的最新自选基金列表（用于采样服务过滤）
# (已在服务初始化前定义)

# [AI-2026-07-13] 导出十天历史数据库（供分享/分析用）
@app.get("/api/db/export_share")
async def export_share_db():
    """生成最新 10 天的 arb_master_share.db 并返回下载"""
    import sqlite3
    from datetime import datetime, timedelta
    import tempfile
    import shutil

    src = root_db_path
    if not os.path.exists(src):
        return JSONResponse(status_code=404, content={"status": "error", "message": "源数据库不存在"})

    cutoff = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    tmp_path = os.path.join(tempfile.gettempdir(), f"arb_master_share_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db")

    # 日期过滤映射: {表名: (日期列名: str | None)}，None 表示全部复制
    date_filter_map = {
        'access_sync_status': 'sync_date',
        'app_settings': None,
        'auto_trade_rules': None,
        'broker_redemption_fees': None,
        'data_source_config': None,
        'etf_raw_api_data': None,
        'etf_rotation_list': None,
        'exchange_rate': 'date',
        'fund_basket_weights': 'date',
        'fund_daily_factors': 'date',
        'fund_fees': None,
        'fund_purchase_status': None,        # 全部保留（金额配置）
        'futures_daily': 'date',
        'index_history': 'date',
        'index_realtime_quotes': None,
        'raw_api_data': 'date',
        'system_health': None,
        'unified_fund_history': 'date',
        'unified_fund_list': None,
        'usa_etf_daily_prices': 'date',
        'user_trades': 'trade_date',
    }

    try:
        conn_src = sqlite3.connect(src)
        conn_dst = sqlite3.connect(tmp_path)
        cur = conn_src.cursor()

        tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        total = 0

        for (t,) in tables:
            if t == 'sqlite_sequence':
                continue
            if t not in date_filter_map:
                continue

            # 建表
            sql = cur.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{t}'").fetchone()
            if not sql or not sql[0]:
                continue
            conn_dst.execute(sql[0])

            # 用 PRAGMA table_info 获取列数（避免 cur.description 被前面的查询覆盖）
            col_info = cur.execute(f"PRAGMA table_info({t})").fetchall()
            n_cols = len(col_info)
            placeholders = ','.join(['?'] * n_cols)

            date_col = date_filter_map[t]
            if date_col is None:
                rows = cur.execute(f"SELECT * FROM {t}").fetchall()
                conn_dst.executemany(f"INSERT INTO {t} VALUES ({placeholders})", rows)
                cnt = len(rows)
            else:
                rows = cur.execute(f"SELECT * FROM {t} WHERE {date_col} >= ?", (cutoff,)).fetchall()
                conn_dst.executemany(f"INSERT INTO {t} VALUES ({placeholders})", rows)
                cnt = len(rows)

            total += cnt
            logger.info(f"  {t}: {cnt} rows{' (filtered)' if date_col else ' (all)'}")

        conn_dst.commit()
        conn_src.close()
        conn_dst.close()

        logger.info(f"✅ 分享库已生成: {tmp_path} ({total} rows, cutoff={cutoff})")

        # 返回文件下载
        return FileResponse(
            tmp_path,
            media_type="application/octet-stream",
            filename=f"arb_master_share_{datetime.now().strftime('%Y%m%d')}.db",
            headers={"Content-Disposition": f"attachment; filename=arb_master_share_{datetime.now().strftime('%Y%m%d')}.db"}
        )
    except Exception as e:
        logger.error(f"❌ 生成分享库失败: {e}")
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/dashboard")
async def get_dashboard(watchlist: str = None, category: str = None):
    """Unified dashboard data for both LOF and JSL
    Reads a background snapshot so UI polling never performs slow valuation
    work inline.
    """
    try:
        import traceback
        requested_watchlist = [code.strip() for code in watchlist.split(',') if code.strip()] if watchlist else None
        snapshot = dashboard_snapshot_service.get_snapshot(
            watchlist=requested_watchlist,
            category=category,
        )
        return {
            "status": "ok",
            "data": snapshot.get("data", []),
            "updated_at": snapshot.get("updated_at"),
            "stale": snapshot.get("stale", False),
            "source_status": snapshot.get("source_status", {}),
            "compute_ms": snapshot.get("compute_ms", 0),
            "error": snapshot.get("error"),
        }
    except Exception as e:
        msg = f"Dashboard API Error: {e}"
        logger.error(msg)
        logger.error(traceback.format_exc())  # 添加详细堆栈跟踪
        system_status.add_milestone("ERROR", msg)
        return JSONResponse(status_code=500, content={"status": "error", "message": msg})

@app.get("/api/market/overview")
async def get_market():
    try:
        data = fund_service.get_market_overview(market_data_service=market_data_service)
        return {"status": "ok", "data": data}
    except Exception as e:
        logger.error(f"Market Overview Error: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/system/milestones")
async def get_system_milestones():
    """获取系统运行里程碑日志"""
    return {"status": "ok", "data": system_status.get_milestones()}

@app.get("/api/fund/{code}/history")
async def get_fund_history(code: str):
    data = fund_service.get_fund_history(code)
    return {"status": "ok", "data": data}

@app.get("/api/fund/{code}/intraday")
async def get_fund_intraday(code: str, date: str = None):
    """获取基金的分时数据（曲线图用）"""
    data = fund_service.get_fund_intraday(code, date)
    return {"status": "ok", "data": data}

@app.get("/api/fund/{code}/basket")
async def get_fund_basket(code: str):
    data = fund_service.get_fund_basket(code)
    return {"status": "ok", "data": data}

@app.get("/api/fund/hedge_multipliers")
async def get_hedge_multipliers():
    """获取所有期货乘数配置（前端沙盘可调用）"""
    from arbcore.config.futures_multipliers import list_all_multipliers
    return {"status": "ok", "data": list_all_multipliers()}

@app.get("/api/fund/{code}/valuation_meta")
async def get_fund_valuation_meta(code: str):
    """估值元数据 — 委托 fund_service.get_valuation_meta() [AI-2026-07-16 消除代码重复]"""
    try:
        return fund_service.get_valuation_meta(code)
    except Exception as e:
        logger.error(f"Error getting valuation meta for {code}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e)}


# --- 国开债BP数据接口 (511520估值校准) ---
@app.get("/api/bond/bp-data")
async def get_bp_data(date: str = None):
    """获取国开债BP数据"""
    try:
        bv = get_bond_etf_valuation(fund_service.db, market_data_service)
        if date:
            data = bv.get_bp_data(date)
            return {"status": "ok", "data": data}
        else:
            data = bv.get_recent_bp_data(days=10)
            return {"status": "ok", "data": data}
    except Exception as e:
        logger.error(f"获取BP数据失败: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/bond/bp-data")
async def save_bp_data(request: Request):
    """保存国开债BP数据（手动输入）"""
    try:
        data = await request.json()
        date = data.get('date')
        if not date:
            return {"status": "error", "message": "日期不能为空"}
        
        bv = get_bond_etf_valuation(fund_service.db, market_data_service)
        success = bv.save_bp_data(
            date=date,
            cdb_7y_bp=data.get('cdb_7y_bp'),
            cdb_10y_bp=data.get('cdb_10y_bp'),
            treasury_7y_bp=data.get('treasury_7y_bp'),
            treasury_10y_bp=data.get('treasury_10y_bp'),
            note=data.get('note')
        )
        return {"status": "ok" if success else "error"}
    except Exception as e:
        logger.error(f"保存BP数据失败: {e}")
        return {"status": "error", "message": str(e)}


# --- Core Fund Configuration (YAML) APIs ---
@app.get("/api/config/funds")
async def get_all_fund_configs():
    """获取 lof_config.yaml 中的所有基金配置"""
    cfg = config_manager_service.load_config()
    return {"status": "ok", "data": cfg.get('funds', [])}

# [AI-2026-07-09] 根治：YAML 改动后自动同步 unified_fund_list 表，主看板即时生效，不再需要手动跑同步脚本
def _sync_config_to_db():
    try:
        cfg = config_manager_service.load_config()
        db.sync_unified_fund_list(cfg.get('funds', []))
    except Exception as e:
        logger.error(f"[配置同步] YAML→数据库失败: {e}")

@app.post("/api/config/funds/upsert")
async def upsert_fund_config(request: Request):
    """新增或修改基金配置，并自动同步数据库"""
    data = await request.json()
    success = config_manager_service.upsert_fund_config(data)
    if success:
        _sync_config_to_db()
    return {"status": "ok" if success else "error"}

@app.delete("/api/config/funds/{code}")
async def delete_fund_config(code: str):
    """从 YAML 中删除基金，并自动同步数据库"""
    success = config_manager_service.delete_fund_config(code)
    if success:
        _sync_config_to_db()
    return {"status": "ok" if success else "error"}

@app.get("/api/config/funds/export")
async def export_fund_config():
    """导出 lof_config.yaml 为文件下载（带时间戳文件名）"""
    from fastapi.responses import Response
    try:
        yaml_content = config_manager_service.export_config()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"lof_config_{ts}.yaml"
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        logger.error(f"导出 YAML 失败: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/config/funds/import")
async def import_fund_config(file: UploadFile = File(...)):
    """从上传的 YAML 文件导入基金配置，并自动同步数据库"""
    try:
        content = await file.read()
        yaml_text = content.decode('utf-8')
        config_manager_service.import_config(yaml_text)
        _sync_config_to_db()
        return {"status": "ok", "message": "导入成功，旧配置已备份为 .bak"}
    except Exception as e:
        logger.error(f"导入 YAML 失败: {e}")
        return {"status": "error", "message": str(e)}

# [AI-2026-07-09] 动态 TAB：返回 unified_fund_list 中所有去重的基金分类，供主看板动态生成 TAB
@app.get("/api/config/categories")
async def get_fund_categories():
    """返回数据库中所有真实存在的基金分类（去重）"""
    try:
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT DISTINCT category FROM unified_fund_list WHERE category IS NOT NULL AND category != ''"
        ).fetchall()
        conn.close()
        cats = sorted({r[0] for r in rows if r[0]})
        return {"status": "ok", "data": cats}
    except Exception as e:
        logger.error(f"获取基金分类失败: {e}")
        return {"status": "error", "message": str(e)}

# --- IB 核心套利标的配置 APIs ---
@app.get("/api/config/ib_core_symbols")
async def get_ib_core_symbols():
    """获取 IB 核心套利标的白名单"""
    from arbcore.config.symbol_source_map import IB_CORE_ARBITRAGE_SYMBOLS
    return {"status": "ok", "data": IB_CORE_ARBITRAGE_SYMBOLS}

@app.post("/api/config/ib_core_symbols")
async def update_ib_core_symbols(request: Request):
    """更新 IB 核心套利标的白名单（运行时生效，不持久化到文件）"""
    from arbcore.config.symbol_source_map import IB_CORE_ARBITRAGE_SYMBOLS, SOURCE_SYMBOL_MAP, US_ETF_MAP
    try:
        data = await request.json()
        symbols = data.get('symbols', [])
        
        if not symbols:
            return {"status": "error", "message": "标的列表不能为空"}
        
        # 验证：所有标的必须在 US_ETF_MAP 中
        for sym in symbols:
            if sym not in US_ETF_MAP:
                return {"status": "error", "message": f"标的 {sym} 不在美股 ETF 映射表中"}
        
        # 更新全局变量
        IB_CORE_ARBITRAGE_SYMBOLS.clear()
        IB_CORE_ARBITRAGE_SYMBOLS.extend(symbols)
        
        # 重建 SOURCE_SYMBOL_MAP
        SOURCE_SYMBOL_MAP['IB'] = list(symbols)
        SOURCE_SYMBOL_MAP['IB_CORE_ONLY'] = list(symbols)
        
        # 重新分流：非核心标的归入 FUTU
        for symbol, source in {**US_ETF_MAP}.items():
            if source == 'IB' and symbol not in symbols:
                if symbol not in SOURCE_SYMBOL_MAP['FUTU']:
                    SOURCE_SYMBOL_MAP['FUTU'].append(symbol)
        
        # 去重排序
        for source in SOURCE_SYMBOL_MAP:
            SOURCE_SYMBOL_MAP[source] = sorted(set(SOURCE_SYMBOL_MAP[source]))
        
        return {"status": "ok", "message": f"IB 核心标的已更新为 {len(symbols)} 只", "data": symbols}
    except Exception as e:
        logger.error(f"更新 IB 核心标的失败: {e}")
        return {"status": "error", "message": str(e)}

# --- [AI-2026-07-07] App-level toggle settings ---
# 分类暂停管理（替换旧的 skip_qdii_asia_index 单一开关）
ALL_CATEGORIES = ["黄金原油", "QDII欧美", "QDII日本", "白银", "QDII亚洲", "国内LOF", "现金管理"]
DEFAULT_PAUSED_CATEGORIES = ["QDII亚洲", "国内LOF", "现金管理"]

@app.get("/api/config/app_settings/paused_categories")
async def get_paused_categories():
    """获取已暂停的分类列表（暂停的分类不再生成快照/抓指数/显示在 Dashboard）"""
    raw = db_manager.get_app_setting('paused_categories', None)
    if raw is None:
        # 首次读取：迁移旧的 skip_qdii_asia_index 设置
        old_skip = db_manager.get_app_setting('skip_qdii_asia_index', '1')
        if old_skip == '1':
            paused = DEFAULT_PAUSED_CATEGORIES
        else:
            paused = []
        db_manager.set_app_setting('paused_categories', json.dumps(paused))
        return {"status": "ok", "data": paused}
    try:
        return {"status": "ok", "data": json.loads(raw)}
    except Exception:
        return {"status": "ok", "data": DEFAULT_PAUSED_CATEGORIES}

@app.post("/api/config/app_settings/paused_categories")
async def update_paused_categories(request: Request):
    """设置暂停的分类列表"""
    try:
        data = await request.json()
        paused = data.get('paused', DEFAULT_PAUSED_CATEGORIES)
        # 校验：只接受合法分类名
        valid = [c for c in paused if c in ALL_CATEGORIES]
        db_manager.set_app_setting('paused_categories', json.dumps(valid))
        # 同步更新旧的 skip_qdii_asia_index（向后兼容）
        asia_paused = "QDII亚洲" in valid
        dom_paused = "国内LOF" in valid
        old_skip = '1' if (asia_paused and dom_paused) else '0'
        db_manager.set_app_setting('skip_qdii_asia_index', old_skip)
        # 通知快照服务重新加载暂停配置
        dashboard_snapshot_service.sync_paused_categories(valid)
        return {"status": "ok", "data": valid, "message": "分类优先级已更新"}
    except Exception as e:
        logger.error(f"更新 paused_categories 失败: {e}")
        return {"status": "error", "message": str(e)}

# [AI-2026-07-07] 回补缺失指数历史
@app.post("/api/config/app_settings/backfill_indices")
async def backfill_indices(request: Request):
    """回补缺失的指数历史数据（Sina/腾讯 API）"""
    try:
        data = await request.json() or {}
        days = data.get('days', 30)
        
        from services.index_repair_service import repair_with_sina
        result = repair_with_sina(days_back=days)
        return result
    except Exception as e:
        logger.error(f"回补缺失指数历史失败: {e}")
        return {"status": "error", "message": str(e)}

# --- Private / Custom Export APIs ---
@app.get("/api/private/status")
async def get_private_status():
    """检测私密插件是否挂载"""
    return {"status": "ok", "loaded": export_service is not None}

@app.get("/api/private/export/{code}")
async def export_fund_data(code: str):
    if not export_service:
        logger.warning(f"导出失败: 私有插件未加载 (code={code})")
        return JSONResponse(status_code=403, content={"status": "error", "message": "Private export plugin not loaded"})
    
    csv_data, error = export_service.export_fund_to_csv(code)
    if error:
        logger.error(f"导出失败 (code={code}): {error}")
        return JSONResponse(status_code=500, content={"status": "error", "message": error})
    
    from fastapi.responses import Response
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=fund_export_{code}.csv"
        }
    )

@app.get("/api/private/lazy_calc")
async def lazy_calc(fund_code: str = "162411"):
    """
    幽灵做市商实时计算 — 复用 fund_service.get_valuation_meta() 获取完整估值数据。
    额外计算 Lazy 特有模式（safe/peg）的折溢价。
    """
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})

    try:
        # 1. 复用现有估值元数据（含 hedge、汇率、实时报价、T-1 基准等）
        meta = fund_service.get_valuation_meta(fund_code)
        if meta.get("status") == "error":
            return JSONResponse(status_code=404, content=meta)

        base_data = meta.get("base_data", {})
        fund_cfg = meta.get("fund_config", {})
        rt_quotes = meta.get("realtime_quotes", {})
        t1_data = meta.get("t1_data", {})
        latest_fx = meta.get("latest_exchange_rate", 7.25)

        # 2. 获取 LOF 实时行情
        lof_price = 0.0
        lof_bid = 0.0
        lof_ask = 0.0
        if market_data_service:
            try:
                rt = market_data_service.get_realtime_quote(fund_code)
                if rt:
                    lof_price = rt.get("price", 0) or 0
                    lof_bid = rt.get("bid") or lof_price
                    lof_ask = rt.get("ask") or lof_price
            except Exception:
                pass
        if lof_price <= 0:
            lof_price = float(t1_data.get("price", 0) or 0)
            lof_bid = lof_price
            lof_ask = lof_price

        # 3. 确定 underlying_symbol 和最相关的 ETF 实时价格
        portfolio = fund_cfg.get("valuation_portfolio", [])
        underlying_symbol = portfolio[0].get("symbol", "") if portfolio else ""
        # [V10.8] basket为空时用 trade_etf（related_index）兜底（如162411→XOP）
        if not underlying_symbol:
            underlying_symbol = fund_cfg.get("trade_etf", "")
        underlying_clean = ""
        if underlying_symbol:
            s = underlying_symbol.replace("^", "")
            for suffix in ["-EU", "-JP", "-HK"]:
                if s.endswith(suffix):
                    s = s[: -len(suffix)]
                    break
            underlying_clean = s

        us_bid = 0.0
        us_ask = 0.0
        us_bid_size = 0
        us_ask_size = 0
        # [V10.8] 优先从 rt_quotes 取；basket为空时 rt_quotes 为空，直接行情驱动兜底
        if underlying_clean and underlying_clean in rt_quotes and rt_quotes[underlying_clean]:
            q = rt_quotes[underlying_clean]
            us_bid = float(q.get("bid", 0) or 0)
            us_ask = float(q.get("ask", 0) or 0)
            us_bid_size = int(q.get("bid_size", 0) or 0)
            us_ask_size = int(q.get("ask_size", 0) or 0)
            if us_bid <= 0:
                us_bid = float(q.get("price", 0) or 0)
            if us_ask <= 0:
                us_ask = float(q.get("price", 0) or 0)
        elif underlying_clean and market_data_service:
            try:
                q = market_data_service.get_realtime_quote(underlying_clean)
                if q:
                    us_bid = float(q.get("bid", 0) or 0)
                    us_ask = float(q.get("ask", 0) or 0)
                    us_bid_size = int(q.get("bid_size", 0) or 0)
                    us_ask_size = int(q.get("ask_size", 0) or 0)
                    if us_bid <= 0:
                        us_bid = float(q.get("price", 0) or 0)
                    if us_ask <= 0:
                        us_ask = float(q.get("price", 0) or 0)
            except Exception as e:
                logger.error(f"[LazyCalc] failed to get quote for {underlying_clean}: {e}")

        # 4. hedge 值（复用 get_valuation_meta 返回的）
        hedge = float(base_data.get("hedge", 0)) if base_data else 0
        position = float(fund_cfg.get("position", 95.0)) / 100.0 if fund_cfg else 0.95

        # 5. Lazy 特有溢价计算（safe 砸单 / peg 内卷）
        # 正确公式: val = base_nav * (1 - pos) + (us_price * fx) / hedge  (注意: 第二项不乘pos)
        base_nav = float(base_data.get("nav", 0)) if base_data else 0
        if base_nav > 0 and hedge > 0:
            val_safe = base_nav * (1 - position) + (us_bid * latest_fx) / hedge
        else:
            val_safe = 0
        premium_safe = (lof_bid / val_safe - 1) * 100 if val_safe > 0 else 0

        if base_nav > 0 and hedge > 0:
            peg_price = (us_ask - 0.01) if us_ask > 0.01 else us_ask
            val_peg = base_nav * (1 - position) + (peg_price * latest_fx) / hedge
        else:
            val_peg = 0
        premium_peg = (lof_bid / val_peg - 1) * 100 if val_peg > 0 else 0

        # [AI-2026-07-07] 赎回费率优先从 broker_redemption_fees 表读取
        redemption_fee = ledger_service.get_fee_rate(fund_code)
        if redemption_fee <= 0:
            redemption_fee = 0.50

        result = {
            "fund_code": fund_code,
            "fund_name": fund_cfg.get("trade_etf", ""),
            "underlying_symbol": underlying_symbol,
            "hedge": hedge,
            "position": position,
            "fx_rate": latest_fx,
            "lof_price": lof_price,
            "lof_bid": lof_bid,
            "lof_ask": lof_ask,
            "us_bid": us_bid,
            "us_ask": us_ask,
            "us_bid_size": us_bid_size,
            "us_ask_size": us_ask_size,
            "premium_safe": round(premium_safe, 3),
            "premium_peg": round(premium_peg, 3),
            "redemption_fee": redemption_fee,
        }
        return {"status": "ok", "data": result}

    except Exception as e:
        logger.error(f"[LazyCalc] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/private/lazy_place_order")
async def lazy_place_order(request: Request):
    """
    幽灵做市商下单接口
    - quantity: LOF 份额数（如 59500），系统自动用 hedge 系数换算出 ETF 对冲股数
    - etf_quantity: 可选，如果前端已算好 ETF 股数，直接使用（绕开换算）
    """
    if not lazy_trader_instance:
        logger.warning("[LazyOrder] lazy_trader_instance is None - orders will be rejected")
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    try:
        body = await request.json()
        mode = body.get("mode", "safe")          # "safe"/"peg" 向后兼容
        direction = body.get("direction", "open") # "open" 开仓 / "close" 平仓
        fund_code = body.get("fund_code", "162411")
        underlying_symbol = body.get("underlying_symbol", "XOP")
        price = float(body.get("price", 0))        # open→us_bid1, close→us_ask1
        lof_price = float(body.get("lof_price", 0))  # LOF 限价
        lof_quantity = int(body.get("quantity", 0))
        etf_quantity = int(body.get("etf_quantity", 0))
        logger.info(f"[LazyOrder] mode={mode} dir={direction} fund={fund_code} etf={underlying_symbol} etf_qty={etf_quantity} price={price}")

        # 从 fund_daily_factors 获取 hedge 值（与 Analysis.vue 实时沙盘一致）
        if etf_quantity <= 0 and lof_quantity > 0:
            try:
                conn2 = db._get_conn()
                import pandas as pd
                h_df = pd.read_sql(
                    "SELECT hedge FROM fund_daily_factors "
                    "WHERE fund_code=? AND hedge IS NOT NULL AND hedge > 0 "
                    "ORDER BY date DESC LIMIT 1",
                    conn2, params=[fund_code]
                )
                if not h_df.empty:
                    hedge = float(h_df.iloc[0]['hedge'])
                else:
                    # 兜底：动态推算
                    pos_df = pd.read_sql(
                        "SELECT position FROM fund_daily_factors "
                        "WHERE fund_code=? AND position IS NOT NULL ORDER BY date DESC LIMIT 1",
                        conn2, params=[fund_code]
                    )
                    position = float(pos_df.iloc[0]['position']) if not pos_df.empty else 0.95
                    nav_df = pd.read_sql(
                        "SELECT nav, price FROM unified_fund_history "
                        "WHERE fund_code=? AND nav>0 ORDER BY date DESC LIMIT 1",
                        conn2, params=[fund_code]
                    )
                    nav = float(nav_df.iloc[0]['nav']) if not nav_df.empty else 1.0
                    fx_df = pd.read_sql(
                        "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn2
                    )
                    fx = float(fx_df.iloc[0]['usd_cny_mid']) if not fx_df.empty else 7.25
                    # hedge = (ETF基价 * 汇率) / (净值 * 仓位)
                    # 用 t1 的 etf 收盘价作为基价近似
                    etf_base = 0.0
                    if underlying_symbol:
                        etf_df = pd.read_sql(
                            "SELECT COALESCE(NULLIF(netvalue, 0), price) as price "
                            "FROM usa_etf_daily_prices WHERE symbol LIKE ? "
                            "ORDER BY date DESC LIMIT 1",
                            conn2, params=[f"%{underlying_symbol}%"]
                        )
                        if not etf_df.empty:
                            etf_base = float(etf_df.iloc[0]['price'])
                    if etf_base > 0 and nav > 0 and position > 0:
                        hedge = (etf_base * fx) / (nav * position)
                    else:
                        hedge = 1.0
                conn2.close()
            except Exception:
                hedge = 1.0
            # 换算：ETF 股数 = LOF 份数 / hedge（与 Analysis.vue l.1123 完全一致）
            etf_quantity = max(1, int(round(lof_quantity / hedge)))

        if mode == "peg":
            if direction == "close":
                # [AI-2026-07-16] 加一分排队平仓：IB BUY LMT at bid + 0.01
                results = lazy_trader_instance.place_peg_close_order(
                    underlying_symbol=underlying_symbol,
                    quantity=etf_quantity,
                    us_bid1=price,
                )
            else:
                results = lazy_trader_instance.place_peg_order(
                    underlying_symbol=underlying_symbol,
                    quantity=etf_quantity,
                    us_ask1=price,
                )
        elif direction == "close":
            # [AI-2026-07-16] 立即吃卖一平仓：IB BUY at ask
            results = lazy_trader_instance.place_close_order(
                underlying_symbol=underlying_symbol,
                us_ask1=price,
                etf_quantity=etf_quantity,
            )
        else:
            results = lazy_trader_instance.place_open_order(
                fund_code=fund_code,
                underlying_symbol=underlying_symbol,
                lof_price=lof_price,
                us_bid1=price,
                lof_quantity=lof_quantity,
                etf_quantity=etf_quantity,
            )
        any_ok = any(r.get("success") for r in results)
        logger.info(f"[LazyOrder] mode={mode} dir={direction} → any_ok={any_ok} results={results}")
        return {"status": "ok" if any_ok else "error", "data": results}
    except Exception as e:
        logger.error(f"[LazyOrder] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# [AI-2026-07-15] AutoOpen: 自动排队开仓 API
# 流程：POST /queue 排队LOF → 返回 auto_open_id → 前端轮询 /status
#       → LOF成交后 → POST /execute 自动空ETF（或自动执行）
_AUTO_OPEN_FILL_CHECKER = None
_AUTO_OPEN_CHECKER_LOCK = threading.Lock()
_AUTO_CLOSE_FILL_CHECKER = None
_AUTO_CLOSE_CHECKER_LOCK = threading.Lock()

def _start_auto_open_fill_checker(lazy_trader_instance):
    """启动后台线程，轮询持仓检测LOF是否成交"""
    global _AUTO_OPEN_FILL_CHECKER
    with _AUTO_OPEN_CHECKER_LOCK:
        if _AUTO_OPEN_FILL_CHECKER and _AUTO_OPEN_FILL_CHECKER.is_alive():
            return
        def _check_loop():
            logger.info("[AutoOpen] Fill checker started")
            while True:
                try:
                    if lazy_trader_instance:
                        with lazy_trader_instance._open_lock:
                            pending_items = list(lazy_trader_instance._pending_opens.items())
                        for ao_id, pending in pending_items:
                            if pending["status"] != "queued":
                                continue
                            # 轮询持仓变化
                            fc = pending["fund_code"]
                            lof_qty = pending["lof_quantity"]
                            try:
                                # [AI-2026-07-20] 优先用 trade_manager.query_position()（8888 短连接，
                                # 银河/国金/通达信脚本均支持），避免 get_positions() 仅走通达信导致
                                # 银河渠道下永远查不到持仓、自动对冲永不触发。
                                held = 0
                                _ts = lazy_trader_instance.trading_service
                                _tm = getattr(_ts, 'trade_manager', None) if _ts else None
                                if _tm and hasattr(_tm, 'query_position'):
                                    _pos = _tm.query_position(fc)
                                    if isinstance(_pos, dict) and _pos.get('volume'):
                                        held = int(_pos.get('volume', 0) or 0)
                                if held == 0 and _ts:
                                    pos_list = _ts.get_positions()
                                    for p in pos_list:
                                        if p.get("code","") == fc or p.get("code","") == f"{fc}.SZ":
                                            held = int(p.get("volume", 0) or p.get("available", 0))
                                            break
                                    # 如果持仓 ≥ lof_qty，说明已成交
                                    trade_etf = ""
                                    etf_qty = 0
                                    # 从 fund_service 获取 ETF 信息
                                    if lazy_trader_instance.fund_service:
                                        meta = lazy_trader_instance.fund_service.get_valuation_meta(fc)
                                        if meta and isinstance(meta, dict):
                                            cfg = meta.get("fund_config", {}) or {}
                                            trade_etf = cfg.get("trade_etf", "") or ""
                                            # 计算 ETF 股数
                                            bd = meta.get("base_data", {}) or {}
                                            hedge = float(bd.get("hedge", 0) or 0)
                                            if hedge > 0:
                                                etf_qty = max(1, int(round(lof_qty / hedge)))

                                    if held >= lof_qty and trade_etf and etf_qty > 0:
                                        # LOF 已成交，自动执行
                                        min_profit = pending.get("min_profit", 0.25)
                                        result = lazy_trader_instance.auto_short_if_profitable(
                                            ao_id, trade_etf, etf_qty, min_profit
                                        )
                                        status = result.get("status","")
                                        if status == "executed":
                                            logger.info(f"[AutoOpen] ✅ {fc} auto-open executed: {result}")
                                        elif status == "profit_too_low":
                                            logger.warning(f"[AutoOpen] ⚠️ {fc} filled but profit too low: {result}")
                                        elif status == "error":
                                            logger.error(f"[AutoOpen] ❌ {fc} auto-open failed: {result}")
                                    elif held >= lof_qty:
                                        logger.info(f"[AutoOpen] {fc} filled, but no trade_etf/etf_qty found, marking as filled")
                                        # 即使没有 ETF 信息也标记为已成交
                                        with lazy_trader_instance._open_lock:
                                            pending["status"] = "filled"
                                            pending["filled_at"] = datetime.now().isoformat()
                                            pending["msg"] = "filled but no ETF info for auto-short"
                            except Exception as e:
                                logger.debug(f"[AutoOpen] check {fc} positions: {e}")
                except Exception as e:
                    logger.error(f"[AutoOpen] checker error: {e}")
                time.sleep(3)  # 每3秒轮询
        _AUTO_OPEN_FILL_CHECKER = threading.Thread(target=_check_loop, daemon=True)
        _AUTO_OPEN_FILL_CHECKER.start()

def _start_auto_close_fill_checker(lazy_trader_instance):
    """启动后台线程，轮询持仓检测LOF是否已卖出（平仓）"""
    global _AUTO_CLOSE_FILL_CHECKER
    with _AUTO_CLOSE_CHECKER_LOCK:
        if _AUTO_CLOSE_FILL_CHECKER and _AUTO_CLOSE_FILL_CHECKER.is_alive():
            return
        def _check_loop():
            logger.info("[AutoClose] Fill checker started")
            while True:
                try:
                    if lazy_trader_instance:
                        with lazy_trader_instance._close_lock:
                            pending_items = list(lazy_trader_instance._pending_closes.items())
                        for ac_id, pending in pending_items:
                            if pending["status"] != "queued":
                                continue
                            fc = pending["fund_code"]
                            lof_qty = pending["lof_quantity"]
                            initial_pos = pending.get("initial_position", 0)
                            try:
                                # [AI-2026-07-20] 优先用 trade_manager.query_position()（8888 短连接），
                                # 避免 get_positions() 仅走通达信导致银河渠道下查不到持仓、自动平仓对冲不触发。
                                current_held = initial_pos  # 默认无变化
                                _ts = lazy_trader_instance.trading_service
                                _tm = getattr(_ts, 'trade_manager', None) if _ts else None
                                if _tm and hasattr(_tm, 'query_position'):
                                    _pos = _tm.query_position(fc)
                                    if isinstance(_pos, dict) and _pos.get('volume'):
                                        current_held = int(_pos.get('volume', 0) or 0)
                                if current_held == initial_pos and _ts:
                                    pos_list = _ts.get_positions()
                                    for p in pos_list:
                                        if p.get("code","") == fc or p.get("code","") == f"{fc}.SZ":
                                            current_held = int(p.get("volume", 0) or p.get("available", 0))
                                            break
                                    # 如果持仓减少 >= lof_qty，说明LOF已卖出
                                    sold_qty = initial_pos - current_held
                                    if sold_qty >= lof_qty:
                                        trade_etf = ""
                                        etf_qty = 0
                                        if lazy_trader_instance.fund_service:
                                            meta = lazy_trader_instance.fund_service.get_valuation_meta(fc)
                                            if meta and isinstance(meta, dict):
                                                cfg = meta.get("fund_config", {}) or {}
                                                trade_etf = cfg.get("trade_etf", "") or ""
                                                bd = meta.get("base_data", {}) or {}
                                                hedge = float(bd.get("hedge", 0) or 0)
                                                if hedge > 0:
                                                    etf_qty = max(1, int(round(lof_qty / hedge)))

                                        if sold_qty >= lof_qty and trade_etf and etf_qty > 0:
                                            min_profit = pending.get("min_profit", -0.41)
                                            result = lazy_trader_instance.auto_close_if_profitable(
                                                ac_id, trade_etf, etf_qty, min_profit
                                            )
                                            status = result.get("status","")
                                            if status == "executed":
                                                logger.info(f"[AutoClose] ✅ {fc} auto-close executed: {result}")
                                            elif status == "profit_too_low":
                                                logger.warning(f"[AutoClose] ⚠️ {fc} sold but profit too low: {result}")
                                            elif status == "error":
                                                logger.error(f"[AutoClose] ❌ {fc} auto-close failed: {result}")
                                        elif sold_qty >= lof_qty:
                                            logger.info(f"[AutoClose] {fc} sold, but no trade_etf/etf_qty found, marking as filled")
                                            with lazy_trader_instance._close_lock:
                                                pending["status"] = "filled"
                                                pending["filled_at"] = datetime.now().isoformat()
                                                pending["msg"] = "filled but no ETF info for auto-buy"
                            except Exception as e:
                                logger.debug(f"[AutoClose] check {fc} positions: {e}")
                except Exception as e:
                    logger.error(f"[AutoClose] checker error: {e}")
                time.sleep(3)
        _AUTO_CLOSE_FILL_CHECKER = threading.Thread(target=_check_loop, daemon=True)
        _AUTO_CLOSE_FILL_CHECKER.start()

@app.post("/api/private/auto_open/queue")
async def auto_open_queue(request: Request):
    """
    自动排队开仓：
    1. 仅排队 LOF 买一（不操作 ETF）
    2. 启动后台成交检测
    3. 返回 auto_open_id 供前端轮询状态
    """
    global _AUTO_OPEN_FILL_CHECKER
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    try:
        body = await request.json()
        fund_code = body.get("fund_code", "")
        lof_price = float(body.get("lof_price", 0))
        lof_quantity = int(body.get("lof_quantity", 0))
        broker = body.get("broker", "yinhe_qmt")
        min_profit = float(body.get("min_profit", 0.25))

        if not fund_code or lof_price <= 0 or lof_quantity <= 0:
            return JSONResponse(status_code=400, content={"status": "error", "message": "缺少必要参数"})

        # 获取赎回费率
        redemption_fee = ledger_service.get_fee_rate(fund_code, broker)
        if redemption_fee <= 0:
            redemption_fee = 0.50

        # 获取预期利润（用当前 GLD 买一价算）
        meta = fund_service.get_valuation_meta(fund_code)
        rt_val = float((meta or {}).get("rt_val", 0) or 0)
        premium = (lof_price / rt_val - 1) * 100 if rt_val > 0 else 0
        expected_profit = round(abs(premium) - redemption_fee, 3)

        # 排队 LOF
        result = lazy_trader_instance.queue_lof_order(fund_code, lof_price, lof_quantity, broker)
        if result.get("status") != "ok":
            return {"status": "error", "message": "LOF下单失败", "detail": result}

        auto_open_id = result["auto_open_id"]

        # 保存 min_profit 到 pending 记录
        with lazy_trader_instance._open_lock:
            p = lazy_trader_instance._pending_opens.get(auto_open_id)
            if p:
                p["min_profit"] = min_profit

        # 确保后台检测线程已启动
        _start_auto_open_fill_checker(lazy_trader_instance)

        return {
            "status": "ok",
            "auto_open_id": auto_open_id,
            "expected_profit": expected_profit,
            "redemption_fee": redemption_fee,
        }
    except Exception as e:
        logger.error(f"[AutoOpen] queue error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/private/auto_open/execute")
async def auto_open_execute(request: Request):
    """当 LOF 已成交，手动触发或自动触发 ETF 空单执行"""
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    try:
        body = await request.json()
        auto_open_id = body.get("auto_open_id", "")
        if not auto_open_id:
            return JSONResponse(status_code=400, content={"status": "error", "message": "缺少 auto_open_id"})

        pending = lazy_trader_instance.get_auto_open_status(auto_open_id)
        if pending.get("status") == "not_found":
            return JSONResponse(status_code=404, content={"status": "error", "message": "auto_open_id 不存在"})

        if pending["status"] != "queued":
            return {"status": "skipped", "message": f"当前状态 {pending['status']}，无需重复执行"}

        # 获取 ETF 信息
        fund_code = pending["fund_code"]
        lof_qty = pending["lof_quantity"]
        meta = fund_service.get_valuation_meta(fund_code)
        if not meta or not isinstance(meta, dict):
            return JSONResponse(status_code=500, content={"status": "error", "message": "无法获取基金信息"})
        cfg = meta.get("fund_config", {}) or {}
        trade_etf = cfg.get("trade_etf", "") or ""
        bd = meta.get("base_data", {}) or {}
        hedge = float(bd.get("hedge", 0) or 0)
        etf_qty = max(1, int(round(lof_qty / hedge))) if hedge > 0 else 0

        if not trade_etf or etf_qty <= 0:
            return JSONResponse(status_code=500, content={"status": "error", "message": "无法计算ETF对冲数量"})

        min_profit = pending.get("min_profit", 0.25)
        result = lazy_trader_instance.auto_short_if_profitable(
            auto_open_id, trade_etf, etf_qty, min_profit
        )
        return result
    except Exception as e:
        logger.error(f"[AutoOpen] execute error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/private/auto_open/status/{auto_open_id}")
async def auto_open_status(auto_open_id: str):
    """查询排队开仓状态"""
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    state = lazy_trader_instance.get_auto_open_status(auto_open_id)
    if state.get("status") == "not_found":
        return JSONResponse(status_code=404, content={"status": "error", "message": "auto_open_id 不存在"})
    return {"status": "ok", "data": state}

@app.get("/api/private/auto_open/positions/{fund_code}")
async def auto_open_check_position(fund_code: str):
    """查询当前持仓（用于前端判断 LOF 是否已成交）"""
    if not trading_service:
        return {"status": "ok", "held": 0, "msg": "trading_service not available"}
    try:
        pos_list = trading_service.get_positions()
        held = 0
        for p in pos_list:
            if p.get("code","") == fund_code or p.get("code","") == f"{fund_code}.SZ":
                held = int(p.get("volume", 0) or p.get("available", 0))
                break
        return {"status": "ok", "held": held}
    except Exception as e:
        return {"status": "error", "message": str(e), "held": 0}

# [AI-2026-07-20] 新增：前端 preview 显示当前持仓。
# 直接走 trade_manager.query_position（8888 短连接，银河/国金/通达信脚本均支持），
# 不依赖 get_positions() 的通达信登录，确保银河渠道下能正确显示底仓（如 161116 持有 66800 股）。
@app.get("/api/private/position/{fund_code}")
async def get_fund_position(fund_code: str):
    """查询单只基金当前持仓（优先 8888 短连接，降级 get_positions）"""
    if not trading_service:
        return {"status": "ok", "held": 0, "msg": "trading_service not available"}
    try:
        tm = getattr(trading_service, 'trade_manager', None)
        held = 0
        if tm and hasattr(tm, 'query_position'):
            pos = tm.query_position(fund_code)
            if isinstance(pos, dict) and pos.get('volume'):
                held = int(pos.get('volume', 0) or 0)
        if held == 0:
            pos_list = trading_service.get_positions()
            for p in pos_list:
                if p.get("code", "") == fund_code or p.get("code", "") == f"{fund_code}.SZ":
                    held = int(p.get("volume", 0) or p.get("available", 0))
                    break
        return {"status": "ok", "held": held}
    except Exception as e:
        return {"status": "error", "message": str(e), "held": 0}

# [AI-2026-07-15] AutoClose: 自动排队平仓 API
@app.post("/api/private/auto_close/queue")
async def auto_close_queue(request: Request):
    """
    自动排队平仓：
    1. 排队卖出 LOF（不操作 ETF）
    2. 启动后台成交检测
    3. 返回 auto_close_id 供前端轮询状态
    """
    global _AUTO_CLOSE_FILL_CHECKER
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    try:
        body = await request.json()
        fund_code = body.get("fund_code", "")
        lof_price = float(body.get("lof_price", 0))
        lof_quantity = int(body.get("lof_quantity", 0))
        broker = body.get("broker", "yinhe_qmt")
        min_profit = float(body.get("min_profit", -0.41))

        if not fund_code or lof_price <= 0 or lof_quantity <= 0:
            return JSONResponse(status_code=400, content={"status": "error", "message": "缺少必要参数"})

        # 排队卖出 LOF
        result = lazy_trader_instance.queue_lof_close_order(fund_code, lof_price, lof_quantity, broker)
        if result.get("status") != "ok":
            return {"status": "error", "message": "LOF卖出下单失败", "detail": result}

        auto_close_id = result["auto_close_id"]

        # 保存 min_profit 到 pending 记录
        with lazy_trader_instance._close_lock:
            p = lazy_trader_instance._pending_closes.get(auto_close_id)
            if p:
                p["min_profit"] = min_profit

        # 确保后台检测线程已启动
        _start_auto_close_fill_checker(lazy_trader_instance)

        return {
            "status": "ok",
            "auto_close_id": auto_close_id,
        }
    except Exception as e:
        logger.error(f"[AutoClose] queue error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/private/auto_close/execute")
async def auto_close_execute(request: Request):
    """当 LOF 已卖出，手动触发买回 ETF"""
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    try:
        body = await request.json()
        auto_close_id = body.get("auto_close_id", "")
        if not auto_close_id:
            return JSONResponse(status_code=400, content={"status": "error", "message": "缺少 auto_close_id"})

        pending = lazy_trader_instance.get_auto_close_status(auto_close_id)
        if pending.get("status") == "not_found":
            return JSONResponse(status_code=404, content={"status": "error", "message": "auto_close_id 不存在"})

        if pending["status"] != "queued":
            return {"status": "skipped", "message": f"当前状态 {pending['status']}，无需重复执行"}

        fund_code = pending["fund_code"]
        lof_qty = pending["lof_quantity"]
        meta = fund_service.get_valuation_meta(fund_code)
        if not meta or not isinstance(meta, dict):
            return JSONResponse(status_code=500, content={"status": "error", "message": "无法获取基金信息"})
        cfg = meta.get("fund_config", {}) or {}
        trade_etf = cfg.get("trade_etf", "") or ""
        bd = meta.get("base_data", {}) or {}
        hedge = float(bd.get("hedge", 0) or 0)
        etf_qty = max(1, int(round(lof_qty / hedge))) if hedge > 0 else 0

        if not trade_etf or etf_qty <= 0:
            return JSONResponse(status_code=500, content={"status": "error", "message": "无法计算ETF对冲数量"})

        min_profit = pending.get("min_profit", -0.41)
        result = lazy_trader_instance.auto_close_if_profitable(
            auto_close_id, trade_etf, etf_qty, min_profit
        )
        return result
    except Exception as e:
        logger.error(f"[AutoClose] execute error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/private/auto_close/status/{auto_close_id}")
async def auto_close_status(auto_close_id: str):
    """查询排队平仓状态"""
    if not lazy_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Trader not loaded"})
    state = lazy_trader_instance.get_auto_close_status(auto_close_id)
    if state.get("status") == "not_found":
        return JSONResponse(status_code=404, content={"status": "error", "message": "auto_close_id 不存在"})
    return {"status": "ok", "data": state}

@app.get("/api/private/lazy_status")
async def lazy_status():
    """Diagnostic: check LazyTrader driver status"""
    if not lazy_trader_instance:
        return {"status": "error", "message": "Lazy Trader not loaded"}
    return {
        "status": "ok",
        "data": {
            "ib_connected": bool(getattr(lazy_trader_instance, 'ib_reader', None) and getattr(lazy_trader_instance.ib_reader, 'connected', False)),
            "ib_reader_exists": lazy_trader_instance.ib_reader is not None,
            "galaxy_qmt_exists": lazy_trader_instance.galaxy_qmt is not None,
            "guojin_qmt_exists": lazy_trader_instance.guojin_qmt is not None,
        }
    }

# --- SmartOpenMonitor API (智能开仓/平仓监控) ---
@app.post("/api/private/smart_monitor/start")
async def smart_monitor_start(request: Request):
    if not _smart_start:
        return JSONResponse(status_code=400, content={"status": "error", "message": "SmartOpenMonitor not loaded"})
    data = await request.json()
    fund_code = data.get("fund_code", "")
    direction = data.get("direction", "open")
    target_premium = data.get("target_premium", 0)
    lof_quantity = data.get("lof_quantity", 0)
    trade_etf = data.get("trade_etf", "")
    lof_broker = data.get("lof_broker", "yinhe_qmt")
    # [AI-2026-07-20] 前端算好的各档溢价率（与盘口表 tag 同源），后端直接使用不再自算
    bid_premiums = data.get("bid_premiums", None)
    ask_premiums = data.get("ask_premiums", None)
    if not fund_code or not trade_etf or not lof_quantity:
        return JSONResponse(status_code=400, content={"status": "error", "message": "缺少必要参数(fund_code/trade_etf/lof_quantity)"})
    success, msg = _smart_start(
        fund_code, direction, target_premium, lof_quantity, trade_etf, lof_broker,
        bid_premiums=bid_premiums, ask_premiums=ask_premiums,
        lazy_trader=_smart_lt, fund_service=_smart_fs,
        market_data_service=_smart_mds, trading_service=_smart_ts,
        trade_manager=getattr(_smart_ts, 'trade_manager', None) if _smart_ts else None,
    )
    if success:
        return {"status": "ok", "message": msg}
    return JSONResponse(status_code=400, content={"status": "error", "message": msg})

@app.post("/api/private/smart_monitor/stop")
async def smart_monitor_stop(request: Request):
    if not _smart_stop:
        return JSONResponse(status_code=400, content={"status": "error", "message": "SmartOpenMonitor not loaded"})
    data = await request.json()
    fund_code = data.get("fund_code", "")
    success, msg = _smart_stop(fund_code)
    if success:
        return {"status": "ok", "message": msg}
    return JSONResponse(status_code=400, content={"status": "error", "message": msg})

@app.get("/api/private/smart_monitor/status")
async def smart_monitor_status():
    if not _smart_status:
        return {"status": "error", "message": "SmartOpenMonitor not loaded"}
    return _smart_status()

# [AI-2026-07-21] 运行时更新目标溢价率（不重启 Monitor）
@app.patch("/api/private/smart_monitor/update_target")
async def smart_monitor_update_target(request: Request):
    if not _smart_update_target:
        return JSONResponse(status_code=400, content={"status": "error", "message": "SmartOpenMonitor not loaded"})
    data = await request.json()
    fund_code = data.get("fund_code", "")
    new_premium = data.get("target_premium", None)
    if new_premium is None:
        return JSONResponse(status_code=400, content={"status": "error", "message": "缺少 target_premium"})
    success, msg = _smart_update_target(fund_code, float(new_premium))
    if success:
        return {"status": "ok", "message": msg}
    return JSONResponse(status_code=400, content={"status": "error", "message": msg})

# --- Lazy Simulator API (weekend mock data) ---
@app.get("/api/private/lazy_simulate/status")
async def lazy_simulate_status():
    """Get current simulation state and history"""
    if not lazy_simulator_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Simulator not loaded"})
    return {"status": "ok", "data": lazy_simulator_instance.get_status()}

@app.post("/api/private/lazy_simulate/control")
async def lazy_simulate_control(request: Request):
    """Start/stop/reset simulation, or toggle forced signal"""
    if not lazy_simulator_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Lazy Simulator not loaded"})
    try:
        body = await request.json()
        action = body.get("action", "status")
        if action == "start":
            result = lazy_simulator_instance.start()
        elif action == "stop":
            result = lazy_simulator_instance.stop()
        elif action == "reset":
            result = lazy_simulator_instance.reset()
        elif action == "force_signal":
            enabled = body.get("enabled", True)
            result = lazy_simulator_instance.set_forced_signal(enabled)
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown action: {action}"})
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error("[LazySim] Control error: %s", e)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# --- Bond ETF BP Override API ---
@app.post("/api/bond/bp-override")
async def set_bp_override(request: Request):
    """Store manual BP input for 511520 (from Choice terminal)"""
    try:
        from services.bond_etf_valuation import set_manual_bp
        body = await request.json()
        code = body.get("code", "511520")
        bp_7y = float(body.get("bp_7y", 0))
        bp_10y = float(body.get("bp_10y", 0))
        set_manual_bp(code, bp_7y, bp_10y)
        return {"status": "ok", "data": {"code": code, "bp_7y": bp_7y, "bp_10y": bp_10y}}
    except Exception as e:
        logger.error("[BPOverride] Error: %s", e)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/bond/bp-override")
async def get_bp_override(code: str = "511520"):
    """Get today's manual BP override"""
    try:
        from services.bond_etf_valuation import get_manual_bp
        override = get_manual_bp(code)
        if override:
            return {"status": "ok", "data": override}
        return {"status": "ok", "data": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/bond/bp-override/clear")
async def clear_bp_override(request: Request):
    """Clear manual BP override"""
    try:
        from services.bond_etf_valuation import clear_manual_bp
        body = await request.json()
        code = body.get("code", "511520")
        clear_manual_bp(code)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# --- Ledger Excel Import API ---
@app.post("/api/ledger/import-excel")
async def import_ledger_excel(request: Request):
    """Parse uploaded Excel file and return preview data"""
    try:
        import io
        import openpyxl
        from fastapi import UploadFile
        
        body = await request.json()
        file_path = body.get("file_path", "")
        
        if not file_path or not os.path.exists(file_path):
            return JSONResponse(status_code=400, content={"status": "error", "message": "File not found"})
        
        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        ws = wb.active
        
        pairs = []
        current_pair = None
        
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            desc = str(row[0] or "").strip()
            
            if not desc:
                continue
            
            # Buy row: contains "买入" or account info
            if "买入" in desc or ("账户" in desc and "5379" in desc or "4020" in desc or "4801" in desc):
                if current_pair and current_pair.get("buy_date"):
                    pairs.append(current_pair)
                current_pair = {
                    "buy_date": desc.split("  ")[0] if "  " in desc else desc[:10],
                    "buy_price": float(row[4] or 0),
                    "buy_volume": abs(int(row[5] or 0)),
                    "hedge_symbol": "XOP" if "GLD" in desc or "黄金" in desc else "XOP",
                    "notes": str(row[7] or ""),
                    "short_qty": int(row[9] or 0) if row[9] else 0,
                    "short_price": float(row[10] or 0) if row[10] else 0,
                }
            
            # Redeem row: contains "可赎回"
            elif "可赎回" in desc or "赎回" in desc:
                if current_pair:
                    current_pair["sell_date"] = desc.split("  ")[0] if "  " in desc else desc[:10]
                    current_pair["sell_price"] = float(row[4] or 0)
                    current_pair["sell_volume"] = abs(int(row[5] or 0)) if row[5] else 0
                    current_pair["redemption_fee"] = float(row[3] or 0) if row[3] else 0
            
            # Closed row: contains "closed Final"
            elif "closed" in desc.lower() or "final" in desc.lower():
                if current_pair:
                    current_pair["pnl_rmb"] = float(row[14] or 0) if row[14] else 0
                    current_pair["status"] = "CLOSED"
                    pairs.append(current_pair)
                    current_pair = None
        
        # Add last pair if not closed
        if current_pair and current_pair.get("buy_date"):
            current_pair["status"] = "ACTIVE"
            pairs.append(current_pair)
        
        wb.close()
        return {"status": "ok", "data": pairs, "total": len(pairs)}
        
    except Exception as e:
        logger.error("[ExcelImport] Parse error: %s", e)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/ledger/import-excel/confirm")
async def confirm_ledger_excel(request: Request):
    """Confirm and import parsed Excel data into ledger"""
    try:
        body = await request.json()
        pairs = body.get("pairs", [])
        
        success_count = 0
        for pair in pairs:
            try:
                # Map to existing addPair format
                trade_data = {
                    "fund_code": "162411",  # Default, will be overridden by notes
                    "fund_name": "华宝油气",
                    "buy_date": pair.get("buy_date", ""),
                    "buy_price": pair.get("buy_price", 0),
                    "buy_volume": pair.get("buy_volume", 0),
                    "sell_date": pair.get("sell_date", ""),
                    "sell_price": pair.get("sell_price", 0),
                    "sell_volume": pair.get("sell_volume", 0),
                    "redemption_fee": pair.get("redemption_fee", 0),
                    "hedge_symbol": pair.get("hedge_symbol", "XOP"),
                    "short_qty": pair.get("short_qty", 0),
                    "short_price": pair.get("short_price", 0),
                    "pnl_rmb": pair.get("pnl_rmb", 0),
                    "status": pair.get("status", "ACTIVE"),
                    "notes": pair.get("notes", ""),
                }
                # Use ledger_service to add pair
                # For now, just count successes
                success_count += 1
            except Exception as e:
                logger.error("[ExcelImport] Pair import error: %s", e)
        
        return {"status": "ok", "imported": success_count, "total": len(pairs)}
        
    except Exception as e:
        logger.error("[ExcelImport] Confirm error: %s", e)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# --- Ledger / Bookkeeping APIs ---
@app.get("/api/ledger/trades")
async def get_ledger_trades(status: str = 'ACTIVE'):
    data = ledger_service.get_all_trades(status=status)
    return {"status": "ok", "data": data}

@app.post("/api/ledger/trades/add")
async def add_ledger_trade(request: Request):
    data = await request.json()
    success = ledger_service.add_trade(data)
    return {"status": "ok" if success else "error"}

@app.post("/api/ledger/trades/close/{trade_id}")
async def close_ledger_trade(trade_id: int):
    success = ledger_service.close_trade(trade_id)
    return {"status": "ok" if success else "error"}

# --- Arbitrage Pairs (V9.2 新账本) ---
@app.get("/api/ledger/pairs")
async def get_ledger_pairs(status: str = None):
    data = ledger_service.get_all_pairs(status=status)
    return {"status": "ok", "data": data}

@app.post("/api/ledger/pairs/add")
async def add_ledger_pair(request: Request):
    data = await request.json()
    try:
        pair_id = ledger_service.add_pair(data)
        return {"status": "ok", "pair_id": pair_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/ledger/pairs/update/{pair_id}")
async def update_ledger_pair(pair_id: int, request: Request):
    data = await request.json()
    success = ledger_service.update_pair(pair_id, data)
    return {"status": "ok" if success else "error"}

@app.post("/api/ledger/pairs/delete/{pair_id}")
async def delete_ledger_pair(pair_id: int):
    success = ledger_service.delete_pair(pair_id)
    return {"status": "ok" if success else "error"}

# --- 自动记录交易（QMT执行回调） ---
@app.post("/api/ledger/auto-record")
async def auto_record_trade(request: Request):
    data = await request.json()
    pair_id = ledger_service.auto_record_trade(data)
    return {"status": "ok" if pair_id > 0 else "error", "pair_id": pair_id}

# --- 获取昨日收盘价（默认填入买入单价） ---
@app.get("/api/market/prev-close/{fund_code}")
async def get_prev_close(fund_code: str):
    price = ledger_service.get_prev_close(fund_code.split('.')[0])
    return {"status": "ok", "price": price}

# --- 获取券商赎回费率（自动关联填入） ---
@app.get("/api/ledger/fee-rate")
async def get_fee_rate(fund_code: str, broker: str = ''):
    rate = ledger_service.get_fee_rate(fund_code, broker)
    return {"status": "ok", "rate": rate}

# --- 清理测试假数据 ---
@app.post("/api/ledger/clear-fake-data")
async def clear_fake_data():
    conn = db._get_conn()
    try:
        conn.execute("DELETE FROM user_trades WHERE id IN (1,2,3,4)")
        conn.commit()
        return {"status": "ok", "message": "已删除4条测试假数据"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

# --- Fee & Commission Management APIs ---
@app.get("/api/config/fees/{code}")
async def get_fund_fees(code: str):
    data = ledger_service.get_fund_fees(code)
    return {"status": "ok", "data": data}

@app.get("/api/ledger/broker_fees")
async def get_broker_fees():
    data = ledger_service.get_broker_redemption_fees()
    return {"status": "ok", "data": data}

@app.post("/api/ledger/broker_fees/add")
async def add_broker_fee(request: Request):
    data = await request.json()
    success = ledger_service.upsert_broker_redemption_fee(data)
    return {"status": "ok" if success else "error"}

@app.post("/api/ledger/broker_fees/delete/{fee_id}")
async def delete_broker_fee(fee_id: int):
    success = ledger_service.delete_broker_redemption_fee(fee_id)
    return {"status": "ok" if success else "error"}

@app.post("/api/config/fees/upsert")
async def upsert_fund_fee(request: Request):
    data = await request.json()
    success = ledger_service.upsert_fund_fee(data)
    return {"status": "ok" if success else "error"}

# --- Trading & Position APIs ---
@app.get("/api/trading/positions")
async def get_trading_positions():
    """获取真实账户持仓"""
    try:
        data = trading_service.get_positions()
        return {"status": "ok", "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/trading/balance")
async def get_trading_balance():
    """获取账户余额"""
    data = trading_service.get_balance()
    return {"status": "ok", "data": data}

@app.post("/api/trading/order")
async def place_manual_order(request: Request):
    """手动下单接口"""
    data = await request.json()
    res = trading_service.execute_order(
        action=data.get('action'),
        code=data.get('code'),
        volume=data.get('volume'),
        price=data.get('price'),
        broker=data.get('broker', 'tdx'),
        account_id=data.get('account_id')
    )
    return res

@app.post("/api/trading/ib_order")
async def place_ib_order(request: Request):
    """简单 IB 下单接口（实时沙盘用，不走 LazyTrader）"""
    try:
        body = await request.json()
        action = body.get('action', 'BUY')
        symbol = body.get('symbol', '')
        quantity = int(body.get('quantity', 0))
        price = float(body.get('price', 0))
        if not symbol or quantity <= 0 or price <= 0:
            return {"status": "error", "message": "参数不完整: symbol/quantity/price 必填"}
        ib_reader = getattr(market_data_service, 'ib_reader', None)
        if not ib_reader or not getattr(ib_reader, 'connected', False):
            return {"status": "error", "message": "IB 未连接"}
        # [AI-2026-07-02] 直接调用 ib_reader.place_us_order，不走 LazyTrader
        success, msg = ib_reader.place_us_order(symbol, action, quantity, price)
        logger.info(f"[IBOrder] {action} {quantity} {symbol} @ {price} -> {'OK' if success else 'FAIL'}: {msg}")
        return {"status": "ok" if success else "error", "message": msg}
    except Exception as e:
        logger.error(f"[IBOrder] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/api/system/accounts")
async def get_accounts():
    """从隐私配置获取交易账号列表供前端渲染，不暴露给Git"""
    try:
        from arbcore.config.account_private import YH_ACCOUNT_LIST
        return {"status": "ok", "data": YH_ACCOUNT_LIST}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": {}}

@app.post("/api/system/accounts")
async def save_accounts(request: Request):
    """保存交易账号列表到 account_private.py"""
    try:
        data = await request.json()
        accounts = data.get("accounts", {})
        
        import os
        import re
        # 定位 account_private.py
        file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "arbcore", "config", "account_private.py")
        
        if not os.path.exists(file_path):
            return {"status": "error", "message": "account_private.py 不存在"}
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 构建新的字典字符串
        dict_str = "YH_ACCOUNT_LIST = {\n"
        for k in ["1", "2", "3", "4", "5", "6"]:
            val = accounts.get(k, "")
            label = "备用" if k == "6" else f"周{['一','二','三','四','五'][int(k)-1]}使用"
            dict_str += f'    "{k}": "{val}",  # {label}\n'
        dict_str += "}"
        
        # 使用正则替换
        new_content = re.sub(r'YH_ACCOUNT_LIST\s*=\s*\{[^}]*\}', dict_str, content)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
            
        return {"status": "ok", "message": "账号保存成功，已写入隐私配置"}
    except Exception as e:
        return {"status": "error", "message": f"保存失败: {str(e)}"}

@app.post("/api/system/reconnect_ib")
async def reconnect_ib():
    """重连 IB - 使用 reconnect() 方法，试连 3 次"""
    try:
        # [V10.1] 重置熔断器
        market_data_service._circuit_reset('IB')
        if market_data_service.ib_reader:
            success, msg = market_data_service.ib_reader.reconnect()
            if success:
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
        else:
            from arbcore.fetchers.ib_reader import IBReader
            reader = IBReader(db_manager=db)
            market_data_service.ib_reader = reader
            success, msg = reader.reconnect()
            if success:
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
    except Exception as e:
        system_status.add_milestone("ERROR", f"IB 重连异常: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/system/reconnect_futu")
async def reconnect_futu():
    """重连富途 - 使用 reconnect() 方法，试连 3 次"""
    try:
        # [V10.1] 重置熔断器
        market_data_service._circuit_reset('富途')
        if market_data_service.futu_reader:
            success, msg = market_data_service.futu_reader.reconnect()
            if success:
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
        else:
            from arbcore.fetchers.futu_reader import FutuReader
            reader = FutuReader()
            market_data_service.futu_reader = reader
            success, msg = reader.reconnect()
            if success:
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
    except Exception as e:
        system_status.add_milestone("ERROR", f"富途重连异常: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/system/reconnect_tdx")
async def reconnect_tdx():
    """重连通达信 - 使用 reconnect() 方法，试连 3 次"""
    try:
        if market_data_service.realtime_manager:
            rm = market_data_service.realtime_manager
            tdx = rm.active_fetchers.get('tdx')
            if tdx:
                # 已在 active_fetchers 中，直接 reconnect
                success, msg = tdx.reconnect()
                if success:
                    system_status.add_milestone("SUCCESS", msg)
                    return {"status": "ok", "message": msg}
                else:
                    system_status.add_milestone("WARNING", msg)
                    return {"status": "error", "message": msg}
            else:
                # V10.0 启动时跳过了客户端源，需要新创建实例并注册
                from arbcore.fetchers.realtime.tdx import TdxRealtimeFetcher
                tdx = TdxRealtimeFetcher()
                success, msg = tdx.reconnect()
                if success:
                    rm.active_fetchers['tdx'] = tdx
                    if rm.symbols:
                        tdx.subscribe(rm.symbols)
                    system_status.add_milestone("SUCCESS", f"通达信 {msg}")
                    return {"status": "ok", "message": msg}
                else:
                    system_status.add_milestone("WARNING", f"通达信 {msg}")
                    return {"status": "error", "message": msg}
        else:
            system_status.add_milestone("WARNING", "实时行情管理器未启动")
            return {"status": "error", "message": "实时行情管理器未启动"}
    except Exception as e:
        system_status.add_milestone("ERROR", f"通达信重连异常: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/system/reconnect_galaxy")
async def reconnect_galaxy():
    """银河QMT仅用于下单，不参与行情轮询"""
    try:
        if not market_data_service.realtime_manager:
            system_status.add_milestone("WARNING", "实时行情管理器未启动")
            return {"status": "error", "message": "实时行情管理器未启动"}
        rm = market_data_service.realtime_manager
        galaxy = rm.active_fetchers.get('galaxy')
        if galaxy:
            # 已有实例，重新连接
            success, msg = galaxy.reconnect()
        else:
            # [AI-2026-06-29] 首次创建：仅注册到active_fetchers供按钮状态和下单使用，不订阅行情
            from arbcore.fetchers.realtime.galaxy import GalaxyQmtFetcher
            galaxy = GalaxyQmtFetcher()
            rm.active_fetchers['galaxy'] = galaxy
            success, msg = galaxy.reconnect()
        if success:
            # 更新 lazy trader 的下单通道引用
            global lazy_trader_instance
            if lazy_trader_instance is not None:
                lazy_trader_instance.inject_drivers(
                    ib_reader=getattr(market_data_service, 'ib_reader', None),
                    galaxy_qmt=galaxy,
                    guojin_qmt=rm.active_fetchers.get('guojin')
                )
            logger.info("[银河QMT] 下单通道正常，已注册active_fetchers (不参与行情轮询)")
            system_status.add_milestone("SUCCESS", "银河QMT下单通道正常 (不参与行情)")
            return {"status": "ok", "message": "银河QMT下单通道正常"}
        else:
            system_status.add_milestone("WARNING", msg)
            return {"status": "error", "message": msg}
    except Exception as e:
        logger.warning(f"[银河QMT] 连接失败: {e}")
        system_status.add_milestone("WARNING", f"银河QMT下单通道连接失败: {e}")
        return {"status": "error", "message": f"银河QMT连接失败: {e}"}

@app.post("/api/system/reconnect_guojin")
async def reconnect_guojin():
    """重连国金QMT - 使用 reconnect() 方法，试连 3 次"""
    try:
        if market_data_service.realtime_manager:
            rm = market_data_service.realtime_manager
            guojin = rm.active_fetchers.get('guojin')
            if guojin:
                success, msg = guojin.reconnect()
            else:
                # 懒创建：首次点击时创建实例并注册到管理器
                from arbcore.fetchers.realtime.guojin import GuojinQmtFetcher
                guojin = GuojinQmtFetcher()
                rm.active_fetchers['guojin'] = guojin
                success, msg = guojin.reconnect()
            if success:
                # [AI-2026-06-29] 重连后重新订阅所有已跟踪标的
                if rm.symbols:
                    guojin.subscribe(rm.symbols)
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
        else:
            system_status.add_milestone("WARNING", "实时行情管理器未启动")
            return {"status": "error", "message": "实时行情管理器未启动"}
    except Exception as e:
        system_status.add_milestone("ERROR", f"国金QMT重连异常: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/system/reconnect_engine")
async def reconnect_engine():
    res = market_data_service.restart_realtime_engine()
    return res

@app.post("/api/system/trigger/{task}")
async def trigger_task(task: str):
    import subprocess
    # [AI-2026-06-28] 修复净值补采500错误：daily_updater.py 实际在 scheduler/ 下，不在 arbcore/scripts/
    scripts_dir = os.path.normpath(os.path.join(backend_dir, "scheduler"))
    lofarb_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "LOFarb"))
    task_map = {
        "011": os.path.join(scripts_dir, "daily_updater.py"),
        "012": [os.path.join(scripts_dir, "daily_updater.py"), "--static-valuation"],
        "nav": [os.path.join(scripts_dir, "daily_updater.py"), "--nav-only"],
        "morning": [os.path.join(scripts_dir, "daily_updater.py"), "--refresh-morning"]
    }
    if task not in task_map:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid task"})

    task_entry = task_map[task]
    if isinstance(task_entry, list):
        script_path = task_entry[0]
        extra_args = task_entry[1:]
    else:
        script_path = task_entry
        extra_args = []
    
    # [V4.1] 尝试多种 Python 路径
    python_exe_candidates = [
        os.path.normpath(os.path.join(backend_dir, "..", "..", ".venv", "Scripts", "python.exe")),  # 项目 .venv
        os.path.normpath(os.path.join(backend_dir, "..", "..", "..", ".venv", "Scripts", "python.exe")),  # 上级 .venv
        os.path.normpath(os.path.join(backend_dir, "..", "..", "..", "Python311", "python.exe")),  # Python311
        "python",  # 系统 Python
    ]
    
    python_exe = None
    for candidate in python_exe_candidates:
        if os.path.exists(candidate):
            python_exe = candidate
            logger.info(f"✅ 找到 Python: {python_exe}")
            break
    
    if not python_exe:
        error_msg = "未找到可用的 Python 解释器"
        system_status.add_milestone("ERROR", error_msg)
        logger.error(f"❌ {error_msg}")
        return JSONResponse(status_code=500, content={"status": "error", "message": error_msg})
    
    try:
        logger.info(f"🚀 启动任务 {task}: {script_path}")
        logger.info(f"🐍 Python: {python_exe}")
        
        # [V4.1] 验证路径有效性
        script_dir = os.path.dirname(script_path)
        if not os.path.exists(script_dir):
            error_msg = f"脚本目录不存在: {script_dir}"
            system_status.add_milestone("ERROR", error_msg)
            logger.error(f"❌ {error_msg}")
            return JSONResponse(status_code=500, content={"status": "error", "message": error_msg})
        
        if not os.path.exists(script_path):
            error_msg = f"脚本文件不存在: {script_path}"
            system_status.add_milestone("ERROR", error_msg)
            logger.error(f"❌ {error_msg}")
            return JSONResponse(status_code=500, content={"status": "error", "message": error_msg})
        
        cmd = [python_exe, script_path] + extra_args
        launched = _popen_script_once(cmd, script_dir, os.path.basename(script_path))
        if not launched:
            return {"status": "ok", "message": f"Task {task} already running"}
        system_status.add_milestone("INFO", f"后台任务 {task} 已手动启动")
        logger.info(f"✅ 手动触发任务 {task}: {' '.join(cmd)}")
        if task == "nav":
            global _nav_last_updated
            _nav_last_updated["time"] = datetime.now().strftime("%H:%M")
            _nav_last_updated["date"] = datetime.now().strftime("%Y-%m-%d")
        return {"status": "ok", "message": f"Task {task} started in background"}
    except Exception as e:
        error_msg = f"后台任务启动失败: {e}"
        system_status.add_milestone("ERROR", error_msg)
        logger.error(f"❌ {error_msg}")
        return JSONResponse(status_code=500, content={"status": "error", "message": error_msg})

@app.get("/api/system/nav-status")
async def get_nav_status():
    """返回净值最后更新时间，供前端展示提醒"""
    global _nav_last_updated
    today = datetime.now().strftime("%Y-%m-%d")
    today_updated = _nav_last_updated.get("date") == today
    return {
        "status": "ok",
        "data": {
            "last_updated_time": _nav_last_updated.get("time"),
            "last_updated_date": _nav_last_updated.get("date"),
            "today_updated": today_updated
        }
    }

@app.get("/api/system/data-status")
async def get_data_status():
    """返回今日各项数据同步状态（供前端展示）"""
    global _morning_refreshed_today
    today = datetime.now().strftime("%Y-%m-%d")
    sources = {
        "woody_lof_batch": "Woody因子",
        "official_exchange_rate": "官方汇率",
        "futures_data": "期货结算价",
        "jsl_shares_data": "场内份额",
    }
    status = {}
    for key, label in sources.items():
        synced = db.is_access_synced_today(today, source=key)
        status[key] = {"label": label, "synced": synced}
    status["nav"] = {"label": "基金净值", "synced": False}
    status["morning"] = {"label": "清晨数据", "synced": _morning_refreshed_today}
    # 统计
    morning_ok = all(status[k]["synced"] for k in sources)
    return {
        "status": "ok",
        "data": {
            "sources": status,
            "morning_ready": _morning_refreshed_today,
            "all_morning_done": morning_ok,
            "today": today
        }
    }

@app.get("/api/system/health-check")
async def health_check():
    """系统自检：验证数据完整性、同步新鲜度"""
    today = datetime.now().strftime("%Y-%m-%d")
    issues = []
    conn = db._get_conn()
    try:
        # 1. 检查静态估值完整性（最近3个交易日）
        recent_dates = conn.execute("""
            SELECT DISTINCT date FROM unified_fund_history 
            ORDER BY date DESC LIMIT 5
        """).fetchall()
        check_dates = [r[0] for r in recent_dates[:3]]
        
        missing_sv = conn.execute("""
            SELECT date, fund_code FROM unified_fund_history 
            WHERE date IN ({}) AND (static_val IS NULL OR static_val <= 0)
              AND date != ?  -- 今天可能还没出净值，排除
              AND nav IS NOT NULL  -- 只检查有实际净值的基金，排除僵尸记录
            ORDER BY date DESC
        """.format(','.join('?' * len(check_dates))), check_dates + [today]).fetchall()
        
        if missing_sv:
            for date, code in missing_sv[:10]:
                issues.append(f"[{code}] {date} static_val 缺失")
        
        # 2. 检查同步新鲜度
        stale_sources = []
        for src in ['woody_lof_batch', 'official_exchange_rate', 'futures_data']:
            synced = db.is_access_synced_today(today, source=src)
            if not synced:
                stale_sources.append(src)
        if stale_sources:
            issues.append(f"同步未完成: {', '.join(stale_sources)}")
        
        # 3. 检查最近 sync 日期是否太旧
        farthest = conn.execute("""
            SELECT sync_date FROM access_sync_status 
            WHERE access_source='woody_lof_batch' 
            ORDER BY sync_date DESC LIMIT 1
        """).fetchone()
        if farthest:
            if farthest[0] < today:
                issues.append(f"Woody因子最后同步日: {farthest[0]}（非今日）")
        
        # 4. 检查数据库健康
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity and integrity[0] != 'ok':
            issues.append(f"数据库完整性异常: {integrity[0]}")
        
        fund_count = conn.execute("SELECT COUNT(DISTINCT fund_code) FROM unified_fund_history").fetchone()[0]
        record_count = conn.execute("SELECT COUNT(*) FROM unified_fund_history").fetchone()[0]
        
    finally:
        conn.close()
    
    status = "healthy" if not issues else "warning"
    return {
        "status": status,
        "issues": issues,
        "today": today,
        "stats": {
            "fund_count": fund_count or 0,
            "total_records": record_count or 0,
            "checked_dates": check_dates
        }
    }

@app.get("/api/system/runtime-health")
async def runtime_health():
    """Runtime health for UI polling and data-source observability."""
    db_status = "unknown"
    try:
        conn = db._get_conn()
        try:
            conn.execute("SELECT 1").fetchone()
            db_status = "ok"
        finally:
            conn.close()
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status": "ok",
        "dashboard": dashboard_snapshot_service.get_runtime_health(),
        "database": {"status": db_status},
    }

# --- Auto Trade Engine APIs (旧版信号监测，重命名文件避免冲突) ---
@app.get("/api/auto_trade/rules")
async def get_auto_trade_rules():
    return {"status": "ok", "rules": auto_trade_runner.engine.rules}

@app.post("/api/auto_trade/rules/add")
async def add_auto_trade_rule(request: Request):
    data = await request.json()
    rule_id = auto_trade_runner.engine.add_rule(data)
    return {"status": "ok", "id": rule_id}

@app.post("/api/auto_trade/rules/update/{rule_id}")
async def update_auto_trade_rule(rule_id: str, request: Request):
    data = await request.json()
    success = auto_trade_runner.engine.update_rule(rule_id, data)
    return {"status": "ok" if success else "error"}

@app.delete("/api/auto_trade/rules/{rule_id}")
async def delete_auto_trade_rule(rule_id: str):
    auto_trade_runner.engine.delete_rule(rule_id)
    return {"status": "ok"}

@app.post("/api/auto_trade/rules")
async def update_all_rules(request: Request):
    data = await request.json()
    if "rules" in data:
        auto_trade_runner.engine.rules = data["rules"]
        auto_trade_runner.engine.save_rules()
        return {"status": "ok", "message": "Rules updated successfully"}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Missing 'rules' in payload"})

@app.get("/api/auto_trade/status")
async def get_auto_trade_status():
    return {"status": "ok", "running": auto_trade_runner.running}

@app.post("/api/auto_trade/toggle")
async def toggle_auto_trade_engine(request: Request):
    data = await request.json()
    action = data.get("action")
    if action == "start":
        auto_trade_runner.start()
        system_status.add_milestone("SUCCESS", "手动启动网格引擎")
        return {"status": "ok", "running": True}
    elif action == "stop":
        auto_trade_runner.stop()
        system_status.add_milestone("WARNING", "手动停止网格引擎")
        return {"status": "ok", "running": False}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid action"})

@app.get("/api/auto_trade/logs")
async def get_auto_trade_logs():
    return {"status": "ok", "logs": auto_trade_runner.get_recent_logs()}

# --- [AI-2026-07-01] RuleEngine API (DB驱动，LazyMode 前端用) ---
@app.get("/api/rule_engine/status")
async def get_rule_engine_status():
    if not rule_engine:
        return {"status": "error", "message": "RuleEngine not loaded", "running": False, "rules": []}
    rules = rule_engine.get_all_rules()
    return {"status": "ok", "running": rule_engine.running, "rules": rules}

@app.post("/api/rule_engine/toggle")
async def toggle_rule_engine(request: Request):
    if not rule_engine:
        return JSONResponse(status_code=400, content={"status": "error", "message": "RuleEngine not loaded"})
    data = await request.json()
    action = data.get("action")
    if action == "start":
        rule_engine.start()
        return {"status": "ok", "running": True}
    elif action == "stop":
        rule_engine.stop()
        return {"status": "ok", "running": False}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid action"})

@app.post("/api/rule_engine/rule_add")
async def add_rule_engine_rule(request: Request):
    if not rule_engine:
        return JSONResponse(status_code=400, content={"status": "error", "message": "RuleEngine not loaded"})
    data = await request.json()
    # 自动映射 hedge_symbol
    fund_code = data.get("fund_code", "")
    hedge = data.get("hedge_symbol", "")
    if not hedge:
        hedge = rule_engine._lookup_hedge(fund_code)
    result = rule_engine.add_rule({
        "fund_code": fund_code,
        "hedge_symbol": hedge,
        "direction": data.get("direction", "open"),
        "condition": data.get("condition", "lt"),
        "threshold": data.get("threshold", -0.5),
        "pos_constraint": data.get("pos_constraint"),
        "pos_value": data.get("pos_value"),
        "cash_constraint": data.get("cash_constraint"),
        "cash_value": data.get("cash_value"),
        "enabled": data.get("enabled", True),
        "note": data.get("note", ""),
    })
    return result

@app.post("/api/rule_engine/rule_update/{rule_id}")
async def update_rule_engine_rule(rule_id: int, request: Request):
    if not rule_engine:
        return JSONResponse(status_code=400, content={"status": "error", "message": "RuleEngine not loaded"})
    data = await request.json()
    success = rule_engine.update_rule(rule_id, data)
    return {"status": "ok" if success else "error"}

@app.delete("/api/rule_engine/rule/{rule_id}")
async def delete_rule_engine_rule(rule_id: int):
    if not rule_engine:
        return JSONResponse(status_code=400, content={"status": "error", "message": "RuleEngine not loaded"})
    rule_engine.delete_rule(rule_id)
    return {"status": "ok"}

@app.get("/api/rule_engine/logs")
async def get_rule_engine_logs():
    if not rule_engine:
        return {"status": "ok", "logs": []}
    return {"status": "ok", "logs": rule_engine.get_recent_logs()}

# --- AutoExecutor (Lazy Trader 自动执行) APIs ---
@app.get("/api/signal_detector/status")
async def get_signal_detector_status():
    running = signal_detector.running if signal_detector else False
    return {"status": "ok", "running": running}

@app.post("/api/signal_detector/toggle")
async def toggle_signal_detector(request: Request):
    if not signal_detector:
        return JSONResponse(status_code=400, content={"status": "error", "message": "SignalDetector not loaded"})
    data = await request.json()
    action = data.get("action")
    if action == "start":
        signal_detector.start()
        system_status.add_milestone("SUCCESS", "信号检测启动")
        return {"status": "ok", "running": True}
    elif action == "stop":
        signal_detector.stop()
        system_status.add_milestone("WARNING", "信号检测停止")
        return {"status": "ok", "running": False}
    return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid action"})

@app.get("/api/signal_detector/logs")
async def get_signal_detector_logs():
    if not signal_detector:
        return {"status": "ok", "logs": []}
    return {"status": "ok", "logs": signal_detector.get_recent_logs()}

# --- Data Source Config APIs ---
@app.get("/api/config/data_sources")
async def get_data_sources(module: str = "realtime_market"):
    data = config_service.get_data_sources(module)
    return {"status": "ok", "data": data}

@app.post("/api/config/data_sources/update")
async def update_data_source(request: Request):
    data = await request.json()
    res = config_service.update_source_config(
        module=data.get('module', 'realtime_market'),
        source_name=data.get('source_name'),
        priority=data.get('priority'),
        is_active=data.get('is_active'),
        config=data.get('config')
    )
    return res

@app.post("/api/config/data_sources/priority")
async def update_priorities(request: Request):
    data = await request.json()
    res = config_service.update_priorities(
        module=data.get('module', 'realtime_market'),
        priorities=data.get('priorities', [])
    )
    market_data_service.restart_realtime_engine()
    return res


# --- Market Data APIs ---
@app.get("/api/market/realtime/{code}")
async def get_realtime_quote(code: str):
    quote = market_data_service.get_realtime_quote(code)
    if quote:
        return {"status": "ok", "data": quote}
    return JSONResponse(status_code=404, content={"status": "error", "message": "Quote not found"})

@app.get("/api/market/historical/nav/{code}")
async def get_hist_nav(code: str, start_date: str = None):
    data = market_data_service.get_historical_nav(code, start_date=start_date)
    return {"status": "ok", "data": data}

@app.get("/api/market/historical/price/{code}")
async def get_hist_price(code: str, start_date: str = None):
    data = market_data_service.get_historical_prices(code, start_date=start_date)
    return {"status": "ok", "data": data}

# --- ETF Rotation APIs (程序4 融合) ---
@app.get("/api/etf-rotation/list")
async def get_etf_rotation_list():
    """获取 ETF 轮动分组配置"""
    data = etf_rotation_service.get_rotation_list()
    return {"status": "ok", "data": data}

@app.get("/api/etf-rotation/prices")
async def get_etf_rotation_prices():
    """获取 ETF 轮动实时价格和估值"""
    data = etf_rotation_service.get_rotation_prices()
    return {"status": "ok", "data": data}

@app.get("/api/etf-rotation/fx")
async def get_etf_rotation_fx():
    """获取 USD/CNY 实时在岸价"""
    rate = etf_rotation_service.get_realtime_fx_spot()
    return {"status": "ok", "data": {"fx_spot": rate}}

@app.get("/api/etf-rotation/history/{group_id}")
async def get_etf_rotation_history(group_id: int):
    """获取某分组的轮动历史数据"""
    data = etf_rotation_service.get_group_history(group_id)
    return {"status": "ok", "data": data}


@app.get("/api/silver/ratio")
async def get_silver_ratio():
    """白银比价数据: (AG_settle / 1000 × 31.1035 / USDCNH) / SI_close
    与 Woody stockhistorycn.php 完全一致的公式
    
    处理逻辑（对齐 Woody）：
    - 历史日期：从 futures_daily + exchange_rate 读取（稳定）
    - 今日日期：SI 和 CNH 从新浪实时抓取（Woody 每个页面访问都覆写 today row）
    - 比价公式与 Woody stockhistoryparagraph.php 完全一致
    """
    conn = fund_service.db._get_conn()
    today_str = datetime.now().strftime('%Y-%m-%d')
    now_hour = datetime.now().hour
    
    # 21:00 定稿：AG0 夜盘 21:00 开新一天的交易，21:00 后的实时价属于"明天"
    # 对齐 Woody mystockref.php: $iHourMinute < 2100 才 _updateStockHistory
    is_finalized = now_hour >= 21  # 21:00+ 今日数据定稿，不再覆写
    
    try:
        cursor = conn.cursor()
        # [AI-2026-07-08] 改用 在岸价 (usd_cny_spot) -> CNH -> 中间价 三级回退，Woody 实际使用在岸价
        cursor.execute("""
            SELECT
                a.date,
                a.close_price AS ag_close,
                a.settle_price AS ag_settle,
                a.volume AS ag_volume,
                s.close_price AS si_close,
                COALESCE(e.usd_cny_spot, e.usd_cnh, e.usd_cny_mid) AS usd_cny_spot
            FROM futures_daily a
            LEFT JOIN futures_daily s ON a.date = s.date AND s.symbol = 'SI'
            LEFT JOIN exchange_rate e ON a.date = e.date
            WHERE a.symbol = 'AG0'
              AND a.close_price IS NOT NULL
              AND s.close_price IS NOT NULL
              AND (e.usd_cny_spot IS NOT NULL OR e.usd_cnh IS NOT NULL OR e.usd_cny_mid IS NOT NULL)
            ORDER BY a.date DESC
        """)
        rows = cursor.fetchall()
        data = []
        
        # 实时抓取今日 SI 和 在岸价 USDCNY（对齐 Woody：21:00 前每次页面访问都覆写 today row）
        today_si = None
        today_spot = None
        if not is_finalized:
            try:
                si_raw = market_data_service.data_fetcher.fetch_si_from_sina()
                if si_raw and si_raw.get('price', 0) > 0:
                    today_si = si_raw['price']
                # Woody 实际使用在岸价 (USDCNY)，不是 CNH
                spot_raw = market_data_service.data_fetcher.fetch_cny_spot_rate()
                if spot_raw and spot_raw.get('人民币在岸价', 0) > 0:
                    today_spot = spot_raw['人民币在岸价']
            except Exception as e:
                logger.warning(f"[白银比价] 实时获取 SI/USDCNY 失败: {e}")
        else:
            logger.info(f"[白银比价] 今日数据已定稿 (≥21:00)，使用数据库存档值")
        
        for row in rows:
            row_date = row[0]
            ag_close = float(row[1]) if row[1] is not None else None
            ag_settle = float(row[2]) if row[2] is not None else ag_close
            ag_volume = int(row[3]) if row[3] is not None else None
            
            # 今日行：用实时 SI 和 USDCNY 覆盖（对齐 Woody 的 _updateStockHistory 机制）
            if row_date == today_str:
                si_close = today_si if today_si else float(row[4])
                usd_cny_spot = today_spot if today_spot else float(row[5])
            else:
                si_close = float(row[4])
                usd_cny_spot = float(row[5])
            
            ratio = (ag_settle / 1000.0 * 31.1035 / usd_cny_spot) / si_close if (usd_cny_spot > 0 and si_close > 0 and ag_settle) else None
            data.append({
                "date": row_date,
                "ag_close": ag_close,
                "ag_settle": ag_settle,
                "ag_volume": ag_volume,
                "si_close": round(si_close, 2),
                "usd_cny_spot": round(usd_cny_spot, 4),
                "ratio": round(ratio, 4) if ratio else None
            })
        
        # 如果数据库还没有今日行但实时数据可用，拼一个今日行（用 AG0 新浪实时数据）
        if (not data or data[0]['date'] != today_str) and today_si and today_spot:
            try:
                ag0_raw = market_data_service.data_fetcher.fetch_ag0_from_sina()
                if ag0_raw:
                    ag_close = ag0_raw.get('price')
                    ag_settle = ag0_raw.get('settle') or ag_close  # settle = parts[9] (今日结算价)
                    ag_volume = ag0_raw.get('volume')
                    ratio = None
                    if ag_settle and today_si > 0 and today_spot > 0:
                        ratio = (ag_settle / 1000.0 * 31.1035 / today_spot) / today_si
                    today_row = {
                        "date": today_str,
                        "ag_close": ag_close,
                        "ag_settle": ag_settle,
                        "ag_volume": ag_volume,
                        "si_close": round(today_si, 2),
                        "usd_cny_spot": round(today_spot, 4),
                        "ratio": round(ratio, 4) if ratio else None
                    }
                    data.insert(0, today_row)
            except Exception as e:
                logger.warning(f"[白银比价] 实时获取 AG0 失败: {e}")
        
        return {"status": "ok", "data": data}
    except Exception as e:
        logger.error(f"获取白银比价失败: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


# ==============================================================
# [V6.5] 静态前端挂载 (公网部署与动静合一)
# 允许使用 512M 小内存 VPS 同时提供 Backend API 和 Frontend
# ==============================================================
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 优先查找上一级目录的 frontend/dist
frontend_dist_path = os.path.join(workspace_root, "frontend", "dist")

if os.path.exists(frontend_dist_path):
    assets_dir = os.path.join(frontend_dist_path, "assets")
    if os.path.exists(assets_dir):
        logger.info(f"Detected frontend dist at {frontend_dist_path}, mounting static files.")
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")
    # SPA Fallback: 用 middleware 代替 catch-all 路由，避免拦截 /api/* 请求
    from starlette.middleware.base import BaseHTTPMiddleware
    class SPAMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            response = await call_next(request)
            if response.status_code == 404:
                path = request.url.path
                # 静态资源和 API 不做 fallback
                if path.startswith("/api/") or path.startswith("/assets/"):
                    return response
                return FileResponse(os.path.join(frontend_dist_path, "index.html"))
            return response
    app.add_middleware(SPAMiddleware)

def kill_port_owner(port: int):
    """
    [Windows 强力补丁] 启动前强行终止占用指定端口的旧残留进程，防止端口冲突闪退。
    """
    if sys.platform != "win32":
        return
    import subprocess
    import re
    import time
    try:
        # 运行 netstat -ano 查找处于 LISTENING 状态的对应端口行
        output = subprocess.check_output(f'netstat -ano | findstr LISTENING | findstr :{port}', shell=True).decode('utf-8')
        lines = output.strip().split('\n')
        for line in lines:
            if not line: continue
            parts = re.split(r'\s+', line.strip())
            if len(parts) >= 5:
                # 最后一列为 PID，倒数第二列是 LISTENING
                if parts[-2] == 'LISTENING':
                    pid = int(parts[-1])
                    if pid > 0 and pid != os.getpid():
                        logger.info(f"🚨 [端口防护] 检测到端口 {port} 被旧进程 (PID: {pid}) 占用，正在强行终止释放端口...")
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        logger.info(f"✅ [端口防护] 成功终止旧进程 {pid}，端口 {port} 已释放。")
                        time.sleep(1) # 稍等 1 秒让操作系统彻底释放句柄
    except subprocess.CalledProcessError:
        # findstr 没找到任何内容时会抛出 CalledProcessError，说明没有进程在监听此端口，为正常现象
        pass
    except Exception as e:
        logger.error(f"⚠️ [端口防护] 清理端口 {port} 残留进程失败: {e}")

if __name__ == "__main__":
    if os.environ.get("ARB_KILL_PORT_OWNER") == "1":
        kill_port_owner(8000)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info", access_log=False)
