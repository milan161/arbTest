# ArbDashboard - AI 编程助手快速入门

> 本文档供 AI 编程助手（CodeBuddy、Gemini、Trae 等）快速了解项目架构，避免在新对话中重复了解上下文。

---

## 一、项目概述

**ArbDashboard** 是我最终要使用的核心项目（程序3），用于监控 LOF 基金折溢价套利机会。

### 三个项目的关系

| 项目 | 目录 | 状态 | 用途 |
|------|------|------|------|
| **程序1** | `LOFarb/` | ✅ 已完成 | LOF 基金折价套利（培训班教学用） |
| **程序2** | `jsl/` | ⚠️ 未完成 | 集思录全市场监控（教学用） |
| **程序3** | `ArbDashboard/` | 🔧 开发中 | **最终核心项目**（未完成，有错误需修复） |
| **程序4** | `ETFRotate/` | ❌ 未使用 | ETF 轮动策略（旧代码，待统一） |

**底层基座**：`arbcore/` - 三个核心程序共享的核心库

---

## 二、ArbDashboard 项目结构

```
d:\Study\arbTest\ArbDashboard\
├── backend/                    # 后端（FastAPI + Python）
│   ├── main.py                 # FastAPI 主服务（端口 8000）
│   ├── database/               # 数据库目录
│   │   └── arb_master.db       # 统一数据库（WAL 模式）
│   └── core/                   # 旧代码（待清理）
│
├── frontend/                   # 前端（Vue 3 + Vite）
│   ├── src/
│   │   ├── views/              # 页面组件
│   │   │   ├── Dashboard.vue   # 套利看板
│   │   │   └── Analysis.vue    # 实时分析
│   │   └── components/         # 可复用组件
│   └── vite.config.js          # Vite 配置（端口 5173）
│
├── docs/                       # 项目文档
├── test/                       # 测试文件
├── start_dashboard.bat         # 启动脚本
└── ISSUE_REALTIME_VALUATION.md # 待修复问题记录
```

### 核心功能

1. **套利看板（Dashboard.vue）**
   - 显示 LOF 基金实时折溢价率
   - 实时估值计算（静态估值 → 实时估值改造中）
   - 折溢价阈值筛选

2. **实时分析（Analysis.vue）**
   - **雷达模式**：全场套利机会实时雷达
     - 可自定义开仓/平仓阈值
     - 阈值设置持久化到 localStorage
   - **详情模式**：专业狙击工作站
     - 基金分类管理
     - 溢价率趋势分析
     - 自选基金过滤
     - 测算沙盘和手工下单

### 折溢价阈值设置

**开仓逻辑**：
- 折价越大越好（负数绝对值越大），如 -0.8%、-1%、-4% → 低价买入
- 默认阈值：-0.5%（折价超过 0.5% 才开仓）

**平仓逻辑**：
- 折价小或溢价，如 -0.1%、0%、+2% → 利润空间小，平仓
- 默认阈值：2.0%（溢价超过 2% 才平仓）

**过滤公式**：
```javascript
f.rt_premium < premiumThreshold.value || f.rt_premium > premiumUpperThreshold.value
```

**localStorage 持久化**：
```javascript
localStorage.setItem('premiumThreshold', '-0.5')       // 开仓阈值
localStorage.setItem('premiumUpperThreshold', '2.0')    // 平仓阈值
```

### 待修复问题

- **实时溢价率改造**：当前使用静态估值（T-1 日数据），需改为实时估值公式：
  - 公式：`(LOF 实时价格 / 实时估值 - 1) × 100`
  - 分母是实时估值，不是静态估值！
  - 涉及文件：`frontend/src/views/Analysis.vue`、`frontend/src/views/Dashboard.vue`

---

## 三、核心基座 arbcore

```
d:\Study\arbTest\arbcore\
├── database/                   # 数据库管理
│   └── database_manager.py    # DatabaseManager 类
├── fetchers/                   # 数据获取器
│   ├── ib_reader.py           # Interactive Brokers（美股 ETF）
│   ├── data_fetcher.py        # 统一数据获取器
│   ├── woody_api_service.py   # Woody API 服务
│   └── realtime/              # 实时行情引擎
│       └── tdx.py             # 通达信
├── calculators/                # 估值计算
│   ├── static_valuation.py    # 静态估值
│   └── dynamic_valuation.py   # 实时估值
├── config/                     # 配置文件
│   └── symbol_source_map.py   # 标的数据源映射（128 个标的）
└── base_app.py                 # BaseApp 基类
```

### 统一基金分类配置（fund_categories.json）

- **位置**：`arbcore/config/fund_categories.json`
- **用途**：程序1/2/3共享的基金分类配置，替代程序1的lof_config.yaml和程序2的fund_list.csv
- **分类结构**：
  - 黄金原油（10只）：跟踪GLD、USO、XOP等ETF
  - QDII欧美（11只）：跟踪纯ETF、美股指数、混合跨境资产
  - QDII亚洲（16只）：跟踪港股、亚洲市场指数
  - 国内LOF（0只）：跟踪A股指数（暂不重点监控）
  - 白银（1只）：跟踪白银期货
- **target_type字段**：
  - `ETF`：跟踪单一ETF（默认，如XOP、XLY、RSPH等），调用ETF数据获取函数
  - `INDEX`：跟踪美股指数（.INX、.NDX），调用指数数据获取函数，考虑13-15小时时差
  - 标记基金：161125（易方达标普500）、161130（易方达纳100）
- **估值对象类型（valuation_object_type）**：
  - **SINGLE_ETF**：单ETF（无锚点）- 跟踪单一ETF，无区域后缀，如XOP、QQQ、SPY。实时估值分子和分母都用同一个符号。历史收盘价来自Woody API（netvalue字段）或IB/TDX数据库
  - **MULTI_ETF_ANCHOR**：多ETF（有锚点）- 同一ETF在不同交易所的锚点，如^USO-EU、^GLD-JP、^USO-HK。分子是底层ETF实时价格（去掉^和-EU/-JP/-HK后缀），分母是Woody API的历史收盘价。**只有Woody数据源认识这种带^前缀和-EU/-JP/-HK后缀的符号**
  - **MULTI_ASSET**：多资产混合 - 跟踪多个股票/ETF/基金，如501225、501312、160644。需要分别获取多个资产的价格
  - **CROSS_MARKET**：跨市场混合 - 跟踪跨市场资产（美股+A股），如501225跟踪SOXX（美股）+ SZ159560（A股）
  - **US_INDEX**：美股指数 - 跟踪美股指数（.INX标普500、.NDX纳斯达克100），调用指数数据获取函数，考虑13-15小时时差
- **数据源规则**：
  - **美股ETF实时价格**：IB（主）或富途（备），绝不可能是TDX
  - **美股ETF历史收盘价**：Woody API（netvalue字段）或新浪，单ETF无锚点用这个
  - **A股ETF实时价格**：TDX（主）或QMT（备）
  - **A股ETF历史收盘价**：TDX数据库
  - **港股股票实时价格**：富途（主）或IB（备）
  - **港股股票历史收盘价**：富途数据库
  - **美股指数实时价格**：新浪（待确认，暂未使用）
  - **Woody API数据源**：只有Woody数据源认识^前缀和-EU/-JP/-HK后缀的锚点符号
  - **Woody API原始数据路径**：`D:\Study\arbTest\data\woodyAPI\Data_woody_lof_YYYYMMDD_HHMM.json`
- **同步脚本**：`backend/scripts/sync_from_json_config.py`
- **锚点（Anchor）概念**：
  - 锚点是Woody发明的概念，指基金跟踪的标的物带有区域后缀（`-EU`欧洲、`-JP`日本、`-HK`香港）
  - 例如：`^USO-EU`、`^GLD-JP`、`^USO-HK`
  - **只有Woody数据源认识这种带^前缀和-EU/-JP/-HK后缀的符号**
  - 其他数据源（IB、TDX、SINA等）不认识锚点符号
  - 实时估值计算：分子是底层ETF实时价格（去掉^和-EU/-JP/-HK后缀），分母是Woody API的历史收盘价
- **有锚点的基金**：
  - 黄金原油：501018、160723、161129、161815、160719、161116、165513（有`-EU`后缀）
  - QDII欧美：164824（INDA，有`^INDA-EU`、`^INDA-JP`、`^INDA-HK`锚点）

### 数据源映射（symbol_source_map.py）

- **IB**：美股 ETF（48 个标的，主数据源）
- **FUTU**：港股 + 美股备用
- **TDX**：A 股 ETF、期货、指数（64+ 标的）
- **QMT_YH**：银河 QMT（备用）
- **QMT_GJ**：国金 QMT（备用）
- **SINA**：指数（9 个）
- **WOODY**：QDII 估值（暂未使用）

### Woody API Key 区分

| 项目 | Key 名称 | 用途 |
|------|----------|------|
| LOFarb | `BOT_Key` | 用于 LOF 基金因子获取 |
| ETFRotate | `ROT_Key` | 用于 ETF 轮动策略 |

---

## 四、数据库设计

### 统一数据库

- **路径**：`d:\Study\arbTest\database\arb_master.db`（上级目录）
- **模式**：WAL 高并发模式
- **模块**：
  - `db.funds` - 基金数据
  - `db.market` - 市场数据
  - `db.system` - 系统配置
- **覆盖项目**：ArbDashboard、JSL、LOFarb、ETFRotate（所有项目共享）
- **已废弃**：`jsl/jsl_monitor.db`（已于 2026-06-09 删除）

### 核心表

- `unified_fund_list` - 统一基金列表（72 只基金）
- `unified_fund_history` - 统一基金历史（37,823+ 条记录）
- `usa_etf_daily_prices` - 美股 ETF 历史价格（symbol 列存储完整符号如 `^USO-EU`）
- `exchange_rate` - 汇率数据
- `index_daily` - 指数日度数据
- `futures_daily` - 期货日度数据
- `fund_daily_factors` - 基金日度因子
- `fund_basket_weights` - 基金篮子权重

---

## 五、快速启动

### 1. 启动 ArbDashboard

```bash
# 双击启动
start_dashboard.bat

# 或手动启动
cd d:\Study\arbTest\ArbDashboard
pip install -r requirements.txt
cd backend && python main.py  # 后端 8000 端口
cd ../frontend && npm run dev  # 前端 5173 端口
```

### 2. 启动 LOFarb

```bash
cd d:\Study\arbTest\LOFarb
python LOF011_daily_updater.py
```

### 3. 启动 ETFRotate

```bash
cd d:\Study\arbTest\ETFRotate
python etf_03_rotation_server.py
```

---

## 六、关键技术细节

### 实时估值计算公式

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

### 标的分类映射

| 分类 | 代表基金 | 跟踪标的 |
|------|----------|----------|
| 黄金原油 | 162411、162415 | GLD、USO、XOP |
| QDII 欧美 | 161126、161127 | SPY、QQQ |
| QDII 亚洲 | 161725、161726 | 亚洲市场 ETF |
| 国内 LOF | 501018 等 | A 股 LOF 基金 |
| 白银 | 161116 | 上期所白银期货 |

---

## 七、常见问题

### 1. 通达信初始化错误

```
RuntimeError: TQ 数据接口未正确初始化
```

**原因**：`__file__` 指向 arbcore 路径，而非通达信插件路径

**影响**：仅影响 A 股 ETF 实时行情，美股 ETF 不受影响

### 2. 数据库路径错误

**正确路径**：`d:\Study\arbTest\database\arb_master.db`

**错误路径**：`backend/arb_master.db`、`backend/database/arb_master.db`、`jsl/jsl_monitor.db`（已废弃）

**注意**：所有项目必须使用统一数据库，不要创建新的独立数据库文件

### 3. 实时估值数据源

- 美股 ETF：从 IB 读取（默认），可切换到富途
- A 股 ETF：从 TDX 读取（默认），可切换到 QMT
- 指数：从新浪读取

---

## 八、开发规范

### 1. 代码位置

- arbcore 唯一目录：`d:\Study\arbTest\arbcore`
- 数据库目录：`d:\Study\arbTest\database`
- **统一数据库**：`d:\Study\arbTest\database\arb_master.db`（所有项目共享）

### 2. 测试文件

- 统一放在 `test/` 目录
- 文件名以 `test_` 开头

### 3. 文档位置

- 架构文档：`docs/`
- 项目文档：各项目 `README.md`（精简为 1 页）

### 4. 日志文件

- `logs/` 目录
- 按日期命名：`YYYYMMDD.log`

### 5. 按钮样式规范

**确认按钮（btn-standard）样式：**

- **默认状态**：单色底色（蓝色 `var(--primary-light)`）+ 蓝色文字（`var(--primary-color)`）+ 蓝色边框
- **鼠标悬停**：白字（`#ffffff`）+ 深蓝色背景（`var(--primary-color)`）
- **点击状态**：亮度降低 10%（`brightness(0.9)`）
- **禁用状态**：透明度 40%（`opacity: 0.4`）

**CSS定义位置**：`frontend/src/App.vue` 第106-134行

**全站统一使用**：所有确认按钮统一使用 `.btn-standard` 类，不要自定义样式

**示例**：
```html
<button class="btn-standard">保存并应用配置</button>
```

---

## 九、联系与资源

- **项目根目录**：`d:\Study\arbTest\`
- **ArbDashboard 目录**：`d:\Study\arbTest\ArbDashboard\`
- **arbcore 目录**：`d:\Study\arbTest\arbcore\`

---

*最后更新：2026-06-10*
