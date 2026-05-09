# LOF031_config_manager.py - 配置管理模块
import os
import sys

# 添加 arbcore 路径到 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arbcore.config.config_loader import load_config

class ConfigManager:
    """配置管理类"""
    
    def __init__(self, config_file):
        """初始化配置管理器"""
        self.config_file = config_file
        self.config = None
    
    def load_config(self):
        """加载配置文件（使用 arbcore 通用配置加载器）"""
        self.config = load_config(self.config_file)
        return self.config if self.config else None
    
    def get(self, key, default=None):
        """获取配置值"""
        if not self.config:
            self.load_config()
        if not self.config:
            return default
        
        # 支持嵌套键，如 'funds.0.code'
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            elif isinstance(value, list) and k.isdigit():
                index = int(k)
                if 0 <= index < len(value):
                    value = value[index]
                else:
                    return default
            else:
                return default
        return value
    
    def get_future_gold_calibration(self):
        """获取黄金期货校准值"""
        return self.get('future_gold_calibration', 10.9067)  # 默认值
    
    def get_future_oil_calibration(self):
        """获取原油期货校准值"""
        return self.get('future_oil_calibration', 0.8227)  # 默认值

    def get_fund_rate_type(self, fund_code):
        """获取基金的汇率基准类型 (midpoint 或 spot)"""
        if not self.config:
            self.load_config()
        for fund in self.config.get('funds', []):
            if str(fund.get('code')) == str(fund_code):
                return fund.get('rate_type', 'midpoint')
        return 'midpoint'