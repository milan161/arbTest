# arbTest 基金套利监控系统 - AI 编程助手快速入门

> 本文档供 AI 编程助手快速了解项目架构，避免在新对话中重复了解上下文。
> 最后更新：2026-06-21

---

## 一、系统概述

**arbTest** 是基金套利监控系统集合，采用**"大一统底层基座 (arbcore + SQLite WAL 模式)"**，共享同一个数据库。

| 项目 | 目录 | 状态 | 用途 |
|------|------|------|------|
| **程序3** | `ArbDashboard/` | 🔧 开发中 | **最终核心项目**（跨市场 QDII 看板与执行） |
| **程序1** | `LOFarb/` | ✅ 已完成 | LOF 基金折价套利（教学用） |
| **程序2** | `jsl/` | ⚠️ 未完成 | 集思录全市场监控（教学用） |
| **程序4** | `ETFRotate/` | ❌ 未使用 | ETF 轮动策略（旧代码） |

**底层基座**：`arbcore/` - 所有程序共享的核心库
**数据库**：`database/arb_master.db` (WAL 高并发模式，Single Source of Truth)

---

## 二、核心架构

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
| 黄金原油 | `commodity_gold_oil` | USO、GLD | 501018、160723、161129 | 美股 ETF 价格 |
| QDII欧美 | `equity_us_etf` | XOP、XLY、XBI | 162411、162415、161126 | 美股 ETF 价格 |
| QDII欧美 | `equity_us_index` | .INX、.NDX | 161125、161130 | 新浪指数价格 |
| QDII欧美 | `hybrid_cross` | 一篮子股票/ETF | 164824、501225、160644 | 多资产组合价格 |
| QDII亚洲 | `equity_asia` | 亚洲市场指数/ETF | 161725、161726 | 亚洲市场数据 |
| 国内LOF | `lof_domestic` | A股 LOF 折溢价 | 501025 等 | A股行情 |
| 现金管理 | `bond_money_market` | 债券ETF/货币基金 | 511880、511360、511520 | 国债指数 000012 |
| 白银 | `commodity_silver` | 上海期货交易所 | 161226 | 上期所白银期货 |

**设计思路**：聚焦高价值套利机会（黄金原油、XOP、INDA），通过自选基金机制让用户自定义关注列表。

### 3.2 估值对象类型（valuation_object_type）

| 类型 | 说明 | 示例 | 实时估值规则 |
|------|------|------|-------------|
| **SINGLE_ETF** | 单ETF（无锚点） | XOP、QQQ | 分子分母都用同一个符号 |
| **MULTI_ETF_ANCHOR** | 多ETF（有锚点） | ^USO-EU、^GLD-JP | 分子：去掉^和-EU后缀取基础代码；分母：保留原始符号查历史价 |
| **MULTI_ASSET** | 多资产混合 | 501225、501312 | 分别获取多个资产价格 |
| **US_INDEX** | 美股指数 | .INX、.NDX | 考虑13-15小时时差 |

### 3.3 锚点（Anchor）

锚点是 Woody 的概念，指基金跟踪的标的物带有区域后缀（`-EU`欧洲、`-JP`日本、`-HK`香港）。

- `^USO-EU`、`^GLD-JP` → **只有 Woody 数据源认识**，其他数据源不认识锚点符号
- **实时估值分子**：去掉 `^` 和后缀，取基础代码实时价格（USO、GLD）
- **分母**：数据库里存的带后缀的历史价格

---

## 四、数据源规则

### 4.1 数据源映射

| 数据源 | 标的类型 | 说明 |
|--------|---------|------|
| **IB** | 美股 ETF（48 个） | 主数据源 |
| **FUTU** | 港股 + 美股备用 | 无 IB 账户时使用 |
| **TDX** | A 股 ETF、期货、指数（64+） | 主数据源 |
| **QMT_YH / QMT_GJ** | A 股/期货 | 银河/国金 QMT 备用 |
| **SINA** | 指数（9 个） | `.INX`、`.NDX` 等 |

### 4.2 数据源选择规则

| 数据类型 | 实时价格数据源 | 历史收盘价/成交量 |
|----------|--------------|----------------|
| 美股ETF | IB（主）或富途（备） | Woody API 或新浪 |
| A股ETF/LOF | TDX/QMT（实时瀑布流） | **腾讯接口**（V8.0升级：精准历史成交量） |
| 港股 | 富途（主）或 IB（备） | 富途数据库 |

### 4.3 时效性限制与 VPS 云端流水线

以下数据源**只支持最新一日**，无法拉取历史：外汇中心汇率、Woody API、新浪期货、深交所份额、Woody 区域变种 ETF。

**对策**：云端 VPS 采集 + 本地程序提取
- 云端：`cloud_siphon.py` (09:20 采集 Woody/汇率/期货)、`041_jsl_cloud_shares.py` (06:00 采集份额)
- 本地：每日更新程序通过 SFTP 从 VPS 拉取 JSON 入库
- 防刷兜底：VPS 失败时自动启动本地 API 兜底抓取

---

## 五、数据库设计

- **路径**：`database/arb_master.db`（上级目录）
- **模式**：WAL 高并发模式
- **核心表**：
  - `unified_fund_list` - 统一基金列表（72 只）
  - `unified_fund_history` - 统一基金历史（37,823+ 条）
  - `usa_etf_daily_prices` - 美股 ETF 历史价格
  - `exchange_rate` / `index_daily` / `futures_daily` - 汇率/指数/期货
  - `fund_daily_factors` - 基金日度因子
  - `fund_basket_weights` - 基金篮子权重（注意：必须加 `MAX(date)` 过滤，否则返回历史重影）

---

## 六、核心业务逻辑

### 6.1 实时估值计算公式

```
实时溢价率 = (LOF 实时价格 / 实时估值 - 1) × 100
```

- **分子**：去掉 `^` 前缀和 `-EU/-JP/-HK` 后缀，用基础代码查实时行情
- **分母**：保留原始符号，查数据库历史价格

### 6.2 实时行情四级瀑布流

优先级：**银河QMT (Socket)** > **通达信 (内存直连)** > **国金QMT (xtquant)** > **新浪API (轮询)**

### 6.3 取价策略

```
LOF 实时价格：卖一价（涨停时降级为最新成交价）
IB ETF 实时价格：买一价
```

构成"买入 A股 LOF (看卖一) + 卖空 美股 ETF (看买一)"的严谨对冲闭环。

### 6.4 前端刷新策略

| 优先级 | TAB | 刷新频率 |
|--------|-----|---------|
| 高 | 我的自选、黄金原油、QDII欧美 | 3 秒/次 |
| 低 | QDII亚洲、国内LOF、白银 | 30 秒/次 |

### 6.5 分时采样机制

1 分钟采样仅针对**我的自选** Tab 中的基金及其底层挂钩美股 ETF，非高频基金跳过实时获取。

---

## 七、启动与常见问题

### 7.1 启动 ArbDashboard（程序3）

```bash
# 双击启动
start_dashboard.bat

# 或手动
cd ArbDashboard/backend && python main.py    # 后端 8000 端口
cd ../frontend && npm run dev                # 前端 5173 端口
```

### 7.2 Master-Slave 架构（通达信 DLL 多开冲突保护）

- **Master**（LOFarb / 程序1）：独占本地 `5000` 端口，独占通达信 TQ 接口
- **Slave**（ArbDashboard / 程序3）：探测端口 5000，被占用则进入 Slave 模式（禁用本地通达信驱动，只做展示）

### 7.3 常见陷阱（⚠️ 必查！）

#### 7.3.1 美股代码格式化错误
❌ 把 GLD 格式化为 `GLD.SZ` → 通达信无法识别
✅ 美股 ETF 保持原样：GLD, SPY；A 股添加后缀：159560.SZ

#### 7.3.2 数据源选择错误
❌ 统一用 TDX → 美股数据获取失败
✅ 查 `symbol_source_map` 选择数据源：`get_symbol_source('GLD')` → 'IB'

#### 7.3.3 SQLite 历史权重查询重影
❌ 直接 `SELECT FROM fund_basket_weights WHERE fund_code=?` → 返回几百条历史权重
✅ 必须加 `AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code=?)`

#### 7.3.4 API 异常熔断
❌ for 循环批量获取实时行情不加 try-except → 断线后整个 API 500 崩溃
✅ 必须为底层行情驱动添加 Error Boundary

#### 7.3.5 SPA Catch-All 路由拦截 API（2026-06-18 已修复）
catch-all 路由必须先判断 `if full_path.startswith("api/")`，命中则跳过不拦截。

#### 7.3.6 对冲比例 (Hedge) 兜底逻辑
如果 `position` 为 `None`，必须动态读取 `fund_cfg` 里的静态默认仓位（如 95%）反向推算 hedge。

#### 7.3.7 数据库路径错误
❌ `backend/arb_master.db`、`backend/database/arb_master.db`
✅ 统一路径：`d:\Study\arbTest\database\arb_master.db`

#### 7.3.8 ETF实时估值公式错误（⚠️ 反复出错！）
❌ `val = nav * (1 - pos) + pos * (price * fx) / hedge` — 第二项多乘了pos
❌ `val = (price * fx) / 100` — 除以100是遗留错误，应除以hedge
✅ 正确公式：`val = nav * (1 - pos) + (price * fx) / hedge`
- 影响范围：ghost_calc（main.py）、ghost_simulator、Analysis.vue etfVal
- 典型症状：估值0.78（错）vs 0.82（对），溢价-93%（错）vs -0.7%（对）
- 162411为例：nav=0.8247, pos=0.95, XOP=154.53, fx=6.813, hedge=1352.24

#### 7.3.9 basket为空时ETF行情和估值为空
❌ basket为空 → etf_symbols为空 → 不获取ETF实时行情 → 估值=0
✅ basket为空时用 `trade_etf`（related_index字段）兜底获取行情
- 影响范围：valuation_meta API（main.py）、Analysis.vue etfVal
- 典型案例：162411（XOP）没有basket权重数据，但有trade_etf='XOP'
- 修复：后端basket为空时用trade_etf获取行情；前端etfVal同理

---

## 八、开发规范

### 8.1 代码位置

| 内容 | 路径 |
|------|------|
| arbcore 唯一目录 | `arbcore/` |
| 统一数据库 | `database/arb_master.db` |
| 前端页面 | `ArbDashboard/frontend/src/views/` |
| 前端布局 | `ArbDashboard/frontend/src/layouts/` |
| 前端私有页面 | `ArbDashboard/frontend/src/private/` |
| 后端服务 | `ArbDashboard/backend/` |

### 8.2 安全红线（⚠️ CRITICAL）

1. **账户密钥绝对禁传**：`arbcore/config/account_private.py`、`.env` 严禁 git add
2. **实盘数据库绝对禁传**：`arb_master.db` 严禁 git add，只传 `arb_master_share.db`
3. **根目录仅允许 `readme.txt`**：所有 `.md` 文件严禁推送 GitHub
4. **Push 前必须确认 commit message**：不得暴露具体实现细节、算法参数、文件路径
5. **目录忽略必须用首斜杠 `/` 锚定**：防止误忽略子目录文件

### 8.3 每日数据自动调度器

| 调度器 | 触发时间 | 行为 |
|--------|---------|------|
| 清晨刷新 | ≥9:20 | 清除 Woody/汇率/期货/份额 标记，重新抓取 |
| 净值补采 | 18:00/19:30/21:00 | 调 `--nav-only` 仅拉基金净值 |

手动触发唯一入口：`/data` 页面橙色按钮。

---

## 九、前端页面布局速查

### 9.1 主看板（Dashboard.vue）

7 个 TAB 分类，3 秒/次高频刷新（自选、黄金原油、QDII欧美）或 30 秒/次低频刷新（QDII亚洲、国内LOF、白银）。

### 9.2 实时交易页（Analysis.vue / 详情模式）

**区块 1**：顶部摘要栏（基金名称 + 基础仓位 + 期货校准 checkbox）
**区块 2**：基准日估值日信息（3 行统一参数卡，列宽 160px|140px|110px|flex）
**区块 3**：估值计算器面板（蓝底色，估值参数 | 预估净值+折价率 | 测试价计算器）
**区块 4**：套利策略提示（黄底色）
**区块 5**：估值与对冲推演区（3 个 Panel）
- Panel 1: ETF实时估值（2行3列网格，160px|140px|flex，USO价:[input] + 估值 + 溢价 + 投入计算器）
- Panel 2: 期货校准估值（橙色底色，checkbox 控制）
- Panel 3: 纯期货估值（绿色底色，checkbox 控制）
**区块 6**：买卖五档行情 + 交易执行面板（A股盘口 | 下单区+按键 | 外盘盘口）
**区块 7**：分时对冲走势图（ECharts，1分钟采样）

### 9.3 实时交易页面（GodMode.vue）

与 Analysis.vue 详情模式结构相同，但基金来源由信号列表提供（不可切换），用于从"信号监视"页面点击进入。

### 9.4 信号监视（AutoTrade.vue）

左侧：实时信号日志终端 | 右侧：活跃套利策略表格（开关、规则名称、监控对象、触发条件、操作）

### 9.5 开发中占位（Developing.vue）

QDII亚洲 / 国内LOF / 白银 TAB 点击后的跳转目标，显示"功能开发中"。

> 详细页面结构：`docs/02_程序3详细说明/12_实时交易页面布局说明.md`

---

## 十、非阻塞连接模式（V9.0）

所有 reader 统一采用"启动试连3次 + disabled 标记 + 按钮重连"模式：

| Reader | 文件 | 端口/方式 | 特殊处理 |
|--------|------|----------|---------|
| 富途 | `futu_reader.py` | `OpenQuoteContext()` 5s超时 | 运行时自动重连（限频30s） |
| IB | `ib_reader.py` | EClient 轮询4端口 | 后台线程 `self.run()` |
| 通达信 | `realtime/tdx.py` | 导入 `tqcenter` 模块 | 抑制 C++ 控制台输出 |
| 银河QMT | `realtime/galaxy.py` | Socket TCP 长连接 | 后台接收线程，周末避让 |
| 国金QMT | `realtime/guojin.py` | `xtquant.xtdata` | 探测连接 |

> 详细实现：`docs/02_程序3详细说明/05_前端组件说明.md` 章节十二

---

## 十一、文档导航

| 需求 | 查看文件 |
|------|---------|
| **快速了解项目** | 本文件（AGENTS.md） |
| **基金分类、锚点概念** | `docs/01_核心原理/01_基金分类与估值方法说明.md` |
| **估值算法原理** | `docs/01_核心原理/02_估值算法深度解析.md` |
| **核心算法说明** | `docs/01_核心原理/03_核心算法说明.md` |
| **后端/前端服务说明** | `docs/02_程序3详细说明/04_后端服务层.md` / `05_前端组件说明.md` |
| **API 接口文档** | `docs/02_程序3详细说明/06_API接口文档.md` |
| **开发调试指南** | `docs/02_程序3详细说明/08_开发调试指南.md` |
| **实时交易页面布局** | `docs/02_程序3详细说明/12_实时交易页面布局说明.md` |
| **待办事项/Bug跟踪** | `docs/05_每日调试记录.md`（末尾） |

---

## ⏰ 待办提醒（下次主动问用户）

> （当前无待办）

---

*最后更新：2026-06-19*


<!-- open-mem-context -->
## Project Activity (auto-generated by open-mem)

### ArbDashboard\backend/
| ID | Type | Title | Date |
|----|------|-------|------|
| 0d05c874-bbd8-422b-9a15-607db67705e1 | 🔄 refactor | Ghost Trader 瘦身：删除冗余计算，复用现有服务 | 2026-06-19 |

**Key concepts:** Ghost Trader, hedge, refactoring, code cleanup, quantity conversion

### ArbDashboard\backend\private/
| ID | Type | Title | Date |
|----|------|-------|------|
| 0d05c874-bbd8-422b-9a15-607db67705e1 | 🔄 refactor | Ghost Trader 瘦身：删除冗余计算，复用现有服务 | 2026-06-19 |

**Key concepts:** Ghost Trader, hedge, refactoring, code cleanup, quantity conversion

### ArbDashboard\frontend\src\private/
| ID | Type | Title | Date |
|----|------|-------|------|
| ed4b731b-7d64-4a43-8de9-828d2c1bd33b | 🔄 refactor | 2026-06-19 前端布局重构与Bug修复 | 2026-06-19 |

**Key concepts:** GodMode, Panel 1, uniqueValuationSymbols, Dashboard rowProps, AutoTrade 操作列, Developing placeholder

### ArbDashboard\frontend\src\router/
| ID | Type | Title | Date |
|----|------|-------|------|
| ed4b731b-7d64-4a43-8de9-828d2c1bd33b | 🔄 refactor | 2026-06-19 前端布局重构与Bug修复 | 2026-06-19 |

**Key concepts:** GodMode, Panel 1, uniqueValuationSymbols, Dashboard rowProps, AutoTrade 操作列, Developing placeholder

### ArbDashboard\frontend\src\views/
| ID | Type | Title | Date |
|----|------|-------|------|
| ed4b731b-7d64-4a43-8de9-828d2c1bd33b | 🔄 refactor | 2026-06-19 前端布局重构与Bug修复 | 2026-06-19 |

**Key concepts:** GodMode, Panel 1, uniqueValuationSymbols, Dashboard rowProps, AutoTrade 操作列, Developing placeholder

💡 *Use `mem-find` to search full details. Use `mem-create` to save important decisions.*
<!-- /open-mem-context -->
