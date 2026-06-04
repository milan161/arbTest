# ArbNext 统一套利看板 - VUE 改造方案与进度手册

> **目的**：将原有的 `LOFarb` 和 `jsl` 监控系统聚合为一个现代化的、高性能的 Vue 3 套利看板。
> **状态**：第三阶段 (稳定性加固与工业级交付) 已完成。

## 一、 核心架构设计

### 1. 技术栈
- **前端 (Frontend)**: Vue 3 (Composition API) + Vite + TypeScript + Naive UI
- **后端 (Backend)**: FastAPI (Python 3.11) + SQLAlchemy/Pandas
- **数据层**: 复用 `arbcore/database/arb_master.db` (SQLite WAL 模式)
- **通信**: RESTful API + Axios

## 二、 已完成步骤

1. **环境初始化**: (2026-06-03 完成)
2. **功能增强与深度分析**: (2026-06-04 完成)
   - 实现了历史溢价走势图 (ECharts) 与成分股拆解看板。
   - 增加了 Dashboard 搜索、筛选及远程任务触发功能。
3. **工业级稳定性加固 (2026-06-04 完成)**:
   - **修复白屏 Bug**: 解决了 Naive UI 组件未显式导入导致的 `useMessage` 运行时异常。
   - **API 健壮性**: 修复了后端 `system_health` 表列名引用错误 (updated_at -> timestamp) 导致的 500 报错。
   - **全量编译通过**: 修复了 19 处 TypeScript 类型错误，确保 `npm run build` 能够完美生成生产包。
   - **空值保护**: 为所有前端渲染字段增加了 Null-Safety 保护，确保在数据缺失时系统平滑降级。

## 三、 运行办法

1. **一键启动**: 双击 `ArbDashboard_Next/start_dashboard.bat`。
2. **访问地址**:
   - **前端界面**: http://localhost:5173
   - **API 文档**: http://127.0.0.1:8000/docs

## 四、 后续开发路线图

1. **实时行情推送**:
   - [ ] 将后端的定时轮询改为 WebSocket，实现毫秒级的 UI 数据跳动。
2. **交易集成 (实验性)**:
   - [ ] 在 Analysis 页增加“一键申购/赎回”模拟（或对接实盘接口）。
3. **多维排序与监控**:
   - [ ] 增加基于“校准因子”或“对冲值”的排序功能。
   - [ ] 增加“系统日志”实时监控面板。

---
*此文档由 Gemini CLI 自动生成，用于记录项目演进过程。*


---
*此文档由 Gemini CLI 自动生成，用于记录项目演进过程。*
