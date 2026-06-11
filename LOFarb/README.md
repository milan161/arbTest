# LOF 基金折价套利监控系统

> 基于 `arbcore` 工业级基座构建的专业级基金套利监控程序。

---

## 🚀 快速启动

### 一键启动（推荐）
```bash
cd LOFarb
./LOF_start_lof_system.bat
```

### 手动启动
```bash
# 1. 数据补全（每日盘前）
python LOF011_daily_updater.py

# 2. 算法对齐（检查数据）
python LOF012_calculate_valuation.py

# 3. 开启监控（核心后台）
python LOF02_fetch_trade_data.py
```

---

## 📁 目录结构

```
LOFarb/
├── readers/              # 核心基座适配层
│   ├── market_gateway.py     # 统一行情网关
│   └── trade_manager.py      # 交易管理器
├── lof_config.yaml       # 全域因子配置中心
├── LOF_start_lof_system.bat # 一键启动脚本
├── LOF011_daily_updater.py  # 数据采集
├── LOF012_calculate_valuation.py # 静态估值计算
├── LOF02_fetch_trade_data.py # 实时行情服务 (端口 5000)
├── LOF03_*.py 系列        # 监控页面
└── logs/                 # 统一日志目录
```

---

## 🌐 服务端口

| 服务组件 | 端口 | 职能 |
|------|------|------|
| 行情网关 | 5000 | 实时 WebSocket 数据流 |
| 管理面板 | 5002 | 数据维护任务 |
| 配置中心 | 5001 | 基金参数配置 |

---

## 🔑 核心特性

1. **BaseApp 基座**：全局 NO_PROXY 强制注入，解决国内行情 API 网络问题
2. **模块化数据库**：`arb_master.db`，支持高并发读写（WAL 模式）
3. **行情网关重构**：无感降级能力（QMT/通达信/IB → 新浪/东财兜底）
4. **跨市场接力**：支持 `-EU`、`-JP`、`-HK` 后缀标的的虚拟快照

---

## 📊 行情优先级

**银河 QMT (Socket)** → **通达信 (内存快照)** → **国金 QMT (xtquant)** → **新浪 API (备用)**

---

## 📚 延伸阅读

- 全局架构：`../docs/002_整体架构设计.md`
- 数据库字典：`../docs/005_数据库.md`
- 新手指南：`README_新手操作.md`

---

*本文档为 V2.2 工业级版本标准架构指南。*
