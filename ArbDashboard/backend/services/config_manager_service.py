import os
import yaml
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManagerService:
    """
    配置管理服务
    负责 CRUD 基金核心配置文件 lof_config.yaml
    """
    def __init__(self, project_root):
        # 兼容 project_root 为 D:\Study\arbTest\ArbDashboard 或 D:\Study\arbTest
        # 统一从 arbcore/config/lof_config.yaml 加载配置
        base_dir = project_root if os.path.exists(os.path.join(project_root, "arbcore")) else os.path.dirname(project_root)
        self.config_path = os.path.normpath(os.path.join(base_dir, "arbcore", "config", "lof_config.yaml"))

    def load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            return {"funds": [], "currencies": []}
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {"funds": [], "currencies": []}
        except Exception as e:
            logger.error(f"加载 YAML 失败: {e}")
            return {"funds": [], "currencies": []}

    def save_config(self, config: Dict[str, Any]) -> bool:
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception as e:
            logger.error(f"保存 YAML 失败: {e}")
            return False

    def get_fund_config(self, code: str) -> Optional[Dict[str, Any]]:
        cfg = self.load_config()
        for f in cfg.get('funds', []):
            if str(f.get('code')) == str(code):
                return f
        return None

    def upsert_fund_config(self, fund_data: Dict[str, Any]) -> bool:
        cfg = self.load_config()
        funds = cfg.get('funds', [])
        code = str(fund_data.get('code'))
        
        found = False
        for i, f in enumerate(funds):
            if str(f.get('code')) == code:
                funds[i] = fund_data
                found = True
                break
        
        if not found:
            funds.append(fund_data)
        
        cfg['funds'] = funds
        return self.save_config(cfg)

    def delete_fund_config(self, code: str) -> bool:
        cfg = self.load_config()
        funds = cfg.get('funds', [])
        new_funds = [f for f in funds if str(f.get('code')) != str(code)]
        if len(new_funds) == len(funds):
            return False
        cfg['funds'] = new_funds
        return self.save_config(cfg)

    def export_config(self) -> str:
        """导出完整 YAML 配置内容为字符串"""
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return f.read()

    def import_config(self, yaml_content: str) -> bool:
        """导入 YAML 配置：先验证结构，再备份旧文件，最后写入新配置"""
        try:
            new_cfg = yaml.safe_load(yaml_content)
            if not isinstance(new_cfg, dict):
                raise ValueError("YAML 根节点必须是字典")
            if 'funds' not in new_cfg:
                raise ValueError("YAML 缺少 'funds' 字段")
            # 备份旧配置
            backup_path = self.config_path + '.bak'
            if os.path.exists(self.config_path):
                import shutil
                shutil.copy2(self.config_path, backup_path)
            # 写入新配置
            return self.save_config(new_cfg)
        except Exception as e:
            logger.error(f"导入 YAML 失败: {e}")
            raise
