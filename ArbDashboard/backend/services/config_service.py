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

    def get_ib_symbols(self) -> List[str]:
        """获取 IB/富途 的美股订阅白名单"""
        try:
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("SELECT config_json FROM data_source_config WHERE module = 'ib_config' AND source_name = 'whitelist'")
            row = cursor.fetchone()
            conn.close()
            if row and row[0]:
                data = json.loads(row[0])
                return data.get('symbols', ["GLD", "USO", "XOP", "SLV", "SPY", "QQQ", "INDA"])
        except Exception as e:
            logger.error(f"Failed to get ib_symbols: {e}")
        return ["GLD", "USO", "XOP", "SLV", "SPY", "QQQ", "INDA"]

    def update_ib_symbols(self, symbols: List[str]):
        """更新 IB/富途 的美股订阅白名单"""
        try:
            # 过滤空值，转为大写，去除空格
            clean_symbols = [s.strip().upper() for s in symbols if s.strip()]
            config_json = json.dumps({"symbols": clean_symbols})
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO data_source_config (module, source_name, config_json)
                VALUES ('ib_config', 'whitelist', ?)
            """, (config_json,))
            conn.commit()
            conn.close()
            return {"status": "ok", "message": "IB symbols whitelist updated"}
        except Exception as e:
            logger.error(f"Failed to update ib_symbols: {e}")
            return {"status": "error", "message": str(e)}
