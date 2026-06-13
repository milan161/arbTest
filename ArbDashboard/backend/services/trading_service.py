import os
import sys
import pandas as pd
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

from .system_status_service import system_status

class TradingService:
    """
    业务级交易服务
    封装底层 TradeManager，提供持仓同步、订单管理等功能
    """
    def __init__(self, db_manager):
        self.db = db_manager
        self.trade_manager = None
        self.tq_failure_count = 0
        self.max_tq_failures = 3
        self.tq_suspended = False
        self._init_manager()

    def _init_manager(self):
        # 直接从 arbcore 导入 (不需要动态引导到 LOFarb)
        try:
            try:
                from arbcore.traders.trade_manager import TradeManager
                self.trade_manager = TradeManager()
                
                # 检查 tdx_available 状态
                if self.trade_manager and hasattr(self.trade_manager, 'tdx_available'):
                    if self.trade_manager.tdx_available:
                        logger.info("TradingService 成功挂载 TradeManager (TDX已就绪)")
                        system_status.add_milestone("SUCCESS", "交易管理器已挂载，通达信就绪")
                    else:
                        logger.info("TradeManager 已挂载，通达信未登录交易账号（当前为只读看盘模式）")
                        system_status.add_milestone("INFO", "通达信交易未登录 (不影响极速行情)")
                else:
                    logger.info("TradingService 成功挂载 TradeManager")
            except ImportError:
                logger.error("未能从 arbcore 导入 TradeManager")
                system_status.add_milestone("ERROR", "未找到 TradeManager 核心库")
        except Exception as e:
            logger.error(f"TradingService 初始化 TradeManager 失败: {e}")
            system_status.add_milestone("ERROR", f"交易引擎初始化失败: {e}")

    def get_positions(self) -> List[Dict[str, Any]]:
        """获取全量持仓"""
        if not self.trade_manager or not getattr(self.trade_manager, 'tdx_available', False):
            return []
        
        if self.tq_suspended:
            return []

        try:
            # 统一转换通达信原始数据为系统标准格式
            raw_pos = self.trade_manager.tq.query_stock_positions(account_id=self.trade_manager.tdx_account_id)
            
            if raw_pos is None:
                self.tq_failure_count += 1
                if self.tq_failure_count >= self.max_tq_failures:
                    self.tq_suspended = True
                    msg = "TQ接口连续响应为空，已自动挂起通达信查询，请检查客户端是否登录"
                    logger.error(msg)
                    system_status.add_milestone("ERROR", msg)
                return []
            
            # 重置失败计数
            self.tq_failure_count = 0
            
            standard_pos = []
            for p in raw_pos:
                code_raw = p.get('Code', '')
                code = code_raw.split('.')[0] if code_raw else ''
                standard_pos.append({
                    "code": code,
                    "name": p.get('Name', ''), 
                    "volume": int(float(p.get('TotalVol', 0))),
                    "available": int(float(p.get('CanUseVol', 0))),
                    "cost_price": float(p.get('Cbj', 0)),
                    "market_value": float(p.get('MarketVal', 0)) if p.get('MarketVal') else 0
                })
            return standard_pos
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return []

    def get_balance(self) -> Dict[str, Any]:
        """获取资金账户余额"""
        if not self.trade_manager or not getattr(self.trade_manager, 'tdx_available', False) or self.tq_suspended:
            return {"balance": 0, "available": 0, "market_value": 0}
        try:
            asset = self.trade_manager.tq.query_stock_asset(account_id=self.trade_manager.tdx_account_id)
            if asset is None:
                return {"balance": 0, "available": 0, "market_value": 0}
            return {
                "balance": float(asset.get('Zzc', 0)),
                "available": float(asset.get('Kyje', 0)),
                "market_value": float(asset.get('Zsz', 0))
            }
        except:
            return {"balance": 0, "available": 0, "market_value": 0}

    def execute_order(self, action: str, code: str, volume: int, price: float, broker: str = 'tdx', account_id: str = None) -> Dict[str, Any]:
        """执行下单"""
        if not self.trade_manager:
            return {"status": "error", "message": "交易引擎未加载"}
        
        symbol = f"{code}.SH" if code.startswith('5') or code.startswith('6') else f"{code}.SZ"
        
        success, msg = self.trade_manager.send_order(
            broker=broker,
            action=action, 
            symbol=symbol,
            volume=int(volume),
            price=float(price),
            account_id=account_id
        )
        
        # 安全处理 msg 为空或 None 的情况
        msg_str = str(msg or "未知响应")
        
        return {
            "status": "ok" if success else "error",
            "message": msg_str,
            "order_id": msg_str.split(':')[-1].strip() if '委托编号' in msg_str else None
        }
