# -*- coding: utf-8 -*-
import os
import sys
import logging
from datetime import datetime

# 🚀 强制全局禁用系统代理 (关键优化)
# 解决矛盾：Gemini CLI 需要梯子，但 Woody/新浪 API 探测到梯子 IP 会反爬或报错
os.environ['NO_PROXY'] = '*'

# 明确路径管理
# 当前文件: D:\Study\arbTest\LOFarb\readers\base_app.py
READER_DIR = os.path.dirname(os.path.abspath(__file__))
LOFARB_DIR = os.path.dirname(READER_DIR)
ROOT_DIR = os.path.dirname(LOFARB_DIR)  # 指向 D:\Study\arbTest

# 将项目根目录添加到 sys.path，确保 arbcore 可被导入
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 导入公共基座
from arbcore.database.db_manager import DatabaseManager
from arbcore.config.config_loader import load_config

def setup_logging(name, log_file_prefix="app"):
    """
    统一日志配置
    """
    # 日志统一放在 LOFarb/logs 目录下
    log_dir = os.path.join(LOFARB_DIR, "logs")
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
    应用基类
    """
    def __init__(self, name, config_name="lof_config.yaml"):
        self.logger = setup_logging(name, log_file_prefix=name)
        self.db = DatabaseManager()
        # 配置文件路径: D:\Study\arbTest\LOFarb\lof_config.yaml
        self.config_path = os.path.join(LOFARB_DIR, config_name)
        self.config = self._load_config()
        self.logger.info(f"🚀 {name} 启动，配置文件: {self.config_path}")

    def _load_config(self):
        try:
            return load_config(self.config_path)
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
