# arbcore - 核心函数库

## 概述

arbcore 是 LOF 基金套利监控系统的核心函数库，提供了数据获取、处理和存储等基础功能，为上层应用提供服务。

## 目录结构

```
arbcore/
├── fetchers/        # 数据获取模块
│   ├── data_fetcher.py         # 统一数据获取接口
│   ├── woody_api_service.py    # 统一Woody API服务 (提取解析与备份)
│   ├── woody_telegram_client.py# Woody Telegram接口客户端
│   ├── ib_reader.py            # IB盈透实时行情与交易基座
│   └── woody_web_crawler.py    # 网页爬虫
├── database/        # 数据库模块
│   ├── db_manager.py           # 数据库管理类
│   └── import_basic_csv.py     # CSV 数据导入工具
```

## 核心模块

### 1. 数据获取模块 (fetchers)

#### data_fetcher.py

**功能**：
- 统一的数据获取接口
- 从多个数据源获取数据
- 支持汇率、LOF 基金、指数、期货和美股数据
- 实现多源数据融合和故障转移

**主要方法**：
- `get_exchange_rate()`：获取汇率数据
- `get_lof_data()`：获取 LOF 基金数据
- `get_index_data()`：获取指数数据
- `get_futures_data()`：获取期货数据
- `get_us_stock_data()`：获取美股数据

#### woody_web_crawler.py

**功能**：
- 网页爬虫，作为 API 数据的备用来源
- 从 Woody 网页获取数据
- 解析 HTML 页面提取数据

**主要方法**：
- `crawl_woody_data()`：爬取 Woody 网页数据
- `parse_woody_html()`：解析 Woody 网页 HTML

### 2. 数据库模块 (database)

#### db_manager.py

**功能**：
- 数据库管理类
- 提供数据库连接和操作
- 实现表结构创建和数据操作
- 支持线程安全的数据库访问

**主要方法**：
- `initialize_database()`：初始化数据库
- `get_exchange_rate()`：获取汇率数据
- `get_futures_settlement()`：获取期货结算价
- `get_lof_data()`：获取 LOF 基金数据
- `insert_exchange_rate()`：插入汇率数据
- `insert_futures_settlement()`：插入期货结算价
- `insert_lof_data()`：插入 LOF 基金数据

#### import_basic_csv.py

**功能**：
- 从 CSV 文件导入基础数据到数据库
- 支持数据清洗和转换
- 提供批量导入功能

**主要方法**：
- `import_csv_to_database()`：导入 CSV 数据到数据库
- `clean_data()`：清洗数据
- `transform_data()`：转换数据

### 3. 工具函数

**功能**：
- 日期处理工具：处理交易日、假期等日期相关逻辑
- 数据处理工具：数据清洗、转换等功能
- 配置管理工具：读取和管理配置文件

**实现方式**：
这些工具函数目前直接集成在各个模块中，没有单独的utils目录。

## 使用指南

### 1. 数据获取

```python
from arbcore.fetchers.data_fetcher import data_fetcher

# 获取汇率数据
rate = data_fetcher.get_exchange_rate('2023-07-01', 'CNY_USD')

# 获取 LOF 基金数据
data = data_fetcher.get_lof_data('501018')

# 获取指数数据
index_data = data_fetcher.get_index_data('000001.SH')

# 获取期货数据
futures_data = data_fetcher.get_futures_data('GC')

# 获取美股数据
us_stock_data = data_fetcher.get_us_stock_data('AAPL')
```

### 2. 数据库操作

```python
from arbcore.database.db_manager import DatabaseManager

# 初始化数据库管理器
db = DatabaseManager()

# 插入汇率数据
db.insert_exchange_rate('2023-07-01', 'CNY_USD', 6.5, 'SAFE')

# 插入期货结算价
db.insert_futures_settlement('2023-07-01', 'GC', 4500.0, 'CME')

# 插入 LOF 基金数据
db.insert_lof_data('2023-07-01', '501018', 1.5, 1.55, 1.52, 1.53, 1.54, 3.33, 1.5, 1.0, 'API')

# 查询数据
rate = db.get_exchange_rate('2023-07-01', 'CNY_USD')
futures = db.get_futures_settlement('2023-07-01', 'GC')
lof_data = db.get_lof_data('501018')
```

### 3. 工具函数使用

工具函数目前直接集成在各个模块中，例如：

- 日期处理函数集成在 `data_fetcher.py` 中
- 配置管理函数集成在各个需要的模块中
- 数据处理函数集成在各个需要的模块中

具体使用方式请参考各个模块的文档。

## 数据流程

1. **数据获取**：通过 data_fetcher 从多个数据源获取数据
2. **数据处理**：对获取的数据进行清洗和转换
3. **数据存储**：将处理后的数据存储到数据库
4. **数据查询**：从数据库查询数据供上层应用使用
5. **数据更新**：定期更新数据，确保数据的及时性

## 错误处理

- **数据源失败**：当主数据源失败时，自动切换到备用数据源
- **数据格式错误**：对获取的数据进行格式验证，处理格式错误
- **网络错误**：处理网络连接失败等错误
- **数据库错误**：处理数据库操作错误

## 性能优化

- **数据缓存**：对频繁访问的数据进行缓存
- **批量操作**：对数据库操作进行批量处理
- **并行处理**：对数据获取和处理进行并行处理
- **连接池**：使用连接池管理数据库连接

## 扩展指南

### 添加新的数据源

1. 在 `data_fetcher.py` 中添加新的数据源获取方法
2. 实现数据源的错误处理和故障转移
3. 更新数据融合逻辑

### 添加新的数据库表

1. 在 `db_manager.py` 中添加表结构创建代码
2. 添加相应的数据插入和查询方法
3. 更新数据库初始化逻辑

### 添加新的工具函数

1. 在相应的模块中添加新的工具函数
2. 确保函数的可重用性和通用性
3. 在模块的 `__init__.py` 文件中导出新的工具函数（如果需要）

## 维护与支持

- **日志**：数据获取和处理过程会记录详细的日志
- **监控**：系统会监控数据获取和处理的状态
- **告警**：当数据获取或处理失败时，系统会发出告警

## 注意事项

- **API 访问限制**：使用 API 时请注意遵守 API 提供商的访问限制
- **数据质量**：虽然系统会进行数据验证，但仍建议对重要数据进行人工验证
- **性能考虑**：处理大量数据时，请注意系统性能
- **安全性**：请妥善保管 API 密钥等敏感信息

arbcore 核心库为 LOF 基金套利监控系统提供了强大的基础功能，通过合理使用这些功能，可以构建更加可靠和高效的套利策略。