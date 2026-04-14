import time
import threading
import random
from typing import Dict, Any, Optional, Callable
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DynamicDataFetcher:
    def __init__(self, http_client, base_interval: int = 20):
        self.http_client = http_client
        self.base_interval = base_interval
        self.current_interval = base_interval
        self.min_interval = 15
        self.max_interval = 60
        self.running = False
        self.fetch_functions: Dict[str, Callable] = {}
        self.last_fetch_times: Dict[str, datetime] = {}
        self.success_rates: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
    
    def register_fetch_function(self, name: str, fetch_func: Callable):
        with self.lock:
            self.fetch_functions[name] = fetch_func
            self.success_rates[name] = {
                'success_count': 0,
                'failure_count': 0,
                'last_success': None,
                'last_failure': None
            }
        logger.info(f"注册数据采集函数: {name}")
    
    def update_success_rate(self, name: str, success: bool):
        with self.lock:
            if name not in self.success_rates:
                self.success_rates[name] = {
                    'success_count': 0,
                    'failure_count': 0,
                    'last_success': None,
                    'last_failure': None
                }
            
            rate_data = self.success_rates[name]
            if success:
                rate_data['success_count'] += 1
                rate_data['last_success'] = datetime.now()
            else:
                rate_data['failure_count'] += 1
                rate_data['last_failure'] = datetime.now()
            
            self._adjust_interval(name)
    
    def _adjust_interval(self, name: str):
        rate_data = self.success_rates.get(name, {})
        success_count = rate_data.get('success_count', 0)
        failure_count = rate_data.get('failure_count', 0)
        total_attempts = success_count + failure_count
        
        if total_attempts < 5:
            return
        
        success_rate = success_count / total_attempts
        
        if success_rate >= 0.9:
            new_interval = max(self.min_interval, self.base_interval * 0.5)
        elif success_rate >= 0.7:
            new_interval = max(self.min_interval, self.base_interval * 0.75)
        elif success_rate >= 0.5:
            new_interval = self.base_interval
        elif success_rate >= 0.3:
            new_interval = min(self.max_interval, self.base_interval * 1.5)
        else:
            new_interval = min(self.max_interval, self.base_interval * 2.0)
        
        if abs(new_interval - self.current_interval) > 1:
            self.current_interval = new_interval
            logger.info(f"调整请求间隔: {name} - {self.current_interval:.1f}秒 (成功率: {success_rate:.1%})")
    
    def get_current_interval(self) -> float:
        return self.current_interval
    
    def get_success_rate(self, name: str) -> Dict[str, Any]:
        with self.lock:
            rate_data = self.success_rates.get(name, {})
            success_count = rate_data.get('success_count', 0)
            failure_count = rate_data.get('failure_count', 0)
            total_attempts = success_count + failure_count
            
            return {
                'name': name,
                'success_rate': success_count / total_attempts if total_attempts > 0 else 0,
                'total_attempts': total_attempts,
                'success_count': success_count,
                'failure_count': failure_count,
                'last_success': rate_data.get('last_success'),
                'last_failure': rate_data.get('last_failure')
            }
    
    def fetch_data(self, name: str) -> Optional[Any]:
        if name not in self.fetch_functions:
            logger.warning(f"未找到数据采集函数: {name}")
            return None
        
        fetch_func = self.fetch_functions[name]
        
        try:
            result = fetch_func()
            if result is not None:
                self.update_success_rate(name, False)
                return None
            
            self.update_success_rate(name, True)
            with self.lock:
                self.last_fetch_times[name] = datetime.now()
            
            return result
        except Exception as e:
            logger.error(f"数据采集异常: {name} - {e}")
            self.update_success_rate(name, False)
            return None
    
    def start_fetching(self):
        if not self.running:
            self.running = True
            logger.info("动态数据采集服务已启动")
            threading.Thread(target=self._fetching_loop, daemon=True).start()
    
    def stop_fetching(self):
        self.running = False
        logger.info("动态数据采集服务已停止")
    
    def _fetching_loop(self):
        while self.running:
            try:
                start_time = time.time()
                
                for name in self.fetch_functions:
                    if not self.running:
                        break
                    
                    try:
                        self.fetch_data(name)
                    except Exception as e:
                        logger.error(f"采集循环异常: {name} - {e}")
                
                elapsed_time = time.time() - start_time
                sleep_time = max(0, self.current_interval - elapsed_time)
                
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    logger.warning(f"采集耗时超过间隔: {elapsed_time:.1f}秒 > {self.current_interval:.1f}秒")
                    
            except Exception as e:
                logger.error(f"采集循环异常: {e}")
                time.sleep(self.base_interval)
    
    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return {
                'running': self.running,
                'current_interval': self.current_interval,
                'registered_functions': list(self.fetch_functions.keys()),
                'success_rates': {
                    name: self.get_success_rate(name)
                    for name in self.fetch_functions
                },
                'last_fetch_times': {
                    name: time.isoformat() if time else None
                    for name, time in self.last_fetch_times.items()
                }
            }
    
    def reset_success_rates(self, name: Optional[str] = None):
        with self.lock:
            if name:
                if name in self.success_rates:
                    self.success_rates[name] = {
                        'success_count': 0,
                        'failure_count': 0,
                        'last_success': None,
                        'last_failure': None
                    }
                    logger.info(f"重置成功率统计: {name}")
            else:
                for func_name in self.success_rates:
                    self.success_rates[func_name] = {
                        'success_count': 0,
                        'failure_count': 0,
                        'last_success': None,
                        'last_failure': None
                    }
                logger.info("重置所有成功率统计")
