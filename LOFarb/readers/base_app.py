# -*- coding: utf-8 -*-
# 兼容性垫片：将请求转发至中央基座 arbcore
import os
import sys

# 确保能找到项目根目录
READER_DIR = os.path.dirname(os.path.abspath(__file__))
LOFARB_DIR = os.path.dirname(READER_DIR)
ROOT_DIR = os.path.dirname(LOFARB_DIR)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from arbcore.base_app import BaseApp, setup_logging
