import time
import threading
from typing import Dict, Any, Optional
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.health_status: Dict[str, Dict[str, Any]] = {}
        self.running = False
        self.check_interval = 60
        self.lock = threading.Lock()
    
    def register_component(self, component_name: str):
        with self.lock:
            self.health_status[component_name] = {
                'status': 'unknown',
                'last_check': None,
                'message': '',
                'failure_count': 0,
                'success_count': 0
            }
        logger.info(f"注册健康监控组件: {component_name}")
    
    def update_status(self, component_name: str, status: str, message: str = ""):
        with self.lock:
            if component_name not in self.health_status:
                self.register_component(component_name)
            
            component = self.health_status[component_name]
            component['status'] = status
            component['message'] = message
            component['last_check'] = datetime.now()
            
            if status == 'success':
                component['success_count'] += 1
                component['failure_count'] = 0
            elif status == 'failed':
                component['failure_count'] += 1
            
            self.db_manager.save_health_status(component_name, status, message)
            
            logger.info(f"健康状态更新: {component_name} - {status} - {message}")
    
    def get_status(self, component_name: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            if component_name:
                return self.health_status.get(component_name, {})
            return self.health_status.copy()
    
    def get_health_summary(self) -> Dict[str, Any]:
        with self.lock:
            total_components = len(self.health_status)
            healthy_components = sum(
                1 for comp in self.health_status.values() 
                if comp.get('status') == 'success'
            )
            failed_components = sum(
                1 for comp in self.health_status.values() 
                if comp.get('status') == 'failed'
            )
            
            return {
                'total_components': total_components,
                'healthy_components': healthy_components,
                'failed_components': failed_components,
                'health_percentage': (healthy_components / total_components * 100) if total_components > 0 else 0,
                'timestamp': datetime.now().isoformat(),
                'components': self.health_status.copy()
            }
    
    def check_component_health(self, component_name: str, check_func) -> bool:
        try:
            result = check_func()
            if result:
                self.update_status(component_name, 'success', '检查通过')
                return True
            else:
                self.update_status(component_name, 'failed', '检查失败')
                return False
        except Exception as e:
            self.update_status(component_name, 'failed', f'异常: {str(e)}')
            return False
    
    def start_monitoring(self):
        if not self.running:
            self.running = True
            logger.info("健康监控服务已启动")
            threading.Thread(target=self._monitoring_loop, daemon=True).start()
    
    def stop_monitoring(self):
        self.running = False
        logger.info("健康监控服务已停止")
    
    def _monitoring_loop(self):
        while self.running:
            try:
                self._perform_health_checks()
                time.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"健康监控循环异常: {e}")
                time.sleep(self.check_interval)
    
    def _perform_health_checks(self):
        for component_name in self.health_status:
            try:
                component = self.health_status[component_name]
                if component.get('failure_count', 0) > 3:
                    logger.warning(f"组件 {component_name} 连续失败，可能需要关注")
            except Exception as e:
                logger.error(f"健康检查异常: {component_name} - {e}")
    
    def get_alert_status(self) -> Dict[str, Any]:
        with self.lock:
            alerts = []
            for component_name, component in self.health_status.items():
                if component.get('failure_count', 0) >= 3:
                    alerts.append({
                        'component': component_name,
                        'level': 'critical',
                        'message': f"{component_name} 连续失败 {component['failure_count']} 次"
                    })
                elif component.get('failure_count', 0) >= 1:
                    alerts.append({
                        'component': component_name,
                        'level': 'warning',
                        'message': f"{component_name} 最近检查失败"
                    })
            
            return {
                'has_alerts': len(alerts) > 0,
                'alert_count': len(alerts),
                'alerts': alerts,
                'timestamp': datetime.now().isoformat()
            }
