import yaml
import os
import time
from typing import Dict, List, Any, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ConfigManager:
    def __init__(self, config_path: str = 'lof_config.yaml'):
        self.config_path = config_path
        self.config = {}
        self.last_modified = 0
        self._load_config()
    
    def _load_config(self):
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
    
    def get_funds(self) -> List[Dict[str, Any]]:
        self._load_config()
        return self.config.get('funds', [])
    
    def get_fund_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        funds = self.get_funds()
        for fund in funds:
            if fund.get('code') == code:
                return fund
        return None
    
    def get_lof_codes(self) -> List[str]:
        funds = self.get_funds()
        return [fund.get('code', '') for fund in funds if fund.get('code')]
    
    def get_future_calibration(self, future_type: str) -> float:
        self._load_config()
        if future_type == 'gold':
            return self.config.get('future_gold_calibration', 10.9714)
        elif future_type == 'oil':
            return self.config.get('future_oil_calibration', 0.8028)
        return 1.0
    
    def get_valuation_portfolio(self, fund_code: str) -> List[Dict[str, Any]]:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('valuation_portfolio', [])
        return []
    
    def get_holdings_info(self, fund_code: str) -> Dict[str, Any]:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('holdings', {})
        return {}
    
    def get_future_hedging(self, fund_code: str) -> List[Dict[str, Any]]:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('future_hedging', [])
        return []
    
    def get_trade_etf(self, fund_code: str) -> str:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('trade_etf', '')
        return ''
    
    def get_trade_future(self, fund_code: str) -> str:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('trade_future', '')
        return ''
    
    def get_category(self, fund_code: str) -> str:
        fund = self.get_fund_by_code(fund_code)
        if fund:
            return fund.get('category', '')
        return ''
    
    def get_equity_ratio(self, fund_code: str) -> float:
        holdings = self.get_holdings_info(fund_code)
        return holdings.get('equity_ratio', 95.0)
