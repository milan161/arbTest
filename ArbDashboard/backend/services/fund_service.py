import os
import sys
import json
import time
import threading
import pandas as pd
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# ============================================================
# [V7.1] 内置东财SSE白银期货长连接阅读器
# 程序3独立直连东财推流，无需依赖程序1(5000端口)
# ============================================================
class SSEFuturesReader:
    """
    东财上期所白银期货(AGm)实时推流读取器。
    - 常驻后台线程，长连接到 https://81.futsseapi.eastmoney.com/sse/113_agm_qt
    - 自动重连，自动解析价格、结算价、VWAP
    - 程序3与程序1同时运行时，互不冲突（各自独立连接SSE推流，读同一组数据）
    """
    def __init__(self):
        self.ag0_price = 0.0
        self.ag0_settlement = 0.0
        self.ag0_vwap = 0.0
        self.running = False
        self._thread = None

    def start(self):
        """启动后台SSE监听线程（幂等：已运行则跳过）"""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="SSE-Silver")
        self._thread.start()
        logger.info("[SSE] 白银期货SSE后台线程已启动 (东财 113_agm_qt)")

    def stop(self):
        self.running = False

    def _is_trading_time(self) -> bool:
        """沪银交易时段：周一~周五 09:00-11:30, 13:30-15:00, 21:00-次日03:00; 周六 00:00-03:00"""
        import time as _t
        now = _t.localtime()
        h, m, wd = now.tm_hour, now.tm_min, now.tm_wday
        if 0 <= wd <= 4:
            if (h == 9 and m >= 0) or h == 10 or (h == 11 and m < 30): return True
            if (h == 13 and m >= 30) or h == 14 or (h == 15 and m == 0): return True
            if h >= 21 or h < 3: return True
        elif wd == 5 and h < 3: return True
        return False

    def _listen_loop(self):
        import requests
        url = "https://81.futsseapi.eastmoney.com/sse/113_agm_qt"
        retry_delay = 2.0
        while self.running:
            if not self._is_trading_time():
                time.sleep(15)
                continue
            try:
                res = requests.get(url, stream=True, timeout=(5, 60),
                                   verify=False, proxies={"http": None, "https": None})
                if res.status_code == 200:
                    retry_delay = 2.0
                    for line in res.iter_lines():
                        if not self.running:
                            break
                        if line:
                            decoded = line.decode('utf-8', errors='replace')
                            if decoded.startswith('data:'):
                                try:
                                    d = json.loads(decoded[5:]).get('qt', {})
                                    if 'p' in d:
                                        self.ag0_price = float(d['p'])
                                    if 'fzjsj' in d and d['fzjsj'] != '-':
                                        self.ag0_settlement = float(d['fzjsj'])
                                    elif 'rzjsj' in d and d['rzjsj'] != '-':
                                        self.ag0_settlement = float(d['rzjsj'])
                                    if 'cje' in d and 'vol' in d and d.get('vol', 0) > 0:
                                        self.ag0_vwap = d['cje'] / (d['vol'] * 15)
                                    elif 'av' in d and d['av'] != '-':
                                        self.ag0_vwap = float(d['av'])
                                except Exception:
                                    pass
                res.close()
            except Exception as e:
                logger.debug(f"[SSE] 白银长连接断开: {e}，{retry_delay:.0f}s后重连...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60.0)


# 全局单例 —— 在模块第一次被导入时创建，随后自动启动
_sse_reader = SSEFuturesReader()
_sse_reader.start()

def get_index_change_percent(symbol: str) -> float:
    """
    [新浪/腾讯指数极速接口] 直接拉取指数日内涨跌幅百分比
    无感对接国内指数（000xxx, 399xxx）、恒生指数HSI等，无需频繁维护静态基准价
    """
    import requests
    headers_sina = {
        'Referer': 'https://finance.sina.com.cn/',
        'Accept': 'text/event-stream'  # [V7.2] 借鉴长连接头部以提高稳定性
    }
    headers_tencent = {
        'Referer': 'https://finance.qq.com/',
        'User-Agent': 'Mozilla/5.0'
    }
    
    clean_sym = symbol.strip().upper()
    if clean_sym.endswith('.CSI'):
        clean_sym = clean_sym[:-4]
    
    try:
        # 1. 港股常见指数 - 必须先检查更长的字符串 HSTECH/HSCEI，再检查 HSI
        if 'HSTECH' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSTECH", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSTECH 涨跌幅: {parts[8]}%")
                    return float(parts[8])
        elif 'HSCEI' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSCEI", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSCEI 涨跌幅: {parts[8]}%")
                    return float(parts[8])
        elif 'HSI' in clean_sym:
            r = requests.get("http://hq.sinajs.cn/list=rt_hkHSI", headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 9:
                    logger.info(f"[INDEX-SINA] 获取港股指数 HSI 涨跌幅: {parts[8]}%")
                    return float(parts[8])
                    
        # 2. A股指数 (6位代码)
        elif clean_sym.isdigit() and len(clean_sym) == 6:
            # 优先尝试新浪接口
            if clean_sym.startswith('399') or clean_sym.startswith('159') or clean_sym.startswith('3999'):
                url = f"http://hq.sinajs.cn/list=s_sz{clean_sym}"
            else:
                url = f"http://hq.sinajs.cn/list=s_sh{clean_sym}"
                
            r = requests.get(url, headers=headers_sina, timeout=1.5)
            if r.status_code == 200 and '="' in r.text:
                parts = r.text.split('"')[1].split(',')
                if len(parts) >= 4 and float(parts[3]) != 0.0:
                    logger.info(f"[INDEX-SINA] 获取A股指数 {clean_sym} 涨跌幅: {parts[3]}%")
                    return float(parts[3])
                    
            # [V7.2] 新浪降级策略：使用腾讯接口兜底 (完美解决新浪没有中证指数的问题)
            prefix = 'sz' if clean_sym.startswith(('399', '159')) else 'sh'
            url_tencent = f"http://qt.gtimg.cn/q={prefix}{clean_sym}"
            r_tc = requests.get(url_tencent, headers=headers_tencent, timeout=1.5)
            if r_tc.status_code == 200 and 'v_' in r_tc.text:
                tc_parts = r_tc.text.split('"')[1].split('~')
                if len(tc_parts) >= 33:
                    logger.info(f"[INDEX-TENCENT] 兜底获取指数 {clean_sym} 涨跌幅: {tc_parts[32]}%")
                    return float(tc_parts[32])
    except Exception as e:
        logger.debug(f"Index fetch failed for {symbol}: {e}")
    return 0.0

def prefetch_index_changes(symbols: List[str]) -> Dict[str, Dict[str, float]]:
    """
    [V6.0 性能优化] 批量预取新浪/腾讯指数数据，将 O(N) 降低为 O(1)
    返回 { "399300": {"price": 4000.0, "pct": 1.63}, ... }
    """
    if not symbols:
        return {}
        
    import requests
    headers_sina = {
        'Referer': 'https://finance.sina.com.cn/',
        'Accept': 'text/event-stream'
    }
    headers_tencent = {
        'Referer': 'https://finance.qq.com/',
        'User-Agent': 'Mozilla/5.0'
    }
    
    sina_codes = []
    tencent_codes = []
    symbol_map = {}  # code -> original_symbol
    tencent_symbol_map = {} # tc_code -> original_symbol
    
    for sym in symbols:
        if not sym or sym == '-':
            continue
        clean_sym = sym.strip().upper()
        if clean_sym.endswith('.CSI'):
            clean_sym = clean_sym[:-4]
            
        if clean_sym.isdigit() and len(clean_sym) == 6:
            if clean_sym.startswith('399') or clean_sym.startswith('159') or clean_sym.startswith('3999'):
                sina_codes.append(f"s_sz{clean_sym}")
                tencent_codes.append(f"sz{clean_sym}")
            else:
                sina_codes.append(f"s_sh{clean_sym}")
                tencent_codes.append(f"sh{clean_sym}")
            symbol_map[clean_sym] = sym
            tencent_symbol_map[clean_sym] = sym
                
        elif 'HSTECH' in clean_sym:
            sina_codes.append("rt_hkHSTECH")
            tencent_codes.append("hkHSTECH")
            symbol_map['HSTECH'] = sym
            tencent_symbol_map['HSTECH'] = sym
        elif 'HSCEI' in clean_sym:
            sina_codes.append("rt_hkHSCEI")
            tencent_codes.append("hkHSCEI")
            symbol_map['HSCEI'] = sym
            tencent_symbol_map['HSCEI'] = sym
        elif 'HSI' in clean_sym:
            sina_codes.append("rt_hkHSI")
            tencent_codes.append("hkHSI")
            tencent_symbol_map['HSI'] = sym
            
    res = {}
    
    # 1. 尝试从新浪获取
    if sina_codes:
        url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"
        try:
            r = requests.get(url, headers=headers_sina, timeout=2.0)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if '="' not in line: continue
                    var_name = line.split('=')[0].strip()
                    parts = line.split('"')[1].split(',')
                    
                    if var_name.startswith('var hq_str_s_sh') or var_name.startswith('var hq_str_s_sz'):
                        code = var_name[-6:]
                        if len(parts) >= 4 and float(parts[3]) != 0.0:
                            if code in symbol_map:
                                res[symbol_map[code]] = {"price": float(parts[1]), "pct": float(parts[3])}
                                logger.info(f"[INDEX-SINA] 获取A股指数 {symbol_map[code]} 价格: {parts[1]} 涨跌幅: {parts[3]}%")
                    elif var_name.startswith('var hq_str_rt_hk'):
                        code = var_name.split('rt_hk')[1]
                        if len(parts) >= 9:
                            if code in symbol_map:
                                res[symbol_map[code]] = {"price": float(parts[6]), "pct": float(parts[8])}
                                logger.info(f"[INDEX-SINA] 获取港股指数 {symbol_map[code]} 价格: {parts[6]} 涨跌幅: {parts[8]}%")
        except Exception as e:
            logger.warning(f"预取新浪指数异常: {e}")
            
    # 2. 对于新浪没拿到数据的指数，用腾讯接口批量兜底
    missing_tc_codes = []
    missing_tc_keys = []
    for tc_code, tc_req in zip(symbol_map.keys(), tencent_codes):
        if symbol_map[tc_code] not in res:
            missing_tc_codes.append(tc_req)
            missing_tc_keys.append(tc_code)
            
    if missing_tc_codes:
        url_tc = f"http://qt.gtimg.cn/q={','.join(missing_tc_codes)}"
        try:
            r_tc = requests.get(url_tc, headers=headers_tencent, timeout=2.0)
            if r_tc.status_code == 200:
                for line in r_tc.text.split(';'):
                    if 'v_' not in line or '=' not in line: continue
                    var_name = line.split('=')[0].strip()
                    data_str = line.split('=')[1].strip(' "')
                    tc_parts = data_str.split('~')
                    
                    if len(tc_parts) >= 33:
                        code = tc_parts[2] # e.g. 000922, HSI
                        if code in tencent_symbol_map:
                            res[tencent_symbol_map[code]] = {"price": float(tc_parts[3]), "pct": float(tc_parts[32])}
                            logger.info(f"[INDEX-TENCENT] 兜底获取指数 {tencent_symbol_map[code]} 价格: {tc_parts[3]} 涨跌幅: {tc_parts[32]}%")
        except Exception as e:
            logger.warning(f"预取腾讯指数兜底异常: {e}")
            
    return res

class FundService:
    def __init__(self, db, market_data_service=None, config_service=None):
        self.db = db
        self.market_data_service = market_data_service
        self.config_service = config_service
        self._calculator = None
    
    def _get_calculator(self):
        """懒加载估值计算器"""
        if self._calculator is None:
            try:
                from arbcore.calculators.dynamic_valuation import DynamicValuationCalculator
                self._calculator = DynamicValuationCalculator(self.db)
            except Exception as e:
                logger.error(f"初始化估值计算器失败: {e}")
        return self._calculator

    def get_unified_dashboard_data(self, watchlist: List[str] = None) -> List[Dict[str, Any]]:
        """
        [V3.8] 终极工业版 - 彻底解决 0 和 None 值的显示 Bug
        [V4.6] 全面防御性编程 - 防止所有 NoneType 错误
        [V6.2] 支持自选过滤加快性能
        """
        conn = self.db._get_conn()
        try:
            funds_df = pd.read_sql_query("SELECT fund_code, fund_name, category, related_index, pos_ratio, idx_code, idx_name FROM unified_fund_list", conn)
            if watchlist and not funds_df.empty:
                watchlist_strs = [str(w) for w in watchlist]
                funds_df = funds_df[funds_df['fund_code'].astype(str).isin(watchlist_strs)]
            
            # 从 fund_info 表读取用户爬虫获取的状态和费率
            status_df = pd.read_sql_query("SELECT fund_code, purchase_status, redemption_status, purchase_fee, redemption_fee FROM fund_info", conn)
            status_dict = status_df.set_index('fund_code').to_dict('index')
            
            if funds_df is None or funds_df.empty:
                logger.warning("未获取到基金列表，返回空数据")
                return []
            
            # 【V7.0 工业级升级】 批量预取所有跟踪指数的日内涨跌幅，用于加速国内LOF与QDII亚洲的实时估值计算
            all_related_indices = funds_df['related_index'].dropna().tolist()
            index_changes_map = prefetch_index_changes(all_related_indices)

            result = []
            for _, fund in funds_df.iterrows():
                if fund is None:
                    continue
                code = fund['fund_code']
                
                # 1. 获取历史记录 (找锚点)
                query_metrics = f"""
                    SELECT date, price, nav, static_val, premium as static_premium,
                           volume, shares, shares_added, turnover_rate
                    FROM unified_fund_history
                    WHERE fund_code='{code}'
                    ORDER BY date DESC LIMIT 10
                """
                metrics_df = pd.read_sql_query(query_metrics, conn)
                metrics = {'price': 0, 'nav': 0, 'static_val': 0, 'static_premium': 0, 'rt_val': None, 'rt_premium': None}
                
                if not metrics_df.empty:
                    # 关键：锁定最新有效净值日期
                    valid_navs = metrics_df.dropna(subset=['nav'])
                    if not valid_navs.empty:
                        metrics['nav'] = valid_navs.iloc[0]['nav']
                        metrics['nav_date'] = valid_navs.iloc[0]['date']
                    
                    # 锁定最新静态估值
                    valid_vals = metrics_df.dropna(subset=['static_val'])
                    if not valid_vals.empty and float(valid_vals.iloc[0]['static_val']) > 0:
                        val = float(valid_vals.iloc[0]['static_val'])
                        # 🚀 脏数据拦截：如果 static_val 偏离 nav 超过 50%（如 0.0476 vs 1.78），必定是异常脏数据，强制使用 nav
                        if metrics.get('nav', 0) > 0 and abs(val - metrics['nav']) / metrics['nav'] > 0.5:
                            metrics['static_val'] = metrics['nav']
                        else:
                            metrics['static_val'] = val
                    else:
                        metrics['static_val'] = metrics.get('nav', 0)
                    
                    # 历史价格兜底
                    valid_prices = metrics_df.dropna(subset=['price'])
                    if not valid_prices.empty:
                        metrics['price'] = valid_prices.iloc[0]['price']
                        
                    # 恢复基本面的缺失字段 (成交额、份额、换手率等)
                    for col in ['volume', 'shares', 'shares_added', 'turnover_rate']:
                        valid_series = metrics_df.dropna(subset=[col])
                        metrics[col] = float(valid_series.iloc[0][col]) if not valid_series.empty else 0.0
                        
                    # 🚀 动态计算缺失的“新增(万)”份额
                    if metrics.get('shares_added') == 0.0:
                        valid_shares = metrics_df.dropna(subset=['shares'])
                        if len(valid_shares) >= 2:
                            shares_t = float(valid_shares.iloc[0]['shares'])
                            shares_t1 = float(valid_shares.iloc[1]['shares'])
                            metrics['shares_added'] = float(shares_t - shares_t1)
                            
                    # 🚀 动态计算缺失的“换手率”
                    if metrics.get('turnover_rate') == 0.0:
                        vol = metrics.get('volume', 0)
                        sh = metrics.get('shares', 0)
                        pr = metrics.get('price', 0)
                        # 假设 volume 是成交额(RMB)，shares 是万份
                        if vol > 0 and sh > 0 and pr > 0:
                            # 换手率 = 成交额 / (份额(万) * 10000 * 价格)
                            metrics['turnover_rate'] = vol / (sh * 10000.0 * pr)

                    # 计算前收盘价用于涨跌幅计算
                    # 注意：unified_fund_history 存的是历史日结数据，所以它的第 0 行就是昨天的收盘价
                    if not valid_prices.empty:
                        metrics['prev_close'] = valid_prices.iloc[0]['price']
                    else:
                        metrics['prev_close'] = 0

                # 2. [V4.0] 灵魂逻辑：现价必须从实时接口获取（毫秒级），用于套利计算
                if self.market_data_service:
                    rt = self.market_data_service.get_realtime_quote(code)
                    if rt and rt.get('price'):
                        metrics['price'] = rt['price']  # 毫秒级实时价格
                        if rt.get('amount'):
                            metrics['volume'] = rt['amount']
                
                # 3. [V6.1 核心机制升级] 永远优先实时计算最新估值，仅在实时计算失败时才从采样表进行历史兜底
                metrics['rt_val'] = None
                metrics['rt_premium'] = None
                
                # 尝试实时计算估值
                try:
                    # 3.1 【白银基金 161226 特殊行情特判】 - 完全同步自程序 1（东财 SSE 接口）的稳定算法
                    if code == '161226':
                        import requests
                        ag_future_price, settlement_price, vwap = 0.0, 0.0, 0.0
                        
                        # [优先级1] 本程序自带的东财SSE长连接阅读器（最精准，无需程序1）
                        if _sse_reader.ag0_price > 0 and _sse_reader.ag0_settlement > 0:
                            ag_future_price = _sse_reader.ag0_price
                            settlement_price = _sse_reader.ag0_settlement
                            vwap = _sse_reader.ag0_vwap
                        
                        # [优先级2] 若SSE还没数据（刚启动），尝试从程序1(5000端口)获取
                        if ag_future_price <= 0 or settlement_price <= 0:
                            try:
                                r = requests.get("http://127.0.0.1:5000/api/futures", timeout=1.0)
                                if r.status_code == 200:
                                    f_data = r.json()
                                    ag0 = f_data.get('AG0', {})
                                    ag_future_price = float(ag0.get('price', 0))
                                    settlement_price = float(ag0.get('settlement', 0))
                                    vwap = float(ag0.get('vwap', 0))
                            except:
                                pass
                        
                        # [优先级3] 降级：新浪 nf_AG0 接口兜底
                        if ag_future_price <= 0 or settlement_price <= 0:
                            try:
                                headers = {'Referer': 'https://finance.sina.com.cn/'}
                                r = requests.get("http://hq.sinajs.cn/list=nf_AG0", headers=headers, timeout=1.5)
                                if r.status_code == 200 and '="' in r.text:
                                    parts = r.text.split('"')[1].split(',')
                                    if len(parts) >= 11:
                                        ag_future_price = float(parts[8])   # 最新价
                                        settlement_price = float(parts[10])  # 昨结算价
                                        # 新浪接口 part[9] 即为今日动态结算均价(VWAP)
                                        vwap = float(parts[9]) if len(parts) > 9 else 0.0
                            except:
                                pass
                                
                        nav_home = float(metrics.get('nav', 0))
                        if ag_future_price > 0 and settlement_price > 0 and nav_home > 0:
                            # 🚀 为了让前端展示 AG0 盘口数据
                            metrics['ag0_price'] = ag_future_price
                            metrics['ag0_settlement'] = settlement_price
                            
                            # 参考估值 (rt_val) = 昨天净值 * (实时成交价 / 昨结算价)
                            rt_val = nav_home * (ag_future_price / settlement_price)
                            metrics['rt_val'] = round(rt_val, 4)
                            if metrics['price'] > 0:
                                metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)
                                
                            # 🚀 官方估值 (static_val) = 昨天净值 * (VWAP / 昨结算价)
                            if vwap > 0:
                                metrics['static_val'] = round(nav_home * (vwap / settlement_price), 4)
                            else:
                                # 如果盘中没取到 vwap，就降级为 NAV (避免出现脏数据)
                                metrics['static_val'] = nav_home
                                
                            # 联动计算官方溢价
                            if metrics['static_val'] > 0 and metrics.get('price', 0) > 0:
                                metrics['static_premium'] = round((metrics['price'] / metrics['static_val'] - 1) * 100, 3)


                    # 3.2 【普通国内LOF/QDII亚洲极速估值】 - 直连新浪指数接口，不占用美股 API，免去自选条件直接计算
                    if not metrics.get('rt_val'):
                        rel_idx = fund.get('related_index')
                        nav_home = float(metrics.get('nav', 0))
                        if rel_idx and rel_idx != '-' and nav_home > 0:
                            idx_data = index_changes_map.get(rel_idx)
                            pct = 0.0
                            if idx_data is not None and isinstance(idx_data, dict):
                                pct = idx_data.get('pct', 0.0)
                                metrics['index_close'] = idx_data.get('price', 0.0)
                            else:
                                pct = get_index_change_percent(rel_idx)
                            
                            # 🚀 把最新涨跌幅赋值给 metrics 供看板展示
                            metrics['index_pct'] = pct
                            
                            if pct != 0.0:
                                pos = float(fund.get('pos_ratio') or 0.95)
                                rt_val = nav_home * (1.0 + pos * (pct / 100.0))
                                metrics['rt_val'] = round(rt_val, 4)
                                if metrics.get('price', 0) > 0:
                                    metrics['rt_premium'] = round((metrics['price'] / rt_val - 1) * 100, 3)

                    # 3.3 【美股原油/黄金等高价值一篮子基金】 - 保持原有基于 lof_config.yaml 的矩阵公式推演
                    calculator = self._get_calculator() if not metrics.get('rt_val') else None
                    if calculator:
                        # 获取基金配置
                        fund_config = self.config_service.get_full_config().get('funds', [])
                        fund_cfg = None
                        for f in fund_config:
                            if str(f.get('code')) == code:
                                fund_cfg = f
                                break
                        
                        if fund_cfg:
                            # 获取最新汇率
                            current_fx = None 
                            try:
                                fx_df = pd.read_sql(
                                    "SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1",
                                    conn
                                )
                                if not fx_df.empty and fx_df.iloc[0]['usd_cny_mid'] > 0:
                                    current_fx = fx_df.iloc[0]['usd_cny_mid']
                            except:
                                pass
                            
                            if current_fx and current_fx > 0:
                                # 获取实时 ETF 价格
                                current_etfs = {}
                                if self.market_data_service:
                                    portfolio = fund_cfg.get('valuation_portfolio', []) or fund_cfg.get('hedging_portfolio', [])
                                    for item in portfolio:
                                        sym = item.get('symbol', '').replace('^', '')
                                        # 去掉地区后缀，得到基础代码 USO/GLD
                                        for suffix in ['-EU', '-JP', '-HK']:
                                            if sym.endswith(suffix):
                                                sym = sym[:-len(suffix)]
                                                break
                                        q = self.market_data_service.get_realtime_quote(sym)
                                        if q and q.get('price'):
                                            current_etfs[sym] = q['price']
                                
                                # 计算实时估值
                                res = calculator.calculate(fund_cfg, current_fx, current_etfs)
                                val_res = res.get('rt_val') if res else None
                                if val_res and val_res > 0:
                                    metrics['rt_val'] = round(val_res, 4)
                                    # 重新计算溢价率
                                    if metrics['price'] > 0:
                                        metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)
                                
                                # 尝试基于指数的实时估值 (QDII亚洲, 国内指数等)
                                if not val_res:
                                    tracking_index = fund_cfg.get('tracking_index')
                                    if tracking_index and self.market_data_service:
                                        q = self.market_data_service.get_realtime_quote(tracking_index)
                                        if q and q.get('price') and q.get('price') > 0:
                                            idx_price = q['price']
                                            base_data = calculator.get_base_data(code)
                                            if base_data and base_data.get('index_close') and base_data['index_close'] > 0:
                                                index_b = base_data['index_close']
                                                b_nav = base_data.get('nav', 0)
                                                position = base_data.get('position', 1.0)
                                                if pd.isna(position):
                                                    position = fund_cfg.get('holdings', {}).get('equity_ratio', 100.0) / 100.0
                                                
                                                fx_ratio = 1.0
                                                # 如果支持获取汇率日内波动，可以在这里添加 fx_ratio = 1 + fx_pct / 100
                                                index_ratio = idx_price / index_b
                                                
                                                # 🚀 把最新指数价格和涨跌幅赋值给 metrics 供看板展示
                                                metrics['index_close'] = idx_price
                                                metrics['index_pct'] = (index_ratio - 1) * 100
                                                
                                                val_res = b_nav * (1 + position * (index_ratio * fx_ratio - 1))
                                                if val_res > 0:
                                                    metrics['rt_val'] = round(val_res, 4)
                                                    if metrics['price'] > 0:
                                                        metrics['rt_premium'] = round((metrics['price'] / metrics['rt_val'] - 1) * 100, 3)
                except Exception as e:
                    logger.error(f"实时计算 {code} 估值失败: {e}")

                # [V6.1] 备用兜底：如果实时计算失败（例如未连行情源，或美股休市无最新价），从采样表获取最近一次的记录
                if not metrics.get('rt_val') or metrics['rt_val'] <= 0:
                    try:
                        sample_query = "SELECT rt_val, premium FROM fund_intraday_quotes WHERE fund_code=? ORDER BY date DESC, time DESC LIMIT 1"
                        sample_df = pd.read_sql(sample_query, conn, params=(code,))
                        if not sample_df.empty and sample_df.iloc[0]['rt_val'] > 0:
                            metrics['rt_val'] = sample_df.iloc[0]['rt_val']
                            metrics['rt_premium'] = sample_df.iloc[0]['premium']
                        else:
                            metrics['rt_val'] = 0
                            metrics['rt_premium'] = 0
                    except Exception as e:
                        logger.error(f"从采样表获取 {code} 历史记录失败: {e}")
                        metrics['rt_val'] = 0
                        metrics['rt_premium'] = 0

                # 3. [V4.0] 灵魂逻辑重算 (确保静态溢价率和涨跌幅不为 0)
                cp = float(metrics.get('price') or 0)
                sv = float(metrics.get('static_val') or 0)
                pc = float(metrics.get('prev_close') or 0)
                
                if cp > 0 and sv > 0:
                    metrics['static_premium'] = (cp / sv - 1) * 100
                if cp > 0 and pc > 0:
                    metrics['price_change'] = (cp / pc - 1) * 100
                else:
                    metrics['price_change'] = 0
                
                # 4. [V4.0] 精度规范：现价3位、溢价率3位、涨跌幅2位
                # 先创建 fund_dict 用于存储基金数据
                fund_dict = fund.to_dict()
                fund_dict.update(metrics)
                
                # 精度处理
                for k in ['price', 'nav', 'static_val', 'rt_val']:
                    if k in fund_dict and fund_dict[k]:
                        fund_dict[k] = round(float(fund_dict[k]), 4 if k != 'price' else 3)
                # 溢价率3位小数
                for k in ['static_premium', 'rt_premium']:
                    if k in fund_dict and fund_dict[k]:
                        fund_dict[k] = round(float(fund_dict[k]), 3)
                # 涨跌幅2位小数
                if 'price_change' in fund_dict and fund_dict['price_change']:
                    fund_dict['price_change'] = round(float(fund_dict['price_change']), 2)
                
                # 状态与费率
                pure_code = code.split('.')[0] if '.' in code else code
                st = status_dict.get(pure_code) or status_dict.get(code) or {}
                fund_dict['purchase_status'] = st.get('purchase_status', '未知')
                fund_dict['redemption_status'] = st.get('redemption_status', '未知')
                fund_dict['purchase_fee'] = st.get('purchase_fee', '-')
                fund_dict['redemption_fee'] = st.get('redemption_fee', '-')
                
                # 指数信息
                fund_dict['idx_code'] = fund.get('idx_code', '-')
                fund_dict['idx_name'] = fund.get('idx_name', '-')

                # 💡 强力防 NaN 注入：将所有 pd.isna 的值转换为 None，防止 json 序列化抛出 ValueError
                for k, v in list(fund_dict.items()):
                    if pd.isna(v):
                        fund_dict[k] = None

                result.append(fund_dict)
            logger.info(f"Dashboard数据生成完成，共 {len(result)} 只基金")
            return result
        except Exception as e:
            import traceback
            logger.error(f"get_unified_dashboard_data 失败: {e}")
            logger.error(traceback.format_exc())
            return []
        finally:
            conn.close()

    def get_fund_history(self, fund_code: str) -> List[Dict[str, Any]]:
        """
        [V3.9] 钢铁加固版：即便今日数据全无，也必须追溯到历史锚点。
        """
        conn = self.db._get_conn()
        try:
            # 1. 基础历史数据 (包含静态估值、汇率、并从 fund_daily_factors 回填缺失的净值)
            query_hist = """
            SELECT h.date, h.price, 
                   COALESCE(h.nav, f.nav) as nav,
                   h.static_val, h.premium as static_premium, h.calibration,
                   h.index_close, h.index_pct, h.shares, h.shares_added, h.turnover_rate, h.volume,
                   h.valuation_error,
                   r.usd_cny_mid, r.hkd_cny_mid
            FROM unified_fund_history h
            LEFT JOIN exchange_rate r ON h.date = r.date
            LEFT JOIN fund_daily_factors f ON h.date = f.date AND h.fund_code = f.fund_code
            WHERE h.fund_code = ? ORDER BY h.date DESC LIMIT 60
            """
            df = pd.read_sql(query_hist, conn, params=(fund_code,))
            if df.empty: return []
            
            # 判断是否是港币基金。若是，在返回的 usd_cny_mid 字段里使用港币汇率 hkd_cny_mid
            is_hkd_fund = False
            try:
                fund_info_df = pd.read_sql("SELECT category, idx_name FROM fund_info WHERE fund_code=? LIMIT 1", conn, params=(fund_code,))
                if not fund_info_df.empty:
                    cat = str(fund_info_df.iloc[0]['category'] or '')
                    idx_name = str(fund_info_df.iloc[0]['idx_name'] or '')
                    if '亚洲' in cat or '恒生' in idx_name or '香港' in idx_name or 'H股' in idx_name or '港币' in idx_name:
                        is_hkd_fund = True
            except:
                pass

            if is_hkd_fund and 'hkd_cny_mid' in df.columns:
                df['usd_cny_mid'] = df['hkd_cny_mid']

            # 计算估值误差百分比: val_error_pct = (static_val / nav - 1) * 100
            # 如果数据库里有 valuation_error 字段直接用，否则根据 static_val 和 nav 动态计算
            if 'valuation_error' in df.columns:
                df['val_error_pct'] = df['valuation_error']
            # 对于 valuation_error 为空的行，用 static_val 和 nav 计算
            mask = df['val_error_pct'].isna() if 'val_error_pct' in df.columns else pd.Series([True] * len(df))
            valid_mask = mask & (df['static_val'] > 0) & (df['nav'] > 0)
            if valid_mask.any():
                if 'val_error_pct' not in df.columns:
                    df['val_error_pct'] = 0.0
                df.loc[valid_mask, 'val_error_pct'] = (df.loc[valid_mask, 'static_val'] / df.loc[valid_mask, 'nav'] - 1) * 100

            # [核心修复] 锚点追溯：确保 nav_date 和 nav 永远不是空的
            # 如果第一行没有 nav，我们需要往后找
            valid_nav_rows = df.dropna(subset=['nav'])
            if not valid_nav_rows.empty:
                latest_nav = valid_nav_rows.iloc[0]['nav']
                latest_nav_date = valid_nav_rows.iloc[0]['date']
            else:
                latest_nav, latest_nav_date = 0, '-'

            # 计算各项变动百分比（因为按 date DESC 排序，所以当前行(i)变动比例为对比它的下一行(i+1)）
            # 用 shift(-1) 获取前一交易日的值
            if 'usd_cny_mid' in df.columns:
                df['usd_cny_mid_chg'] = (df['usd_cny_mid'] / df['usd_cny_mid'].shift(-1) - 1) * 100
            df['price_chg'] = (df['price'] / df['price'].shift(-1) - 1) * 100
            df['nav_chg'] = (df['nav'] / df['nav'].shift(-1) - 1) * 100
            df['static_val_chg'] = (df['static_val'] / df['static_val'].shift(-1) - 1) * 100

            # 清理所有 NaN 和 Infinity 以符合 JSON 规范
            import numpy as np
            df = df.replace([np.inf, -np.inf], np.nan)
            df = df.fillna(0)

            # 2. 为前端摘要页准备一个特殊的第一行 (注入最新锚点信息)
            # 我们将这些信息挂载在返回列表的每一项中，确保前端 Analysis.vue 无论点开哪一行都能拿到
            import math
            data_list = []
            for _, row in df.iterrows():
                item = row.to_dict()
                item['nav_date'] = latest_nav_date
                item['latest_nav'] = latest_nav # 备用字段
                # 历史表对账逻辑：收盘价 / 净值
                if item['nav'] and item['nav'] > 0:
                    item['static_premium'] = (item['price'] / item['nav'] - 1) * 100
                
                # 绝对防御：将字典中所有 float 类型的 NaN/Inf 强转为 0，防止 fastapi json 渲染报错
                for k, v in item.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        item[k] = 0.0
                data_list.append(item)

            return data_list
        finally:
            conn.close()

    def get_market_overview(self, market_data_service=None) -> Dict[str, Any]:
        conn = self.db._get_conn()
        res = {"rates": {}, "usd_change": 0, "hkd_change": 0, "active_sources": [], "stats": {"fund_count": 0}}
        
        # [V4.6] 修复行情状态未显示的 Bug
        if market_data_service:
            res["active_sources"] = market_data_service.get_active_source_names()
            
        try:
            rates_df = pd.read_sql_query("SELECT * FROM exchange_rate ORDER BY date DESC LIMIT 2", conn)
            if not rates_df.empty:
                res["rates"] = rates_df.iloc[0].to_dict()
                # 计算涨跌幅（百分比）
                if len(rates_df) >= 2:
                    current = rates_df.iloc[0]
                    previous = rates_df.iloc[1]
                    # USD/CNY 涨跌幅
                    if 'usd_cny_mid' in current and pd.notna(current.get('usd_cny_mid')) and pd.notna(previous.get('usd_cny_mid')):
                        prev_val = previous['usd_cny_mid']
                        curr_val = current['usd_cny_mid']
                        if prev_val != 0:
                            res["usd_change"] = ((curr_val - prev_val) / prev_val) * 100
                    # HKD/CNY 涨跌幅
                    if 'hkd_cny_mid' in current and pd.notna(current.get('hkd_cny_mid')) and pd.notna(previous.get('hkd_cny_mid')):
                        prev_val = previous['hkd_cny_mid']
                        curr_val = current['hkd_cny_mid']
                        if prev_val != 0:
                            res["hkd_change"] = ((curr_val - prev_val) / prev_val) * 100
            count_df = pd.read_sql_query("SELECT count(*) as count FROM unified_fund_list", conn)
            res["stats"]["fund_count"] = int(count_df.iloc[0]['count']) if not count_df.empty else 0
        except: pass
        finally: conn.close()
        return res

    def get_fund_intraday(self, fund_code: str, date: str = None) -> List[Dict[str, Any]]:
        if not date: date = pd.Timestamp.now().strftime('%Y-%m-%d')
        conn = self.db._get_conn()
        try:
            query = "SELECT time, price, rt_val, premium FROM fund_intraday_quotes WHERE fund_code = ? AND date = ? ORDER BY time ASC"
            return pd.read_sql(query, conn, params=(fund_code, date)).to_dict(orient='records')
        finally: conn.close()

    def get_fund_basket(self, fund_code: str) -> List[Dict[str, Any]]:
        conn = self.db._get_conn()
        try:
            query = "SELECT underlying_symbol, weight, date FROM fund_basket_weights WHERE fund_code = ? AND date = (SELECT MAX(date) FROM fund_basket_weights WHERE fund_code = ?)"
            return pd.read_sql_query(query, conn, params=(fund_code, fund_code)).to_dict(orient='records')
        finally: conn.close()
    
    def get_my_watchlist(self) -> List[str]:
        """
        [V6.0] 获取"我的自选"基金列表
        优先从fund_watchlist表读取，如果为空则返回所有基金（兼容旧版本）
        """
        conn = self.db._get_conn()
        try:
            # 查询自选基金表
            cursor = conn.execute("SELECT fund_code FROM fund_watchlist ORDER BY fund_code")
            watchlist = [row[0] for row in cursor.fetchall()]
            
            # 如果自选表为空，返回所有基金（兼容旧版本，全部采样）
            if not watchlist:
                logger.info("ℹ️ 自选列表为空，采样服务将处理所有基金（兼容模式）")
                all_funds_cursor = conn.execute("SELECT fund_code FROM unified_fund_list ORDER BY fund_code")
                watchlist = [row[0] for row in all_funds_cursor.fetchall()]
                return watchlist
            
            logger.info(f"✅ 采样服务使用自选列表: {len(watchlist)} 只基金")
            return watchlist
        finally:
            conn.close()
