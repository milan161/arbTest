# -*- coding: utf-8 -*-
import os
import sys
import logging
from datetime import datetime

# 统一路径管理：将项目根目录(arbTest)添加到 sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# 导入公共基座（假定 arbcore 已在 sys.path 中）
from arbcore.database.db_manager import DatabaseManager
from arbcore.config.config_loader import load_config

def setup_logging(name, log_file_prefix="app"):
    """
    统一日志配置，支持文件和控制台输出
    """
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{log_file_prefix}_{datetime.now().strftime('%Y%m%d')}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True,
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8-sig'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    # 降低第三方库日志噪音
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    return logging.getLogger(name)

class BaseApp:
    """
    应用基类，处理通用的配置加载和数据库连接
    """
    def __init__(self, name, config_name="lof_config.yaml"):
        self.logger = setup_logging(name, log_file_prefix=name)
        self.db = DatabaseManager()
        self.config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), config_name)
        self.config = self._load_config()
        self.logger.info(f"🚀 {name} 启动，配置文件: {self.config_path}")

    def _load_config(self):
        try:
            return load_config(self.config_path)
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
