import os
import sys
import subprocess
import pandas as pd
import logging
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
file_handler = logging.FileHandler(log_filepath, encoding='utf-8')
file_handler.setFormatter(logging.Formatter(log_format))

# Setup Console Handler (with colors)
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter(log_format))

# Configure Root Logger
logging.basicConfig(level=logging.INFO, handlers=[file_handler, console_handler])
logger = logging.getLogger("ArbNext")

# [Master-Slave] 检查主交易程序 (LOFarb) 是否运行
import socket
lof_is_running = False
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.1)
    if sock.connect_ex(("127.0.0.1", 5000)) == 0:
        lof_is_running = True

# [V4.4] 强力补丁：全局唯一 TQ 抢占与锁定
# 必须在所有业务模块导入之前执行，防止 TradeManager 或 RealtimeManager 产生冲突
if lof_is_running:
    logger.warning("[主从架构] 检测到主交易程序(LOFarb)正在运行！当前为只读监控模式(Slave)，主动跳过通达信(tdx)全局初始化。")
else:
    try:
        tq_plugin_path = r"D:\new_tdx_test\PYPlugins\user"
        if tq_plugin_path not in sys.path:
            sys.path.insert(0, tq_plugin_path)
        
        import tqcenter
        from tqcenter import tq
        
        # 1. 注入 sys.modules 防止重复加载不同路径的同名模块
        sys.modules['tqcenter'] = tqcenter
        sys.modules['readers.tqcenter'] = tqcenter # 针对 LOFarb 的潜在导入路径
        
        # 2. 强制执行一次正确路径的初始化
        if not getattr(tq, '_is_globally_initialized', False):
            tq.initialize(tq_plugin_path)
            tq._is_globally_initialized = True
            logger.info(f"[Global] TQ 数据接口已全局抢占初始化: {tq_plugin_path}")
            
            # 3. 拦截并强制重定向后续所有初始化
            def safe_initialize(path=None):
                logger.info(f"[Global] 拦截并重定向重复的 TQ 初始化请求 (原请求路径: {path} -> 现强制路径: {tq_plugin_path})")
                return True
            tq.initialize = safe_initialize
            
            # 4. 终极防御：拦截 _get_run_id 以防止回调函数抛出 RuntimeError
            #    注意：_get_run_id 是 classmethod，必须同时 patch 类字典才能拦截 cls._get_run_id() 调用
            _orig_get_run_id = tq._get_run_id
            def safe_get_run_id():
                try:
                    rid = _orig_get_run_id()
                    if rid is None: return 1 # 强制返回一个 dummy ID
                    return rid
                except:
                    return 1
            tq._get_run_id = safe_get_run_id
            # 同时通过类字典 patch，防止 cls._get_run_id() 绕过实例 patch
            try:
                type(tq)._get_run_id = staticmethod(safe_get_run_id)
            except:
                pass
            
            # 5. 拦截 _data_callback_transfer 回调，彻底阻断 RuntimeError 刷屏
            _orig_callback = getattr(tq, '_data_callback_transfer', None)
            if _orig_callback:
                def safe_data_callback_transfer(*args, **kwargs):
                    try:
                        return _orig_callback(*args, **kwargs)
                    except RuntimeError:
                        if not getattr(safe_data_callback_transfer, 'logged', False):
                            logger.warning("[TDX] 回调中 _get_run_id RuntimeError 已被拦截（后续相同错误将静默）")
                            safe_data_callback_transfer.logged = True
                        return None
                    except Exception:
                        return None
                safe_data_callback_transfer.logged = False
                try:
                    tq._data_callback_transfer = safe_data_callback_transfer
                    type(tq)._data_callback_transfer = safe_data_callback_transfer
                except:
                    pass
    except Exception as e:
        logger.error(f"[Global] TQ 全局初始化锁定失败: {e}")

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
    from services.trading_service import TradingService
    from services.config_manager_service import ConfigManagerService
    from services.ledger_service import LedgerService
    
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
        logger.info("交易服务已就绪 (独立模式)")
        
        # [V4.7] 严防死守：若通达信未启动且不是从机模式，显示强力警告并中断程序启动 (仅限 Windows)
        if sys.platform == "win32" and (not trading_service.trade_manager or not getattr(trading_service.trade_manager, 'tdx_available', False)):
            import sys
            import time
            print("\n" + "="*80)
            print("!!! 致命错误：未检测到已成功连接的【通达信】交易账户！ !!!")
            print("="*80)
            print("👉 原因分析：")
            print("   1. 本地【通达信客户端 (TdxW.exe)】尚未启动，或未成功登录交易账号。")
            print("   2. tqcenter 插件无法取得有效的 stock_account 句柄。")
            print("\n👉 解决办法：")
            print("   1) 请先手动双击启动并登录【通达信交易客户端】。")
            print("   2) 确保通达信的 tqcenter 插件成功载入。")
            print("   3) 重新双击运行 start_dashboard.bat 启动看板系统。")
            print("="*80)
            print("正在安全退出系统后端服务，请按任意键关闭窗口并重启通达信...\n")
            time.sleep(2)
            sys.exit(1)
            
    except SystemExit:
        sys.exit(1)
    except Exception as e:
        logger.error(f"交易服务启动失败 (严重异常): {e}")
        import sys
        sys.exit(1) 
_active_watchlist = []
market_data_service = MarketDataService(db)
fund_service = FundService(db, market_data_service=market_data_service, config_service=config_service)
sampler_service = IntradaySamplerService(db, market_data_service, config_service)
sampler_service.active_watchlist = _active_watchlist
config_manager_service = ConfigManagerService(project_root)
ledger_service = LedgerService(db)

# 3. Try to load Private Plugins
try:
    from private.export_service import PrivateExportService
    export_service = PrivateExportService(root_db_path, project_root)
    logger.info("Private export plugins loaded.")
except (ImportError, NameError) as e:
    export_service = None
    logger.info(f"Private export plugins not found or initialization failed: {e}")

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
            # 调用 011 更新脚本
            lofarb_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "LOFarb"))
            script_path = os.path.join(lofarb_dir, "LOF011_daily_updater.py")
            
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
                    subprocess.Popen([python_exe, script_path], cwd=lofarb_dir)
                    logger.info("✅ 011 任务已在后台启动")
                    system_status.add_milestone("SUCCESS", "011 数据更新任务已启动")
                except Exception as e:
                    logger.error(f"❌ 011 任务启动失败: {e}")
                    system_status.add_milestone("ERROR", f"011 任务启动失败: {e}")
            else:
                logger.warning(f"⚠️ 011 脚本不存在: {script_path}")
                system_status.add_milestone("WARNING", "011 脚本路径不存在")
        
        asyncio.create_task(run_011_first())

        # 2. 启动分时采样服务
        await sampler_service.start()
        if sampler_service.running:
            system_status.add_milestone("SUCCESS", "分时采样服务已启动")
        else:
            system_status.add_milestone("INFO", "分时采样服务未启动 (已配置禁用)")

        # 3. 启动实时行情引擎（延迟10秒，等 011 任务先跑起来）
        # 011 需要 1-2 分钟，通达信可以稍后启动
        async def start_mds_later():
            await asyncio.sleep(10) # 等待 10 秒
            try:
                market_data_service.realtime_manager.start()
                logger.info("✅ 实时行情引擎已在后台启动")
                system_status.add_milestone("SUCCESS", "实时行情引擎已启动")
            except Exception as e:
                logger.error(f"❌ 实时行情引擎启动失败: {e}")
                system_status.add_milestone("ERROR", f"实时行情引擎启动失败: {e}")
        
        asyncio.create_task(start_mds_later())

        # 4. 注入依赖并启动自动交易引擎
        auto_trade_runner.db = db
        auto_trade_runner.trade_service = trading_service
        auto_trade_runner.market_service = market_data_service
        # [V4.6] 禁用自动交易引擎启动，防止其暗中加载 TradingService 导致 TDX 冲突
        # auto_trade_runner.start()
        logger.warning("⚠️ [Security] 自动交易引擎已强制停机")
        system_status.add_milestone("WARNING", "自动交易引擎已禁用")

    except Exception as e:
        logger.error(f"❌ Failed during backend startup: {e}")
        system_status.add_milestone("ERROR", f"系统启动自检异常: {e}")

    yield

    logger.info("🛠️ Shutting down ArbNext Backend...")
    await sampler_service.stop()
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
async def get_dashboard(watchlist: str = None):
    """Unified dashboard data for both LOF and JSL
    [V6.0] 接收前端传递的自选基金列表，用于采样服务过滤
    """
    global _active_watchlist
    # 如果前端传递了watchlist参数，更新全局变量（逗号分隔的基金代码）
    if watchlist:
        _active_watchlist = [code.strip() for code in watchlist.split(',') if code.strip()]
        logger.info(f"📌 更新活跃自选列表: {len(_active_watchlist)} 只基金")
        if sampler_service:
            sampler_service.active_watchlist = _active_watchlist
    
    try:
        import traceback
        # 传递自选列表，按需仅计算自选基金，极大地加速响应
        data = fund_service.get_unified_dashboard_data(watchlist=_active_watchlist if watchlist else None)
        return {"status": "ok", "data": data}
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
        # 1. 获取 YAML 配置中的基金信息
        cfg = config_manager_service.load_config()
        funds = cfg.get('funds', [])
        fund_cfg = next((f for f in funds if str(f.get('code')) == code), None)
        if not fund_cfg:
            return {"status": "error", "message": f"Fund {code} not found in config"}
            
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
        portfolio = fund_cfg.get('valuation_portfolio', []) or fund_cfg.get('hedging_portfolio', [])
        etf_symbols = []
        for item in portfolio:
            sym = item.get('symbol', '').replace('^', '')
            for suffix in ['-EU', '-JP', '-HK']:
                if sym.endswith(suffix):
                    sym = sym[:-len(suffix)]
                    break
            etf_symbols.append(sym)
            
        realtime_quotes = {}
        for sym in etf_symbols:
            q = market_data_service.get_realtime_quote(sym) if market_data_service else None
            if q:
                realtime_quotes[sym] = {
                    'price': q.get('price'),
                    'bid': q.get('bid') if q.get('bid') is not None else q.get('price'),
                    'ask': q.get('ask') if q.get('ask') is not None else q.get('price'),
                    'source': q.get('source', '')
                }
            else:
                realtime_quotes[sym] = None
            
        future_symbol = fund_cfg.get('trade_future', '')
        future_quote = None
        if future_symbol:
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
            
        # 5. 获取 T-1 基准估值日数据
        t1_data = {}
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT h.date, COALESCE(h.nav, f.nav) as nav, h.static_val, r.usd_cny_mid, h.calibration 
                FROM unified_fund_history h
                LEFT JOIN exchange_rate r ON h.date = r.date
                LEFT JOIN fund_daily_factors f ON h.date = f.date AND h.fund_code = f.fund_code
                WHERE h.fund_code = ? 
                ORDER BY h.date DESC LIMIT 1
            """, (code,))
            row = cursor.fetchone()
            if row:
                t1_data = {
                    "date": row[0],
                    "nav": float(row[1]) if row[1] is not None else 0.0,
                    "static_val": float(row[2]) if row[2] is not None else 0.0,
                    "exchange_rate": float(row[3]) if row[3] is not None else 0.0,
                    "calibration": float(row[4]) if row[4] is not None else 0.0
                }
                
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
                
                
                # 获取该 T-1 日期对应的 ETF 收盘价
                etf_prices = []
                for item in portfolio:
                    symbol = item.get('symbol', '')
                    if not symbol: continue
                    alt_symbol = symbol if symbol.startswith('^') else f"^{symbol}"
                    cursor.execute("""
                        SELECT COALESCE(NULLIF(netvalue, 0), price) as price 
                        FROM usa_etf_daily_prices 
                        WHERE symbol IN (?, ?) AND date = ?
                    """, (symbol, alt_symbol, row[0]))
                    p_row = cursor.fetchone()
                    p_val = float(p_row[0]) if p_row and p_row[0] is not None else 0.0
                    
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
                    
        return {
            "status": "ok",
            "fund_config": fund_cfg,
            "base_data": formatted_base_data,
            "t1_data": t1_data,
            "latest_exchange_rate": latest_fx,
            "realtime_quotes": realtime_quotes,
            "future_quote": future_quote
        }
    except Exception as e:
        logger.error(f"Error getting valuation meta for {code}: {e}")
        import traceback
        logger.error(traceback.format_exc())
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

# --- Fee & Commission Management APIs ---
@app.get("/api/config/fees/{code}")
async def get_fund_fees(code: str):
    data = ledger_service.get_fund_fees(code)
    return {"status": "ok", "data": data}

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
        broker=data.get('broker', 'tdx')
    )
    return res

@app.post("/api/system/reconnect_ib")
async def reconnect_ib():
    if market_data_service.ib_reader:
        connected = market_data_service.ib_reader.connect_to_ib()
        if connected:
            system_status.add_milestone("INFO", "IB 客户端已成功重连")
            return {"status": "ok", "message": "IB reconnected successfully"}
        else:
            system_status.add_milestone("WARNING", "IB 客户端连接失败，请检查 TWS 是否运行")
            return {"status": "error", "message": "Failed to connect to IB"}
    else:
        from arbcore.fetchers.ib_reader import IBReader
        market_data_service.ib_reader = IBReader(db_manager=db)
        if market_data_service.ib_reader.connect_to_ib():
            system_status.add_milestone("INFO", "IB 客户端已成功启动并连接")
            return {"status": "ok", "message": "IB initialized and connected"}
        else:
            market_data_service.ib_reader = None
            system_status.add_milestone("WARNING", "IB 客户端启动失败，请检查 TWS 是否运行")
            return {"status": "error", "message": "Failed to initialize IB"}

@app.post("/api/system/reconnect_engine")
async def reconnect_engine():
    res = market_data_service.restart_realtime_engine()
    return res

@app.post("/api/system/trigger/{task}")
async def trigger_task(task: str):
    import subprocess
    # [FIX] 脚本路径计算 - LOFarb 在 arbTest 目录下（与ArbDashboard同级）
    # backend -> ArbDashboard -> arbTest -> LOFarb
    lofarb_dir = os.path.normpath(os.path.join(backend_dir, "..", "..", "LOFarb"))
    task_map = {
        "011": os.path.join(lofarb_dir, "LOF011_daily_updater.py"),
        "012": os.path.join(lofarb_dir, "LOF012_calculate_static_valuation.py")
    }
    if task not in task_map:
        return JSONResponse(status_code=400, content={"status": "error", "message": "Invalid task"})

    script_path = task_map[task]
    
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
        
        subprocess.Popen([python_exe, script_path], cwd=script_dir)
        system_status.add_milestone("INFO", f"后台任务 {task} 已手动启动")
        return {"status": "ok", "message": f"Task {task} started in background"}
    except Exception as e:
        error_msg = f"后台任务启动失败: {e}"
        system_status.add_milestone("ERROR", error_msg)
        logger.error(f"❌ {error_msg}")
        return JSONResponse(status_code=500, content={"status": "error", "message": error_msg})

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
    
    # 捕获所有非 API 的前端路由 (SPA Fallback)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # 如果请求静态资源(favicon, etc)，直接返回
        potential_file = os.path.join(frontend_dist_path, full_path)
        if os.path.isfile(potential_file):
            return FileResponse(potential_file)
        # 否则统一返回 index.html 让 Vue Router 接管
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

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
    kill_port_owner(8000)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
