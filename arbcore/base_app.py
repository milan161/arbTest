# -*- coding: utf-8 -*-
import os
import sys
import logging
from datetime import datetime
import io

# 强制 sys.stdout 使用 UTF-8 (解决 Windows 控制台输出 emoji 时报错)
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 🚀 强制全局禁用系统代理
os.environ['NO_PROXY'] = '*'

# 明确路径管理：获取 arbcore 所在的目录
# 当前文件: .../arbcore/base_app.py
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CORE_DIR)

# 将项目根目录添加到 sys.path
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 导入公共基座
from arbcore.database.db_manager import DatabaseManager
from arbcore.config.config_loader import load_config

def setup_logging(name, log_dir, log_file_prefix="app"):
    """
    统一日志配置
    """
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
    工业级应用基类 (Industrial Grade V2.2)
    """
    def __init__(self, name, config_name="lof_config.yaml", app_dir=None):
        # 如果没有传 app_dir，则尝试自动发现（当前脚本所在的目录）
        if app_dir is None:
            # 找到调用者的目录
            import inspect
            frame = inspect.stack()[1]
            module = inspect.getmodule(frame[0])
            if module and hasattr(module, '__file__'):
                app_dir = os.path.dirname(os.path.abspath(module.__file__))
            else:
                app_dir = os.getcwd()

        self.app_dir = app_dir
        log_dir = os.path.join(self.app_dir, "logs")
        self.logger = setup_logging(name, log_dir, log_file_prefix=name)
        
        self.db = DatabaseManager()
        
        # 配置文件路径，优先在应用目录下查找
        self.config_path = os.path.join(self.app_dir, config_name)
        self.config = self._load_config()
        self.logger.info(f"🚀 {name} 启动，应用目录: {self.app_dir}，配置文件: {self.config_path}")

    def _load_config(self):
        try:
            if os.path.exists(self.config_path):
                return load_config(self.config_path)
            else:
                self.logger.warning(f"配置文件未找到: {self.config_path}，将返回空配置。")
                return {}
        except Exception as e:
            self.logger.error(f"加载配置文件失败: {e}")
            raise
