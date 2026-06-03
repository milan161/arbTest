# LOF 基金套利监控系统 (Industrial Grade V2.2)

## 项目概述

LOF 基金套利监控系统是一个实时监控 LOF 基金折价/溢价机会的专业级平台。通过集成 A 股（QMT/通达信）、美股（IB/新浪）及期货（CME）的多维度行情，实现全天候、高精度的实时估值与对冲参考。

系统已全面重构，采用 **BaseApp 标准化基座** 与 **模块化 DatabaseManager**，确保在无人值守环境下的极致稳定性。

## 系统架构 (三层金字塔)

1. **核心基座层** (`arbcore`)：提供工业级组件
   - `BaseApp`：标准化启动器，管理日志、配置与数据库。
   - `DatabaseManager`：职责分离的数据库管理系统（支持 WAL 并发）。
   - `Fetchers`：具备熔断与降级保护的数据采集矩阵。
2. **数据持久层** (`arbcore/database`)：
   - 统一数据库：`arb_master.db`。
   - 实现“动静结合”的数据流转，完美记录实时现价与官方净值。
3. **业务应用层**：
   - `LOFarb`：跨境与大宗基金折价套利。
   - `jsl`：全市场 LOF/ETF 监控看板（JSL 风格）。

## 快速开始

### 环境配置

- **Python 版本**：3.11+ (推荐使用 Miniconda/Anaconda 管理环境)
- **依赖安装**：
  ```bash
  pip install -r requirements.txt
  ```

### 启动流程

1. **一键启动 (推荐)**：
   ```bash
   cd LOFarb
   LOF_start_lof_system.bat
   ```

2. **核心脚本职能**：
   - `LOF011_daily_updater.py`：数据大一统采集（每日盘前执行，支持 VPS 追溯）。
   - `LOF012_calculate_static_valuation.py`：纯本地静态估值流水线。
   - `LOF02_fetch_trade_data.py`：实时行情网关（核心服务，5000 端口）。
   - `LOF01_admin_launcher.py`：管理调度面板（5002 端口）。

## 目录结构

```
├── arbcore/             # 工业级核心库
│   ├── calculators/     # 估值与对冲算法引擎
│   ├── database/        # 模块化数据库管理 (managers/)
│   └── fetchers/        # 多源行情采集 (IB, Woody, Sina)
├── LOFarb/              # 跨境套利主应用
│   ├── readers/         # 数据接口与基座适配
│   └── LOF*.py          # 业务主脚本
├── jsl/                 # 集思录风格全市场看板
├── docs/                # 技术专题文档
└── arb_master.db        # 全局唯一数据库
```

## 数据源与估值

- **A股行情**：首选银河QMT或通达信长连接，新浪API作为降级兜底。
- **海外行情**：IB Gateway 提供原生美股/期货报价。
- **估值体系**：
  - **静态官方**：用于 T-1 日历史复盘。
  - **动态推演**：提供三种实时模式（ETF/期货校准/期货原生）。

## 维护与支持

- **日志监控**：所有 `BaseApp` 脚本日志统一输出至 `logs/` 或标准输出。
- **数据库维护**：支持 `db.vacuum_database()` 空间优化与自动数据清理。
- **健康监控**：`system_health` 表实时记录各组件心跳。

---
*稳健的系统，是套利盈利的基石。*
