"""
Pydantic 请求/响应 Schema — 统一校验所有 POST 端点
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── 基金配置 ──

class FundConfigUpsert(BaseModel):
    code: str
    name: str = ""
    category: str = ""
    trade_etf: str = ""
    trade_future: str = ""
    holdings: dict = Field(default_factory=lambda: {"equity_ratio": 95.0})
    valuation_portfolio: list = Field(default_factory=list)
    redemption_fee_rate: float = 0.5
    commission_rate: float = 0


class FundConfigDelete(BaseModel):
    code: str


# ── 交易 ──

class OrderRequest(BaseModel):
    action: str
    code: str
    volume: int
    price: float
    broker: str = "tdx"
    account_id: Optional[str] = None


# ── 自动交易 ──

class AutoTradeRule(BaseModel):
    name: str = ""
    target: str = ""
    type: str = "code"
    indicator: str = "discount"
    threshold: float = 0.7
    action: str = "BUY"
    max_pos_wan: float = 50.0
    order_vol: int = 2000
    capital_limit_wan: float = 10.0
    enabled: Optional[bool] = None


class AutoTradeToggle(BaseModel):
    action: str  # "start" | "stop"


class AutoTradeBatchUpdate(BaseModel):
    rules: List[dict]


# ── 实盘对账 ──

class TradeAdd(BaseModel):
    fund_code: str
    fund_name: str = ""
    price: float = 0.0
    volume: int = 0
    account_suffix: str = ""
    trade_ts: Optional[int] = None
    trade_date: Optional[str] = None
    remind_ts: Optional[int] = None
    remind_date: Optional[str] = None
    hedge_symbol: str = ""
    hedge_price: float = 0.0
    hedge_vol: int = 0
    action: str = "BUY"
    fees: float = 0.0
    note: str = ""


class FeeUpsert(BaseModel):
    fund_code: str = ""
    broker_name: str = ""
    redemption_fee_rate: float = 0.5


# ── 数据源配置 ──

class DataSourceUpdate(BaseModel):
    module: str = "realtime_market"
    source_name: str
    priority: Optional[int] = None
    is_active: Optional[int] = None
    config: Optional[dict] = None


class DataSourcePriorityUpdate(BaseModel):
    module: str = "realtime_market"
    priorities: List[Dict[str, Any]]


# ── 账号管理 ──

class AccountSave(BaseModel):
    accounts: Dict[str, str]
