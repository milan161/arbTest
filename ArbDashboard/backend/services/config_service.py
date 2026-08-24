import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigService:
    def __init__(self, db_manager):
        self.db = db_manager

    def get_data_sources(self, module: str = "realtime_market") -> List[Dict[str, Any]]:
        """获取数据源配置列表

        [2026-08-24] 取消实时行情优先级功能：原 db.get_data_source_config 查询会阻塞
        事件循环导致 /api/config/data_sources 接口超时。改为返回硬编码默认顺序，
        恢复「通达信 → 新浪/腾讯 → 银河QMT → 国金QMT」，不再由 DB priority 驱动。
        """
        if module != "realtime_market":
            # 历史/其他模块仍走 DB（这些接口未被报告超时）
            configs = self.db.get_data_source_config(module)
            for cfg in configs:
                try:
                    cfg['config'] = json.loads(cfg['config_json'])
                except:
                    cfg['config'] = {}
            return configs
        DEFAULT_SOURCES = [
            {'source_name': 'tdx',    'priority': 1, 'is_active': 1, 'config_json': '{"desc": "通达信内存直连"}'},
            {'source_name': 'sina',   'priority': 2, 'is_active': 1, 'config_json': '{"desc": "新浪/腾讯行情"}'},
            {'source_name': 'galaxy', 'priority': 3, 'is_active': 1, 'config_json': '{"desc": "银河QMT (Socket)"}'},
            {'source_name': 'guojin', 'priority': 4, 'is_active': 1, 'config_json': '{"desc": "国金QMT (xtquant)"}'},
        ]
        out = []
        for cfg in DEFAULT_SOURCES:
            item = dict(cfg)
            try:
                item['config'] = json.loads(cfg['config_json'])
            except:
                item['config'] = {}
            out.append(item)
        return out

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
        # lof_config.yaml 在 D:/Study/arbTest/arbcore/config/lof_config.yaml
        # project_root 需要指向 D:/Study/arbTest
        project_root = os.path.abspath(os.path.join(backend_dir, "..", ".."))
        cms = ConfigManagerService(project_root)
        return cms.load_config()

    def get_fund_config(self, code: str) -> Optional[Dict[str, Any]]:
        """获取单只基金的 YAML 配置（委托 ConfigManagerService）

        供 fund_service.get_valuation_meta 调用，按 code 从 lof_config.yaml 查单只基金。
        """
        from .config_manager_service import ConfigManagerService
        import os
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        project_root = os.path.abspath(os.path.join(backend_dir, "..", ".."))
        cms = ConfigManagerService(project_root)
        return cms.get_fund_config(code)

