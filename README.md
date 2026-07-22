# arbTest - QDII/LOF 基金折溢价套利监控系统

> 一套围绕 **LOF / QDII 跨境基金折溢价套利** 的完整工作流:实时行情采集 → 估值计算 → 套利看板 → 自动交易 → 实盘对账。

本仓库包含两个核心部分:

| 目录 | 角色 | 技术栈 |
|------|------|--------|
| `arbcore/` | **公共基座库**:数据获取、估值计算、数据库管理、交易接口 | Python |
| `ArbDashboard/` | **监控面板应用**(最终核心项目):看板、分析、自动交易、对账 | FastAPI + Vue 3 |
| `database/` | 共享示例数据库(`arb_master_share.db`,仅含表结构与基础数据) | SQLite (WAL) |

> 注:完整开发环境中还存在 LOFarb(程序1)、jsl(程序2)、ETFRotate(程序4)等姊妹项目,它们与 ArbDashboard 共享 arbcore 基座和统一数据库,但**不在本仓库范围内**(见文末"隐私与开源边界")。

---

## 一、整体架构

```
┌──────────────────────────────────────────────────────┐
│  展示层  Vue 3 + Vite + Naive UI + ECharts            │
│  Dashboard(看板) / Analysis(分析) / AutoTrade(自动交易)│
│  Data(数据管理) / Ledger(对账) / Settings(配置)        │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP / REST(Vite 代理 /api → :8000)
┌──────────────────────┴───────────────────────────────┐
│  服务层  FastAPI(backend/main.py,端口 8000)          │
│  FundService / TradingService / LedgerService          │
│  MarketDataService / ConfigService / SamplerService    │
└──────────────────────┬───────────────────────────────┘
┌──────────────────────┴───────────────────────────────┐
│  基座层  arbcore                                       │
│  Fetchers(行情) / Calculators(估值) / Traders(交易)  │
│  DatabaseManager(funds / market / system 三大模块)    │
└──────────────────────┬───────────────────────────────┘
┌──────────────────────┴───────────────────────────────┐
│  数据层  SQLite WAL(arb_master.db)+ 外部行情源       │
│  通达信 / QMT / IB / 富途 / 新浪 / 腾讯 / 东财 / Woody │
└──────────────────────────────────────────────────────┘
```

### 核心业务脉络(一条数据的旅程)

1. **采集**:`arbcore/fetchers` 从多个数据源拉取行情——实时价格走 `realtime/` 引擎(TDX、QMT、新浪、腾讯),历史收盘价走 `historical/` 引擎(东财、新浪、腾讯、雪球),美股 ETF 走 `ib_reader` / `futu_reader`,QDII 估值因子走 Woody API。
2. **落库**:统一写入 SQLite 数据库(WAL 高并发模式),由 `DatabaseManager` 按 `funds` / `market` / `system` 三个子管理器分域管理。
3. **估值**:`arbcore/calculators` 基于 T-1 净值、持仓因子、汇率,计算**静态估值**(收盘后)与**实时估值**(盘中动态,带 10 分钟基准数据缓存)。
4. **展示**:FastAPI 聚合估值与行情,前端每 15 秒轮询 `/api/dashboard`,渲染折溢价看板与实时曲线。
5. **交易**:自动交易规则引擎按阈值扫描全场,触发后经 `TradeManager`(通达信 TQ 接口)下单;交易明细自动进入 Ledger 对账,并按 T+3 提示快速赎回。

---

## 二、arbcore 基座库

```
arbcore/
├── base_app.py                # BaseApp 应用基类(统一日志/配置/数据库初始化)
├── fetchers/                  # 数据获取
│   ├── realtime/              # 实时行情引擎(manager 统一调度)
│   │   ├── tdx.py             #   通达信(A股 ETF 主源)
│   │   ├── galaxy.py          #   银河 QMT
│   │   ├── guojin.py          #   国金 QMT
│   │   ├── sina.py / tencent.py  # 新浪 / 腾讯
│   ├── historical/            # 历史行情引擎(manager 统一调度)
│   │   ├── eastmoney.py / sina.py / tencent.py / xueqiu.py
│   ├── ib_reader.py           # Interactive Brokers(美股 ETF 主源)
│   ├── futu_reader.py         # 富途(港股主源 / 美股备源)
│   ├── woody_api_service.py   # Woody API(QDII 估值因子与锚点收盘价)
│   ├── market_data_router.py  # 数据源路由(按优先级选源、故障切换)
│   └── market_data_fetcher.py # 统一行情入口
├── calculators/               # 估值计算
│   ├── valuation_math.py      # 核心数学公式(magic / basket 估值)
│   ├── static_valuation.py    # 静态估值(T-1 收盘后批量计算)
│   └── dynamic_valuation.py   # 实时估值(盘中高频,带基准缓存)
├── database/
│   ├── db_manager.py          # DatabaseManager 入口
│   └── managers/              # fund / market / system 子管理器
├── traders/
│   └── trade_manager.py       # A股/LOF 统一交易接口(通达信 TQ)
├── config/
│   ├── fund_categories.json   # 统一基金分类配置(各项目共享)
│   ├── symbol_source_map.py   # 标的 → 数据源映射(128 个标的)
│   └── valuation_mapping.py   # 估值对象类型映射
└── utils/                     # 配置管理 / 健康监控 / 重试管理
```

### 估值核心算法

```
实时溢价率 = (LOF 实时价格 / 实时估值 - 1) × 100
```

- **分子**:基金场内实时价格(TDX / QMT)。
- **分母(实时估值)**:由底层标的实时价格、T-1 净值、持仓比例(position)、对冲因子(hedge)、校准因子(calibration)、汇率联合推算。

### 估值对象类型(valuation_object_type)

| 类型 | 含义 | 示例 |
|------|------|------|
| `SINGLE_ETF` | 跟踪单一 ETF,无锚点 | XOP、QQQ、SPY |
| `MULTI_ETF_ANCHOR` | 同一 ETF 的跨交易所锚点(`^` 前缀 + `-EU/-JP/-HK` 后缀) | `^USO-EU`、`^GLD-JP` |
| `MULTI_ASSET` | 多资产混合 | 501225、160644 |
| `CROSS_MARKET` | 跨市场混合(美股 + A股) | 501225(SOXX + SZ159560) |
| `US_INDEX` | 跟踪美股指数(考虑 13-15 小时时差) | `.INX`、`.NDX` |

> **锚点(Anchor)**:指基金跟踪标的带区域后缀的符号(如 `^USO-EU`),**只有 Woody 数据源认识锚点符号**。实时估值时分子取去掉前后缀的底层 ETF 实时价,分母取 Woody 提供的锚点历史收盘价。

### 数据源选取规则

| 数据需求 | 主源 | 备源 |
|----------|------|------|
| 美股 ETF 实时价 | IB | 富途 |
| 美股 ETF 历史收盘价 | Woody API | 新浪 |
| A股 ETF 实时价 | 通达信(TDX) | QMT |
| A股 ETF 历史收盘价 | TDX 数据库 | — |
| 港股实时价 | 富途 | IB |
| 美股指数 | 新浪 | — |

---

## 三、ArbDashboard 应用

### 后端(`ArbDashboard/backend/`,FastAPI,端口 8000)

`main.py` 启动时的关键流程:
1. **主从架构检测**:探测 5000 端口判断主交易程序(LOFarb)是否在运行——若在运行,则降级为**只读监控模式(Slave)**,跳过通达信全局初始化,避免 TQ 接口冲突。
2. **TQ 全局抢占初始化**:在所有业务模块导入前完成通达信插件的唯一初始化,并拦截重复初始化与回调异常。
3. **端口防护**:启动前自动清理占用 8000 端口的残留进程。

API 分组(约 40 个端点):

| 分组 | 路由前缀 | 职责 |
|------|----------|------|
| 看板 | `/api/dashboard`、`/api/market/*` | 全场折溢价数据、实时/历史行情 |
| 基金 | `/api/fund/{code}/*` | 历史、分时、篮子权重、估值元数据 |
| 自动交易 | `/api/auto_trade/*` | 规则增删改查、启停、运行日志 |
| 实盘 | `/api/trading/*`、`/api/ledger/*` | 持仓、资金、下单、交易记录与 T+3 赎回 |
| 配置 | `/api/config/*` | 基金列表维护、费率、数据源优先级(可拖拽调整) |
| 系统 | `/api/system/*`、`/api/health` | 数据同步触发、IB 重连、引擎重连、里程碑日志 |

服务层(`services/`):`fund_service`(估值聚合)、`trading_service`(封装 TradeManager,带 TQ 故障熔断)、`ledger_service`(对账)、`market_data_service`(行情)、`config_service` / `config_manager_service`(配置)、`system_status_service`(状态里程碑)、`intraday/sampler_service`(盘中采样)。

### 前端(`ArbDashboard/frontend/`,Vue 3 + TypeScript + Vite)

技术栈:Vue 3 + Pinia + Vue Router + Naive UI + ECharts(vue-echarts)+ Axios。

| 页面 | 路由 | 功能 |
|------|------|------|
| 套利看板 | `/dashboard` | 全场分类监控(黄金原油 / QDII 欧美 / QDII 亚洲 / 国内 LOF / 白银),现价、实时与静态估值及溢价率,15 秒轮询 |
| 深度分析 | `/analysis` | 现价 vs 实时估值双曲线、溢价率红绿柱状图、测算沙盘(假设价格推演) |
| 自动交易 | `/auto-trade` | 网格化规则引擎、信号触发进度条、5 秒守护线程 |
| 数据管理 | `/data` | 手动触发数据同步、数据库健康监控 |
| 实盘对账 | `/ledger` | 交易明细、T+3 快速赎回提醒(自动跳过周末) |
| 系统配置 | `/settings` | 数据源优先级拖拽、启停、连接测试 |

> 部分页面组件从 `frontend/src/private/` 动态加载,该目录不入库(见下文)。

### 基金分类一览

| 分类 | 数量 | 代表基金 | 跟踪标的 |
|------|------|----------|----------|
| 黄金原油 | 10 | 162411、162415 | GLD、USO、XOP |
| QDII 欧美 | 11 | 161126、161127 | SPY、QQQ |
| QDII 亚洲 | 16 | 161725、161726 | 港股 / 亚洲指数 ETF |
| 国内 LOF | — | 501018 等 | A 股指数(暂非重点) |
| 白银 | 1 | 161116 | 上期所白银期货 |

---

## 四、数据库设计

- **统一数据库**:所有项目共享一个 `arb_master.db`(SQLite WAL 模式);本仓库提供脱敏示例库 `database/arb_master_share.db`。
- **访问方式**:统一经 `DatabaseManager`,按 `db.funds` / `db.market` / `db.system` 三个域操作,禁止各项目私建独立库。

核心表:

| 表 | 内容 |
|----|------|
| `unified_fund_list` | 统一基金列表(72 只) |
| `unified_fund_history` | 基金历史净值/价格 |
| `usa_etf_daily_prices` | 美股 ETF 历史价(symbol 含锚点符号如 `^USO-EU`) |
| `fund_daily_factors` | 日度估值因子(position / hedge / calibration) |
| `fund_basket_weights` | 基金篮子权重 |
| `exchange_rate` / `index_daily` / `futures_daily` | 汇率 / 指数 / 期货日度数据 |

---

## 五、快速启动

```bash
# 后端(端口 8000)
cd ArbDashboard/backend
pip install -r requirements.txt
python main.py

# 前端(端口 5173,/api 自动代理到 8000)
cd ArbDashboard/frontend
npm install
npm run dev
```

- 前端页面:http://localhost:5173
- API 文档(Swagger):http://localhost:8000/docs

> 完整功能依赖本地行情环境:通达信 TQ 插件(A股实时)、IB TWS / Gateway(美股实时)、富途 OpenD(港股)。缺少时系统会自动降级(只读 / 备源切换),看板仍可基于数据库数据运行。

---

## 六、隐私与开源边界

本仓库采用**白名单制**(见 `.gitignore`),只包含 ArbDashboard 与 arbcore 运行所必需的代码,以下内容**永不入库**:

- `ArbDashboard/backend/private/`、`frontend/src/private/`:私有页面与策略实现
- `account_private.py`、`arb_config.yaml`、`.env`:账号与密钥
- `LOFarb/`、`jsl/`、`ETFRotate/` 等姊妹项目目录
- 真实数据库、原始行情数据(`data/`)、日志与内部文档

---

*文档基于代码现状整理,最后更新:2026-06-12*
