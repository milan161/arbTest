import logging
from datetime import datetime
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SystemStatusService:
    """
    系统状态记录服务。
    用于捕捉关键里程碑（如数据源连接、初始化结果），并展示在主页。
    """
    def __init__(self):
        self.milestones: List[Dict[str, Any]] = []
        self.max_milestones = 50

    def add_milestone(self, level: str, message: str):
        """记录一个系统里程碑"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        event = {
            "time": timestamp,
            "level": level.upper(), # INFO, SUCCESS, ERROR, WARNING
            "message": message
        }
        self.milestones.insert(0, event) # 最新的在前面
        if len(self.milestones) > self.max_milestones:
            self.milestones.pop()
        
        # 同步打印到日志
        log_msg = f"🚀 [System Milestone] {message}"
        if level.upper() == 'ERROR': logger.error(log_msg)
        elif level.upper() == 'WARNING': logger.warning(log_msg)
        else: logger.info(log_msg)

    def get_milestones(self) -> List[Dict[str, Any]]:
        return self.milestones

# 全局单例
system_status = SystemStatusService()
