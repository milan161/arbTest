# LOF 基金套利监控系统

## 项目概述

LOF 基金套利监控系统是一个实时监控 LOF 基金折价/溢价机会的系统，通过跟踪 A 股、美股 ETF 和期货数据，实时计算 LOF 基金的估值，帮助投资者发现套利机会。

系统包含两个主要模块：
- **LOFarb**：专注于 LOF 基金的折价/溢价套利
- **ETFrotate**：专注于 ETF 的轮动策略

## 系统架构

系统采用三层架构设计：

1. **核心层** (`arbcore`)：提供通用函数库，包括数据获取、处理和存储等核心功能
2. **数据层** (`arbcore/database`)：使用 SQLite 数据库存储基金数据、汇率数据和期货数据
3. **应用层**：
   - `LOFarb`：聚焦折价套利
   - `ETFrotate`：聚焦轮动套利

## 核心功能

- **实时估值**：基于多种方法计算 LOF 基金的实时估值
- **套利机会检测**：自动检测折价/溢价机会
- **数据自动更新**：定期更新基金净值、价格和相关市场数据
- **可视化监控**：通过网页界面实时监控套利机会

## 快速开始

### 环境要求

- Python 3.11+
- 依赖包：见 `requirements.txt`

### 启动步骤

1. **安装依赖**：
   ```bash
   pip install -r requirements.txt
   ```

2. **折价套利程序 启动系统**：
   ```bash
   # 方法1：使用批处理脚本
   cd LOFarb
   LOF_start_lof_system.bat
   
   # 方法2：手动启动
   cd LOFarb
   python LOF011_daily_updater.py  # 数据更新
   python LOF012_calculate_valuation.py  # 估值计算
   python LOF02_fetch_trade_data.py  # 实时数据服务 (端口 5000)
   python LOF01_admin_launcher.py  # 管理面板 (端口 5002)
   python LOF03_generate_monitor_html.py  # 生成监控页面
   ```

3. **访问界面**：
   - 监控看板：http://localhost:5000/
   - 管理后台：http://localhost:5002/

## 目录结构

```
├── arbcore/             # 核心函数库
│   ├── fetchers/        # 数据获取模块
│   ├── database/        # 数据库模块
├── LOFarb/              # 折价套利程序
│   ├── data/            # 数据文件
│   ├── docs/            # 说明文档
│   ├── logs/            # 日志
│   ├── readers/         # 读取数据
│   └── LOF*.py          # 核心脚本
├── ETFrotate/           # 轮动套利程序
├── README.md            # 项目概述
├── ARCHITECTURE.md      # 系统架构设计
├── DATABASE.md          # 数据库设计
└── API.md               # API 数据处理指南
```

## 核心脚本

1. **LOF011_daily_updater.py**：每日数据更新，获取基础数据和基金数据
2. **LOF012_calculate_valuation.py**：计算基金静态官方估值
3. **LOF02_fetch_trade_data.py**：实时数据服务，提供 REST API、WebSocket 和 SSE
4. **LOF03_generate_monitor_html.py**：生成监控页面
5. **LOF00_input_LOF_info.py**：配置管理界面
6. **LOF01_admin_launcher.py**：管理面板

## 数据来源

- **A股**：新浪/东财 SSE API
- **美股**：IB Gateway，新浪财经作为备用
- **期货**：CME via IB
- **汇率**：国家外汇管理局、新浪财经

## 估值方法

1. **静态官方估值**：基准日净值 + 估值日 ETF/汇率变化
2. **ETF实时估值**：基准日净值 + 当然ETF/汇率变化
3. **期货校准实时估值**：基于期货价格校准为ETF
4. **期货原生实时估值**：直接使用期货价格

## 技术栈

- Python 3.11+
- Flask/Dash for web UI
- SQLite for data storage
- IB Gateway for real-time market data

## 维护与支持

- **日志**：`LOFarb/logs/` 
- **配置**：`LOFarb/lof_config.yaml`
- **数据**：`arbcore/database/arb_data.db`