# -*- coding: utf-8 -*-
"""
重试机制、熔断器等通用工具模块

本模块直接复用 LOFarb 项目的稳定实现（readers/retry_manager.py）
用于所有需要容错、重试、熔断的场景

作者: 基于 LOFarb 项目抽取
"""

import time
import threading
import functools
import logging
from typing import Callable, Optional, Any, Type, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class RetryManager:
    """
    重试管理器
    
    支持指数退避重试策略，适用于网络请求、API调用等可能临时失败的场景
    
    参数:
        max_retries: 最大重试次数（默认3次）
        base_delay: 基础延迟秒数（默认1秒）
        max_delay: 最大延迟秒数（默认60秒）
        exponential_backoff: 是否使用指数退避（默认True）
    
    示例:
        retry = RetryManager(max_retries=3, base_delay=1.0)
        result = retry.execute_with_retry(some_function, arg1, arg2)
        
        # 或使用装饰器
        @retry.retry_decorator((ConnectionError, TimeoutError))
        def fetch_data():
            ...
    """
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, 
                 max_delay: float = 60.0, exponential_backoff: bool = True):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_backoff = exponential_backoff
    
    def calculate_delay(self, attempt: int) -> float:
        """计算重试延迟时间"""
        if self.exponential_backoff:
            delay = self.base_delay * (2 ** attempt)
        else:
            delay = self.base_delay * (attempt + 1)
        return min(delay, self.max_delay)
    
    def execute_with_retry(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        执行函数，带自动重试机制
        
        参数:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        返回:
            函数执行结果，如果所有重试都失败则返回 None
        """
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
        """
        重试装饰器工厂
        
        参数:
            exceptions: 需要捕获并重试的异常类型元组
            
        返回:
            装饰器函数
        """
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
    """
    熔断器
    
    实现熔断器模式，防止对失败服务的频繁调用
    
    状态转换:
        closed -> open: 失败次数达到阈值
        open -> half-open: 等待超时后
        half-open -> closed: 测试调用成功
        half-open -> open: 测试调用失败
    
    参数:
        failure_threshold: 触发熔断的失败次数阈值（默认5次）
        timeout: 熔断恢复超时时间（秒，默认60秒）
    
    示例:
        breaker = CircuitBreaker(failure_threshold=5, timeout=60)
        try:
            result = breaker.call(some_function, arg1)
        except Exception as e:
            logger.error(f"熔断器触发: {e}")
    """
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = 'closed'
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs) -> Optional[Any]:
        """
        通过熔断器执行函数
        
        参数:
            func: 要执行的函数
            *args: 位置参数
            **kwargs: 关键字参数
            
        返回:
            函数执行结果
            
        异常:
            Exception: 熔断器开启时抛出
        """
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
        """处理成功调用"""
        with self.lock:
            if self.state == 'half-open':
                self.state = 'closed'
                self.failure_count = 0
                logger.info("熔断器状态: half-open -> closed")
            else:
                self.failure_count = max(0, self.failure_count - 1)
    
    def _on_failure(self):
        """处理失败调用"""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = datetime.now().timestamp()
            
            if self.failure_count >= self.failure_threshold:
                self.state = 'open'
                logger.warning(f"熔断器状态: closed -> open (失败次数: {self.failure_count})")
    
    def get_state(self) -> str:
        """获取当前熔断器状态"""
        with self.lock:
            return self.state
    
    def reset(self):
        """重置熔断器到关闭状态"""
        with self.lock:
            self.state = 'closed'
            self.failure_count = 0
            self.last_failure_time = None
            logger.info("熔断器已重置")


# 工厂函数
def create_retry_manager(max_retries: int = 3, base_delay: float = 1.0) -> RetryManager:
    """创建重试管理器实例"""
    return RetryManager(max_retries=max_retries, base_delay=base_delay)


def create_circuit_breaker(failure_threshold: int = 5, timeout: int = 60) -> CircuitBreaker:
    """创建熔断器实例"""
    return CircuitBreaker(failure_threshold=failure_threshold, timeout=timeout)
