# 程序3：ArbDashboard - API 接口文档

## 一、接口概览

所有 API 接口均基于 RESTful 风格，基础路径为 `http://localhost:8000/api`。

API 文档可通过 Swagger UI 查看：`http://localhost:8000/docs`

## 二、接口列表

### 2.1 套利看板接口

#### GET /api/dashboard

**功能**：获取主页全量套利看板数据

**请求参数**：无

**响应示例**：
```json
{
  "黄金原油": [
    {
      "fund_code": "162411",
      "fund_name": "华宝油气",
      "price": 1.234,
      "change_pct": 2.5,
      "rt_val": 1.200,
      "rt_premium": 2.83,
      "static_val": 1.180,
      "static_premium": 4.58,
      "nav": 1.150,
      "nav_date": "2026-06-05",
      "volume": 5000.0,
      "category": "黄金原油"
    }
  ],
  "纯ETF": [...],
  "美股指数": [...],
  "混合跨境": [...]
}
```

---

### 2.2 基金数据接口

#### GET /api/fund/{code}/history

**功能**：获取单基金的历史对账数据

**路径参数**：
- `code`：基金代码（如 162411）

**请求参数**：
- 无

**响应示例**：
```json
{
  "history": [
    {
      "date": "2026-06-05",
      "price": 1.234,
      "nav": 1.150,
      "static_val": 1.180,
      "static_premium": 4.58,
      "exchange_rate": 7.123,
      "xop_price": 165.50,
      "pct_change": 2.5,
      "val_error_pct": 0.3
    }
  ],
  "basket_weights": [
    {"asset_code": "XOP", "weight": 0.85}
  ]
}
```

---

#### GET /api/fund/{code}/intraday

**功能**：获取单基金的分时采样数据

**路径参数**：
- `code`：基金代码

**请求参数**：
- `date`：日期（YYYY-MM-DD），默认当天

**响应示例**：
```json
{
  "fund_code": "162411",
  "date": "2026-06-08",
  "data": [
    {"time": "09:31:00", "price": 1.230, "rt_val": 1.200, "premium": 2.5},
    {"time": "09:32:00", "price": 1.232, "rt_val": 1.201, "premium": 2.58}
  ]
}
```

---

#### GET /api/fund/{code}/basket

**功能**：获取基金持仓权重/估值标的

**路径参数**：
- `code`：基金代码

**请求参数**：
- 无

**响应示例**：
```json
{
  "fund_code": "162411",
  "basket": [
    {"asset_code": "XOP", "weight": 0.85, "name": "XOP ETF"},
    {"asset_code": "USD", "weight": 0.15, "name": "美元现金"}
  ]
}
```

---

### 2.3 交易接口

#### GET /api/trading/positions

**功能**：获取通达信真实账户持仓

**请求参数**：无

**响应示例**：
```json
{
  "positions": [
    {
      "fund_code": "162411",
      "fund_name": "华宝油气",
      "volume": 10000,
      "avg_price": 1.200,
      "market_value": 12340.0,
      "available_volume": 8000
    }
  ],
  "total_market_value": 50000.0,
  "available_cash": 30000.0
}
```

---

#### POST /api/trading/order

**功能**：执行下单操作

**请求体**：
```json
{
  "action": "BUY",
  "code": "162411",
  "volume": 10000,
  "price": 1.234
}
```

**参数说明**：
- `action`：BUY 或 SELL
- `code`：基金代码
- `volume`：数量（份）
- `price`：限价

**响应示例**：
```json
{
  "success": true,
  "order_id": "123456",
  "message": "下单成功"
}
```

---

### 2.4 自动交易接口

#### GET /api/auto_trade/status

**功能**：获取自动交易引擎状态

**请求参数**：无

**响应示例**：
```json
{
  "running": true,
  "thread_alive": true,
  "last_run": "2026-06-08 10:30:00"
}
```

---

#### POST /api/auto_trade/toggle

**功能**：启动/停止自动交易引擎

**请求体**：
```json
{
  "action": "start"
}
```

**参数**：
- `action`：start 或 stop

**响应示例**：
```json
{
  "success": true,
  "message": "引擎已启动"
}
```

---

#### GET /api/auto_trade/logs

**功能**：获取引擎日志（前端每 3 秒轮询）

**请求参数**：
- `limit`：返回日志条数（默认 100）

**响应示例**：
```json
{
  "logs": [
    {
      "time": "2026-06-08 10:30:05",
      "level": "INFO",
      "message": "[10:30:05] 监测到 162411 折价 1.5% -> 满足L1规则，发送买单"
    }
  ]
}
```

---

#### GET /api/auto_trade/rules

**功能**：获取所有规则

**请求参数**：无

**响应示例**：
```json
[
  {
    "id": 1,
    "fund_code": "162411",
    "fund_name": "华宝油气",
    "direction": "BUY",
    "trigger_type": "PREMIUM",
    "threshold": -1.5,
    "order_vol": 10000,
    "max_pos_wan": 10,
    "is_active": true,
    "created_at": "2026-06-08"
  }
]
```

---

#### POST /api/auto_trade/rules

**功能**：新增规则

**请求体**：
```json
{
  "fund_code": "162411",
  "fund_name": "华宝油气",
  "direction": "BUY",
  "trigger_type": "PREMIUM",
  "threshold": -1.5,
  "order_vol": 10000,
  "max_pos_wan": 10,
  "capital_limit_wan": 5,
  "is_active": true
}
```

**响应示例**：
```json
{
  "success": true,
  "id": 2,
  "message": "规则创建成功"
}
```

---

#### PUT /api/auto_trade/rules/{id}

**功能**：更新规则

**路径参数**：
- `id`：规则 ID

**请求体**：同新增规则

**响应示例**：
```json
{
  "success": true,
  "message": "规则更新成功"
}
```

---

#### DELETE /api/auto_trade/rules/{id}

**功能**：删除规则

**路径参数**：
- `id`：规则 ID

**响应示例**：
```json
{
  "success": true,
  "message": "规则删除成功"
}
```

---

### 2.5 配置接口

#### GET /api/config/data_sources

**功能**：获取当前各数据源状态与优先级

**请求参数**：无

**响应示例**：
```json
[
  {
    "module": "realtime_market",
    "source_name": "tdx",
    "priority": 1,
    "is_active": 1,
    "config_json": "{\"port\": 7709}"
  },
  {
    "module": "realtime_market",
    "source_name": "guojin",
    "priority": 2,
    "is_active": 1,
    "config_json": "{}"
  }
]
```

---

#### POST /api/config/data_sources/priority

**功能**：批量更新数据源优先级

**请求体**：
```json
[
  {
    "module": "realtime_market",
    "source_name": "tdx",
    "priority": 1,
    "is_active": 1
  },
  {
    "module": "realtime_market",
    "source_name": "guojin",
    "priority": 2,
    "is_active": 1
  }
]
```

**响应示例**：
```json
{
  "success": true,
  "message": "配置已更新，引擎正在重启"
}
```

---

#### GET /api/config/data_sources/test/{source_name}

**功能**：测试数据源连接

**路径参数**：
- `source_name`：数据源名称（tdx/guojin/galaxy/sina）

**响应示例**：
```json
{
  "success": true,
  "message": "通达信连接成功"
}
```

---

### 2.6 数据管理接口

#### POST /api/data/sync/lof011

**功能**：手动触发 LOF011 历史数据同步

**请求参数**：无

**响应示例**：
```json
{
  "success": true,
  "logs": [
    "2026-06-08 10:30:00 - 开始同步历史数据...",
    "2026-06-08 10:30:05 - 同步完成，更新 50 只基金"
  ]
}
```

---

#### POST /api/data/sync/lof012

**功能**：手动触发 LOF012 静态估值计算

**请求参数**：无

**响应示例**：
```json
{
  "success": true,
  "logs": [
    "2026-06-08 10:30:00 - 开始计算静态估值...",
    "2026-06-08 10:30:10 - 计算完成，更新 50 只基金"
  ]
}
```

---

#### GET /api/data/health

**功能**：获取系统健康状态

**请求参数**：无

**响应示例**：
```json
{
  "database": {
    "status": "OK",
    "size_mb": 45.2,
    "record_count": 37680
  },
  "sampler": {
    "status": "RUNNING",
    "last_sample": "2026-06-08 10:30:00"
  },
  "auto_trade": {
    "status": "STOPPED",
    "thread_alive": false
  },
  "milestones": [
    {"time": "09:20", "event": "今日官方人民币中间价已更新", "status": "DONE"},
    {"time": "15:05", "event": "盘后收盘价同步完成", "status": "PENDING"}
  ]
}
```

---

## 三、错误码说明

| 错误码 | 说明 |
|--------|------|
| 200 | 成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在 |
| 500 | 服务器内部错误 |

**错误响应格式**：
```json
{
  "detail": "错误信息描述"
}
```

---

## 四、使用示例

### 4.1 使用 curl 调用

```bash
# 获取看板数据
curl http://localhost:8000/api/dashboard

# 获取分时数据
curl "http://localhost:8000/api/fund/162411/intraday?date=2026-06-08"

# 启动引擎
curl -X POST http://localhost:8000/api/auto_trade/toggle \
  -H "Content-Type: application/json" \
  -d '{"action": "start"}'

# 新增规则
curl -X POST http://localhost:8000/api/auto_trade/rules \
  -H "Content-Type: application/json" \
  -d '{
    "fund_code": "162411",
    "fund_name": "华宝油气",
    "direction": "BUY",
    "trigger_type": "PREMIUM",
    "threshold": -1.5,
    "order_vol": 10000,
    "is_active": true
  }'
```

### 4.2 使用 Axios 调用（前端）

```javascript
import api from '@/api'

// 获取看板数据
const data = await api.get('/api/dashboard')

// 获取分时数据
const intraday = await api.get('/api/fund/162411/intraday', {
  params: { date: '2026-06-08' }
})

// 启动引擎
await api.post('/api/auto_trade/toggle', { action: 'start' })
```

---

*本文档描述程序3（ArbDashboard）的 REST API 接口，最后更新：2026-06-08*
