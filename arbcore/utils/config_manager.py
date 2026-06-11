# -*- coding: utf-8 -*-
"""
配置管理器模块

本模块直接复用 LOFarb 项目的稳定实现（readers/config_manager.py）
支持 YAML 配置文件的加载、热更新和查询

作者: 基于 LOFarb 项目抽取
"""

import yaml
import os
import time
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """
    YAML 配置管理器
    
    支持配置文件热更新，自动检测文件修改时间并重新加载
    
    参数:
        config_path: 配置文件路径（默认 'config.yaml'）
    
    示例:
        config = ConfigManager('lof_config.yaml')
        funds = config.get_funds()
        fund = config.get_fund_by_code('161125')
        portfolio = config.get_valuation_portfolio('161125')
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        self.config_path = config_path
        self.config = {}
        self.last_modified = 0
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        try:
            current_modified = os.path.getmtime(self.config_path)
            if current_modified > self.last_modified:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    self.config = yaml.safe_load(f)
                self.last_modified = current_modified
                logger.info(f"配置文件已加载: {self.config_path}")
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            self.config = {'funds': []}
    
    def reload(self):
        """强制重新加载配置文件"""
        self._load_config()
    
    def get_funds(self) -> List[Dict[str, Any]]:
        """获取所有基金列表"""
        self._load_config()
        return self.config.get('funds', [])
    
    def get_fund_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """根据基金代码获取基金信息"""
        funds = self.get_funds()
        for fund in funds:
            if fund.get('code') == code:
                return fund
        return None
    
    def get_lof_codes(self) -> List[str]:
        """获取所有 LOF 基金代码列表"""
        funds = self.get_funds()
        return [fund.get('code', '') for fund in funds if fund.get('code')]
    
    def get_future_calibration(self, future_type: str) -> float:
        """
        获取期货校准参数
        
        参数:
            future_type: 期货类型 ('gold', 'oil')
            
        返回:
            校准参数值
        """
        self._load_config()
        if future_type == 'gold':
            return self.config.get('future_gold_calibration', 10.9714)
        elif future_type == 'oil':
            return self.config.get('future_oil_calibration', 0.8028)
        return 1.0
    
    def get_valuation_portfolio(self, fund_code: str) -> List[Dict[str, Any]]:
        """获取基金的估值组合配置"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('valuation_portfolio', [])
        return []
    
    def get_holdings_info(self, fund_code: str) -> Dict[str, Any]:
        """获取基金的持仓信息"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('holdings', {})
        return {}
    
    def get_future_hedging(self, fund_code: str) -> List[Dict[str, Any]]:
        """获取基金的期货对冲配置"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('future_hedging', [])
        return []
    
    def get_trade_etf(self, fund_code: str) -> str:
        """获取基金交易的 ETF 代码"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('trade_etf', '')
        return ''
    
    def get_trade_future(self, fund_code: str) -> str:
        """获取基金交易的期货代码"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('trade_future', '')
        return ''
    
    def get_category(self, fund_code: str) -> str:
        """获取基金分类"""
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('category', '')
        return ''
    
    def get_equity_ratio(self, fund_code: str) -> float:
        """获取基金权益比例"""
        holdings = self.get_holdings_info(fund_code)
        return holdings.get('equity_ratio', 95.0)
    
    def get_raw_config(self) -> Dict[str, Any]:
        """获取原始配置字典（用于调试或导出）"""
        self._load_config()
        return self.config
