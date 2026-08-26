import asyncio
import logging
from datetime import datetime
import pandas as pd
from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator

logger = logging.getLogger(__name__)

def _scalar_level(v):
    """[AI-2026-08-24] A股实时源(tdx/sina/guojin/galaxy/tencent)的bid/ask为5档list，
    IB/FUTU分支为标量买一/卖一。统一取首档（list[0]）或原值，避免list>int崩溃。"""
    if isinstance(v, (list, tuple)) and v:
        return float(v[0]) if v[0] is not None else 0
    return v

class IntradaySamplerService:
    """
    分时数据采样服务 (每分钟执行一次)
    负责在交易时段采集实时价格、实时估值、实时溢价率并存入数据库。
    """
    def __init__(self, db_manager, market_data_service, config_service):
        self.db = db_manager
        self.market_data = market_data_service
        self.config_service = config_service
        self.calculator = DynamicValuationCalculator(db_manager)
        self.running = False
        self._task = None
        self.active_watchlist = []
        self.lof_prices = {}   # [2026-08-21] LOF买卖一价缓存
        self.etf_prices = {}   # [2026-08-21] ETF买卖一价缓存

    async def start(self):
        if self.running: return

        # [AI-2026-08-18] 启用分时采样服务：
        # - 只采样重点基金（target_codes = {'162411'}），DB 压力可控
        # - 汇率改用 DB 美元中间价（exchange_rate.usd_cny_mid），零网络请求
        # - 实时价格从内存缓存读取，零网络请求
        # - 每60秒采样一次，仅 A股交易时段（9:30-15:00）
        enable_sampler = True

        if not enable_sampler:
            logger.info("ℹ️ 分时采样服务已根据配置禁用 (enable_intraday_sampler 默认为 False)")
            return
            
        self.running = True
        self._task = asyncio.create_task(self._sampling_loop())
        logger.info("分时采样服务已启动")

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
        logger.info("⏹️ 分时采样服务已停止")

    def is_market_open(self):
        """判断是否为 A 股交易时间 (9:30-11:30, 13:00-15:00)"""
        now = datetime.now()
        # 排除周末
        if now.weekday() >= 5: return False
        
        current_time = now.strftime('%H:%M')
        if '09:30' <= current_time <= '11:30' or '13:00' <= current_time <= '15:00':
            return True
        return False

    async def _sampling_loop(self):
        while self.running:
            try:
                if self.is_market_open():
                    # [修复] 同步网络/DB 调用不应跑在事件循环上，整体丢线程池避免 head-of-line 阻塞
                    await asyncio.to_thread(self._perform_sample_sync)
            except Exception as e:
                import traceback
                logger.error(f"🚨 采样循环异常: {e}")
                logger.error(traceback.format_exc())
            
            # 每 60 秒采样一次
            await asyncio.sleep(60)

    def _perform_sample_sync(self):
        try:
            # 加载所有的配置基金
            all_config_funds = []
            try:
                cfg = self.config_service.get_full_config() or {}
                all_config_funds = cfg.get('funds', []) or []
            except Exception as e:
                logger.error(f"采样服务读取配置基金失败: {e}")

            # [AI-2026-08-20] 东哥指定常用基金：162411（华宝油气）+ 164701（汇添富贵金属）+ 161116（易方达黄金）
            # 最多5只，每只每天约240条（4小时×60分钟），5只 = 1200条/天，10天 = 12000条 ≈ 2MB
            target_codes = {'162411', '164701', '161116'}
            
            funds_to_sample = []
            for f in all_config_funds:
                if not isinstance(f, dict):
                    continue
                code = str(f.get('code', '')).strip()
                if code in target_codes:
                    funds_to_sample.append(f)
            
            logger.info(f"📊 采样服务临时限定处理测试基金: {len(funds_to_sample)} 只")
            if not funds_to_sample:
                return
            
            # [AI-2026-08-18] 改用美元中间价汇率（从 DB 读，不新增网络请求）
            # 东哥要求：LOF 基金只使用美元中间价，不需要新浪在岸价
            current_fx = None
            try:
                conn = self.db._get_conn()
                row = conn.execute("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1").fetchone()
                conn.close()
                if row and row[0]:
                    current_fx = float(row[0])
                    logger.info(f"📊 采样服务使用美元中间价汇率: {current_fx}")
            except Exception as e:
                logger.warning(f"⚠️ 获取美元中间价汇率失败: {e}")
            
            # [修复] 构建完整符号的实时价格字典（如 ^INDA-EU → 35.5）
            current_etfs = {}
            
            # 第一步：收集所有待采样基金对应的美股ETF（用于实时估值计算）
            us_etf_symbols = set()
            for f in funds_to_sample:
                if f is None:
                    continue
                # 获取估值组合中ETF的实时价格（完整符号如 ^INDA-EU）
                v_port = f.get('valuation_portfolio') or []
                h_port = f.get('hedging_portfolio') or []
                portfolio = v_port if v_port else h_port
                if portfolio is None: portfolio = []
                
                for item in portfolio:
                    if item is None:
                        continue
                    symbol = item.get('symbol', '')  # 完整符号（如 ^INDA-EU）
                    if not symbol:
                        continue
                    
                    # 过滤掉A股ETF代码（6位纯数字或带SZ/SH前缀）
                    clean_symbol = symbol.lstrip('^')
                    base_sym = clean_symbol
                    for suffix in ['-EU', '-JP', '-HK']:
                        if base_sym.endswith(suffix):
                            base_sym = base_sym[:-len(suffix)]
                            break
                            
                    if clean_symbol.isdigit() and len(clean_symbol) == 6:
                        continue
                    if symbol.upper().startswith(('SZ', 'SH')):
                        continue
                    
                    # [核心安全阀解除] 白名单限制已废除
                    # 因为混合基金的重负载美股(TSMC, NVDA等)已经硬路由至富途分流
                    # 剩下的核心套利ETF(GLD, USO, XOP等)不到20只，盈透(IB)完全可以全量接管夜盘流式订阅
                    
                    # 添加到待采集集合
                    us_etf_symbols.add(symbol)
            
            logger.info(f"📈 采样服务需要采集的美股ETF: {len(us_etf_symbols)} 只 ({', '.join(list(us_etf_symbols)[:5])})")
            
            # 第二步：采集所有美股ETF的实时价格（9:30-15:00）
            for symbol in us_etf_symbols:
                q = self.market_data.get_realtime_quote(symbol)
                if q and q.get('price'):
                    current_etfs[symbol] = q['price']
                    # [2026-08-24] 补订 ORDER_BOOK 获取真实买卖一价
                    futu_code = symbol.lstrip('^')
                    if hasattr(self.market_data, '_fetch_order_book'):
                        ob_bid, ob_ask, _, _, _, _ = self.market_data._fetch_order_book(futu_code)
                        if ob_bid and ob_bid > 0 and ob_ask and ob_ask > 0:
                            q['bid'] = ob_bid
                            q['ask'] = ob_ask
                    # [2026-08-21] 保存 ETF 买卖一价
                    if 'etf_prices' not in dir(self):
                        self.etf_prices = {}
                    self.etf_prices[symbol] = {
                        'bid': q.get('bid', 0),
                        'ask': q.get('ask', 0),
                        'price': q['price']
                    }
                    logger.info(f"📈 采样ETF: {symbol} price={q['price']}, bid={q.get('bid')}, ask={q.get('ask')}")
            
            # 第三步：采集自选LOF基金的实时价格
            for f in funds_to_sample:
                if f is None:  # [修复] 跳过None元素
                    continue
                
                # 获取LOF基金实时价格
                code = str(f.get('code', ''))
                if not code or not code.isdigit():
                    continue
                
                if code.isdigit() and len(code) in [5, 6]:
                    q = self.market_data.get_realtime_quote(code)
                    if q and q.get('price'):
                        current_etfs[code] = q['price']
                        # [2026-08-21] 保存 LOF 买卖一价
                        if 'lof_prices' not in dir(self):
                            self.lof_prices = {}
                        self.lof_prices[code] = {
                            'bid': q.get('bid', 0),
                            'ask': q.get('ask', 0),
                            'price': q['price']
                        }
            
            # 执行采样
            now = datetime.now()
            date_str = now.strftime('%Y-%m-%d')
            time_str = now.strftime('%H:%M')
            conn = self.db._get_conn()
            try:
                cursor = conn.cursor()
                for fund in funds_to_sample:
                    if fund is None:  # [修复] 跳过None元素
                        continue
                    code = fund['code']
                    # [2026-08-24] 修复：LOF价格从lof_prices获取，不是current_etfs
                    price = self.lof_prices.get(code, {}).get('price', 0)
                    if price <= 0:
                        continue
                    
                    # 计算实时估值（传入完整符号格式的current_etfs）
                    res = self.calculator.calculate(fund, current_fx, current_etfs)
                    if res and res.get('rt_val') and res['rt_val'] > 0:
                        rt_val = res['rt_val']
                        premium = (price / rt_val - 1) * 100

                        # [2026-08-21] 计算真实开仓/平仓溢价率
                        # open_premium = (LOF_ask1 / backendRtValSafe - 1) * 100  # 买LOF吃卖一
                        # close_premium = (LOF_bid1 / backendRtValPeg - 1) * 100   # 卖LOF吃买一
                        lof_ask = _scalar_level(self.lof_prices.get(code, {}).get('ask', 0))
                        lof_bid = _scalar_level(self.lof_prices.get(code, {}).get('bid', 0))

                        # backendRtValSafe: 用ETF买一价（bid）计算
                        #   开仓时卖空ETF吃买一（低价），成本保守→估值偏低→溢价偏高
                        # backendRtValPeg: 用ETF卖一价（ask）计算
                        #   平仓时买平ETF吃卖一（高价），成本激进→估值偏高→溢价偏低
                        portfolio = fund.get('valuation_portfolio', []) or fund.get('hedging_portfolio', [])
                        etf_symbol = portfolio[0].get('symbol', '') if portfolio else ''
                        etf_bid = _scalar_level(self.etf_prices.get(etf_symbol, {}).get('bid', 0)) if etf_symbol else 0
                        etf_ask = _scalar_level(self.etf_prices.get(etf_symbol, {}).get('ask', 0)) if etf_symbol else 0

                        # 构建safe/peg两种估值所需的ETF价格字典
                        etfs_safe = dict(current_etfs)  # 默认用last价
                        etfs_peg = dict(current_etfs)
                        if etf_symbol:
                            # safe估值：用ETF bid价（开仓卖空ETF吃买一，成本保守）
                            if etf_bid > 0:
                                etfs_safe[etf_symbol] = etf_bid
                            # peg估值：用ETF ask价（平仓买平ETF吃卖一，成本激进）
                            if etf_ask > 0:
                                etfs_peg[etf_symbol] = etf_ask

                        # 计算backendRtValSafe和backendRtValPeg
                        res_safe = self.calculator.calculate(fund, current_fx, etfs_safe)
                        res_peg = self.calculator.calculate(fund, current_fx, etfs_peg)
                        backend_rt_val_safe = res_safe.get('rt_val', 0) if res_safe else 0
                        backend_rt_val_peg = res_peg.get('rt_val', 0) if res_peg else 0

                        open_premium = None
                        close_premium = None
                        if lof_ask > 0 and backend_rt_val_safe > 0:
                            open_premium = (lof_ask / backend_rt_val_safe - 1) * 100
                        if lof_bid > 0 and backend_rt_val_peg > 0:
                            close_premium = (lof_bid / backend_rt_val_peg - 1) * 100

                        cursor.execute("""
                            INSERT INTO fund_intraday_quotes
                            (fund_code, date, time, price, rt_val, premium, open_premium, close_premium,
                             lof_bid1, lof_ask1, etf_bid1, etf_ask1)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (code, date_str, time_str, price, rt_val, premium,
                              open_premium, close_premium,
                              lof_bid, lof_ask, etf_bid, etf_ask))
                conn.commit()
            except Exception as e:
                logger.error(f"❌ 采样写入数据库失败: {e}")
                import traceback
                logger.error(traceback.format_exc())
            finally:
                conn.close()
                
        except Exception as e:
            import traceback
            logger.error(f"❌ _perform_sample 异常: {e}")
            logger.error(traceback.format_exc())
            raise
