import os
import sys
import subprocess
import pandas as pd
import logging
from logging.handlers import RotatingFileHandler
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from datetime import datetime

# Setup logging
backend_dir = os.path.dirname(os.path.abspath(__file__))
workspace_root = os.path.abspath(os.path.join(backend_dir, ".."))
logs_dir = os.path.join(workspace_root, "logs")

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
    
    try:
        from core.auto_trade.engine_runner import auto_trade_runner
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
    from private.ghost_trader import ghost_trader_instance
    # 注入实盘驱动
    ib_reader = getattr(market_data_service, 'ib_reader', None)
    galaxy_qmt = None
    guojin_qmt = None
    if getattr(market_data_service, 'realtime_manager', None):
        rt = market_data_service.realtime_manager
        galaxy_qmt = rt.active_fetchers.get('galaxy')
        guojin_qmt = rt.active_fetchers.get('guojin')
    ghost_trader_instance.inject_drivers(ib_reader=ib_reader, galaxy_qmt=galaxy_qmt, guojin_qmt=guojin_qmt)
    logger.info("✅ Ghost Trader plugin loaded.")
except (ImportError, NameError) as e:
    ghost_trader_instance = None
    logger.info(f"Ghost Trader plugin not found: {e}")

# Ghost Simulator (weekend mock data)
try:
    from private.ghost_simulator import ghost_simulator_instance
    logger.info("Ghost Simulator loaded.")
except (ImportError, NameError) as e:
    ghost_simulator_instance = None
    logger.info(f"Ghost Simulator not found: {e}")

try:
    from private.signal_detector import signal_detector
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
            # 调用 011 (指向统一的 daily_updater.py) 更新脚本
            scripts_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "arbcore", "scripts"))
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
        
        asyncio.create_task(start_mds_later())

        # 4. SignalDetector（信号检测引擎 — 默认不启动，用户手动开启）
        if signal_detector:
            logger.info("SignalDetector 已就绪，等待用户手动启动")
            system_status.add_milestone("INFO", "信号检测引擎就绪")
        else:
            logger.info("SignalDetector 未加载")
            system_status.add_milestone("INFO", "信号检测引擎未加载")

        # —— 旧版引擎完全禁用 ——

        # 5. 定义脚本路径和 Python 查找的公共函数
        def _get_scripts_dir():
            return os.path.normpath(os.path.join(backend_dir, "..", "..", "arbcore", "scripts"))
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

@app.get("/api/fund/{code}/valuation_meta")
async def get_fund_valuation_meta(code: str):
    try:
        # 1. 获取数据库中的基金信息
        conn = fund_service.db._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT fund_name, related_index, pos_ratio FROM unified_fund_list WHERE fund_code=?", (code,))
        f_row = cursor.fetchone()
        if not f_row:
            return {"status": "error", "message": f"Fund {code} not found in database"}
            
        trade_future = ""
        if "原油" in str(f_row[0]) or "USO" in str(f_row[1]): trade_future = "CL"
        elif "金" in str(f_row[0]) or "GLD" in str(f_row[1]): trade_future = "GC"
        elif "白银" in str(f_row[0]): trade_future = "AG0"
            
        fund_cfg = {
            "code": code,
            "trade_etf": f_row[1] or '',
            "position": float(f_row[2] or 0.95) * 100,
            "trade_future": trade_future
        }
        
        basket_df = pd.read_sql("SELECT underlying_symbol as symbol, weight FROM fund_basket_weights WHERE fund_code=? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)", conn, params=(code, code))
        if not basket_df.empty:
            fund_cfg["valuation_portfolio"] = basket_df.to_dict('records')
        
        # 2. 获取底层的 calculator 基准数据
        calculator = fund_service._get_calculator()
        base_data = calculator.get_base_data(code) if calculator else None
        
        # 动态推演 Hedge 值（如果数据库里为空）
        if base_data and (not base_data.get('hedge') or float(base_data.get('hedge', 0)) <= 0):
            try:
                trade_etf = fund_cfg.get('trade_etf', '')
                if trade_etf:
                    base_etf_price = base_data.get(trade_etf) or base_data.get(f"^{trade_etf}")
                    base_nav = base_data.get('nav')
                    base_pos = base_data.get('position')
                    if base_pos is None or float(base_pos) <= 0:
                        base_pos = float(fund_cfg.get('position', 95.0)) / 100.0
                    base_fx = base_data.get('exchange_rate')
                    if base_etf_price and base_nav and base_pos and base_fx:
                        calc_hedge = (float(base_etf_price) * float(base_fx)) / (float(base_nav) * float(base_pos))
                        base_data['hedge'] = calc_hedge
            except Exception as e:
                logger.error(f"Failed to calculate missing hedge: {e}")
        
        # 3. 获取最新汇率
        conn = fund_service.db._get_conn()
        fx_df = pd.read_sql("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1", conn)
        latest_fx = float(fx_df.iloc[0]['usd_cny_mid']) if not fx_df.empty else 7.0
        
        # 4. 获取最新实时行情 (用于标的 ETF 价格和期货价格)
        portfolio = fund_cfg.get('valuation_portfolio', [])
        etf_symbols = []
        for item in portfolio:
            sym = item.get('symbol', '').replace('^', '')
            for suffix in ['-EU', '-JP', '-HK']:
                if sym.endswith(suffix):
                    sym = sym[:-len(suffix)]
                    break
            etf_symbols.append(sym)
            
        from concurrent.futures import ThreadPoolExecutor, as_completed
        realtime_quotes = {}
        def _fetch_quote(sym):
            try:
                q = market_data_service.get_realtime_quote(sym) if market_data_service else None
                if q:
                    return sym, {
                        'price': q.get('price'),
                        'bid': q.get('bid') if q.get('bid') is not None else q.get('price'),
                        'ask': q.get('ask') if q.get('ask') is not None else q.get('price'),
                        'source': q.get('source', '')
                    }
                return sym, None
            except Exception as e:
                logger.error(f"Error getting quote for {sym}: {e}")
                return sym, None
        with ThreadPoolExecutor(max_workers=min(len(etf_symbols) or 1, 5)) as pool:
            for sym, result in pool.map(_fetch_quote, etf_symbols):
                realtime_quotes[sym] = result
            
        future_symbol = fund_cfg.get('trade_future', '')
        future_quote = None
        if future_symbol:
            try:
                q = market_data_service.get_realtime_quote(future_symbol) if market_data_service else None
                if q:
                    future_quote = {
                        'price': q.get('price'),
                        'bid': q.get('bid') if q.get('bid') is not None else q.get('price'),
                        'ask': q.get('ask') if q.get('ask') is not None else q.get('price'),
                        'source': q.get('source', '')
                    }
                else:
                    future_quote = None
            except Exception as e:
                logger.error(f"Error getting future quote for {future_symbol}: {e}")
                future_quote = None
            
        # 5. 获取 T-1 估值日数据（最新美股收盘日）
        t1_data = {}
        try:
            cursor = conn.cursor()
            # T-1 估值日 = 美股最近收盘日（usa_etf_daily_prices 最新日期）
            cursor.execute("SELECT MAX(date) FROM usa_etf_daily_prices")
            t1_date_row = cursor.fetchone()
            if t1_date_row:
                t1_date = t1_date_row[0]
            else:
                t1_date = base_data.get('date', '') if base_data else ''

            if t1_date:
                # NAV 仍取最新有净值的记录（可能早于 T-1）
                cursor.execute("""
                    SELECT COALESCE(h.nav, f.nav) as nav, h.static_val, r.usd_cny_mid, h.calibration, h.price 
                    FROM unified_fund_history h
                    LEFT JOIN exchange_rate r ON h.date = r.date
                    LEFT JOIN fund_daily_factors f ON h.date = f.date AND h.fund_code = f.fund_code
                    WHERE h.fund_code = ? AND COALESCE(h.nav, f.nav, 0) > 0
                    ORDER BY h.date DESC LIMIT 1
                """, (code,))
                row = cursor.fetchone()
                if row:
                    t1_data = {
                        "date": t1_date,
                        "nav": float(row[0]) if row[0] is not None else 0.0,
                        "static_val": float(row[1]) if row[1] is not None else 0.0,
                        "exchange_rate": float(row[2]) if row[2] is not None else 0.0,
                        "calibration": float(row[3]) if row[3] is not None else 0.0,
                        "price": float(row[4]) if row[4] is not None else 0.0
                    }
                elif base_data:
                    # 连净值都取不到时，以 T-2 垫底
                    t1_data = dict(base_data)
                    t1_data['date'] = t1_date
                
                if not t1_data:
                    # 无任何数据可用，跳过 T-1 处理
                    pass
                else:
                    # 如果没有独立校准值，查找全局期货校准值兜底
                    if t1_data["calibration"] == 0.0 and future_symbol:
                        base_fsym = future_symbol
                        if 'MGC' in future_symbol or 'GC' in future_symbol: base_fsym = 'GC'
                        elif 'MCL' in future_symbol or 'CL' in future_symbol: base_fsym = 'CL'
                        elif 'MNQ' in future_symbol or 'NQ' in future_symbol: base_fsym = 'NQ'
                        elif 'MES' in future_symbol or 'ES' in future_symbol: base_fsym = 'ES'
                        
                        cursor.execute("""
                            SELECT calibration FROM futures_daily 
                            WHERE symbol = ? AND calibration IS NOT NULL 
                            ORDER BY date DESC LIMIT 1
                        """, (base_fsym,))
                        crow = cursor.fetchone()
                        if crow:
                            t1_data["calibration"] = float(crow[0])
                            if base_data:
                                base_data['calibration'] = float(crow[0])
                    
                    # 获取该 T-1 日期对应的 ETF 收盘价（精确日期优先，缺失则往前找最近一日）
                    etf_prices = []
                    for item in portfolio:
                        symbol = item.get('symbol', '')
                        if not symbol: continue
                        alt_symbol = symbol if symbol.startswith('^') else f"^{symbol}"
                        cursor.execute("""
                            SELECT COALESCE(NULLIF(netvalue, 0), price) as price 
                            FROM usa_etf_daily_prices 
                            WHERE symbol IN (?, ?) AND date = ?
                        """, (symbol, alt_symbol, t1_date))
                        p_row = cursor.fetchone()
                        p_val = float(p_row[0]) if p_row and p_row[0] is not None else 0.0
                        
                        # 精确日期没取到，往前找最近一日
                        if p_val <= 0:
                            cursor.execute("""
                                SELECT COALESCE(NULLIF(netvalue, 0), price) as price 
                                FROM usa_etf_daily_prices 
                                WHERE symbol IN (?, ?) AND date <= ? AND price > 0
                                ORDER BY date DESC LIMIT 1
                            """, (symbol, alt_symbol, t1_date))
                            fallback_row = cursor.fetchone()
                            if fallback_row:
                                p_val = float(fallback_row[0])
                        
                        display_symbol = symbol
                        for suffix in ['-EU', '-JP', '-HK']:
                            if display_symbol.endswith(suffix) and not display_symbol.startswith('^'):
                                display_symbol = f"^{display_symbol}"
                                break
                        
                        base_price = 0
                        if base_data:
                            base_price = float(base_data.get(display_symbol, base_data.get(symbol, 0)))
                        
                        pct_change = 0
                        if base_price > 0:
                            pct_change = (p_val / base_price - 1) * 100
                            
                        etf_prices.append({
                            "symbol": display_symbol,
                            "price": p_val,
                            "pct_change": pct_change
                        })
                    t1_data["etfs_info"] = etf_prices
                    
                    # 如果 T-1 的静态估值为 0，则利用 T-2 的基准数据和 T-1 的 ETF 收盘价进行动态推演
                    if t1_data["static_val"] <= 0 and base_data and calculator:
                        try:
                            t1_etfs = {info["symbol"].lstrip('^'): info["price"] for info in etf_prices}
                            for info in etf_prices:
                                t1_etfs[info["symbol"]] = info["price"]
                            
                            t1_fx = t1_data["exchange_rate"] if t1_data["exchange_rate"] > 0 else base_data.get("exchange_rate", 7.0)
                            
                            calc_res = calculator.calculate(fund_cfg, t1_fx, t1_etfs)
                            if calc_res and calc_res.get('rt_val'):
                                t1_data["static_val"] = float(calc_res['rt_val'])
                        except Exception as e:
                            logger.error(f"Failed to dynamically calculate T-1 static_val: {e}")
        except Exception as e:
            logger.warning(f"获取 T-1 估值日数据失败: {e}")

        # 格式化 base_data 以免 JSON 序列化失败
        formatted_base_data = {}
        if base_data:
            import numpy as np
            for k, v in base_data.items():
                if pd.isna(v):
                    formatted_base_data[k] = None
                elif isinstance(v, (np.integer, int)):
                    formatted_base_data[k] = int(v)
                elif isinstance(v, (np.floating, float)):
                    formatted_base_data[k] = float(v)
                else:
                    formatted_base_data[k] = str(v)
        
        # [现金管理] 为511880/511360/511520添加估值参数
        BOND_ETF_CODES = ['511880', '511360', '511520']
        bond_extra = {}
        if code in BOND_ETF_CODES:
            try:
                from services.bond_etf_valuation import get_bond_etf_valuation
                bv = get_bond_etf_valuation(conn, market_data_service)
                val = bv.get_valuation(code)
                bond_extra = {
                    "avg_daily_growth": val.get('avg_daily_growth'),
                    "treasury_index_pct": val.get('treasury_index_pct'),
                    "estimated_nav": val.get('estimated_nav'),
                    "latest_nav": val.get('latest_nav'),
                    "latest_nav_date": val.get('latest_nav_date'),
                    "futures_pct": val.get('futures_pct'),
                    "tf_pct": val.get('tf_pct'),
                    "futures_adjustment": val.get('futures_adjustment'),
                    "total_adjustment": val.get('total_adjustment'),
                }
            except Exception as e:
                logger.error(f"[BondETF] valuation_meta获取失败 {code}: {e}")
                    
        return {
            "status": "ok",
            "fund_config": fund_cfg,
            "base_data": formatted_base_data,
            "t1_data": t1_data,
            "latest_exchange_rate": latest_fx,
            "realtime_quotes": realtime_quotes,
            "future_quote": future_quote,
            **bond_extra
        }
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

@app.post("/api/config/funds/upsert")
async def upsert_fund_config(request: Request):
    """新增或修改基金配置"""
    data = await request.json()
    success = config_manager_service.upsert_fund_config(data)
    return {"status": "ok" if success else "error"}

@app.delete("/api/config/funds/{code}")
async def delete_fund_config(code: str):
    """从 YAML 中删除基金"""
    success = config_manager_service.delete_fund_config(code)
    return {"status": "ok" if success else "error"}

# --- Private / Custom Export APIs ---
@app.get("/api/private/status")
async def get_private_status():
    """检测私密插件是否挂载"""
    return {"status": "ok", "loaded": export_service is not None}

@app.get("/api/private/export/{code}")
async def export_fund_data(code: str):
    if not export_service:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Private export plugin not loaded"})
    
    csv_data, error = export_service.export_fund_to_csv(code)
    if error:
        return JSONResponse(status_code=500, content={"status": "error", "message": error})
    
    from fastapi.responses import Response
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=fund_export_{code}.csv"
        }
    )

@app.get("/api/private/ghost_calc")
async def ghost_calc(fund_code: str = "162411"):
    """
    幽灵做市商实时计算 — 复用 fund_service.get_valuation_meta() 获取完整估值数据。
    额外计算 Ghost 特有模式（safe/peg）的折溢价。
    """
    if not ghost_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Ghost Trader not loaded"})

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

        # 4. hedge 值（复用 get_valuation_meta 返回的）
        hedge = float(base_data.get("hedge", 0)) if base_data else 0
        position = float(fund_cfg.get("position", 95.0)) / 100.0 if fund_cfg else 0.95

        # 5. Ghost 特有溢价计算（safe 砸单 / peg 内卷）
        # 正确公式: val = base_nav * (1 - pos) + pos * (us_price * fx) / hedge
        base_nav = float(base_data.get("nav", 0)) if base_data else 0
        if base_nav > 0 and hedge > 0:
            val_safe = base_nav * (1 - position) + position * (us_bid * latest_fx) / hedge
        else:
            val_safe = 0
        premium_safe = (lof_bid / val_safe - 1) * 100 if val_safe > 0 else 0

        if base_nav > 0 and hedge > 0:
            peg_price = (us_ask - 0.01) if us_ask > 0.01 else us_ask
            val_peg = base_nav * (1 - position) + position * (peg_price * latest_fx) / hedge
        else:
            val_peg = 0
        premium_peg = (lof_bid / val_peg - 1) * 100 if val_peg > 0 else 0

        # 6. 赎回费率（从 get_valuation_meta 的 t1_data 信息里取，默认 0.50）
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
        logger.error(f"[GhostCalc] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.post("/api/private/ghost_place_order")
async def ghost_place_order(request: Request):
    """
    幽灵做市商下单接口
    - quantity: LOF 份额数（如 59500），系统自动用 hedge 系数换算出 ETF 对冲股数
    - etf_quantity: 可选，如果前端已算好 ETF 股数，直接使用（绕开换算）
    """
    if not ghost_trader_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Ghost Trader not loaded"})
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
            results = ghost_trader_instance.place_peg_order(
                underlying_symbol=underlying_symbol,
                quantity=etf_quantity,
                us_ask1=price,
            )
        elif direction == "close":
            results = ghost_trader_instance.place_close_order(
                fund_code=fund_code,
                underlying_symbol=underlying_symbol,
                lof_price=lof_price,
                us_ask1=price,
                lof_quantity=lof_quantity,
                etf_quantity=etf_quantity,
            )
        else:
            results = ghost_trader_instance.place_open_order(
                fund_code=fund_code,
                underlying_symbol=underlying_symbol,
                lof_price=lof_price,
                us_bid1=price,
                lof_quantity=lof_quantity,
                etf_quantity=etf_quantity,
            )
        any_ok = any(r.get("success") for r in results)
        return {"status": "ok" if any_ok else "error", "data": results}
    except Exception as e:
        logger.error(f"[GhostOrder] Error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

# --- Ghost Simulator API (weekend mock data) ---
@app.get("/api/private/ghost_simulate/status")
async def ghost_simulate_status():
    """Get current simulation state and history"""
    if not ghost_simulator_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Ghost Simulator not loaded"})
    return {"status": "ok", "data": ghost_simulator_instance.get_status()}

@app.post("/api/private/ghost_simulate/control")
async def ghost_simulate_control(request: Request):
    """Start/stop/reset simulation, or toggle forced signal"""
    if not ghost_simulator_instance:
        return JSONResponse(status_code=403, content={"status": "error", "message": "Ghost Simulator not loaded"})
    try:
        body = await request.json()
        action = body.get("action", "status")
        if action == "start":
            result = ghost_simulator_instance.start()
        elif action == "stop":
            result = ghost_simulator_instance.stop()
        elif action == "reset":
            result = ghost_simulator_instance.reset()
        elif action == "force_signal":
            enabled = body.get("enabled", True)
            result = ghost_simulator_instance.set_forced_signal(enabled)
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": f"Unknown action: {action}"})
        return {"status": "ok", "data": result}
    except Exception as e:
        logger.error("[GhostSim] Control error: %s", e)
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
    """重连银河QMT - 使用 reconnect() 方法，试连 3 次"""
    try:
        if market_data_service.realtime_manager:
            rm = market_data_service.realtime_manager
            galaxy = rm.active_fetchers.get('galaxy')
            if galaxy:
                success, msg = galaxy.reconnect()
            else:
                # 懒创建：首次点击时创建实例并注册到管理器
                from arbcore.fetchers.realtime.galaxy import GalaxyQmtFetcher
                galaxy = GalaxyQmtFetcher()
                rm.active_fetchers['galaxy'] = galaxy
                success, msg = galaxy.reconnect()
            if success:
                system_status.add_milestone("SUCCESS", msg)
                return {"status": "ok", "message": msg}
            else:
                system_status.add_milestone("WARNING", msg)
                return {"status": "error", "message": msg}
        else:
            system_status.add_milestone("WARNING", "实时行情管理器未启动")
            return {"status": "error", "message": "实时行情管理器未启动"}
    except Exception as e:
        system_status.add_milestone("ERROR", f"银河QMT重连异常: {e}")
        return {"status": "error", "message": str(e)}

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
    # [FIX] 脚本路径计算 - 彻底解耦 LOFarb，指向统一的 arbcore/scripts/daily_updater.py
    scripts_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "arbcore", "scripts"))
    lofarb_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "LOFarb"))
    task_map = {
        "011": os.path.join(scripts_dir, "daily_updater.py"),
        "012": os.path.join(lofarb_dir, "LOF012_calculate_static_valuation.py"),
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

# --- Auto Trade Engine APIs ---
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

# --- AutoExecutor (Ghost Trader 自动执行) APIs ---
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


# ==============================================================
# [V6.5] 静态前端挂载 (公网部署与动静合一)
# 允许使用 512M 小内存 VPS 同时提供 Backend API 和 Frontend
# ==============================================================
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 优先查找上一级目录的 frontend/dist
frontend_dist_path = os.path.join(workspace_root, "frontend", "dist")

if os.path.exists(frontend_dist_path):
    logger.info(f"Detected frontend dist at {frontend_dist_path}, mounting static files.")
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist_path, "assets")), name="assets")

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
