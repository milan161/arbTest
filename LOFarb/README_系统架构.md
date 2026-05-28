# 📊 LOF 基金折价套利监控系统

本系统是一个半自动化监控跨境基金套利的程序，通过抓取美股ETF/期货的实时价格、人民币汇率、以及历史因子（对冲值、校准值），推演出基金的静态官方估值，进一步预估"实时估值"，指导实盘套利打单。

---

## 📁 目录结构

```
LOFarb/
├── data/                 # 历史数据目录（已废弃，改用数据库）
├── docs/                 # 技术文档子目录
├── ibapi/                # IB API接口库
├── logs/                 # 日志文件
├── my-ai/                # AI相关文件
├── readers/              # 数据读取模块
│   ├── config_manager.py     # 配置管理
│   ├── data_fetcher.py       # 数据获取
│   ├── database_manager.py   # 数据库管理
│   ├── dynamic_data_fetcher.py # 动态数据获取
│   ├── health_monitor.py     # 健康监控
│   ├── http_client.py        # HTTP客户端
│   ├── qmt_socket_client.py  # QMT Socket客户端
│   ├── qmt_socket_server.py  # QMT Socket服务端（银河QMT策略）
│   ├── retry_manager.py      # 重试管理
│   └── trade_manager.py      # 交易管理器
├── lof_config.yaml       # 配置文件
├── lof_monitor.html      # 静态监控页面
├── LOF_start_lof_system.bat  # 一键启动脚本
├── LOF00_input_LOF_info.py   # 配置管理界面
├── LOF01_admin_launcher.py   # 管理面板
├── LOF011_daily_updater.py   # 每日数据更新
├── LOF012_calculate_valuation.py # 静态估值计算
├── LOF02_fetch_trade_data.py # 实时数据服务
├── LOF03_generate_monitor_html.py # 监控页面生成
├── LOF031_config_manager.py  # 配置管理组件
├── LOF032_data_processor.py  # 数据处理组件
└── LOF033_html_generator.py  # HTML生成组件
```

---

## 🚀 快速启动

### 方法一：一键启动（推荐）

```bash
cd LOFarb
LOF_start_lof_system.bat
```

### 方法二：手动启动

```bash
cd LOFarb

# 1. 数据初始化（首次运行）
python LOF00_input_LOF_info.py

# 2. 每日数据更新（盘后执行）
python LOF011_daily_updater.py

# 3. 静态估值计算
python LOF012_calculate_valuation.py

# 4. 启动实时数据服务（端口5000）
python LOF02_fetch_trade_data.py

# 5. 启动管理面板（端口5002）
python LOF01_admin_launcher.py

# 6. 生成监控页面
python LOF03_generate_monitor_html.py
```

---

## 🌐 访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 监控看板 | http://localhost:5000 | 实时监控套利机会 |
| 管理后台 | http://localhost:5002 | 系统管理和任务执行 |
| 配置界面 | http://localhost:5001 | 基金配置管理 |

---

## 📋 核心程序说明

### 1. 数据大一统更新 (LOF011_daily_updater.py)
- **功能**：按顺序执行完整的数据抓取流水线
- **数据源**：Woody API、外汇局、新浪、东财
- **核心特征**：受 `access_sync_status` 表保护，每日单次抓取

### 2. 静态估值计算 (LOF012_calculate_valuation.py)
- **功能**：启动纯数学计算引擎，计算基金静态官方估值
- **核心特征**：不访问外网，仅使用数据库数据，执行速度极快

### 3. 实时数据服务 (LOF02_fetch_trade_data.py)
- **功能**：整合所有实时数据源，提供API服务
- **行情优先级**：银河QMT(Socket) → 通达信(内存直连) → 国金QMT(xtquant) → 新浪API(兜底)
- **输出**：REST API、WebSocket、SSE流

### 4. 监控页面生成 (LOF03_generate_monitor_html.py)
- **功能**：生成静态HTML监控页面
- **架构**：店长(03)-菜单(031)-厨师(032)-装修(033)-电工(034) 职责分离

---

## 🔗 交易接口支持

系统支持以下交易通道：

| 通道 | 类型 | 说明 |
|------|------|------|
| 银河QMT | Socket | 通过 qmt_socket_server.py 连接 |
| 国金QMT | xtquant | 原生API直连 |
| 通达信 | tqcenter | 内存直连 |
| IB盈透 | IB API | 外盘数据和交易 |

---

## 📚 参考文档

- 系统架构：`../docs/002_整体架构设计.md`
- 数据库设计：`../docs/005_数据库.md`
- 估值算法：`../docs/009_估值_校准值、对冲值.md`
- QMT/通达信技术文档：`../docs/012_QMT通达信技术文档.md`

---

## ⚠️ 注意事项

1. 首次运行前请确保配置文件 `lof_config.yaml` 正确设置
2. 运行实时服务前请确保相关交易客户端已启动（如QMT、通达信）
3. 数据库文件位于 `../database/arb_master.db`
4. 日志文件位于 `logs/` 目录