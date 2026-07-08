# -*- coding: utf-8 -*-
"""
futures_multipliers.py - 期货乘数统一配置

[AI-2026-07-07] 创建：集中管理所有期货乘数，消除前端/后端多处硬编码。
参考 Woody PalmmicroAPI.arMultiplier 设计思路，但独立于其 API。

每手合约价值 = 价格 × 合约乘数

乘数来源：
  - CME Micro: MCL=100桶, MES=$5/点, MGC=10盎司, MNQ=$2/点
  - CME Mini:  CL=1000桶, ES=$50/点, GC=100盎司, NQ=$20/点
  - COMEX:     SI=5000盎司（白银）
  - 上期所:    AG=15千克（沪银）
"""

from typing import Dict

# ============================================================
# 期货合约乘数字典（symbol → 每点/每手合约乘数）
# ============================================================
# 格式：{ '期货代码': 合约乘数 }
# 注意大小写：CME 微小型合约（MCL/MES/MGC/MNQ）与大合约（CL/ES/GC/NQ）分开

FUTURES_MULTIPLIERS: Dict[str, float] = {
    # ---- CME 微型（Micro） ----
    'MCL': 100,     # 微型原油：1 手 = 100 桶
    'MES': 5,       # 微型标普：$5 / 指数点
    'MGC': 10,      # 微型黄金：10 盎司
    'MNQ': 2,       # 微型纳指：$2 / 指数点

    # ---- CME 迷你（Mini） ----
    'CL': 1000,     # 原油：1 手 = 1,000 桶
    'ES': 50,       # 标普：$50 / 指数点
    'GC': 100,      # 黄金：100 盎司
    'NQ': 20,       # 纳指：$20 / 指数点

    # ---- COMEX ----
    'SI': 5000,     # 白银期货：5,000 盎司

    # ---- 上期所（SHFE） ----
    'AG': 15,       # 沪银：15 千克/手
}

# ============================================================
# 查询函数
# ============================================================

def get_multiplier(symbol: str) -> float:
    """
    获取期货合约乘数。
    
    Args:
        symbol: 期货代码，如 'MCL', 'GC', 'SI', 'AG'
    
    Returns:
        合约乘数，未找到返回 1.0（兜底）
    """
    return FUTURES_MULTIPLIERS.get(symbol.upper(), 1.0)


def list_all_multipliers() -> Dict[str, float]:
    """返回所有期货乘数的副本（用于 API 输出）"""
    return dict(FUTURES_MULTIPLIERS)
