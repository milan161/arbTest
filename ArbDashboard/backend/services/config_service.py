import json
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class ConfigService:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_data_sources(self, module: str = "realtime_market") -> List[Dict[str, Any]]:
        """获取数据源配置列表"""
        configs = self.db.get_data_source_config(module)
        for cfg in configs:
            try:
                # 解析 config_json 方便前端展示
                cfg['config'] = json.loads(cfg['config_json'])
            except:
                cfg['config'] = {}
        return configs

    def update_source_config(self, module: str, source_name: str, priority: int = None, is_active: int = None, config: Dict = None):
        """更新数据源配置"""
        config_json = None
        if config is not None:
            config_json = json.dumps(config)
            
        self.db.update_data_source_config(
            module=module,
            source_name=source_name,
            priority=priority,
            is_active=is_active,
            config_json=config_json
        )
        return {"status": "ok", "message": f"Source {source_name} updated"}

    def update_priorities(self, module: str, priorities: List[Dict[str, Any]]):
        """
        批量更新优先级。
        priorities: [{'source_name': 'sina', 'priority': 1}, ...]
        """
        for item in priorities:
            self.db.update_data_source_config(
                module=module,
                source_name=item['source_name'],
                priority=item['priority']
            )
        return {"status": "ok", "message": "Priorities updated"}

    def get_full_config(self) -> Dict[str, Any]:
        """获取全量基金配置 (通常来自 YAML)"""
        from .config_manager_service import ConfigManagerService
        import os
        # 这里的 backend_dir 是 ArbDashboard/backend
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # lof_config.yaml 在 D:/Study/arbTest/LOFarb/lof_config.yaml
        # project_root 需要指向 D:/Study/arbTest
        project_root = os.path.abspath(os.path.join(backend_dir, "..", ".."))
        cms = ConfigManagerService(project_root)
        return cms.load_config()

