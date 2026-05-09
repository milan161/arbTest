# arbcore/config/config_loader.py - 通用配置加载器
# 提供统一的配置文件读取接口，支持私密配置优先

import os
import yaml

DEFAULT_CONFIG_NAME = "lof_config.yaml"
PRIVATE_CONFIG_NAME = "lof_config_private.yaml"

def load_config(config_path=None):
    """
    加载配置文件，优先读取私密配置
    
    Args:
        config_path: 配置文件路径（可选）。如果不提供，默认在调用者目录下查找 lof_config.yaml
    
    Returns:
        dict: 配置数据，如果加载失败返回空字典
    """
    if config_path is None:
        # 自动检测调用者目录
        import inspect
        caller_frame = inspect.stack()[1]
        caller_dir = os.path.dirname(os.path.abspath(caller_frame.filename))
        config_path = os.path.join(caller_dir, DEFAULT_CONFIG_NAME)
    
    base_dir = os.path.dirname(config_path)
    private_config_path = os.path.join(base_dir, PRIVATE_CONFIG_NAME)
    
    # 优先读取私密配置
    if os.path.exists(private_config_path):
        print(f"🔒 使用私密配置文件: {private_config_path}")
        try:
            with open(private_config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"加载私密配置失败，回退到默认配置: {e}")
    
    # 读取默认配置
    if not os.path.exists(config_path):
        print(f"警告: 配置文件不存在: {config_path}")
        return {}
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"加载配置文件失败: {e}")
        return {}

def get_fund_codes(config_path=None):
    """
    获取配置中的基金代码列表
    
    Args:
        config_path: 配置文件路径（可选）
    
    Returns:
        list: 基金代码列表
    """
    config = load_config(config_path)
    return [str(fund.get('code', '')) for fund in config.get('funds', [])]

def get_config_path():
    """
    获取当前使用的配置文件路径
    
    Returns:
        str: 当前配置文件路径
    """
    import inspect
    caller_frame = inspect.stack()[1]
    caller_dir = os.path.dirname(os.path.abspath(caller_frame.filename))
    config_path = os.path.join(caller_dir, DEFAULT_CONFIG_NAME)
    private_config_path = os.path.join(caller_dir, PRIVATE_CONFIG_NAME)
    
    if os.path.exists(private_config_path):
        return private_config_path
    return config_path
