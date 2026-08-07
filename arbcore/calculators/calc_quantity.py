# -*- coding: utf-8 -*-
# calc_quantity.py - 对冲数量计算引擎
#
# [AI-2026-07-07] 创建：统一对冲数量计算，消除前端/后端多处重复逻辑。
# 参考 Woody PalmmicroAPI.CalcQuantity 设计思路，但独立于其 API。
#
# 核心思路：
#   hedge 值 = 每份 LOF 对应标的的 RMB 敞口（来自 fund_daily_factors.hedge）
#   通过 hedge × calibration × multiplier 换算为每手期货合约的对冲价值
#
# 三种对冲模式：
#   1. ETF对冲：   lof_shares = target_capital / lof_price
#                  etf_shares = lof_shares / hedge
#   2. 期货校准对冲： hedge_value_per_contract = hedge × calib × multiplier
#                    lof_shares = n_contracts × hedge_value / lof_price
#   3. 一篮子拆解：   按 weight / price 将总敞口分配到各标的下

import logging
from typing import Optional, List, Dict, Any

from arbcore.config.futures_multipliers import get_multiplier

logger = logging.getLogger(__name__)


class CalcQuantity:
    """
    对冲数量计算引擎。
    
    统一处理 ETF 对冲、期货对冲、一篮子拆解三种场景的计算。
    所有输入值均为 float，返回计算结果字典。
    """
    
    @staticmethod
    def etf_hedge(
        target_capital: float,
        lof_price: float,
        hedge: float,
        position: float = 1.0,
        portfolio: Optional[List[Dict[str, Any]]] = None,
        exchange_rate: float = 0.0,
        nav: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        ETF 对冲数量计算。
        
        公式：
            lof_qty = target_capital / lof_price
            etf_qty = lof_qty / hedge
        
        Args:
            target_capital: 目标投资金额（RMB）
            lof_price:      LOF 现价（RMB）
            hedge:          对冲因子（每份 LOF 对应的 ETF 敞口 RMB）
            position:       仓位比例（0.0~1.0，默认全仓）
            portfolio:      一篮子持仓列表 [{'symbol':str, 'weight':float}, ...]
            exchange_rate:   USD/CNY 汇率（篮子拆解时需要）
        
        Returns:
            {
                'lof_qty': int,          # LOF 股数（100 的倍数）
                'etf_qty': int,          # ETF 股数
                'exposure_rmb': float,   # 实际敞口（RMB）
                'exposure_usd': float,   # 实际敞口（USD）
                'breakdown': list,       # 篮子拆解明细（如有 portfolio）
                'mode': 'etf'
            }
            任何必要参数为 0 或 None 时返回 {'mode': 'etf', 'error': '...'}
        """
        if target_capital <= 0 or lof_price <= 0 or hedge <= 0:
            return {'mode': 'etf', 'error': '参数无效: target_capital/lof_price/hedge 必须 > 0'}
        
        # 计算 LOF 股数
        raw_lof_qty = target_capital / lof_price
        lof_qty = max(100, round(raw_lof_qty / 100) * 100)
        
        # 计算 ETF 股数
        etf_qty = max(1, round(lof_qty / hedge))
        
        # 实际 RMB 敞口：必须用净值 NAV（不是 LOF 市价）——见 docs/004-2 第九节已定位 bug
        # nav 提供时优先用净值；否则回退 lof_price（兼容旧调用 / 单 ETF 场景）
        _exposure_basis = nav if (nav is not None and nav > 0) else lof_price
        exposure_rmb = lof_qty * _exposure_basis * position
        exposure_usd = exposure_rmb / exchange_rate if exchange_rate > 0 else 0.0
        
        result: Dict[str, Any] = {
            'mode': 'etf',
            'lof_qty': lof_qty,
            'etf_qty': etf_qty,
            'exposure_rmb': round(exposure_rmb, 2),
            'exposure_usd': round(exposure_usd, 2),
            'breakdown': [],
        }
        
        # 一篮子拆解
        if portfolio and exchange_rate > 0:
            breakdown = CalcQuantity._basket_breakdown(
                exposure_usd=exposure_usd,
                portfolio=portfolio,
            )
            result['breakdown'] = breakdown
        
        return result
    
    @staticmethod
    def futures_hedge(
        n_contracts: float,
        hedge: float,
        calibration: float,
        multiplier: float,
        lof_price: float,
        position: float = 1.0,
        nav: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        期货对冲数量计算。
        
        公式：
            hedge_value_per_contract = hedge × calibration × multiplier
            lof_qty = n_contracts × hedge_value_per_contract / lof_price
        
        Args:
            n_contracts:    期货合约手数
            hedge:          对冲因子（来自 fund_daily_factors.hedge）
            calibration:    校准值（来自 fund_daily_factors.calibration 或 futures_daily）
            multiplier:     期货合约乘数（来自 futures_multipliers）
            lof_price:      LOF 现价（RMB）
            position:       仓位比例（0.0~1.0）
            nav:            LOF 净值（用于计算真实敞口，优先于 lof_price）
        
        Returns:
            {
                'hedge_value_per_contract': float,  # 每手期货合约对冲的 RMB 价值
                'lof_qty': int,                      # LOF 股数
                'exposure_rmb': float,               # 实际敞口
                'mode': 'futures'
            }
        """
        if n_contracts <= 0 or hedge <= 0 or calibration <= 0 or multiplier <= 0 or lof_price <= 0:
            return {'mode': 'futures', 'error': '参数无效: 所有输入必须 > 0'}
        
        hedge_value_per_contract = hedge * calibration * multiplier
        if hedge_value_per_contract <= 0:
            return {'mode': 'futures', 'error': '计算失败: hedge_value_per_contract <= 0'}
        
        total_hedge_value = n_contracts * hedge_value_per_contract
        raw_lof_qty = total_hedge_value / lof_price
        lof_qty = max(100, round(raw_lof_qty / 100) * 100)
        
        # [AI-2026-08-06] 实际 RMB 敞口：必须用净值 NAV（不是 LOF 市价）——与 etf_hedge 保持一致
        # nav 提供时优先用净值；否则回退 lof_price（兼容旧调用）
        _exposure_basis = nav if (nav is not None and nav > 0) else lof_price
        exposure_rmb = lof_qty * _exposure_basis * position
        
        return {
            'mode': 'futures',
            'n_contracts': n_contracts,
            'hedge_value_per_contract': round(hedge_value_per_contract, 4),
            'lof_qty': lof_qty,
            'exposure_rmb': round(exposure_rmb, 2),
            'params': {
                'hedge': hedge,
                'calibration': calibration,
                'multiplier': multiplier,
            }
        }
    
    @staticmethod
    def pure_futures_hedge(
        n_contracts: float,
        hedge: float,
        calibration: float,
        lof_price: float,
        future_symbol: str,
        position: float = 1.0,
        nav: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        [占位/实验性] 纯期货对冲（从期货代码自动获取乘数）。
        
        注意：Woody 不使用此方法，他的做法是用校准因子将期货转换为 ETF 等价价格，
        然后走标准 ETF 篮子估值公式。此处保留为将来探索"直接用期货估值"的算法预留。
        算法公式与 futures_hedge 相同，区别在于 future_symbol 自动查乘数字典。
        
        Args:
            n_contracts:    期货合约手数
            hedge:          对冲因子
            calibration:    校准值
            lof_price:      LOF 现价
            future_symbol:  期货代码（如 'MCL', 'GC'）
            position:       仓位比例
            nav:            LOF 净值（用于计算真实敞口，优先于 lof_price）
        
        Returns:
            同 futures_hedge
        """
        multiplier = get_multiplier(future_symbol)
        return CalcQuantity.futures_hedge(
            n_contracts=n_contracts,
            hedge=hedge,
            calibration=calibration,
            multiplier=multiplier,
            lof_price=lof_price,
            position=position,
            nav=nav,  # [AI-2026-08-06] 透传 nav 参数
        )
    
    @staticmethod
    def calc_contract_value(
        price: float,
        multiplier: float,
        n_contracts: float = 1.0
    ) -> float:
        """
        计算 N 手期货合约的名义价值（USD）。
        
        对应 Woody CalcQuantity: nQty × nPrice × fMultiplier
        
        Args:
            price:        期货价格（USD）
            multiplier:   合约乘数
            n_contracts:  合约手数
        
        Returns:
            名义价值（USD）
        """
        return n_contracts * price * multiplier
    
    @staticmethod
    def _convert_yahoo_symbol(symbol: str) -> str:
        """
        符号归一化：将 ^XXX-YY 格式转换为 XXX（底层标的）。
        
        例如：
            ^GLD-EU  →  GLD（GLD 在欧洲休市时刻的价格快照）
            ^GLD-JP  →  GLD（GLD 在东京休市时刻的价格快照）
            ^INDA-HK →  INDA（INDA 在香港休市时刻的价格快照）
            GLD      →  GLD（本身不变）
        
        这是 Woody 的 ConvertYahooNetValueSymbol 函数的 Python 实现。
        ^XXX-YY 不是不同交易所上市的 ETF，而是同一标的在不同时区休市时刻的价格快照。
        """
        import re
        pattern = r'^\^([A-Z]+)-[A-Z]{2}$'
        match = re.match(pattern, symbol)
        if match:
            return match.group(1)  # 返回底层标的
        return symbol  # 不符合格式则返回原字符串
    
    @staticmethod
    def _basket_breakdown(
        exposure_usd: float,
        portfolio: List[Dict[str, Any]],
        actual_holdings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        一篮子持仓拆解：按权重将总敞口分配到各标的，并与 Woody 算法完全对齐。
        
        Woody 算法（palmmicroapi.py __calc_holdings_quantity）：
        1. 各成分分别算：qty_i = fAmount × ratio_i% / price_i
        2. 符号归一化：^GLD-EU → GLD, ^GLD-JP → GLD
        3. 聚合到真实标的：arReal['GLD'] = qty_GLD + qty_^GLD-EU + qty_^GLD-JP
        4. fMax 约束：如果用户提供了实际持仓，检查是否超出，等比缩放
        5. 各成分分别取整（floor），聚合后总量也取整
        
        Woody 显示格式：
        - 主消息：「买入 INDA 3798@50.41」— 3798 是聚合后总量（floor）
        - 补充内容：「^INDA-EU 978 + ^INDA-JP 57 + ^INDA-HK 49」— 各成分取整分量
        
        Args:
            exposure_usd:  总 USD 敞口
            portfolio:     [{'symbol':str, 'weight':float, 'price':float}, ...]
            actual_holdings: 用户实际持仓 {真实标的：股数}，如 {'GLD': 10, 'INDA': 5}
                           如果为 None，则不做 fMax 约束
        
        Returns:
            {
                'total': {真实标的: 聚合后取整数量},  # 主消息用
                'components': [{原始符号, 取整数量, ...}],  # 补充内容用
            }
        """
        if exposure_usd <= 0 or not portfolio:
            return {'total': {}, 'components': []}
        
        import math
        
        # 第 1 步：各成分分别算
        ar_quantity = {}  # {原始符号: 股数}
        for item in portfolio:
            symbol = item.get('symbol', '')
            weight = float(item.get('weight', 0))
            price = float(item.get('price', 0))
            
            # weight=0 或 price<=0 跳过
            if weight == 0 or price <= 0:
                continue
            
            # 金额敞口 = 总敞口 × 权重占比
            weight_ratio = weight / 100.0 if abs(weight) > 1 else weight
            allocated_usd = exposure_usd * weight_ratio
            
            if allocated_usd == 0:
                continue
            
            shares = allocated_usd / price
            ar_quantity[symbol] = shares
        
        # 第 2 步：符号归一化 + 聚合到真实标的
        ar_real = {}  # {真实标的：聚合后股数}
        for symbol, shares in ar_quantity.items():
            real_symbol = CalcQuantity._convert_yahoo_symbol(symbol)
            if real_symbol in ar_real:
                ar_real[real_symbol] += shares
            else:
                ar_real[real_symbol] = shares
        
        # 第 3 步：fMax 约束缩放（Woody 的 fMax 机制）
        if actual_holdings:
            f_max = 0.0
            for real_symbol, theoretical_qty in ar_real.items():
                actual_qty = actual_holdings.get(real_symbol)
                if actual_qty is not None and actual_qty > 0.000001:
                    f_compare = theoretical_qty / actual_qty
                    if f_compare > f_max:
                        f_max = f_compare
            
            if f_max > 1.0:
                for symbol in ar_quantity:
                    ar_quantity[symbol] /= f_max
                
                # 重新聚合
                ar_real = {}
                for symbol, shares in ar_quantity.items():
                    real_symbol = CalcQuantity._convert_yahoo_symbol(symbol)
                    if real_symbol in ar_real:
                        ar_real[real_symbol] += shares
                    else:
                        ar_real[real_symbol] = shares
        
        # 第 4 步：各成分分别取整（floor）
        ar_dst = {}  # {原始符号: 取整后股数}
        for symbol, shares in ar_quantity.items():
            ar_dst[symbol] = math.floor(shares) if shares >= 0 else 0
        
        # 第 5 步：构建返回结果
        # total: 聚合后真实标的的取整总量
        total = {}
        for real_symbol, agg_shares in ar_real.items():
            floored_total = math.floor(agg_shares)
            if floored_total >= 1:
                total[real_symbol] = floored_total
        
        # components: 各原始成分的取整分量（用于补充内容显示）
        components = []
        for symbol, floored_shares in ar_dst.items():
            if floored_shares < 1:
                continue
            
            item = next((i for i in portfolio if i.get('symbol') == symbol), None)
            weight = float(item.get('weight', 0)) if item else 0
            price = float(item.get('price', 0)) if item else 0
            weight_ratio = weight / 100.0 if abs(weight) > 1 else weight
            
            components.append({
                'symbol': symbol,
                'shares': floored_shares,
                'is_short': floored_shares < 0,
                'weight_pct': round(weight_ratio * 100, 4),
                'price': price,
            })
        
        return {
            'total': total,
            'components': components,
        }
