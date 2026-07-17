# 银河 QMT Socket 下单调试总结

> 最后更新：2026-07-17（v5.2.0 成交监听 + 持仓查询）
> 涉及文件：`trade_manager.py` / `Test_Yinhe_qmt_ServerV5.py` / `safe_buy_test.py` / `manager.py` / `galaxy.py`

---

## 一、全景概览：两天的调试历程

| 日期 | 尝试方案 | 结果 | 根本原因 |
|------|---------|------|---------|
| 周六（非交易） | v5.0 队列模式 | 全部超时 | QMT 周末引擎休眠，`run_time` 定时器不触发，队列永不消费 |
| 周六（非交易） | v4.3 改进子线程 | 同 v5.0 | 仍依赖 `run_time` |
| 周六（非交易） | v4.0 子线程并发锁 | BUY 成功但 QUERY_TICK 死锁 | `passorder` 是异步写→成功；`get_full_tick` 是同步读→子线程死锁 |
| **周一（交易）** | **v4.0 + 重启QMT** | **BUY 500×0.84 秒到委托单，QUERY_TICK 正常** | **交易时段引擎活跃 + 无僵尸线程** |

---

## 二、核心问题一：周末 QMT 引擎休眠机制（周六失败的根因）

### 2.1 QMT 周末行为

QMT 的 C++ 引擎在非交易时段进入深度休眠状态，表现为：

| 功能 | 周末表现 | 原理 |
|------|---------|------|
| `ContextInfo.run_time()` 定时器 | ❌ 完全不触发 | C++ 引擎停止调度 Python 回调 |
| `get_full_tick()` 同步行情读取 | ❌ 子线程调用死锁 | 失去主线程保护，底层被锁死 |
| `passorder()` 异步委托写入 | ✅ 成功（fire-and-forget） | 只写入本地内存队列，不等待回执 |
| daemon socket 线程调度 | ❌ GIL 冻结 | 主引擎不触发 Python 回调 → daemon 线程抢不到 GIL |

### 2.2 结论

> **周末不可能跑通全功能。** 不是代码 bug，是 QMT 的固有设计——它不为非交易时段提供行情查询支持。v5.0 依赖定时器所以在周末完全失效；v4.0 的子线程能下单但查不了行情。**任何方案在周末都有致命缺陷。**

---

## 三、核心问题二：僵尸线程抢占端口（周一开盘时的关键发现）

### 3.1 现象

```
netstat -an | find "8888"
  TCP 127.0.0.1:8888   LISTENING   (出现 6 次)
```

每次 QMT 策略编辑器中点击「保存/重载」，旧策略中的 `socket_server_thread` 线程并不会被销毁——它变成了"僵尸线程"，继续霸占 8888 端口。新策略虽然也绑定了 8888，但新客户端连接可能被路由到任意一个僵尸线程，导致指令被丢弃。

### 3.2 解决方案

> **第一步必须是重启 QMT 客户端，而不是修改代码。** 不管什么版本、什么架构，只要 8888 端口有残留僵尸线程，下单就不稳定。

---

## 四、周一成功的关键：两个要素缺一不可

### 要素 1：交易时段

14:45 ~ 14:57 交易时段内，QMT 引擎完全激活：
- `run_time` 定时器 1 秒触发一次 → `push_ticks()` 正常推送
- `get_full_tick()` 瞬间返回 → 行情查询正常
- `passorder()` 2-4ms 完成 → 委托秒到交易所
- 行情和交易使用 `g_api_lock` 互斥锁保护，**无冲突**

### 要素 2：重启 QMT 清空僵尸线程

清空前：8888 端口 6 个 LISTENING
清空后：8888 端口 1 个 LISTENING（干净）
结果：每条指令都到达正确的 socket server，不再丢失

### 4.3 为什么是 v4.0 而不是 v5.0

v4.0（子线程并发锁）在交易时段比 v5.0（定时器队列）更优的原因：

| 对比项 | v4.0 子线程锁 | v5.0 定时器队列 |
|--------|-------------|---------------|
| 下单延迟 | 2-4ms（直接执行） | 500ms+（排队等定时器） |
| 开盘日行情 | ✅ 正常 | ✅ 正常 |
| 周末行情 | ❌ get_full_tick 死锁 | ❌ 定时器不触发 |
| 高并发稳定性 | ⚠️ 子线程调 C++ 有风险（已加锁） | ✅ 工业级安全 |

**结论：交易时段用 v4.0，周末不交易。**

---

## 五、今日修复汇总（2026-06-15 14:30 ~ 14:57）

### 已修复的 Bug

| 问题 | 文件 | 改动 |
|------|------|------|
| 国金QMT `connect()` 谎报成功 | `guojin.py` | 增加 `get_full_tick` 实时探测，失败设 `is_connected=False` |
| xtquant ERROR 每 2 秒刷屏拖死后端 | `guojin.py` + `manager.py` | 只有启动时探测，之后不再轮询 |
| 数据源无重试机制，一次失败就放弃 | `manager.py` | 3 次重试（间隔 3 秒），全失败输出"请前往主面板启动X" |
| 银河QMT `push_ticks` 短格式被静默丢弃 | `galaxy.py` | 增加 5 字段短格式 TICK 解析 |
| 完整的 5 档盘口 TICK pre_close/amount 索引重叠 | `galaxy.py` | 修正位置（24→pre_close, 25→amount） |
| `push_ticks` 只发 lastPrice 不含盘口 | `Test_Yinhe_qmt_ServerV5.py` | 升级为 27 字段（含 5 档买卖盘口+昨收+成交额） |

### 关键架构变化

**Data Source 3-Retry Protocol（全局）**：
- 通达信/国金QMT/银河QMT 首次连接失败后，等 3 秒重试，最多 3 次
- 3 次全失败 → 输出中文提示"请前往主面板启动X客户端"
- 不再继续轮询，绝不刷屏
- 通过 `System Milestone` 写入日志，前端可展示

---

## 六、交易时段验证结果（2026-06-15 周一 14:45~14:57）

### 测试条件
- QMT 客户端重启后加载 **v4.0 绝杀版**（`Test_Yinhe_qmt_ServerV5.py`）
- 安全测试价：买入 0.78（现价 0.841），绝不成交

### 测试结果

| 时间 | 测试项 | 结果 | 说明 |
|------|--------|------|------|
| 14:45 | BUY 162411.SZ 500@0.84 | ✅ QMT 秒回 OK，委托单出现在 银河APP | 全链路首通 |
| 14:45 | Dashboard 前端下单 0.841×300 | ❌ 失败（后端已死） | 根因：xtquant 错误洪水拖死进程 |
| 14:57 | QUERY_TICK 162411.SZ | ✅ 返回 `0.84` 昨收 `0.861` | 后端重启后正常 |
| 14:57 | BUY 162411.SZ 100@0.78 | ✅ 秒回 OK | 修复后再次验证 |

### 核心结论

> **交易时段，银河QMT v4.0 同时处理行情查询和下单没有任何冲突。** 使用 `g_api_lock` 互斥锁保护 C++ 接口，行情推送 (`push_ticks` 每秒 1 次) 和委托执行 (`passorder` 2-4ms) 在独立线程中稳定并存。

---

## 七、程序3（ArbDashboard）集成要点

### 7.1 V10.0 非阻塞模式（2026-06-18 重要更新）

所有 reader 统一采用"启动试连3次 + disabled 标记 + 按钮重连"的非阻塞模式：

| 阶段 | 行为 |
|------|------|
| **启动时** | `__init__` 调用 `_try_connect_silent()`，最多试连 3 次，每次失败 sleep 1s。成功 → `disabled=False`。全部失败 → `disabled=True`，不再重试 |
| **运行时** | `get_prices()` / `get_quote()` 首行检查 `if self.disabled: return`，**绝不阻塞** |
| **用户重连** | 点击页面顶部对应标签 → 调用 `reconnect()` → 重置 `disabled=False` → 重新试连 3 次 |

**银河QMT 启动行为变化**：
- V10.0 之前：启动时自动尝试连接所有数据源
- V10.0 之后：启动时**跳过**银河QMT（`weekday() >= 5` 时跳过，工作日也跳过），用户手动点击顶部"银河QMT"标签重连

### 7.2 交易通道集成

`trade_manager.py` 中 `yinhe_qmt` 分支：Socket 短连接发送，try-read-OK 模式（发送后尝试读回执，超时视为成功）。

**完整协议表（v5.2.0 — 2026-07-17）：**

| 方向 | 命令 | 格式 | 说明 |
|------|------|------|------|
| 请求→ | `BUY` | `BUY,code,volume,price\n` | 买入委托 |
| 请求→ | `SELL` | `SELL,code,volume,price\n` | 卖出委托 |
| 请求→ | `QUERY_TICK` | `QUERY_TICK,code\n` | 查询最新行情 |
| 请求→ | `QUERY_POSITION` | `QUERY_POSITION,code\n` | 查询单只持仓 |
| 请求→ | `SUBSCRIBE` | `SUBSCRIBE,code1,code2,...\n` | 订阅行情推送 |
| 请求→ | `PING` | `PING\n` | 心跳 |
| ←回复 | OK | `OK\n` | 委托已入队 |
| ←回复 | `TICK_RESULT` | `TICK_RESULT,code,lastPrice,preClose\n` | 行情快照 |
| ←回复 | `POSITION_RESULT` | `POSITION_RESULT,code,vol,price\n` | 持仓快照 |
| ←广播 | `TICK` | `TICK,code,last,vol,ap1,av1,...\n` | 1s 定时行情推送（27字段含5档盘口） |
| ←广播 | `DEAL` | `DEAL,code,vol,price\n` | `deal_callback` 成交实时广播 |
| ←广播 | `ORDER` | `ORDER,code,sysid,status\n` | `order_callback` 订单状态广播 |

### 7.3 行情通道集成（银河QMT 同时提供行情和交易）

| 组件 | 文件 | 角色 |
|------|------|------|
| v4.0 Socket Server | `Test_Yinhe_qmt_ServerV5.py` | QMT 内部，监听 8888，推送 TICK + 执行委托 |
| GalaxyQmtFetcher | `galaxy.py` | Python 端，接收推送 TICK，缓存到 `quotes` 字典；V10.0 增加 `disabled`/`_try_connect_silent()`/`reconnect()` |
| 行情管理器 | `manager.py` | 协调多数据源优先级，银河QMT 作为 A 股 LOF 主源 |

### 7.4 后端重连 API

| 端点 | 行为 |
|------|------|
| `POST /api/system/reconnect_galaxy` | 调用 `GalaxyQmtFetcher.reconnect()`，写 milestone |

### 7.5 其他数据源降级策略

| 数据源 | V10.0 启动行为 | 说明 |
|--------|--------------|------|
| 银河QMT (port 8888) | 跳过自动连接 | 用户手动点击重连 |
| 通达信 (tqcenter) | 跳过自动连接 | 用户手动点击重连 |
| 国金QMT (xtquant) | 跳过自动连接 | 用户手动点击重连 |
| 富途 (Futu) | 跳过自动连接 | 用户手动点击重连 |
| IB (盈透) | 跳过自动连接 | 用户手动点击重连 |
| 新浪财经 (轮询) | **始终自动连接** | 纯API源，无需客户端，兜底 |
| 腾讯财经 (轮询) | **始终自动连接** | 纯API源，无需客户端，兜底 |

---

## 八、操作指南

### 8.1 开盘流程

```
1. 启动银河QMT客户端
2. QMT策略编辑器 → 打开 Test_Yinhe_qmt_ServerV5.py → 加载/保存
3. 验证端口：netstat -an | find "8888"（应只有 1 个 LISTENING）
4. 启动 Dashboard 后端：python main.py
5. 验证健康：curl http://127.0.0.1:8000/api/health
```

### 8.2 如果遇到僵尸线程

```
1. 完全退出 QMT 客户端（任务管理器确认进程已死）
2. 重启 QMT
3. 重新加载策略
4. 验证 8888 端口只剩 1 个 LISTENING
```

### 8.3 安全测试规则（重要）

```
买入测试价 = 现价 × 0.9（确保挂在买一之下，绝不成交）
卖出测试价 = 现价 × 1.5（确保挂在卖一之上，绝不成交）
```

使用 `safe_buy_test.py`，严禁使用 `pure_buy_test.py` 的 1.0 危险价格。

---

## 九、2026-07-17 新增：成交监听与持仓查询

> SmartOpenMonitor 所需的基础设施。方案 A（实时 DEAL 广播）+ 方案 B（QUERY_POSITION 轮询保底）。

### 9.1 架构

```
┌─ QMT 策略 (Test_Yinhe_qmt_ServerV5.py v5.2.0) ──────────────────┐
│                                                                    │
│  deal_callback ─→ _broadcast("DEAL,code,vol,price") ─→ socket 客户端│
│  order_callback ─→ _broadcast("ORDER,code,sysid,status")          │
│  position_callback ─→ 更新 latest_positions 缓存                    │
│  QUERY_POSITION ─→ 从 latest_positions 缓存读取返回                  │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─ 后端 (TradeManager) ───────────────────────────────────────────┐
│                                                                    │
│  start_deal_listener() → 持久连接接收 DEAL 广播 → 分发回调           │
│  on_deal(callback)     → 注册成交回调 fn(code, vol, price)         │
│  query_position(code)  → 短连接 QUERY_POSITION → 返回 dict         │
│  stop_deal_listener()  → 关闭监听                                  │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### 9.2 QMT 策略改动（3 个回调 + 1 条命令）

| 改动 | 文件 | 说明 |
|------|------|------|
| `position_callback` 重写 | `Test_Yinhe_qmt_ServerV5.py` | 不再静默无视，改为更新 `latest_positions` 缓存（加锁，不打印） |
| `deal_callback` 加广播 | `Test_Yinhe_qmt_ServerV5.py` | `_broadcast(f"DEAL,{code},{vol},{price}\n")` — 成交实时通知 |
| `order_callback` 加广播 | `Test_Yinhe_qmt_ServerV5.py` | `_broadcast(f"ORDER,{code},{sysid},{status}\n")` — 订单状态通知 |
| `QUERY_POSITION` 命令 | `Test_Yinhe_qmt_ServerV5.py` | `client_handler` 新增：从 `latest_positions` 缓存读取并返回 |
| 共享状态新增 | `Test_Yinhe_qmt_ServerV5.py` | `latest_positions` + `positions_lock` |

### 9.3 后端改动（6 个新方法）

| 方法 | 说明 |
|------|------|
| `TradeManager.on_deal(callback)` | 注册成交回调 `fn(code, vol, price)`，可注册多个 |
| `TradeManager.query_position(code)` | 短连接查持仓，返回 `{code, volume, price}` 或 `None` |
| `TradeManager.start_deal_listener()` | 启动后台线程：持久连接 `:8888`，阻塞读 DEAL 广播 |
| `TradeManager.stop_deal_listener()` | 关闭 socket 停止监听线程 |
| `TradeManager._deal_listener_loop()` | 内部线程函数：重连循环 + 行解析 |
| `TradeManager._dispatch_deal_line(line)` | 解析 `DEAL,code,vol,price` 并逐个调用回调 |

### 9.4 使用示例

```python
# 启动监听
trade_manager.start_deal_listener()

# 方案 A：注册实时成交回调
def on_my_deal(code, vol, price):
    print(f"🏁 成交! {code} {vol}股@{price}")
    # → 触发对冲：short GLD / 更新 SmartOpenMonitor 状态
trade_manager.on_deal(on_my_deal)

# 方案 B：保底轮询持仓
pos = trade_manager.query_position("162411")
if pos and pos['volume'] > 0:
    print(f"已持仓 {pos['volume']} 股 @ {pos['price']}")
```

### 9.5 设计要点

1. **DEAL 广播 vs TRADES tick**：`deal_callback` 是 QMT 官方成交回调，比轮询行情判成交更可靠
2. **position_callback 作为缓存源**：QMT 实时推送仓位变化 → 更新内存缓存 → QUERY_POSITION 零延迟读取，不调用 C++ API
3. **持久连接自动重连**：监听线程 detect 连接断开或 QMT 重启后，5s 自动重连
4. **无单点故障**：A 方案断连时 B 方案（QUERY_POSITION 短连接）仍可用

---

## 十、已知限制

| 限制 | 影响 | 解决方案 |
|------|------|---------|
| 周末 `get_full_tick` 在子线程死锁 | 周末无法查行情 | 周末不交易，行情非必需 |
| 策略重载后僵尸线程残留 | 下单可能丢失 | 重启 QMT |
| 国金QMT (xtquant) 不稳定 | A股行情降级新浪 | 用银河QMT代替 |
| DEAL 广播依赖持久连接 | 连接断开期间成交事件丢失 | 方案 B 轮询保底 + 自动重连 |

---

## 十一、关键日志

### QMT 端日志（周一交易时段）

```
11:28:07  加载 v4.0 绝杀版 Socket 策略 (同步并发锁)...
11:28:08  QMT Socket Server Started. Listening on 8888...
11:28:53  新客户端接入: ('127.0.0.1', 11334)
11:28:54  Order Sent: BUY 162411.SZ 100 @ 0.78
11:28:54  客户端断开: ('127.0.0.1', 11334)

14:45:27  新客户端接入: ('127.0.0.1', 6813)
14:45:28  Order Sent: BUY 162411.SZ 500 @ 0.84
14:45:28  客户端断开: ('127.0.0.1', 6813)
```

### Dashboard 后端日志（核心修复前后对比）

```
# 修复前（14:34）：xtquant 错误每 2 秒刷屏，进程被拖死
ERROR - Error getting realtime quote for 160924: 无法连接xtquant服务
ERROR - Error getting realtime quote for 164705: 无法连接xtquant服务
ERROR - Error getting realtime quote for 501021: 无法连接xtquant服务
...

# 修复后（14:40）：只有启动时 3 次探测，之后完全安静
⏳ 通达信 连接失败 (第1次)，3秒后第2次重试...
⏳ 通达信 连接失败 (第2次)，3秒后第3次重试...
⚠️ 通达信客户端未运行（已检测3次均失败），请前往主面板启动通达信交易终端
⚠️ 国金QMT（xtquant）未运行（已检测3次均失败），请前往主面板启动国金极速交易终端
✅ 银河QMT Socket 已连接 (127.0.0.1:8888)
```

---

*备忘：下次开盘直接用 v4.0，无需修改代码。如果 Dashboard 不显示行情，检查 8888 端口是否有僵尸线程（重启 QMT 即可）。*