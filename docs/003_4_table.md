
## 十、基金符号路由与估值核对全量表（= 基金大盘点）

> 本节是「数据管理 → 核心基金配置 → **基金大盘点**」按钮所渲染的全量配置一览表的权威说明。
> 该表由程序**直接读取  的  列表**逐项生成（一张表对应一个 YAML 文件），
> 后端  /  与前端大盘点用的是同一份配置，故表内每一格都能被程序识别并用于静态/动态估值计算。
> 离线快照见 。

### 10.1 列定义与方法论

| 列 | 含义 |
|----|------|
| LOF历史/净值源 | 基金份额历史价/净值来源 = 东财/新浪 |
| 估值办法 | basket=篮子矩阵 / etf=单一ETF / index=指数（程序按  识别） |
| 估值对象 | 估值所用的底层标的；161125/161130 分两段：静态读 （.INX/.NDX），实时读 （SPY/QQQ） |
| 估值对象来源 | WOODY（^区域锚点收盘价）/ Yahoo(VPS)（NKY收盘）/ IB·FUTU（美股ETF期货）/ sina（NK期货、AG0新浪nf_AG0）/ tencent / TDX（不含 guojin·银河，QMT仅用于对冲突） |
| 对冲标的 | = （QDII日本=NK期货；白银=AG0） |
| 对冲源 | IB·FUTU（NK=sina；AG0=待定） |

### 10.2 类别配色（与前端主看板一致）

| 类别 | 颜色 |
|------|------|
| 黄金原油 | #d97706 琥珀 |
| QDII欧美 | #0891b2 青蓝 |
| QDII日本 | #db2777 粉 |
| QDII亚洲 | #7c3aed 紫 |
| 国内LOF | #2563eb 蓝 |
| 白银 | #059669 绿 |
| 现金管理 | #64748b 灰 |

### 10.3 特殊规则（易错点）

- **161125 / 161130**：静态估值用指数（.INX/.NDX→SINA），实时估值用 ETF（SPY/QQQ→IB·FUTU）。估值办法记为 。
- **QDII日本**：静态=指数公式（N225，收盘来自 VPS Yahoo）；实时=NK 期货标准公式（新浪 hf_NK 实时价）。
- **白银（AG0）**：估值对象=AG0，来源=新浪 nf_AG0（SINA）；对冲源=待定（白银对冲尚未实现）。
- **区域锚点（^GLD-EU 等）**：仅收盘价来自 Woody API，无实时价；消费端统一  归一。
- **来源同值折叠**：同一基金所有估值对象来源相同（如多篮子纯 IB/FUTU）时，表格折叠为单个标签；来源混搭（如 GLD=IB/FUTU + ^GLD-EU=WOODY）则并排保留以保映射。

### 10.4 全量核对表（91 只）

| 基金代码 | 名称 | 类别 | LOF历史/净值源 | 估值办法 | 估值对象 | 估值对象来源 | 对冲标的 | 对冲源 |
|---------|------|------|--------------|---------|---------|-----------|---------|-------|
| 160216 | 国泰大宗商品 | 黄金原油 | 东财/新浪 | basket | GLD / SLV / USO | IB/FUTU | GLD | IB/FUTU |
| 160719 | 嘉实黄金 | 黄金原油 | 东财/新浪 | basket | GLD / ^GLD-EU | IB/FUTU / WOODY | GLD | IB/FUTU |
| 160723 | 嘉实原油 | 黄金原油 | 东财/新浪 | basket | USO / ^USO-EU | IB/FUTU / WOODY | USO | IB/FUTU |
| 161116 | 易方达黄金 | 黄金原油 | 东财/新浪 | basket | GLD / ^GLD-EU | IB/FUTU / WOODY | GLD | IB/FUTU |
| 161129 | 易方达原油 | 黄金原油 | 东财/新浪 | basket | USO / ^USO-EU / ^USO-HK | IB/FUTU / WOODY / WOODY | USO | IB/FUTU |
| 161815 | 银华抗通胀 | 黄金原油 | 东财/新浪 | basket | GLD / ^USO-EU / USO | IB/FUTU / WOODY / IB/FUTU | GLD | IB/FUTU |
| 163208 | 诺安油气能源 | 黄金原油 | 东财/新浪 | basket | XLE / USO | IB/FUTU | XLE | IB/FUTU |
| 164701 | 汇添富贵金属 | 黄金原油 | 东财/新浪 | basket | GLD | IB/FUTU | GLD | IB/FUTU |
| 165513 | 中信保诚 | 黄金原油 | 东财/新浪 | basket | GLD / ^GLD-EU / ^GLD-JP | IB/FUTU / WOODY / WOODY | GLD | IB/FUTU |
| 501018 | 南方原油 | 黄金原油 | 东财/新浪 | basket | USO / ^USO-EU / ^USO-JP | IB/FUTU / WOODY / WOODY | USO | IB/FUTU |
| 159502 | 嘉实标普生物 | QDII欧美 | 东财/新浪 | etf | XBI | IB/FUTU | XBI | IB/FUTU |
| 159518 | 嘉实标普石油 | QDII欧美 | 东财/新浪 | etf | XOP | IB/FUTU | XOP | IB/FUTU |
| 159561 | 德国ETF嘉实 | QDII欧美 | 东财/新浪 | etf | DAX | IB/FUTU | DAX | IB/FUTU |
| 160644 | 港美互联网 | QDII欧美 | 东财/新浪 | basket | MU / SNDK / 01888 / 00992 / 00148 / 03690 / 09988 / NVDA / TSM / AMD | IB/FUTU |  | - |
| 161125 | 易方达标普500 | QDII欧美 | 东财/新浪 | index(静态)/etf(实时) | .INX(静态)/SPY(实时) | SINA(静态) / IB/FUTU(实时) | SPY | IB/FUTU |
| 161126 | 标普医疗保健 | QDII欧美 | 东财/新浪 | etf | RSPH | IB/FUTU | RSPH | IB/FUTU |
| 161127 | 标普生物科技 | QDII欧美 | 东财/新浪 | etf | XBI | IB/FUTU | XBI | IB/FUTU |
| 161130 | 易方达纳100 | QDII欧美 | 东财/新浪 | index(静态)/etf(实时) | .NDX(静态)/QQQ(实时) | SINA(静态) / IB/FUTU(实时) | QQQ | IB/FUTU |
| 162411 | 华宝油气 | QDII欧美 | 东财/新浪 | etf | XOP | IB/FUTU | XOP | IB/FUTU |
| 162415 | 美国消费 | QDII欧美 | 东财/新浪 | etf | XLY | IB/FUTU | XLY | IB/FUTU |
| 164824 | 交银印度 | QDII欧美 | 东财/新浪 | basket | INDA / ^INDA-EU / ^INDA-JP / ^INDA-HK | IB/FUTU / WOODY / WOODY / WOODY | INDA | IB/FUTU |
| 164906 | 交银中证海外 | QDII欧美 | 东财/新浪 | etf | KWEB | IB/FUTU | KWEB | IB/FUTU |
| 501225 | 顺丰半导体芯片 | QDII欧美 | 东财/新浪 | basket | SOXX / SZ159560 | IB/FUTU / TDX | SOXX | IB/FUTU |
| 501300 | 海富通 美元债 | QDII欧美 | 东财/新浪 | etf | AGG | IB/FUTU |  | - |
| 501312 | 海外科技 | QDII欧美 | 东财/新浪 | basket | ARKK / ARKG / ARKQ / AIQ / BOTZ / ARKX / XLK / SMH / SOXX / QQQ | IB/FUTU |  | - |
| 513350 | 富国标普石油 | QDII欧美 | 东财/新浪 | etf | XOP | IB/FUTU | XOP | IB/FUTU |
| 159866 | 华安日经225ETF | QDII日本 | 东财/新浪 | index | NKY | Yahoo(VPS) | NK | sina |
| 513000 | 易方达日经225ETF | QDII日本 | 东财/新浪 | index | NKY | Yahoo(VPS) | NK | sina |
| 513520 | 工银日经225ETF | QDII日本 | 东财/新浪 | index | NKY | Yahoo(VPS) | NK | sina |
| 513880 | 华安日经225ETF | QDII日本 | 东财/新浪 | index | NKY | Yahoo(VPS) | NK | sina |
| 160322 | 港股精选 | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 160717 | H股LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 160924 | 恒生指数LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 161124 | 港股小盘LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 161831 | 恒生国企LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 164705 | 恒生LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501025 | 香港银行LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501301 | 香港大盘LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501302 | 恒生指数基金 | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501303 | 恒生中型股 | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501305 | 港股高股息 | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501306 | 港股高股息LOFC | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501307 | 银华高股息LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 501311 | 新经济港股通LOF | QDII亚洲 | 东财/新浪 | equity_asia |  |  |  | - |
| 160225 | 新能源汽车LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160615 | 鹏华沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160632 | 酒LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160639 | 高铁LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160643 | 空天军工LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160706 | 嘉实沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 160925 | 沪深300LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161025 | 互联网LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161029 | 银行龙头LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161031 | 工业4.0LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161032 | 煤炭龙头LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161118 | 中小企业100LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161217 | 国投资源LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161227 | 国投深证100LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161604 | 融通深证100 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161631 | 人工智能LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161715 | 大宗商品LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161716 | 招商双债LOF | 国内LOF | 东财/新浪 | na |  |  |  | - |
| 161725 | 白酒基金LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161726 | 生物医药LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161811 | 银华沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 161812 | 深证100LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 162412 | 医疗基金LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 162509 | 国联安沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 162711 | 广发沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 163109 | 申万深成LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 163113 | 申万菱信沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 163407 | 兴全沪深300LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 165511 | 中信保诚500LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 165522 | TMTLOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 165523 | 信诚沪深300 | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 167301 | 保险主题LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 168204 | 煤炭LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501007 | 互联网医疗LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501043 | 沪深300LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501048 | 证券公司LOFC | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501050 | 50AHLOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501057 | 新能源车LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501058 | 新能源车LOFC | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501089 | 消费红利增强LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 501227 | 泓德红利优选LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 502000 | 500增强LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 502056 | 医疗基金LOF | 国内LOF | 东财/新浪 | lof_domestic |  |  |  | - |
| 511360 | 海富通短融 | 现金管理 | 东财/新浪 | na |  |  |  | - |
| 511520 | 富国政金 | 现金管理 | 东财/新浪 | na |  |  |  | - |
| 511880 | 银华日利 | 现金管理 | 东财/新浪 | na |  |  |  | - |
| 161226 | 国瑞白银期货 | 白银 | 东财/新浪 | futures | AG0 | 新浪(nf_AG0) | AG0 | 待定 |
