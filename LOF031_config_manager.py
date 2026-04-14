# LOF031_config_manager.py - 配置管理模块
import os
import yaml

class ConfigManager:
    """配置管理类"""
    
    def __init__(self, config_file):
        """初始化配置管理器"""
        self.config_file = config_file
        self.config = None
    
    def load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            print(f"配置文件不存在: {self.config_file}")
            return None
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
            return self.config
        except Exception as e:
            print(f"加载配置文件失败: {e}")
            return None
    
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