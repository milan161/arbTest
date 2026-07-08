# Woody PalmmicroAPI 对比分析与修改记录

> 创建日期：2026-07-07
> 目的：记录 Woody 新版 PalmmicroAPI 与 arbTest 已有功能的对比分析，为后续开发提供决策依据

---

## 一、概述

### 1.1 分析背景

Woody 在 2026 年 7 月发布了全新的 PalmmicroAPI（`palmmicroapi.py`），重写了净值和数量计算引擎。我们的 arbTest 程序与此 API 存在功能交叉，需要通过对比找出差距、统一方案、保持独立。

### 1.2 Woody API 依赖底线

经用户确认，我们离不开 Woody API 的只有 **3 类数据**：
1. LOF 基金的 Position（持仓比例）
2. 区域锚点（`^GLD-EU`、`^USO-JP` 等）的 weight 和 EU/JP 收盘价
3. **期货校准因子（calibration）** — Woody 独有算法计算，用于期货校准估值时不可替代

> ⚠️ **修正说明**：hedge 值不属于 Woody 依赖。可以通过 Yahoo Finance v7 API（`^XXX-IV` 净值符号）自行获取 ETF 净值计算得出。详见 Woody 文档 `004_技术文档_Yahoo_ETF净值获取技术记录.md`。

其他所有计算（估值、对冲数量、期货校准公式本身）都应保持程序独立。

### 1.3 参考文件

| 文件 | 路径 |
|------|------|
| Woody PalmmicroAPI | `D:\Study\私人文件\woody\woodyAPI\palmmicroapi.py` |
| Woody Stock 工具 | `D:\Study\私人文件\woody\woodyAPI\palmmicrostock.py` |
| Woody 微信文章 1 | https://mp.weixin.qq.com/s/9RrDqMyQ7WFdFYAFm-T1Ng |
| Woody 微信文章 2 | https://mp.weixin.qq.com/s/xRfTSv32WGFB3p_1QWTGpg |
| Woody 微信文章 3 | https://mp.weixin.qq.com/s/GNdx6I-KrjMMFGrYxDfAug |
| Woody 微信文章 4 | https://mp.weixin.qq.com/s/Qb0NezOh16-PKDyL2BlAvQ |
| 期货乘数配置 | `arbcore/config/futures_multipliers.py` |
| 对冲数量计算引擎 | `arbcore/calculators/calc_quantity.py` |
| Woody 数据抓取 | `arbcore/fetchers/woody_api_service.py` |
| 每日更新调度 | `ArbDashboard/backend/scheduler/daily_updater.py` |
| 前端沙盘面板 | `ArbDashboard/frontend/src/views/Analysis.vue` |
| 后端估值接口 | `ArbDashboard/backend/main.py` |

---

## 二、架构对比

### 2.1 Woody PalmmicroAPI 架构

```
PalmmicroAPI (配置驱动)
├── arMultiplier (静态乘数字典)
│   ├── hf_CL = 100    # MCL:100, CL:1000
│   ├── hf_ES = 5      # MES:5, ES:50
│   ├── hf_GC = 10     # MGC:10, GC:100
│   ├── hf_NQ = 2      # MNQ:2, NQ:20
│   ├── hf_SI = 5000   # SI:5000
│   ├── nf_AG0 = 15    # 沪银:15
│   └── default = 1
│
├── EstNetValue()     # 实时净值估算
│   ├── is_single → __est_calibration_netvalue (有 calibration 字段)
│   │   └── 公式: (1-pos)×NAV + pos×fEst×CNY/calibration
│   └── !is_single → __est_holdings_netvalue (有 symbol_hedge 篮子)
│       └── 公式: NAV × (1 + pos × (Σratio×price/est_price×CNY/CNYholdings - 1))
│
└── CalcQuantity()    # 对冲数量计算
    ├── is_single → __calc_calibration_quantity
    │   └── fHedge = ar['hedge'] × multiplier(strHedgeSymbol)
    └── !is_single → __calc_holdings_quantity
        └── 基于篮子权重的复杂分配算法
```

**关键设计理念**：
- 配置驱动：每个基金对应一个配置字典，通过 `get_param(strSymbol)` 获取
- 两层判断：`is_single(ar)` = 是否有 `'calibration'` 字段
- 递归估值：ETF 的净值估算可以递归到期货价格

### 2.2 arbTest 架构

```
arbTest (分层架构)
├── 数据层
│   ├── arbcore/fetchers/ (woody_api_service.py, etc.)
│   ├── arbcore/database/ (db_manager.py)
│   └── fund_daily_factors, fund_basket_weights 等表
│
├── 计算层
│   ├── arbcore/calculators/ (calc_quantity.py, dynamic_valuation.py, etc.)
│   ├── arbcore/config/ (futures_multipliers.py, lof_config.yaml)
│   └── 公式: 篮子估值/静态估值/期货校准估值
│
└── 展示层
    ├── ArbDashboard/backend/ (FastAPI + fund_service.py)
    └── ArbDashboard/frontend/ (Vue 3 + Analysis.vue 沙盘)
```

**关键差异**：
- arbTest 使用数据库驱动（SQLite），Woody 使用配置字典驱动
- arbTest 的计算在前端和后端分离，Woody 全在后端
- arbTest 的篮子数据来自 `fund_basket_weights` 表，Woody 的篮子数据来自 API 返回的 `symbol_hedge`

---

## 三、功能逐项对比

### 3.1 实时净值估算（EstNetValue）

| 项目 | Woody | arbTest | 结论 |
|------|-------|---------|------|
| calibration 型 | `(1-pos)×NAV + pos×fEst×CNY/calib` | 前端 `futCalibVal` 实现相同公式 ✅ | **一致** |
| holdings 型 | `NAV × (1+pos×(Σratio×price/est_price×CNY/CNYholdings-1))` | 前端 `etfVal` 篮子公式 ✅ | **一致** |
| 区域锚点 | 用主标实时价代替（`^GLD-EU` → GLD） | 第 1069 行 `cleanSym` 逻辑 ✅ | **一致** |
| 递归估值 | 支持 ETF→期货递归 | 不支持（前端只算一层） | **保留差异** |

**结论**：估值公式完全一致。我们 7 月 3 日改造后已对齐。

### 3.2 期货校准估值

| 项目 | Woody | arbTest | 结论 |
|------|-------|---------|------|
| 公式 | `equivSpot = futuresPrice / calibration` 然后入篮子公式 | `futCalibVal` 中 `equivSpot = futPrice / calib` ✅ | **一致** |
| 校准因子来源 | API 返回的 `calibration` 字段 | `fund_daily_factors.calibration` | **数据来源不同，值可能不同** |
| 适用基金类型 | 有 `calibration` 字段的基金（如 USO, GLD, 162411） | 所有设置了 `trade_future` 的基金 | **保留差异**（见下文） |

**注意**：160723 嘉实原油在 Woody 数据中**没有** `calibration` 字段（是 holdings 型）。我们的 `trade_future='MCL'` 是额外赋予的。

### 3.3 对冲数量计算（CalcQuantity）

| 项目 | Woody | arbTest | 结论 |
|------|-------|---------|------|
| calibration 型 | `_round_quantity(n_contracts × hedge × multiplier)` | 前端 `hedge × calib × multiplier / lof_price` | **见 Bug 1** |
| holdings 型 | `__calc_holdings_quantity` 复杂算法 | 不支持（只用简化公式） | **保留差异** |
| 微型合约 | 全部用微型号（hf_CL=100） | 原本用标准号（CL=1000） | **已修** |
| `_round_quantity` | `int((x+49.9)/100)*100` | `Math.round(x/100)*100` | **保留差异** |

**关键发现**：
- 公式缺除以 lof_price → **已修**（Bug 1）
- 乘数 CL=1000 改为 MCL=100 → **已修**（Bug 2）
- holdings 型基金的算法不同 → **保留差异**，待用户定夺

### 3.4 期货乘数配置

| 项目 | Woody | arbTest | 结论 |
|------|-------|---------|------|
| 配置位置 | `arMultiplier` 类静态变量 | `arbcore/config/futures_multipliers.py` | **独立实现，清单一致** |
| MCL/CL | `hf_CL=100`（微型的） | 原本 `CL=1000`，`MCL=100` 并存 | **已统一为微型** |
| MGC/GC | `hf_GC=10`（微型的） | 原本 `GC=100`，`MGC=10` 并存 | **已统一为微型** |
| MES/ES | `hf_ES=5` | 原本 `ES=50`，`MES=5` 并存 | **已统一为微型** |
| MNQ/NQ | `hf_NQ=2` | 原本 `NQ=20`，`MNQ=2` 并存 | **已统一为微型** |
| SI | `hf_SI=5000` | `SI=5000` ✅ | **一致** |
| AG0 | `nf_AG0=15` | `AG=15` ✅ | **一致** |

---

## 四、修改记录

### 4.1 已修改：期货乘数后端统一管理

**文件**：`arbcore/config/futures_multipliers.py` — **新建**

包含 10 个期货乘数：
```python
FUTURES_MULTIPLIERS = {
    'MCL': 100, 'MES': 5, 'MGC': 10, 'MNQ': 2,  # CME 微型
    'CL': 1000, 'ES': 50, 'GC': 100, 'NQ': 20,   # CME 迷你
    'SI': 5000, 'AG': 15,                          # COMEX/上期所
}
```

提供 `get_multiplier()` 和 `list_all_multipliers()` 查询接口。
API 端点：`GET /api/fund/hedge_multipliers`

### 4.2 已修改：对冲数量计算引擎

**文件**：`arbcore/calculators/calc_quantity.py` — **新建**

3 种计算方法：
- `etf_hedge()` — ETF 对冲数量
- `futures_hedge()` — 期货校准对冲数量（`hedge × calib × multiplier / lof_price`）
- `pure_futures_hedge()` — [占位/实验性] 纯期货对冲

### 4.3 已修改：后端 trade_future 改用微型合约

**文件**：`ArbDashboard/backend/main.py` 第 588-591 行

```
改前: "原油" → trade_future = "CL"
改后: "原油" → trade_future = "MCL"  (匹配 Woody 的 hf_CL=100)

改前: "金" → trade_future = "GC"
改后: "金" → trade_future = "MGC"   (匹配 Woody 的 hf_GC=10)
```

### 4.4 已修改：前端期货校准估值面板布局

**文件**：`ArbDashboard/frontend/src/views/Analysis.vue`

| 修改 | 说明 |
|------|------|
| 布局改为 2 行 | 与 ETF 实时估值面板一致 |
| 去掉 CL 后的冒号 | `CL:` → `CL价` |
| 校准改为只读文本 | `校准: [输入框]` → `校准 0.658`（小数 3 位，字体缩小） |
| `校准` 移到右侧区域 | 与上方 `买LOF` 左对齐 |
| 去掉自动填充期货价格 | 不再随 15 秒轮询重置用户输入 |

### 4.5 已修改：前端期货对冲数量公式修复

**文件**：`ArbDashboard/frontend/src/views/Analysis.vue` 第 1276-1282 行

```javascript
// 改前（Bug：除以 100 而非 lof_price，且没有除以 lof_price）
const finalLofQty = Math.round((targetLotsFuture.value * displayHedgeValue) / 100) * 100

// 改后（正确：先除 lof_price 得股数，再四舍五入到 100 的倍数）
const rawLofQty = (targetLotsFuture.value * displayHedgeValue) / simLofPrice.value
const finalLofQty = Math.round(rawLofQty / 100) * 100
```

### 4.6 已修改：前端 ETF 对冲输入格式

**文件**：`ArbDashboard/frontend/src/views/Analysis.vue`

- 校准标签：`结算价` → `校准值`
- 精度：`.toFixed(2)` → `.toFixed(3)`
- ETF 对冲输入格式：匹配"我的交易"页面

### 4.7 已删除：无用工具函数

**文件**：`arbcore/config/futures_multipliers.py`

按奥卡姆剃刀原则删除：
- `resolve_future_from_hedge()`
- `get_future_from_trade_symbol()`
- `BASE_TO_FUTURE` 字典
- `HF_TO_FUTURE` 字典

---

## 五、保留的差异（刻意不一致）

| 差异项 | Woody | arbTest | 原因 |
|--------|-------|---------|------|
| 数据结构 | 配置字典驱动 | 数据库（SQLite）驱动 | arbTest 需要持久化历史数据 |
| holdings 对冲算法 | `__calc_holdings_quantity` 复杂算法 | 简化公式 | 用户确认 160723 的篮子算法较复杂，暂不实现 |
| `pure_futures_hedge` | 不使用此路径 | 占位保留 | 用户确认 Woody 不用纯期货路径，标记为实验性 |
| 递归估值 | 支持 ETF→期货递归 | 前端只算一层 | 目前无需递归，估值精度已满足 |
| 前端的 `_round_quantity` | `int((x+49.9)/100)*100`（Floor 风格） | `Math.round(x/100)*100`（四舍五入） | 差异在 ±50 股以内，不影响实际交易 |
| 校准值默认值 | 无默认值 | `testFutCalib` 默认 `1.0` | 防止除零，用户可自行调整 |

---

## 六、当前存在问题

### 6.1 160723 期货对冲数量差异（🚩 待确认）

| 来源 | 1 手微型合约对应 LOF 股数 | 状态 |
|------|--------------------------|------|
| 改前程序 | 324,400 股（CL=1000，缺÷lof_price） | ❌ 已修 |
| 改后程序 | **18,500 股**（MCL=100，已÷lof_price） | ❓ 待核对 |
| Woody 数据 | 31,800 股 | 参考值 |

**推测原因**：
- 160723 在 Woody 架构中是 holdings 型基金，他用 `__calc_holdings_quantity` 算法
- 该算法从 USO 篮子出发做多层换算，与我们的简化公式不同
- Woody 的 `ar['hedge']` 值可能与我们的 DB 值不同（推算约 846 vs 493）

**下一步**：明天 A 股开盘后，用 Woody 的企业微信数据核对该基金的对冲数量。

### 6.2 160719 实时溢价差异

| 来源 | 实时溢价 | 状态 |
|------|---------|------|
| arbTest 沙盘 | -1.47% | ❓ 待确认 |
| Woody 数据 | -1.33% | 参考值 |

**可能原因**：GLD 实时价格来源不同（我们的 GLD 价 382.43 vs Woody 的 IB 数据 382.13）

**下一步**：用户输入框留空让它自动获取，对比自动获取的 GLD 价格与 Woody 数据。

### 6.3 Woodyk 数据缺失模式

- `woody_2026-07-07.json` 未生成
- 程序启动早于 Woody 的 9:20 CNY 更新时触发 `防刷标记` 守卫
- **临时方案**：已确认数据文件 `Data_woody_lof_20260707_0913.json` 存在

**下一步**：监控明天的数据同步流程，确认是否会在 Woody 更新后补拉。

### 6.4 holdings 基金的对冲数量算法

160723 嘉实原油在 Woody 中属于 holdings 型（有 `symbol_hedge`，无 `calibration`）。
其对冲数量走 `__calc_holdings_quantity` 算法，步骤：

1. 从默认开仓金额（100 万份 LOF）算出各篮子标的的持仓股数
2. 按实际标的汇总（如 USO, ^USO-EU, ^USO-JP 都汇总为 USO）
3. 找到期货合约能覆盖的最大持仓比例
4. 缩放后算出最终 LOF 股数

**决定**：暂不实现此算法，等用户确认是否需要精确匹配 Woody。

### 6.5 前端乘数硬编码未完全迁移

前端 `Analysis.vue` 第 1264-1274 行仍有硬编码的 `if/else` 乘数链。
后端 `/api/fund/hedge_multipliers` 接口已存在，但前端未调用。

**决定**：暂不修改。前端乘数链与 Woody 一致后（都用微型合约），可保持现状。
如需统一管理入口，可后续改为从后端 API 拉取。

---

## 七、关键代码位置速查

| 功能 | 文件 | 行号 |
|------|------|------|
| Woody 净估值估算 | `palmmicroapi.py` | 177-185 (EstNetValue) |
| Woody 数量计算 | `palmmicroapi.py` | 304-310 (CalcQuantity) |
| Woody 乘数字典 | `palmmicroapi.py` | 15-21 (arMultiplier) |
| 前端篮子估值 | `Analysis.vue` | 1060-1083 (etfVal) |
| 前端期货校准估值 | `Analysis.vue` | 1089-1164 (futCalibVal) |
| 前端期货对冲数量 | `Analysis.vue` | 1257-1284 (lofQtyFuture) |
| 前端数据获取 | `Analysis.vue` | ~1490-1497 (fetchMeta) |
| 后端 trade_future 配置 | `main.py` | 588-591 |
| 后端 hedge_multipliers API | `main.py` | 571-575 |
| 期货乘数配置 | `futures_multipliers.py` | 全部 |
| 对冲数量引擎 | `calc_quantity.py` | 全部 |

---

## 八、后续行动清单

### 开盘后优先验证
- [ ] 160723 对冲数量：在 Woody 企业微信中核对 1 手 MCL → 多少股 160723
- [ ] 160719 溢价差异：输入框留空让程序自动获取 GLD 价格，对比 Woody 数据
- [ ] 确认 woody 数据文件是否正常生成

### 短期可执行
- [ ] 监控今天 woody_2026-07-07.json 是否最终生成
- [ ] 验证我们的 `trade_future='MCL'` 是否在所有原油基金中生效
- [ ] 将 AG0 映射改为 AG（已统一）

### 📌 明日任务：实现 ETF NAV 自动获取

**背景**：hedge 值不依赖 Woody，可通过 ETF 净值自行计算。

**两个独立数据源**（互不替代，按 ETF 选用）：

#### 数据源 A：Invesco 官方 API（仅限 Invesco 旗下 ETF）

```
GET https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/{CUSIP}/prices?idType=cusip&variationType=priceListing&productType=ETF&productSubType=ETF
```

示例（QQQ CUSIP: 46090E103）：
```json
{ "effectiveDate": "2026-07-06", "cusip": "46090E103", "nav": 722.447979, ... }
```

✅ 官方数据，无需 VPN
⚠️ 只适用于 Invesco 发行的 ETF，需要知道 CUSIP
⚠️ QQQ 可用，但 GLD、USO、XOP 等非 Invesco 产品不适用

#### 数据源 B：Yahoo Finance v7 API（通用方案）

利用 Yahoo 的隐藏功能，通过 `^XXX-IV` 符号获取 ETF 净值：

```
GET https://query1.finance.yahoo.com/v7/finance/chart/{symbol}?range=1d&interval=1d&indicators=quote
```

- XOP 净值：`^XOP-IV`
- INDA 净值：`^INDA-IV`
- 其他 ETF 类推

⚠️ 需要 VPN 代理（中国大陆无法直连 Yahoo）
⚠️ 需要配置代理、请求头、SSL 禁用（仿 Woody 实现）
详见 Woody 文档 `004_技术文档_Yahoo_ETF净值获取技术记录.md`

#### 参考文件
- `D:\Study\私人文件\woody\web_woody\TEST\004_技术文档_Yahoo_ETF净值获取技术记录.md`
- Invesco API 示例：https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/prices
- CUSIP 46090E103 = QQQ

### 长期待定
- [ ] 是否实现 holdings 基金的对冲数量算法
- [ ] 是否将前端乘数改为从后端 API 拉取
- [ ] 是否实现 `pure_futures_hedge`（半成品，用户确认暂不开发）

---

## 附：公式速查表

### 篮子实时估值（已对齐）
```
fxChange = currentFx / baseFx
wChange = Σ(weight_i × cPrice_primary / bPrice_i)     # cPrice 用主标实时价
rt_val = base_nav × [1 + position × (wChange × fxChange - 1)]
```

### 期货校准估值（已对齐）
```
equivSpot = futuresPrice / calibration                 # 期货→ETF等价价
# 然后代入篮子公式（用 equivSpot 代替所有篮子项的价格变化）
```

### 期货对冲数量（已修复）
```
hedge_value_per_contract = hedge × calib × multiplier  # RMB/手
lof_shares = n_contracts × hedge_value_per_contract / lof_price
```

### Woody 对冲数量（参考）
```python
# calibration 型（单标的）
fHedge = ar['hedge'] * get_multiplier(strHedgeSymbol)
arDst[strSymbol] = _round_quantity(iHedgeQuantity * fHedge)

# holdings 型（篮子）
# 见 __calc_holdings_quantity 复杂算法（第 245-302 行）
```
