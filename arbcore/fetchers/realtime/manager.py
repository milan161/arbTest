import logging
from typing import List, Dict, Optional, Any
from .base import BaseRealtimeFetcher
from .guojin import GuojinQmtFetcher
from .galaxy import GalaxyQmtFetcher
from .sina import SinaRealtimeFetcher
from .tdx import TdxRealtimeFetcher
from .tencent import TencentRealtimeFetcher

logger = logging.getLogger(__name__)

class RealtimeMarketManager:
    """
    实时行情管理器。
    负责协调多个数据源，实现优先级排序和自动降级。
    """

    def __init__(self, db_manager=None, priority_list: List[str] = None):
        # 可用的 Fetcher 映射
        self.fetcher_classes = {
            "guojin": GuojinQmtFetcher,
            "galaxy": GalaxyQmtFetcher,
            "tdx": TdxRealtimeFetcher,
            "sina": SinaRealtimeFetcher,
            "tencent": TencentRealtimeFetcher
        }

        self.db_manager = db_manager
        self.priority_list = priority_list
        self.active_fetchers: Dict[str, BaseRealtimeFetcher] = {}
        self.symbols = []
        self._on_update_callback = None
        self.system_status = None # 允许注入

    def start(self):
        """按照优先级启动数据源，直到至少有一个成功"""
        # 尝试通过 sys.modules 寻找已存在的 system_status (单例)
        if not self.system_status:
            try:
                import sys
                for name, mod in sys.modules.items():
                    if 'system_status_service' in name and hasattr(mod, 'system_status'):
                        self.system_status = mod.system_status
                        break
            except: pass

        # 从数据库加载完整配置
        full_config = []
        if self.db_manager:
            full_config = self.db_manager.get_data_source_config("realtime_market")

        if not full_config:
            priority_names = self.priority_list or ["tdx", "guojin", "galaxy", "tencent", "sina"]
            full_config = [{"source_name": name, "config_json": "{}"} for name in priority_names]
            self.priority_list = priority_names
        else:
            self.priority_list = [item['source_name'] for item in full_config]

        logger.info(f"🚀 行情引擎启动，准备挂载数据源...")
        if self.system_status: self.system_status.add_milestone("INFO", "行情引擎启动，开始挂载数据源...")
        
        # [Master-Slave架构] 检查主交易程序 (LOFarb) 是否正在运行
        import socket
        lof_is_running = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.1)
            # 5000 是 LOF02_fetch_trade_data.py 的主端口
            if sock.connect_ex(("127.0.0.1", 5000)) == 0:
                lof_is_running = True
                
        if lof_is_running:
            msg = "⚠️ [主从架构] 检测到主交易程序(LOFarb)正在运行！当前为只读监控模式(Slave)，主动禁用通达信(tdx)行情，避免多开冲突崩溃。"
            logger.warning(msg)
            if self.system_status: self.system_status.add_milestone("WARNING", msg)
            if "tdx" in self.priority_list:
                self.priority_list.remove("tdx")
            full_config = [item for item in full_config if item['source_name'] != 'tdx']
        
        import json
        source_name_map = {
            "tdx": "通达信",
            "guojin": "国金QMT",
            "galaxy": "银河QMT",
            "sina": "新浪财经"
        }

        for item in full_config:
            source_name_key = item['source_name']
            source_name_cn = source_name_map.get(source_name_key, source_name_key)

            config_dict = {}
            try:
                config_dict = json.loads(item.get('config_json', '{}'))
            except: pass

            if source_name_key in self.fetcher_classes:
                try:
                    if source_name_key == "galaxy":
                        fetcher = self.fetcher_classes[source_name_key](
                            host=config_dict.get('host', '127.0.0.1'),
                            port=config_dict.get('port', 8888)
                        )
                    else:
                        fetcher = self.fetcher_classes[source_name_key]()
                except Exception as e:
                    msg = f"实例化 {source_name_cn} 失败: {e}"
                    logger.error(msg)
                    if self.system_status: self.system_status.add_milestone("ERROR", msg)
                    continue

                if fetcher.connect():
                    fetcher.set_on_update(self._on_internal_update)
                    self.active_fetchers[source_name_key] = fetcher
                    msg = f"数据源已成功挂载: {source_name_cn}"
                    logger.info(f"✅ {msg}")
                    if self.system_status: self.system_status.add_milestone("SUCCESS", msg)

                    if self.symbols:
                        fetcher.subscribe(self.symbols)
                else:
                    msg = f"数据源连接失败: {source_name_cn}"
                    if self.system_status: self.system_status.add_milestone("WARNING", msg)
        
        # 如果没有任何主源成功，尝试启动新浪兜底
        if not self.active_fetchers and "sina" in self.priority_list:
            sina = SinaRealtimeFetcher()
            if sina.connect():
                sina.set_on_update(self._on_internal_update)
                self.active_fetchers["sina"] = sina
                if self.symbols:
                    sina.subscribe(self.symbols)
                logger.warning("⚠️ 所有极速源失效，已启动【新浪轮询】兜底")

    def subscribe(self, symbols: List[str]):
        self.symbols = list(set(self.symbols + symbols))
        for fetcher in self.active_fetchers.values():
            fetcher.subscribe(symbols)

    def set_on_update(self, callback):
        self._on_update_callback = callback

    def _on_internal_update(self, symbol, quote):
        if self._on_update_callback:
            self._on_update_callback(symbol, quote)

    def get_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """按照优先级从活跃源中获取行情"""
        for source_name in (self.priority_list or ["tdx", "guojin", "galaxy", "tencent", "sina"]):
            if source_name in self.active_fetchers:
                quote = self.active_fetchers[source_name].get_quote(symbol)
                if quote and quote.get('price', 0) > 0:
                    return quote
        return None

    def stop(self):
        for fetcher in self.active_fetchers.values():
            fetcher.disconnect()
        self.active_fetchers.clear()
