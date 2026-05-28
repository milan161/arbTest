-- 基金每日因子表 (专门存储各个LOF基金的私有属性和Woody API常量)
CREATE TABLE IF NOT EXISTS fund_daily_factors (
    date TEXT NOT NULL,               -- 交易日期 (格式: YYYY-MM-DD)
    fund_code TEXT NOT NULL,          -- 基金代码 (如 '162411')
    calibration REAL,                 -- 校准值 (Calibration = (E_base × F_base) / V_base)
    hedge REAL,                       -- 对冲值 (Hedge = Calibration / position)
    position REAL,                    -- 仓位比例 (如 0.945 表示 94.5%)
    nav REAL,                         -- 基金T-1日净值 (可选，用于快速核对公式)
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- 数据最后更新时间
    PRIMARY KEY (date, fund_code)     -- 联合主键：确保一天一个基金只有一条最新记录
);

-- 建立联合索引：前端页面需要极速查询某只基金最新一天的 Hedge 和 Position
CREATE INDEX IF NOT EXISTS idx_fund_code_date 
ON fund_daily_factors (fund_code, date DESC);
