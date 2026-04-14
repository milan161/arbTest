import requests
import time
from typing import Optional, Dict, Any
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HTTPClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.retry_count = 3
        self.retry_delay = 1.0
    
    def get(self, url: str, headers: Optional[Dict[str, str]] = None, 
            timeout: int = 10, retry_on_failure: bool = True) -> Optional[requests.Response]:
        for attempt in range(self.retry_count):
            try:
                if headers:
                    self.session.headers.update(headers)
                response = self.session.get(url, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                logger.warning(f"请求失败 (尝试 {attempt + 1}/{self.retry_count}): {url} - {e}")
                if attempt < self.retry_count - 1 and retry_on_failure:
                    time.sleep(self.retry_delay * (attempt + 1))
                elif not retry_on_failure:
                    return None
        return None
    
    def post(self, url: str, data: Optional[Dict[str, Any]] = None, 
             headers: Optional[Dict[str, str]] = None, timeout: int = 10) -> Optional[requests.Response]:
        for attempt in range(self.retry_count):
            try:
                if headers:
                    self.session.headers.update(headers)
                response = self.session.post(url, json=data, timeout=timeout)
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as e:
                logger.warning(f"POST请求失败 (尝试 {attempt + 1}/{self.retry_count}): {url} - {e}")
                if attempt < self.retry_count - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        return None
    
    def close(self):
        self.session.close()
