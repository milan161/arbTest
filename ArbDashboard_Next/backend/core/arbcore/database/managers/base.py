import sqlite3
import threading
import logging
import os
from datetime import datetime
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class BaseManager:
    def __init__(self, db_path, lock=None):
        self.db_path = db_path
        self.lock = lock or threading.Lock()

    def _get_conn(self):
        try:
            conn = sqlite3.connect(self.db_path, timeout=15.0)
            try:
                conn.execute('PRAGMA journal_mode=WAL;')
            except Exception as e:
                logger.warning(f"Failed to enable WAL mode: {e}")
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to database at {self.db_path}: {e}")
            raise
