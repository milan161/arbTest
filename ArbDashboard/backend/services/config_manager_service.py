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
        # 彻底废弃 LOFarb，统一从 arbcore/scripts/lof_config.yaml 加载配置
        base_dir = project_root if os.path.exists(os.path.join(project_root, "arbcore")) else os.path.dirname(project_root)
        self.config_path = os.path.normpath(os.path.join(base_dir, "arbcore", "scripts", "lof_config.yaml"))

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
