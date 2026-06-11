# LOFarb - AI 编程助手快速入门

> 本文档供 AI 编程助手快速了解项目架构。

---

## 一、项目概述

**LOFarb** 是程序 1，LOF 基金折价套利系统，已完成并正常运行，用于培训班教学。

---

## 二、核心功能

1. **每日数据更新**：`LOF011_daily_updater.py`
2. **Woody API 集成**：获取 QDII 基金估值因子
3. **套利机会监控**：折溢价率计算与提醒

---

## 三、Woody API Key

- **Key 名称**：`BOT_Key`
- **用途**：LOF 基金因子获取

---

## 四、快速启动

```bash
cd d:\Study\arbTest\LOFarb
python LOF011_daily_updater.py
```

---

*最后更新：2026-06-09*
