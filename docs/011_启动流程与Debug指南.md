# ArbDashboard 启动流程与 Debug 指南

> 本文档描述 ArbDashboard（程序3）的完整启动流程、时序、常见冲突风险点，以及如何通过 Debug 输出定位问题。
> 最后更新：2026-06-17

---

## 一、启动方式

### 1.1 一键启动（推荐）

```bash
cd D:\Study\arbTest\ArbDashboard
start_dashboard.bat
```

### 1.2 手动分别启动

```bash
# 终端1：后端（端口 8000）
cd D:\Study\arbTest\ArbDashboard\backend
D:\Study\arbTest\.venv\Scripts\python.exe main.py

# 终端2：前端（端口 5173）
cd D:\Study\arbTest\ArbDashboard\frontend
npm run dev
```

**手动启动的风险**：如果先启动前端再启动后端，前端会立即请求 `/api/*` 接口，此时后端尚未就绪，产生 `ECONNREFUSED` 错误。

---

## 二、`start_dashboard.bat` 启动流程（含 Debug）

批处理文件执行以下步骤：

```
步骤0: 杀死旧的 8000 端口进程 → 等待 2 秒
步骤1: 启动后端（新窗口）
步骤2: 健康检查循环（每 2 秒检查一次，最多 30 秒）
步骤3: 后端就绪后，启动前端（新窗口）
步骤4: 3 秒后打开浏览器
```

### 2.1 Debug 输出示例与解读

```
========================================
 Starting ArbNext Unified Dashboard...
========================================
[DEBUG] Batch file started at 17:04:19.63          ← 批处理开始执行
[Pre-check] Cleaning port 8000...
 Killing old process PID: 5100                      ← 杀死旧进程（如果有）
[1/3] Starting Backend (port 8000)...
[DEBUG] Backend start time: 17:04:22.19             ← 后端 start 命令发出
Waiting for backend to start (checking every 2s, max 30s)...
[DEBUG] Health check attempt 1...                   ← 第 1 次健康检查
[DEBUG] HTTP response code: 200                     ← 后端返回 200（端口已开）
Backend is ready (attempt 1)                         ← 健康检查通过
[2/3] Backend health check PASSED at 17:04:24.80    ← 通过时间
[3/3] Starting Frontend (port 5173)...
[DEBUG] Frontend start time: 17:04:24.80            ← 前端启动

========================================
 Backend: http://127.0.0.1:8000
 Frontend: http://localhost:5173
========================================

Done. Keep both windows open.
```

**关键时间点**：
- 后端启动到健康检查通过：`17:04:22.19 → 17:04:24.80` = **2.6 秒**
- 前端在后端就绪后才启动 → **不会出现 ECONNREFUSED**

### 2.2 健康检查失败的输出

```
[DEBUG] Health check attempt 1...
[DEBUG] HTTP response code: 000                     ← 连接失败（端口未开）
[DEBUG] Backend not ready yet, retrying...
[DEBUG] Health check attempt 2...
[DEBUG] HTTP response code: 200                     ← 第 2 次通过
Backend is ready (attempt 2)
```

如果 15 次全部失败：
```
[DEBUG] Health check failed after 15 attempts (30 seconds)
WARNING: Backend did not respond within 30 seconds.
Check the 'ArbNext Backend' window for error messages.
```

---

## 三、后端启动内部时序

后端 `main.py` 的启动分为多个阶段：

### 3.1 模块加载阶段（~1.5 秒）

```
17:04:23,655  TQ 数据接口全局抢占初始化
17:04:23,656  使用 arbcore 目录、数据库路径
17:04:23,836  SSE 白银期货后台线程启动
17:04:24,186  Core modules imported successfully     ← 模块导入完成
17:04:24,209  TradeManager 挂载通达信
17:04:24,211  TradingService 就绪
17:04:24,211  MarketDataService 初始化（IB Reader 后台线程启动）
17:04:24,212  富途 Reader 初始化
17:04:24,305  检测前端 dist 目录
17:04:24,468  Starting ArbNext Backend lifespan...   ← FastAPI lifespan 开始
```

**注意**：uvicorn 在 lifespan 之前就已经绑定端口 8000 并开始监听。这就是为什么健康检查能在 `17:04:24.80` 通过（lifespan 还在 `17:04:24.470` 才开始）。

### 3.2 Lifespan 初始化阶段（~1 秒）

```
17:04:24,469  分时采样服务启动
17:04:24,469  自动交易引擎已禁用（安全模式）
17:04:24,470  清晨刷新定时器注册
17:04:24,470  自动净值更新定时器注册
17:04:24,470  启动时自动运行 011 数据更新任务
17:04:24,490  011 任务已在后台启动
```

### 3.3 后台连接阶段（~30 秒，非阻塞）

这些在后台线程中运行，不阻塞启动：

```
17:04:26,214  富途连接失败（3次），已禁用
17:04:29,876  国金QMT连接失败
17:04:34,493  行情引擎启动，挂载数据源
17:04:34,600  通达信挂载成功
17:04:42,834  IB连接失败（3次），已禁用
17:04:47,877  国金QMT检测3次失败
17:04:57,963  银河QMT检测3次失败
17:04:57,963  新浪财经挂载成功
17:04:57,963  实时行情引擎已启动                  ← 全部数据源挂载完成
17:05:00,002  富途 OpenD 连接正常
```

**关键**：这些后台连接失败（IB、QMT、富途）不影响前端页面展示，只是对应数据源不可用。

---

## 四、常见冲突风险点

### 4.1 ECONNREFUSED（前端连不上后端）

**原因**：前端启动时后端端口 8000 未开。

**触发条件**：
- 手动先启动前端再启动后端
- `start_dashboard.bat` 健康检查被跳过或失败后仍继续

**解决**：始终使用 `start_dashboard.bat` 启动，不要手动分别启动。

### 4.2 端口 8000 被占用

**现象**：后端启动失败，报 `Address already in use`。

**原因**：上次的后端进程未完全退出。

**解决**：`start_dashboard.bat` 会自动杀死占用 8000 端口的旧进程。如果是手动启动，需先手动杀进程：
```bash
netstat -ano | findstr :8000
taskkill /F /PID <进程ID>
```

### 4.3 后端启动超时（30 秒内未就绪）

**现象**：健康检查 15 次全部失败，批处理暂停。

**可能原因**：
- Python 虚拟环境路径错误
- `arbcore` 模块导入失败
- 数据库文件不存在或损坏
- 端口被其他程序占用

**排查**：查看 "ArbNext Backend" 窗口的错误输出。

### 4.4 通达信 DLL 冲突

**现象**：后端日志报 `RuntimeError: TQ 数据接口未正确初始化`。

**原因**：多个程序同时使用通达信 TQ 接口。

**解决**：Master-Slave 架构自动处理 —— 如果 `LOFarb`（程序1）已运行占用端口 5000，ArbDashboard 自动进入 Slave 模式（禁用本地通达信驱动）。

### 4.5 前端 Vite 代理报错但后端正常

**现象**：前端控制台显示 `[vite] http proxy error: ECONNREFUSED`，但后端日志显示正常。

**原因**：Vite v8 的代理中间件在后端完全就绪前发出请求。

**解决**：刷新页面即可，后续请求正常。这是 Vite v8 的已知行为，无法完全抑制。

---

## 五、Debug 输出分析指南

### 5.1 启动时序分析

检查批处理窗口的 Debug 输出：

| 检查项 | 正常值 | 异常值 | 含义 |
|--------|--------|--------|------|
| `Batch file started` → `Backend start time` | ~2-3 秒 | >5 秒 | 旧进程清理耗时过长 |
| `Backend start time` → `Health check PASSED` | 2-6 秒 | >15 秒 | 后端启动慢 |
| `Health check attempt` | 1-3 次 | 15 次（失败） | 后端未就绪 |
| `HTTP response code` | 200 | 000 / 空 | 端口未开或 curl 失败 |

### 5.2 后端日志时间线分析

查看 `D:\Study\arbTest\ArbDashboard\logs\` 目录下的日志文件：

```bash
# 查看最新的后端日志
ls -lt D:\Study\arbTest\ArbDashboard\logs\*.log | head -1
```

关键时间点：
1. **第一行时间** = 后端进程实际启动时间
2. **`Core modules imported`** = 模块加载完成（应在启动后 1-2 秒内）
3. **`Starting ArbNext Backend lifespan`** = FastAPI 初始化开始
4. **`Dashboard数据生成完成`** = 第一次成功处理请求（应在启动后 5-7 秒内）
5. **`实时行情引擎已启动`** = 所有数据源挂载完成（可能需要 30+ 秒，但不阻塞）

### 5.3 常见 Debug 模式

#### 模式 A：健康检查立即通过（attempt 1，~2 秒）
```
正常。后端启动快，uvicorn 端口绑定迅速。
```

#### 模式 B：健康检查第 2-3 次通过（~4-6 秒）
```
正常。后端模块加载较慢，但仍在合理范围内。
```

#### 模式 C：健康检查 15 次全部失败
```
异常。检查：
1. 后端窗口是否有 Python traceback
2. 端口 8000 是否被其他程序占用
3. Python 虚拟环境是否正确
```

#### 模式 D：后端日志显示 `ECONNREFUSED` 连接 VPS 失败
```
正常。VPS SSH 连接失败不影响本地功能。
检查 VPS 配置文件 D:\Study\arbTest\arbcore\config\account_private.py
```

---

## 六、AI 故障排查清单

当用户报告启动问题时，AI 应按以下顺序排查：

### 步骤 1：确认启动方式
- 问用户是用 `start_dashboard.bat` 还是手动启动
- 如果手动启动 → 建议改用批处理

### 步骤 2：检查批处理 Debug 输出
- 健康检查是否通过？
- 通过时间是多少？
- 如果失败，后端窗口显示什么错误？

### 步骤 3：检查后端日志
```bash
# 查看最新日志的前 30 行
head -30 D:\Study\arbTest\ArbDashboard\logs\*.log
```

检查：
- 第一行时间戳（启动时间）
- 是否有 `Core modules imported`（模块加载成功）
- 是否有 `Dashboard数据生成完成`（后端正常工作）
- 是否有 `UnicodeEncodeError` 或 `WinError`（已知的非致命错误）

### 步骤 4：检查端口占用
```bash
netstat -ano | findstr :8000
netstat -ano | findstr :5173
```

### 步骤 5：检查进程
```bash
tasklist | findstr python
tasklist | findstr node
```

### 步骤 6：常见修复
- 杀死占用端口的旧进程
- 重启批处理文件
- 如果后端日志有 Python 异常，检查依赖是否完整：`pip install -r requirements.txt`

---

## 七、已知的非致命错误

以下错误在日志中出现但不影响系统运行：

| 错误 | 原因 | 影响 |
|------|------|------|
| `UnicodeEncodeError: 'gbk'` | Windows 控制台不支持 emoji 字符 | 仅影响 `_print_data_source_banners()` 输出，不影响功能 |
| `[WinError 1] 函数不正确` | 同上 | 同上 |
| `ConnectionResetError: [WinError 10054]` | VPS SSH 连接中断 | 不影响本地功能 |
| `[WinError 64] 指定的网络名不再可用` | uvicorn socket 在 lifespan 期间被重置 | 不影响功能，lifespan 完成后自动恢复 |
| `IB/QMT/富途 连接失败` | 对应客户端未运行 | 仅影响对应数据源，前端正常展示其他数据 |

---

*最后更新：2026-06-17*
