# arbTest 基金套利监控系统 - AI 编程助手快速入门

> 本文档供 AI 编程助手（CodeBuddy、Gemini、Trae 等）快速了解项目架构，避免在新对话中重复了解上下文。
> 最后更新：2026-06-11

---

## 一、系统概述

**arbTest** 是基金套利监控系统集合，采用**"大一统底层基座 (arbcore + SQLite WAL 模式)"**，共享同一个数据库。

### 项目关系

| 项目 | 目录 | 状态 | 用途 |
|------|------|------|------|
| **程序1** | `LOFarb/` | ✅ 已完成 | LOF 基金折价套利 |
| **程序2** | `jsl/` | ⚠️ 未完成 | 集思录全市场监控 |
| **程序3** | `ArbDashboard/` | 🔧 开发中 | **最终核心项目**（跨市场 QDII 看板与执行） |
| **程序4** | `ETFRotate/` | ❌ 未使用 | ETF 轮动策略（旧代码，待统一） |

**底层基座**：`arbcore/` - 所有程序共享的核心库

**核心技术栈**：
- **大一统数据库**：`database/arb_master.db` (WAL 高并发模式，Single Source of Truth)
- **标准化基座**：`BaseApp` (提供统一日志、配置加载与数据库连接)
- **模块化管理**：`DatabaseManager` 采用组合模式拆分为 `Fund` / `Market` / `System` 子管理器

---

## 二、核心架构 (工业级铁三角)

```
1. 交易中台 (arbcore/traders) → TradeManager (TDX/QMT 统一接口)
2. 数据中台 (arbcore/fetchers) → 统一 Historical/Realtime 管理器 (Sina/EM/Tencent/Xueqiu/IB/Futu)
3. 智能路由 (arbcore/config) → symbol_source_map (全自动标的分发)
4. 冲突保护 → Master-Slave 架构 (解决通达信 DLL 多开冲突)
```

---

## 三、基金分类与估值对象类型

### 3.1 前端 TAB 分类

| 前端 TAB | 内部估值方法 | 跟踪标的 | 代表基金 | 数据源 |
|----------|-------------|---------|---------|--------|
| 黄金原油 | `commodity_gold_oil` | GLD、USO、XOP 及区域锚点 | 162411、162415 | 美股 ETF 价格 |
| QDII欧美 | `equity_us_etf` | 美股 ETF（SPY、QQQ 等） | 161126、161127、164906 | 美股 ETF 价格 |
| QDII欧美 | `equity_us_index` | 美国指数（.INX、.NDX） | 161125、161130 | **新浪指数价格** |
| QDII欧美 | `hybrid_cross` | 一篮子股票/ETF | 160225、501225 | 多资产组合价格 |
| QDII亚洲 | `equity_asia` | 亚洲市场指数/ETF | 161725、161726 | 亚洲市场数据 |
| 国内LOF | `lof_domestic` | A股 LOF 折溢价 | 501018、501025 等 | A股行情 |
| 白银 | `commodity_silver` | 上海期货交易所 | 161116 | 上期所白银期货 |

### 3.1.1 设计思路：聚焦高价值套利机会

**核心认知**：套利主要机会集中在黄金原油、XOP、INDA 等少数基金上，其他分类的套利机会相对较少。

**设计体现**：

1. **自选基金机制**
   - 程序提供"自选基金"功能，用户可以聚焦关注的少数基金
   - 实盘分析和执行时，默认只监控自选基金列表

2. **实时行情获取策略**
   - 美股实时行情默认只获取有限的少数美股 ETF 夜盘行情（IB、富途）
   - 避免一次性获取全部 ETF 行情，降低 IB、富途 API 负载
   - 避免程序处理过多数据造成性能压力

3. **实盘分析聚焦**
   - 实盘分析部分聚焦有限的几个高价值基金的折价、溢价监控
   - 黄金原油、XOP、INDA 等是重点监控对象
   - 其他分类（QDII 亚洲、国内 LOF 等）作为辅助参考

4. **前端 TAB 设计**
   - 黄金原油 TAB 放在最前面，方便快速查看
   - 其他 TAB 作为补充，用户可根据需要切换

**总结**：程序不是监控所有基金，而是聚焦少数高价值套利机会，通过自选基金机制让用户自定义关注列表，实现精准监控。

### 3.2 估值对象类型（valuation_object_type）

| 类型 | 说明 | 示例 | 实时估值分子分母规则 |
|------|------|------|---------------------|
| **SINGLE_ETF** | 单ETF（无锚点） | XOP、QQQ、SPY | 分子分母都用同一个符号 |
| **MULTI_ETF_ANCHOR** | 多ETF（有锚点） | ^USO-EU、^GLD-JP、^USO-HK | 分子：去掉^和-EU/-JP/-HK后缀，取基础代码实时价格<br>分母：保留原始符号，查 Woody API 历史收盘价 |
| **MULTI_ASSET** | 多资产混合 | 501225、501312、160644 | 需要分别获取多个资产的价格 |
| **CROSS_MARKET** | 跨市场混合 | 501225（SOXX美股 + SZ159560 A股） | 跨市场资产分别获取价格 |
| **US_INDEX** | 美股指数 | .INX（标普500）、.NDX（纳斯达克100） | 调用指数数据获取函数，考虑13-15小时时差 |

### 3.3 锚点（Anchor）概念

**锚点是 Woody 发明的概念**，指基金跟踪的标的物带有区域后缀（`-EU`欧洲、`-JP`日本、`-HK`香港）。

**示例**：
- `^USO-EU`、`^GLD-JP`、`^USO-HK`
- **只有 Woody 数据源认识这种带^前缀和-EU/-JP/-HK后缀的符号**
- 其他数据源（IB、TDX、SINA等）不认识锚点符号

**实时估值计算规则**：
- **分子（实时价格）**：`^USO-EU`、`^USO-JP`、`^USO-HK` → 都取 USO 实时价格（去掉^和-EU/-JP/-HK后缀）
- **分母（基准日价格）**：数据库里存的带后缀的历史价格（如 `^USO-EU` 的基准日价格）

**有锚点的基金**：
- 黄金原油：501018、160723、161129、161815、160719、161116、165513（有`-EU`后缀）
- QDII欧美：164824（INDA，有`^INDA-EU`、`^INDA-JP`、`^INDA-HK`锚点）

---

## 四、数据源规则

### 4.1 数据源映射（symbol_source_map.py）

| 数据源 | 标的类型 | 数量 | 说明 |
|--------|---------|------|------|
| **IB** | 美股 ETF | 48 个标的 | 主数据源 |
| **FUTU** | 港股 + 美股备用 | 48 个美股标的 | 富途，无 IB 账户时使用 |
| **TDX** | A 股 ETF、期货、指数 | 64+ 标的 | 主数据源 |
| **QMT_YH** | A 股/期货 | 备用 | 银河 QMT |
| **QMT_GJ** | A 股/期货 | 备用 | 国金 QMT |
| **SINA** | 指数 | 9 个 | `.INX`、`.NDX` 等 |
| **WOODY** | QDII 估值 | 暂未使用 | 只有 Woody 认识锚点符号 |

### 4.2 数据源选择规则

| 数据类型 | 实时价格数据源 | 历史收盘价/成交量数据源 |
|----------|--------------|----------------|
| **美股ETF** | IB（主）或富途（备），**绝不可能是 TDX** | Woody API（netvalue字段）或新浪 |
| **A股ETF/LOF** | TDX/QMT（实时瀑布流） | **腾讯接口（Tencent）**（V8.0重大升级：完美平替新浪，提供精准历史成交量） |
| **港股股票** | 富途（主）或 IB（备） | 富途数据库 |
| **美股指数** | 新浪（待确认，暂未使用） | - |
| **Woody API** | 只有 Woody 认识锚点符号 | Woody API 原始数据路径：`D:\Study\arbTest\data\woodyAPI\Data_woody_lof_YYYYMMDD_HHMM.json` |

### 4.3 切换数据源

```python
# 美股 ETF 切换
get_symbol_source('GLD', use_ib=True)  # → 'IB'（默认）
get_symbol_source('GLD', use_ib=False) # → 'FUTU'

# A 股 ETF 切换
get_cn_stock_source('YH')  # → 'QMT_YH'（银河 QMT）
get_cn_stock_source('GJ')  # → 'QMT_GJ'（国金 QMT）
```

### 4.4 历史 K 线与成交量（V8.0 重大升级：腾讯接口）
曾长期使用新浪（Sina）接口拉取 A 股/QDII LOF 历史收盘价，但新浪历史 K 线接口**已不再返回成交量 (Volume)**。
为了支持对冲与流动性分析，系统于 V8.0 将历史收盘价与成交量数据源**全面替换为腾讯（Tencent）`fqkline` 接口**：
- **优势**：不仅返回精准的复权收盘价，还能返回精确的成交量（以“手”为单位，程序会自动换算为“万元”成交额），完美平替新浪且数据更全。
- **机制**：在 `LOF011_daily_updater.py` 中，使用 `TencentHistoricalFetcher` 获取所有 72 只关注基金的日度历史收盘价和成交额并入库 `unified_fund_history`。

### 4.5 特定数据源的时效性限制与 VPS 云端流水线
请特别注意，以下五个数据源**只支持获取最新一日的数据**，无法通过传入历史日期来拉取过往记录：
1. **外汇中心汇率** (`usd_cny_mid`)：只能获取当天中间价。
2. **Woody API**：接口只返回最新日期的各项估值、基准价。
3. **新浪全球期货结算价与收盘价** (`http://hq.sinajs.cn/list=hf_...`)：只返回上一个交易日的结算价和收盘价。
4. **深交所“场内份额”**：只返回前一日的最新场内流通份额。
5. **Woody 区域变种 ETF 行情** (例如 `^USO-EU`)：经常因为节假日缺失。

> **对策与三级兜底防刷机制**：为了应对此时效性限制，系统设计了云端 VPS 采集 + 本地程序提取的架构：
- **云端**：通过 `ArbDashboard/scripts/cloud_siphon.py` (09:20 采集 Woody/汇率/期货) 和 `041_jsl_cloud_shares.py` (06:00 采集深交所份额)，日夜持续运行并生成 JSON。
- **本地 (LOF011)**：每日更新程序通过 SFTP 从 VPS 拉取上述 JSON 文件入库（大一统表）。
- **防刷兜底**：如 `step8_fetch_sina_futures_from_vps`，首先检查数据库当日是否已标记为成功；如果未成功，去拉取 VPS 数据；如果 VPS 失败或未采集到当天数据，则自动启动**本地新浪 API 兜底抓取** (`data_fetcher.py`)，确保数据链条绝对稳固。

---

## 五、数据库设计

### 5.1 统一数据库

- **路径**：`d:\Study\arbTest\database\arb_master.db`（上级目录）
- **模式**：WAL 高并发模式
- **模块**：
  - `db.funds` - 基金数据
  - `db.market` - 市场数据
  - `db.system` - 系统配置
- **覆盖项目**：ArbDashboard、JSL、LOFarb、ETFRotate（所有项目共享）
- **已废弃**：`jsl/jsl_monitor.db`（已于 2026-06-09 删除）

### 5.2 核心表

- `unified_fund_list` - 统一基金列表（72 只基金）
- `unified_fund_history` - 统一基金历史（37,823+ 条记录）
- `usa_etf_daily_prices` - 美股 ETF 历史价格（symbol 列存储完整符号如 `^USO-EU`）
- `exchange_rate` - 汇率数据
- `index_daily` - 指数日度数据
- `futures_daily` - 期货日度数据
- `fund_daily_factors` - 基金日度因子
- `fund_basket_weights` - 基金篮子权重

---

## 六、核心业务逻辑

### 6.1 实时估值计算公式

```
实时溢价率 = (LOF 实时价格 / 实时估值 - 1) × 100
```

**分子（实时价格）**：
- `^USO-EU`、`^USO-JP`、`^USO-HK` → 都取 USO 实时价格
- `^GLD-EU`、`^GLD-JP`、`^GLD-HK` → 都取 GLD 实时价格
- 实现：去掉 `^` 前缀和 `-EU/-JP/-HK` 后缀，用基础代码查 `current_etfs` 字典

**分母（基准日价格）**：
- 数据库里存的带后缀的历史价格（如 `^USO-EU`、`^GLD-JP` 的基准日价格）
- 实现：保留原始符号（如 `^USO-EU`），查 `base_data` 字典

### 6.2 实时行情四级瀑布流

优先级：**银河QMT (Socket)** > **通达信 (内存直连)** > **国金QMT (xtquant)** > **新浪API (轮询)**

### 6.3 跨市场时间差替身（虚拟后缀）的本质

带有 `-EU`、`-JP`、`-HK` 后缀的资产（如 `GLD-EU`）是该 ETF 在其他交易所收盘时的"美股盘中快照价"。

- **静态估值**：`T日-EU / T-1日-EU`（对点对比原则）
- **实时估值**：`实时美股价格 / T-1日-EU`（归拢原则）

### 6.4 取价策略

```
LOF 实时价格：卖一价（涨停时降级为最新成交价）
IB ETF 实时价格：买一价
```

这套取价逻辑在数学上构成了**"买入 A股 LOF (看卖一) + 卖空 美股 ETF (看买一)"** 的严谨对冲闭环。

### 6.5 实时估值计算流程

```
1. fund_service.py 接收请求
   ↓
2. 从 fund_basket_weights 读取基金的跟踪标的（如 GLD, XBI）
   ↓
3. 调用 symbol_source_map.py 查询每个标的的数据源
   ↓
4. 根据数据源选择 fetcher：
   - IB → IBReader
   - FUTU → FutuReader
   - TDX → TDXFetcher
   ↓
5. 获取实时价格
   ↓
6. dynamic_valuation.py 计算加权估值
   ↓
7. 返回实时估值和溢价率
```

### 6.6 基金优先级分类与前端刷新策略

为了保障关键套利窗口的高频刷新，同时避免过度占用接口，系统采用**分级刷新策略**：
1. **高优先级 Tab** (`我的自选`、`黄金原油`、`QDII欧美`): 前端以 **3 秒/次** 进行高频轮询刷新。
2. **普通优先级 Tab** (`QDII亚洲`、`国内LOF`、`白银`): 前端以 **30 秒/次** 进行低频刷新。
3. 自选列表存储：自选基金列表被持久化于数据库的 `fund_watchlist` 表与前端的 `localStorage` 中。

### 6.8 性能优化预留方案（待实现）

当监控基金数量庞大时（例如 70+ 只），为了解决 `get_dashboard_data` 计算耗时过长导致前端页面等待的问题，计划引入以下高级优化策略：
1. **数据库查询缓存机制（Cache）**：
   - 对于每日固定不变的历史数据（如 T-1 的净值、静态估值等），可引入 Redis 或内存级 `lru_cache`。
   - 避免每次请求都触发 SQLite 的截面查询，把耗时的大批量 `pd.read_sql_query` O(N) 操作降维到 O(1)。
2. **多线程/协程并发拉取（Concurrent Fetching）**：
   - 当遇到多个需要网络请求的操作（如请求新浪/腾讯 API 获取指数）时，采用 `asyncio` 或 `ThreadPoolExecutor` 并发拉取。
   - 避免顺序请求导致的总耗时叠加，特别是当某个接口出现网络波动时，可以利用超时控制快速降级。

### 6.7 高效分时采样执行机制（1分钟白名单过滤与单自选采集）

分时数据采样（存储于 `fund_intraday_quotes` 表，包含价格、实时估值、折溢价率）为 1 分钟触发一次，但由于全市场采样开销极大，系统实施了**按优先级按需采样**：
1. **行级过滤**：在每次执行 1 分钟采样时，程序会遍历所有基金，但**只筛选并采样属于【我的自选】（Watchlist）这一类高频 Tab 里的基金**。
2. **标的白名单过滤**：对于需要采样的基金，系统会**自动将其底层挂钩的美股 ETF（如 GLD, USO 等）纳入动态白名单**并向 IB/富途 订阅夜盘实时价格。未在【我的自选】（Watchlist）中的非高频基金则跳过实时获取，大大减轻了 CPU 负荷和 API 请求压力。不再需要人工在界面上维护订阅名单。

---

## 七、常见问题

### 7.1 启动 ArbDashboard（程序3，核心项目）

```bash
# 双击启动
start_dashboard.bat

# 或手动启动
cd d:\Study\arbTest\ArbDashboard
pip install -r requirements.txt
cd backend && python main.py  # 后端 8000 端口
cd ../frontend && npm run dev  # 前端 5173 端口
```

### 7.2 启动 LOFarb（程序1）

```bash
cd d:\Study\arbTest\LOFarb
python LOF011_daily_updater.py
```

### 7.3 启动 ETFRotate（程序4）

```bash
cd d:\Study\arbTest\ETFRotate
python etf_03_rotation_server.py
```

---

## 八、常见问题

### 8.1 通达信初始化错误

```
RuntimeError: TQ 数据接口未正确初始化
```

**原因**：`__file__` 指向 arbcore 路径，而非通达信插件路径

**影响**：仅影响 A 股 ETF 实时行情，美股 ETF 不受影响

### 8.2 数据库路径错误

**正确路径**：`d:\Study\arbTest\database\arb_master.db`

**错误路径**：`backend/arb_master.db`、`backend/database/arb_master.db`、`jsl/jsl_monitor.db`（已废弃）

**注意**：所有项目必须使用统一数据库，不要创建新的独立数据库文件

### 8.3 Master-Slave 架构（通达信 DLL 多开冲突保护与独立数据录入）

- **主从冲突保护机制**：
  - **Master（主系统 - LOFarb / 程序1）**：启动时独占占用本地 `5000` 端口 (Flask)，独占通达信 TQ 接口。
  - **Slave（从系统 - ArbDashboard 看板 / 程序3）**：启动时探测 `127.0.0.1:5000` 端口。
    - 如果端口 5000 被占用 → 自动进入 **Slave 模式**（禁用本地通达信驱动和下单功能，只做数据展示和模拟沙盘，以避开通达信多开 DLL 冲突）。
    - 如果端口 5000 未被占用 → 进入 **Master 独立运行模式**，直接绑定本地通达信/QMT驱动，此时无需运行程序1即可获取完整国内行情。
- **数据独立录入与持久化**：即使不启动程序1（LOFarb），程序3在独立模式下运行时，也会周期性将最新计算出的基金净值（latest_nav）、日度因子（daily factors）以及历史折溢价价格持续自动写入大一统数据库 `database/arb_master.db` 中（采用 SQLite WAL 模式，天然具备并发访问与防锁保护），实现 Single Source of Truth。

### 8.4 常见陷阱（避免踩坑！）

#### 8.4.1 美股代码格式化错误 ❌

**错误做法**：
```python
# 在 tdx.py 的 normalize_symbol 中
# 把 GLD 格式化为 GLD.SZ → 通达信无法识别
```

**正确做法**：
```python
# 美股 ETF 保持原样：GLD, SPY
# A 股添加后缀：159560.SZ, 510050.SH
# 港股添加后缀：00700.HK
```

#### 8.4.2 数据源选择错误 ❌

**错误**：统一用通达信获取所有数据
```python
# 所有标的都用 TDX → 美股数据获取失败
```

**正确**：查映射表选择数据源
```python
from arbcore.config.symbol_source_map import get_symbol_source
source = get_symbol_source('GLD')  # → 'IB'
# 根据 source 选择对应的 fetcher
```

---

## 九、开发规范

### 9.1 代码位置

- arbcore 唯一目录：`d:\Study\arbTest\arbcore`
- 数据库目录：`d:\Study\arbTest\database`
- **统一数据库**：`d:\Study\arbTest\database\arb_master.db`（所有项目共享）

### 9.2 测试文件

- 统一放在 `test/` 目录
- 文件名以 `test_` 开头

### 9.3 文档位置

- **核心原理**：本文件（`AGENTS.md`）
- **详细文档**：`docs/` 目录
  - `docs/01_核心原理/` - 基金分类、估值算法等通用知识
  - `docs/02_程序3详细说明/` - 程序3的详细使用说明
- **项目文档**：各项目 `README.md`（精简为 1 页）

### 9.4 日志文件

- `logs/` 目录
- 按日期命名：`YYYYMMDD.log`

---

## 十、文档结构

### 10.1 文档组织原则

- **核心原理**：本文件（`AGENTS.md`），AI 最先看到
- **详细文档**：集中在 `docs/` 目录，按主题分类
- **项目说明**：各项目 `README.md`，精简使用说明

### 10.2 最终文件结构

```
d:/Study/arbTest/
├── AGENTS.md                    ← AI 最先看到这个（核心原理 + 系统概述）
│                              包含：
│                              - 系统概述（三个项目关系）
│                              - 核心架构（工业级铁三角）
│                              - 基金分类、锚点概念、数据源规则
│                              - 数据库设计
│                              - 核心业务逻辑
│                              - 快速启动
│
├── docs/                        ← 所有详细文档集中在这里
│   ├── 01_核心原理/
│   │   ├── 01_基金分类与估值方法说明.md      ← 基金分类、估值方法、数据源
│   │   ├── 02_估值算法深度解析.md            ← Woody 估值算法原理
│   │   └── 03_核心算法说明.md               ← 核心业务逻辑、公式
│   │
│   ├── 02_程序3详细说明/
│   │   ├── 04_后端服务层.md                 ← 后端架构、Service 说明
│   │   ├── 05_前端组件说明.md               ← 前端架构、组件说明
│   │   ├── 06_API接口文档.md                ← API 接口说明
│   │   ├── 08_开发调试指南.md               ← 程序3调试指南
│   │   └── 09_部署运维手册.md               ← 部署架构、运维
│   │
│   ├── 02_arbcore基座/                    ← arbcore 核心库文档
│   ├── 03_估值算法/                         ← 估值算法相关文档
│   ├── 04_API与数据源/                      ← API 与数据源文档
│   └── 文档整合进度.md                      ← 文档整合记录
│
├── ArbDashboard/
│   └── README.md                        ← 程序3详细说明（精简版）
│
├── LOFarb/                              ← 程序1（待废弃）
├── ETFRotate/                           ← 程序4（待废弃）
├── jsl/                                 ← 程序2（待废弃）
├── arbcore/                             ← 核心库（不需要文档）
└── database/                            ← 统一数据库
```

### 10.3 文档查找指南

| 需求 | 查看文件 |
|------|---------|
| **快速了解项目** | `AGENTS.md`（本章） |
| **基金分类、锚点概念** | `docs/01_核心原理/01_基金分类与估值方法说明.md` |
| **估值算法原理** | `docs/01_核心原理/02_估值算法深度解析.md` |
| **核心算法说明** | `docs/01_核心原理/03_核心算法说明.md` |
| **后端服务说明** | `docs/02_程序3详细说明/04_后端服务层.md` |
| **前端组件说明** | `docs/02_程序3详细说明/05_前端组件说明.md` |
| **API 接口文档** | `docs/02_程序3详细说明/06_API接口文档.md` |
| **开发调试指南** | `docs/02_程序3详细说明/08_开发调试指南.md` |
| **部署运维手册** | `docs/02_程序3详细说明/09_部署运维手册.md` |
| **程序3详细说明** | `ArbDashboard/README.md` |

### 10.4 文档维护规则

1. **核心原理**更新时，同步更新 `AGENTS.md` 和 `docs/01_核心原理/`
2. **程序3详细说明**更新时，同步更新 `docs/02_程序3详细说明/` 和 `ArbDashboard/README.md`
3. **不再创建新文档**，优先更新现有文档，避免文档分散
4. **所有文档**集中在 `docs/` 目录，不要在其他位置创建文档

---

## 十一、联系与资源

- **项目根目录**：`d:\Study\arbTest\`
- **ArbDashboard 目录**：`d:\Study\arbTest\ArbDashboard\`
- **arbcore 目录**：`d:\Study\arbTest\arbcore\`
- **详细文档**：`d:\Study\arbTest\docs\`

---

*最后更新：2026-06-11*
