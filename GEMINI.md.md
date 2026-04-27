**arbTest 基金套利监控系统** - AI 上下文备忘录
---
# 一  概述

我正在编写两个基金套利程序发，采用**“大一统底层基座 (arbcore + SQLite WAL 模式)”** ：
## 1. 公用数据库，"D:\Study\arbTest\database"，
### ✅ 完成核心重构 (纯 SQLite 架构与数据链路健壮性)
在近期的迭代中，彻底抛弃了脆弱的 CSV 文件存储，全面拥抱 SQLite 关系型数据库，并对数据大一统采集 (011)、静态估值计算 (012) 和报表生成 (03) 进行了深度修复与重构。

###  核心数据库表结构字典 (SQLite: etf_rotation.db)

当前系统的数据架构已完全从 CSV 文件驱动升级为 SQLite 关系型数据库驱动。所有盘中 tick 数据均不落库，数据库仅作为**“单点事实来源(Single Source of Truth, SSOT)”**记录历史日线级常数与最终成绩单。

| 表名 | 职能定义 | 核心字段 |
| :--- | :--- | :--- |
| **`fund_data`** | **A股基金成绩单(含LOF/ETF)** | `date`, `fund_code`, `price` (收盘价), `nav` (官方净值), `premium` (最终折溢价率) |
| **`exchange_rate`** | **汇率锚点** | `date`, `usd_cny_mid` (外汇局人民币中间价) |
| **`usa_etf_daily_prices`** | **海外底层美股ETF价格** | `date`, `symbol`, `price`。(注：此表是所有底层资产的统一定价源，标准ETF由新浪爬虫更新，带 `^` 前缀的区域变种由 Woody 网页爬虫更新) |
| **`futures_daily`** | **期货历史大一统表** | `date`, `symbol` (如GC/CL), `settle_price` (新浪结算价), `calibration` (Woody 物理校准兑换比例) |
| **`fund_daily_factors`** | **Woody运算系数箱** | `date`, `fund_code`, `calibration`, `hedge`, `position` (仓位)。此表**绝不包含**净值，专供实时估值计算提取系数。 |
| **`fund_basket_weights`**| **底层篮子权重** | `date`, `fund_code`, `underlying_symbol`, `weight`。专门解决大宗商品（黄金/原油）底层挂钩多个区域变种ETF的 1对N 扁平化存储问题。 |
| **`access_sync_status`** | **全局访问控制** | `sync_date`, `access_source`, `sync_time`。防止新浪/东财/外汇局/Woody的接口被频繁调用导致封IP。 |
| **`raw_api_data`** | **API数据湖** | `date`, `source`, `raw_content`。原汁原味存储 Woody API 返回的原始 JSON 字符串，供随时回溯。 |
| **`system_health`** | **系统健康日志** | `component`, `status`, `message`, `timestamp`。记录各类后台服务、爬虫节点的心跳报错。 |
| **`sqlite_sequence`** | **(内部系统表)** | SQLite 自带的自增主键指针表，严禁修改或删除。 |


### ✅ 数据库与概念的“正名”大重构
   - 彻底将 A股公募产品统称为 `fund`，美股底层资产统称为 `usa_etf`，历史对账表统归为 `fund_history_xxx`，消除了“ETF”一词在系统中的歧义。
   - 剥离了混入 LOFarb 的三个 A股 ETF（159502/159518/513350），将其纯粹交由 ETFRotate 管理，精简了 LOF03 前端无用面板。


## 2.  通用的函数抽取做成库，在"D:\Study\arbTest\arbcore" 

**arbcore 目录结构**：
```
arbcore/
├── __init__.py
├── calculators/         # 估值计算器
│   ├── __init__.py
│   ├── dynamic_valuation.py  # 动态估值
│   └── static_valuation.py   # 静态估值
├── database/            # 数据库管理
│   ├── __init__.py
│   ├── database_manager.py  # 数据库管理器
│   ├── db_manager.py        # 数据库管理（主要）
│   ├── import_basic_csv.py   # CSV 导入
│   └── schema_fund_factors.sql  # 数据库 schema
└── fetchers/            # 数据获取模块
    ├── __init__.py
    ├── data_fetcher.py        # 基础数据获取
    ├── ib_reader.py           # IB 数据读取
    ├── woody_api_service.py   # Woody API 服务
    ├── woody_telegram_client.py # Telegram 客户端
    └── woody_web_crawler.py   # Woody 网页爬虫
```
### ✅ 阶段性里程碑：估值双引擎下沉 ArbCore，全面跨入后台智驾时代，准备开启轮动套利
**当前架构状态**：底层数据抓取（011）具有极高健壮性与防刷机制。静态推演与动态盘中推演的核心算法已全部剥离为独立微服务模块，寄宿在 `arbcore` 基座中。

## 3. Woody API接口
本系统的数据源很多核心数据来自于woody网站，最简单的是使用woody API接口，读取的数据格式是"D:\Study\arbTest\LOFarb\data\woodyAPI\Data_woodyAPI_20260421_1605.json"。 这个接口函数在 "D:\Study\arbTest\LOFarb\telegram.py" ，只接受基金代码的输入，如sz160719的格式,不接受 SPY等美股ETF的输入。 根据输入基金代码的不同，返回三种形态：

1. 黄金 原油类基金，如 160719 161116 164701 165513 161815 160216 等黄金类基金 + 501018 160723 161129 等原油类基金，返回的是一个数据，里面有对应的GLD或者USO 以及它们的区域变种即后缀 -EU（代表欧洲），-JP（代表日本），-HK（代表香港）的收盘价格，和权重ratio。 对于计算估值来说，这些数据很重要；
2. 纯ETF 类基金，如162411 161127 162415 等，跟踪美股ETF 如 XOP  XBI XLY 等，返回数据比较简单，包括calibration 校准值， 和hedge对冲值，
3. 指数类基金，如161125 161130，跟踪标普指数和纳斯达克100 指数，返回数据很特别，除了返回常规的数据之外，还自动额外返回对应的ETF，如SPY QQQ的数据。这一点在设计数据库的时候要考虑周全；

API返回的都是历史数据，也就是程序里定义的“基准日”数据,每天原则上调用API一次就够了。所以程序必须限制，不能每天多次访问API，即：程序当天第一次访问API之后，要做一个标记，程序再次运行，就不能再去调用API接口了，只能去访问数据库里面刚刚保存的当天第一次访问API接口取回来的数据。API不返回实时变化的人民币在岸价。

程序的所有数据，最基础的“锚点”是日期，是这个日期的人民币中间价（每个交易日早上9:15 官方发布，这一天就不再变动了）

## 4. 估值算法
日期的定义:当前交易日、上一个交易日（通常就是估值日）、估值日、基准日。基准日的特点是基金净值已经发布，所以这一天的数据全部收集完毕了，可以作为基准来计算“估值日”的基金估值（静态官方估值、实时估值）。woody API 返回的就是基准日的数据。

1. 计算静态估值的算法"D:\Study\arbTest\docs\009_估值_校准值、对冲值.md"
2. 计算动态估值的算法几乎一模一样，见"D:\Study\arbTest\docs\010_实时估值的源码真相与校准值计算.md"。
3. 利用woodyAPI返回的基准日数据，尤其是calibration，可简化地计算净值。"D:\Study\arbTest\公众号\15_已发表_揭秘Woody实时估值的数学魔法.md"

### ✅ 静态估值引擎 (Static Valuation) 独立封装
   - 新建 `arbcore/calculators/static_valuation.py`，接管了原来庞大的 pandas 矩阵推演计算逻辑。

### ✅ 极速动态估值引擎 (Dynamic Valuation) 诞生
   - 三种实时净值，ETF、期货校准、纯期货； 
   - 新建 `arbcore/calculators/dynamic_valuation.py`，专为后台无人值守环境打造。
   - **引入内存级缓存 (Memory Cache)**：在盘中首次调用时查询 SQLite 获取 `T-1` 完美基座数据并驻留内存。后续面对每秒数次的 Tick 级实时汇率、实时 ETF/期货跳动，实现 **O(1) 微秒级极速推演**，彻底告别 IO 瓶颈

### 🛑 估值引擎的“魔法安全锁” (多资产变种的矩阵降级)
在对接 Woody API 的极速 O(1) 魔法引擎时，确立了一条不可逾越的数学铁律：**对于底层包含多个区域变种 ETF（如黄金 `GLD + ^GLD-EU`，原油 `USO + ^USO-JP` 等）的基金，绝不能简单粗暴地用单一主资产（如 `GLD`）的实时价格去硬套魔法公式！**
*   **误区**：因为 API 返回的 `Hedge` 涵盖的是一篮子组合的整体折算，若把主资产绝对价格硬塞给所有区域变种，会导致变种资产的基准价格被错误覆盖，其涨跌幅会被严重扭曲，从而产生离谱的估值误差。
*   **三道安全锁**：我们在前端 JS 沙盘 (`LOF03`)、后端静态计算 (`static_valuation.py`) 和动态盘中推演 (`dynamic_valuation.py`) 中均实施了严格的智能路由分流：
    1.  **极速魔法通道**：仅限底层**只包含 1 支纯净 ETF**（`len(portfolio) == 1`，如 162411/XOP, 161130/QQQ）的基金使用常量折叠代入，极度节省算力。
    2.  **矩阵兜底通道**：只要是多区域组合（黄金/原油），系统主动拒绝魔法捷径，**强制退回传统的 O(N) 矩阵兜底算法**（严格按照各个变种资产的 T/T-1 变化率及其权重平移加权）。由此彻底封死了估值失真的漏洞，使推演结果与理论 Excel 严丝合缝。

# 二 详细设计

LOF和ETF 基金的套利程序，区别在于LOF主要用于折价套，即LOFarb程序，ETF基金用于轮动套利， 即ETFrotate程序。

## 1. 第一个子系统 LOF折价套利系统
是一个半自动化监控跨境基金套利的程序，通过抓取美股ETF/期货的实时价格，人民币汇率、以及历史因子（对冲值、校准值），推演出基金的静态官方估值，进一步预估“实时估值”，指导实盘套利打单（已接入 银河QMT/通达信与 IB 盈透）。

"D:\Study\arbTest\LOFarb" LOFarb目录下的LOF基金折价套利（以后简称"折价套利"）程序

**LOFarb 目录结构**：
```
LOFarb/
├── data/        # 数据文件，早期版本使用CSV文件保存数据，现在已经废弃不再使用，改用数据库
├── docs/        # 说明文档
├── ibapi/       # IB API接口库
├── logs/        # 日志文件
├── my-ai/       # AI 相关文件
├── readers/     # 数据读取模块
│   ├── __init__.py
│   ├── config_manager.py
│   ├── data_fetcher.py
│   ├── database_manager.py
│   ├── dynamic_data_fetcher.py
│   ├── health_monitor.py
│   ├── http_client.py
│   ├── qmt_socket_client.py
│   ├── qmt_socket_server.py
│   ├── retry_manager.py
│   └── trade_manager.py
├── lof_config.yaml  # 配置文件
├── lof_monitor.html # 监控页面
├── LOF_start_lof_system.bat     # 系统启动脚本
├── LOF00_input_LOF_info.py      # 配置管理界面
├── LOF01_admin_launcher.py      # 管理面板
├── LOF011_daily_updater.py      # 每日数据更新
├── LOF012_calculate_valuation.py # 静态官方估值计算
├── LOF02_fetch_trade_data.py    # 实时数据服务
├── LOF03_generate_monitor_html.py # 生成监控页面
├── LOF031_config_manager.py     # 配置管理
├── LOF032_data_processor.py     # 数据处理
└── LOF033_html_generator.py     # HTML 生成器
```

"D:\Study\arbTest\ETFRotate"ETFrotate目录下的ETF轮动套利（以下简称“轮动”套利程序）

### ✅ A股实时行情引擎四级瀑布流
   - `LOF02` 实时行情读取架构升级为：**银河QMT (Socket) -> 通达信 (内存直连) -> 国金QMT (xtquant) -> 新浪API (轮询兜底)**。
   - 新增针对国金QMT的15秒断流心跳检测与自动降级新浪的灾备机制，确保无人值守时的坚若磐石。


## 2. 第二个子系统 ETF轮动套利系统
**ETFrotate 目录结构**：
```
ETFrotate/
├── core/            # 核心模块
│   ├── __init__.py
│   ├── _mytoken.py  # 令牌文件
│   ├── db_manager.py # 数据库管理
│   ├── ib_reader.py  # IB 数据读取
│   ├── woody_api_service.py # Woody API 服务
│   └── woody_telegram_client.py # Telegram 客户端
├── data/            # 数据文件
│   └── woodyAPI/    # Woody API 数据
├── logs/            # 日志文件
├── templates/       # 模板文件
├── etf_01_data_init.py          # 数据初始化
├── etf_02_woody_api.py          # Woody API 调用
├── etf_03_rotation_server.py    # 轮动服务器
├── ETFList.csv                  # ETF 列表
├── 启动ETF轮动.bat              # 启动脚本
└── 轮动readme.md                # 轮动说明文档
```

# 三 LOF折价套利系统 LOFarb
### ✅ 成功创建了 `LOF011_daily_updater.py`。
  - 把工作流简化为四步流水线：`拉取 API 数据湖` -> `提取每日私有因子入库` -> `抓取宏观市场数据` -> `抓取 LOF 收盘/净值`。
   - 全面拥抱 SQLite 持久化，所有脏活累活收口到 `arbcore.database.db_manager`。


### ✅ 重构 011 工业级智能防刷与缓存机制*
   - **宏观数据单次阻断**：对汇率、期货结算价、美股标准 ETF、Woody区域变种 ETF 全面启用 `access_sync_status` 数据库级校验，实现每日单次抓取，系统热启动提速至秒级。


### ✅ 基础数据的健壮性
如果调用 woodyAPI 失败呢？在 arbcore 中已经有了 woody_web_crawler.py。未来的健壮性逻辑必须是：
1. 基础数据(A股现价/净值/汇率)：很多数据如汇率、基金净值、基金收盘价，直接可以从外汇管理局、新浪、东财获得。data_fetcher.py 已经实现）。
2. 核心因子(API返回数据最核心的就是仓位、黄金和原油类基金的ETF权重ratio，对冲值/校准值)：首选 Woody API -> 如果超时或报错 -> 自动触发 WoodyWebCrawler 走无头浏览器/Requests 爬取woody网页解析 -> 如果再失败 -> 回退读取数据库昨天的旧数据兜底 ； 
3. 单次阻断：API 成功获取一次后，当天写入 access_sync_status 表，后续全部从数据库读，保护 IP。


# 四 [2024-04-25] ETF轮动套利系统 (ETFRotate) 重构完成

**目标与愿景**：
将原有的 `ETFRotate` 模块打造为不依赖外部复杂环境、代码极简、开箱即用且数据物理隔离的教学版工具压缩包，供量化培训班学生学习“估值与溢价套利推演”使用。

**核心变更记录**:
1. **脱离外部依赖 (Green Portable)**:
   - 将底层核心代码（`db_manager.py`, `woody_api_service.py`, `ib_reader.py`）专门剥离复制到 `ETFRotate/core/` 目录下，作为独立依赖包。
   - 移除了 01, 02, 03 主程序中所有跨目录的 `sys.path.append(BASE_DIR)` 引用，剪断“寻址脐带”，实现完整的文件内聚。

2. **数据库智能隔离 (Smart DB Isolation)**:
   - 优化 `DatabaseManager` 的路径寻址，加入智能环境探测：
     - 若探测到父级存在原系统数据库（老师开发环境），则自动挂载老数据库，保留历史数据。
     - 若未探测到父级路径（学生绿色版环境），则自动在 `ETFRotate` 目录下生成全新的 `database/arb_master.db` 沙盒。
   - 修复了建表时遗漏的 `nav REAL` 字段，并在获取因子的 SQL 中补充了 `nav` 的提取。

3. **业务逻辑极简化与解耦**:
   - **01 初始化程序**: 彻底废弃并移除了 `data_fetcher.py` 爬虫组件，不再爬取天天基金网和新浪历史收盘价。现仅保留读取 `ETFList.csv` 并同步数据库配置池的功能。
   - **02 Woody提取程序**: 升级为“数据源头核心”，在提取仓位和对冲因子的同时，直接复用 Woody 官方 API 返回的 `netvalue` 作为 T-1 基准净值入库。
   - **03 独立监控中心**: 
     - **UI 与推演升级**: 前端增加实时汇率雷达、最后更新时间牌，以及动态“套利计划本金”修改器（可实时联动建议股数的重算）。
     - **防崩溃防御**: 彻底重写前端 JS 的解析和加载逻辑，杜绝白屏和变量冲突；后端加入 `try-except` 包裹 IB 模块，确保在无盈透环境下的完美降级运行。
     - **安全隔离**: 剔除通达信 TDX 相关的物理下单代码，所有买卖按钮仅作弹窗提示，彻底杜绝学生误操作真金白银的风险。


# 五. 接下来的计划与待办事项 (TODO)
在 ETFRotate (轮动套利系统) 中引入并跑通静态估值 (`static_valuation.py`) 功能，实现双模态推演的完美闭环。

目前正在开始LOF04 sandbox的 编写，"D:\Study\arbTest\公众号\16_沙盘推演_折价套利模型与风险控制.md"