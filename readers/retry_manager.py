import time
import functools
import logging
from typing import Callable, Optional, Any, Type, Tuple
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RetryManager:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, 
                 max_delay: float = 60.0, exponential_backoff: bool = True):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
    
    def calculate_delay(self, attempt: int) -> float:
        if self.exponential_backoff:
            delay = self.base_delay * (2 ** attempt)
        else:
            delay = self.base_delay * (attempt + 1)
        return min(delay, self.max_delay)
    
    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        last_exception = None
        
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    delay = self.calculate_delay(attempt)
                    logger.warning(f"重试 {attempt + 1}/{self.max_retries} - {func.__name__}: {e}，等待{delay:.1f}秒")
                    time.sleep(delay)
                else:
                    logger.error(f"重试失败 - {func.__name__}: {e}")
        
        if last_exception:
            raise last_exception
        return None
    
    def retry_decorator(self, exceptions: Tuple[Type[Exception], ...] = (Exception,)):
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Optional[Any]:
                last_exception = None
                
                for attempt in range(self.max_retries):
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        if attempt < self.max_retries - 1:
                            delay = self.calculate_delay(attempt)
                            logger.warning(f"装饰器重试 {attempt + 1}/{self.max_retries} - {func.__name__}: {e}，等待{delay:.1f}秒")
                            time.sleep(delay)
                        else:
                            logger.error(f"装饰器重试失败 - {func.__name__}: {e}")
                
                if last_exception:
                    raise last_exception
                return None
            return wrapper
        return decorator


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        with self.lock:
            if self.state == 'open':
                if datetime.now().timestamp() - self.last_failure_time > self.timeout:
                    self.state = 'half-open'
                    logger.info("熔断器状态: open -> half-open")
                else:
                    raise Exception("熔断器开启，服务暂时不可用")
            
            if self.state == 'half-open':
                logger.info("熔断器状态: half-open，允许一次测试调用")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e
    
    def _on_success(self):
        with self.lock:
            if self.state == 'half-open':
                self.state = 'closed'
                self.failure_count = 0
                logger.info("熔断器状态: half-open -> closed")
            else:
                self.failure_count = max(0, self.failure_count - 1)
    
    def _on_failure(self):
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now().timestamp()
            
            if self.failure_count >= self.failure_threshold:
                self.state = 'open'
                logger.warning(f"熔断器状态: closed -> open (失败次数: {self.failure_count})")
    
    def get_state(self) -> str:
        with self.lock:
            return self.state
    
    def reset(self):
        with self.lock:
            self.state = 'closed'
            self.failure_count = 0
            self.last_failure_time = None
            logger.info("熔断器已重置")


import threading


def create_retry_manager(max_retries: int = 3, base_delay: float = 1.0) -> RetryManager:
    return RetryManager(max_retries=max_retries, base_delay=base_delay)


def create_circuit_breaker(failure_threshold: int = 5, timeout: int = 60) -> CircuitBreaker:
    return CircuitBreaker(failure_threshold=failure_threshold, timeout=timeout)
