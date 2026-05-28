# -*- coding: utf-8 -*-
import time
import json
import threading
import requests
import random
import pandas as pd
from datetime import datetime
from readers.base_app import setup_logging

# 尝试导入行情库
try:
    from futu import OpenQuoteContext, SubType, Session
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

class MarketGateway:
    """
    行情网关：统一管理 A股、美股、期货等多种实时行情来源
    """
    def __init__(self, db_manager, socketio=None):
        self.logger = setup_logging("market_gateway")
        self.db = db_manager
        self.socketio = socketio
        self.futu_reader = FutuReader(self.logger)
        self.sina_futures_reader = SinaFuturesReader(self.logger, self.socketio)
        self.sse_futures_reader = SSEFuturesReader(self.logger, self.socketio, self.sina_futures_reader)
        self.lof_price_reader = LOFPriceReader(self.logger, self.db, self.socketio)

    def start_all(self):
        self.logger.info("🚀 正在启动所有行情监听服务...")
        self.sse_futures_reader.start_sse_listener()
        self.lof_price_reader.start_price_polling()

    def stop_all(self):
        self.logger.info("🛑 正在停止所有行情监听服务...")
        self.sse_futures_reader.stop_sse_listener()
        self.lof_price_reader.stop_price_polling()
        self.futu_reader.close()

class FutuReader:
    def __init__(self, logger):
        self.logger = logger
        self.ctx = None
        self.prices = {}
        self.subscribed_codes = set()
        self.last_connect_time = 0
        self.last_log_time = 0
        
    def close(self):
        if self.ctx:
            try: self.ctx.close()
            except: pass
            self.ctx = None

    def get_prices(self, symbols):
        if not FUTU_AVAILABLE:
            return False, "未安装 futu-api", self.prices
        try:
            if self.ctx is None:
                if time.time() - self.last_connect_time < 60:
                    return False, "等待重连...", self.prices
                self.last_connect_time = time.time()
                self.ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                self.subscribed_codes = set()
            
            futu_codes = [f"US.{sym}" for sym in symbols]
            new_codes = [c for c in futu_codes if c not in self.subscribed_codes]
            if new_codes:
                ret, data = self.ctx.subscribe(new_codes, [SubType.QUOTE], session=Session.ALL)
                if ret != 0:
                    self.close()
                    return False, f"订阅失败: {data}", self.prices
                self.subscribed_codes.update(new_codes)
            
            ret, data = self.ctx.get_stock_quote(futu_codes)
            if ret == 0:
                for _, row in data.iterrows():
                    code = row['code'].replace('US.', '')
                    bid, ask, last = 0.0, 0.0, 0.0
                    if 'bid_price_0' in row and pd.notna(row['bid_price_0']): bid = float(row['bid_price_0'])
                    if 'ask_price_0' in row and pd.notna(row['ask_price_0']): ask = float(row['ask_price_0'])
                    if 'last_price' in row and pd.notna(row['last_price']): last = float(row['last_price'])
                    
                    if bid <= 0 or ask <= 0:
                        fallback = 0.0
                        for k in ['overnight_price', 'pre_price', 'after_price', 'last_price']:
                            if k in row and pd.notna(row[k]) and float(row[k]) > 0:
                                fallback = float(row[k]); break
                        if fallback > 0:
                            if bid <= 0: bid = fallback
                            if ask <= 0: ask = fallback
                    
                    if bid <= 0 and last > 0: bid = last
                    if ask <= 0 and last > 0: ask = last
                    if bid > 0 and ask <= 0: ask = bid
                    
                    if bid > 0:
                        self.prices[code] = {'bid': bid, 'ask': ask, 'last': last if last > 0 else bid}
                return True, "成功", self.prices
            else:
                self.close()
                return False, f"获取失败: {data}", self.prices
        except Exception as e:
            self.close()
            return False, str(e), self.prices

class SinaFuturesReader:
    def __init__(self, logger, socketio):
        self.logger = logger
        self.socketio = socketio
        self.prices = {'GC': 0, 'CL': 0, 'AG': 0, 'NQ': 0, 'ES': 0}
        self.prev_prices = {'GC': 0, 'CL': 0, 'AG': 0, 'NQ': 0, 'ES': 0}
        self.settlement_prices = {'AG': 0, 'GC': 0, 'CL': 0, 'NQ': 0, 'ES': 0}
        self.headers = {'Referer': 'https://finance.sina.com.cn/'}
    
    def is_trading_time(self):
        now = time.localtime()
        h, m, wd = now.tm_hour, now.tm_min, now.tm_wday
        if 0 <= wd <= 4:
            if (9 <= h <= 11) or (13 <= h <= 15) or (h >= 21) or (h < 3): return True
        elif wd == 5 and h < 3: return True
        return False
    
    def update_prices(self):
        url = "http://hq.sinajs.cn/list=hf_GC,hf_CL,nf_AG0,hf_NQ,hf_ES"
        try:
            res = requests.get(url, headers=self.headers, timeout=10, proxies={"http": None, "https": None})
            res.encoding = 'gbk'
            if res.status_code == 200:
                for line in res.text.strip().split('\n'):
                    parts = line.split('"')
                    if len(parts) < 2: continue
                    v = parts[1].split(',')
                    sym_map = {'hf_GC': 'GC', 'hf_CL': 'CL', 'hf_NQ': 'NQ', 'hf_ES': 'ES'}
                    for k, sym in sym_map.items():
                        if k in line and len(v) >= 14:
                            curr, sett = float(v[0]), float(v[7])
                            if self.prices[sym] != curr:
                                self.prices[sym] = curr
                                if self.socketio:
                                    self.socketio.emit('futures_price_update', {'symbol': sym, 'price': curr, 'source': 'Sina'})
                            self.prev_prices[sym] = sett
                            self.settlement_prices[sym] = sett
                    if 'nf_AG0' in line and len(v) >= 15:
                        buy, sell = float(v[6]), float(v[7])
                        new_p = (buy + sell) / 2 if buy > 0 and sell > 0 else float(v[3])
                        if self.prices['AG'] != new_p:
                            self.prices['AG'] = new_p
                            if self.socketio:
                                self.socketio.emit('futures_price_update', {'symbol': 'AG', 'price': new_p, 'source': 'Sina'})
                        self.settlement_prices['AG'] = float(v[9]) if float(v[9])>0 else float(v[11])
        except Exception as e:
            self.logger.error(f"SinaFutures update error: {e}")

class SSEFuturesReader:
    def __init__(self, logger, socketio, sina_reader):
        self.logger = logger
        self.socketio = socketio
        self.sina_reader = sina_reader
        self.ag0_price, self.ag0_settlement, self.ag0_vwap = 0.0, 0.0, 0.0
        self.running = False

    def start_sse_listener(self):
        if not self.running:
            self.running = True
            threading.Thread(target=self._sse_listener, daemon=True).start()

    def stop_sse_listener(self): self.running = False

    def _sse_listener(self):
        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        while self.running:
            if not self.sina_reader.is_trading_time():
                time.sleep(10); continue
            try:
                res = requests.get(url, stream=True, timeout=(5,30), verify=False, proxies={"http": None, "https": None})
                if res.status_code == 200:
                    for line in res.iter_lines():
                        if not self.running: break
                        if line and line.decode('utf-8').startswith('data:'):
                            d = json.loads(line.decode('utf-8')[5:])['qt']
                            if 'p' in d:
                                self.ag0_price = float(d['p'])
                                if self.socketio:
                                    self.socketio.emit('futures_price_update', {'symbol': 'AG0', 'price': self.ag0_price, 'source': 'SSE'})
                            if 'fzjsj' in d and d['fzjsj'] != '-': self.ag0_settlement = float(d['fzjsj'])
                            if 'cje' in d and 'vol' in d and d['vol'] > 0: self.ag0_vwap = d['cje'] / (d['vol'] * 15)
            except:
                self.sina_reader.update_prices()
                time.sleep(5)

class LOFPriceReader:
    def __init__(self, logger, db, socketio):
        self.logger = logger
        self.db = db
        self.socketio = socketio
        self.lof_prices = {}
        self.running = False
        self.use_tdx = False
        self.use_qmt = False
        self.preferred_source = "tongdaxin"

    def start_price_polling(self):
        self.logger.info(f"📡 行情引擎启动 (首选: {self.preferred_source})")
        # 这里简化了原有的复杂逻辑，仅保留核心框架
        # 实际实现应包含 QMT/TDX 的挂载逻辑
        self.running = True

    def stop_price_polling(self): self.running = False
