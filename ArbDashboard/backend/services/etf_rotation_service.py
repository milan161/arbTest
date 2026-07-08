# -*- coding: utf-8 -*-
# etf_rotation_service.py - ETF 轮动服务（程序4 功能融合版）
# 独立于 LOF 体系，所有 ETF 轮动逻辑集中于此

import logging
import time
import requests
import pandas as pd
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# 分组 -> 美股锚点映射
GROUP_US_MAP = {1: 'XOP', 2: 'XBI', 3: 'SPY', 4: 'QQQ'}
GROUP_NAMES = {1: '油气', 2: '生物科技', 3: '标普500', 4: '纳指100'}

# 新浪缓存（15秒 TTL）
_fx_cache = {'rate': 0.0, 'time': 0.0}


class ETFRotationService:
    def __init__(self, db, market_data_service=None):
        self.db = db
        self.market_data_service = market_data_service

    # ─── 基础: 读取 ETF 轮动配置 ──────────────────────────

    def get_rotation_list(self) -> List[Dict[str, Any]]:
        """返回 etf_rotation_list 表中的分组配置"""
        conn = self.db._get_conn()
        try:
            df = pd.read_sql("SELECT * FROM etf_rotation_list ORDER BY group_id", conn)
            if df.empty:
                return []
            # 按 group_id 聚合为分组结构
            groups = {}
            for _, row in df.iterrows():
                gid = int(row['group_id'])
                if gid not in groups:
                    groups[gid] = {'group_id': gid, 'group_name': GROUP_NAMES.get(gid, f'组{gid}'), 'funds': []}

                lof_code = str(row.get('lof_code', '') or '').split('.')[0].strip()
                etf_code = str(row.get('etf_code', '') or '').split('.')[0].strip()

                # LOF 条目
                if lof_code and lof_code.lower() not in ('nan', ''):
                    fund_key = (gid, lof_code, 'LOF')
                    if not any(f['code'] == lof_code and f['type'] == 'LOF' for f in groups[gid]['funds']):
                        groups[gid]['funds'].append({
                            'group_id': gid,
                            'code': lof_code,
                            'name': str(row.get('lof_name', '') or ''),
                            'type': 'LOF'
                        })

                # ETF 条目
                if etf_code and etf_code.lower() not in ('nan', ''):
                    fund_key = (gid, etf_code, 'ETF')
                    if not any(f['code'] == etf_code and f['type'] == 'ETF' for f in groups[gid]['funds']):
                        groups[gid]['funds'].append({
                            'group_id': gid,
                            'code': etf_code,
                            'name': str(row.get('etf_name', '') or ''),
                            'type': 'ETF'
                        })

            result = []
            for gid in sorted(groups.keys()):
                result.append(groups[gid])
            return result
        finally:
            conn.close()

    # ─── 汇率: 实时在岸价（ETF 用） ─────────────────────

    def get_realtime_fx_spot(self) -> float:
        """从新浪获取 USD/CNY 实时在岸价（ETF 基金用，实盘市场汇率）"""
        now = time.time()
        if now - _fx_cache['time'] < 15 and _fx_cache['rate'] > 0:
            return _fx_cache['rate']

        try:
            resp = requests.get(
                "http://hq.sinajs.cn/list=fx_susdcny",
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=3.0,
                proxies={"http": None, "https": None}
            )
            resp.encoding = 'gbk'
            if resp.text and '="' in resp.text:
                parts = resp.text.split('"')[1].split(',')
                if len(parts) >= 2:
                    rate = float(parts[1])
                    if rate > 0:
                        _fx_cache['rate'] = rate
                        _fx_cache['time'] = now
                        logger.debug(f"[FX] 新浪在岸价: {rate}")
                        return rate
        except Exception as e:
            logger.warning(f"[FX] 获取新浪在岸价失败: {e}")

        # 兜底：如果交易所开盘但新浪失败，用数据库最近中间价 * 1.02 粗略估算
        if _fx_cache['rate'] > 0:
            return _fx_cache['rate']
        return 7.25

    # ─── 汇率: 人民币中间价（LOF 用）───────────────────

    def get_fx_mid(self) -> float:
        """从数据库获取 USD/CNY 人民币中间价（LOF 基金估值用，PBOC 每日发布）"""
        try:
            conn = self.db._get_conn()
            cur = conn.cursor()
            cur.execute("SELECT usd_cny_mid FROM exchange_rate ORDER BY date DESC LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row and row[0] and row[0] > 0:
                return float(row[0])
        except Exception as e:
            logger.warning(f"[FX] 获取中间价失败: {e}")
        # 兜底：回落为在岸价
        return self.get_realtime_fx_spot()

    # ─── 实时行情: 美股锚点价格 ────────────────────────

    def _get_us_price(self, symbol: str) -> float:
        """通过 IB/富途/新浪获取美股实时价格"""
        if self.market_data_service:
            try:
                q = self.market_data_service.get_realtime_quote(symbol)
                if q and q.get('price', 0) > 0:
                    return q['price']
            except Exception as e:
                logger.debug(f"[US] {symbol} IB获取失败: {e}")

        # 降级：新浪美股接口
        try:
            resp = requests.get(
                f"http://hq.sinajs.cn/list=gb_{symbol.lower()}",
                headers={"Referer": "https://finance.sina.com.cn/"},
                timeout=2.0,
                proxies={"http": None, "https": None}
            )
            resp.encoding = 'gbk'
            if resp.text and '="' in resp.text:
                parts = resp.text.split('"')[1].split(',')
                if len(parts) >= 2:
                    return float(parts[1])
        except Exception as e:
            logger.debug(f"[US] {symbol} 新浪获取失败: {e}")

        return 0.0

    # ─── 估值: 获取基准数据 ──────────────────────────

    def _get_fund_base_data(self, code: str, fund_type: str, group_id: int) -> Dict[str, Any]:
        """
        获取基金估值所需的基准数据
        - LOF: 从 fund_daily_factors 获取 nav/position/hedge
        - ETF: 从 unified_fund_history 获取 nav，固定 position=0.95
        """
        result = {'nav': 0.0, 'position': 0.95, 'hedge': None}

        if fund_type == 'LOF':
            # LOF: 优先从 fund_daily_factors 取最新数据
            try:
                conn = self.db._get_conn()
                df = pd.read_sql(
                    "SELECT nav, position, hedge FROM fund_daily_factors "
                    "WHERE fund_code=? ORDER BY date DESC LIMIT 1",
                    conn, params=(code,)
                )
                if not df.empty:
                    row = df.iloc[0]
                    result['nav'] = float(row['nav']) if pd.notna(row['nav']) and row['nav'] > 0 else 0.0
                    result['position'] = float(row['position']) if pd.notna(row['position']) else 0.95
                    result['hedge'] = float(row['hedge']) if pd.notna(row['hedge']) else None

                # 兜底: 从 unified_fund_history 取 nav
                if result['nav'] <= 0:
                    df2 = pd.read_sql(
                        "SELECT COALESCE(nav, 0) as nav FROM unified_fund_history "
                        "WHERE fund_code=? AND nav > 0 ORDER BY date DESC LIMIT 1",
                        conn, params=(code,)
                    )
                    if not df2.empty:
                        result['nav'] = float(df2.iloc[0]['nav'])
                conn.close()
            except Exception as e:
                logger.warning(f"[BASE] LOF {code} 获取基准数据失败: {e}")

        else:
            # ETF: 从 unified_fund_history 获取 nav
            try:
                conn = self.db._get_conn()
                df = pd.read_sql(
                    "SELECT COALESCE(nav, 0) as nav FROM unified_fund_history "
                    "WHERE fund_code=? AND nav > 0 ORDER BY date DESC LIMIT 1",
                    conn, params=(code,)
                )
                if not df.empty:
                    result['nav'] = float(df.iloc[0]['nav'])

                # 也尝试从 fund_daily_factors 拿（虽然数据可能旧一些）
                if result['nav'] <= 0:
                    df2 = pd.read_sql(
                        "SELECT nav, position, hedge FROM fund_daily_factors "
                        "WHERE fund_code=? ORDER BY date DESC LIMIT 1",
                        conn, params=(code,)
                    )
                    if not df2.empty:
                        result['nav'] = float(df2.iloc[0]['nav']) if pd.notna(df2.iloc[0]['nav']) else 0.0
                conn.close()
            except Exception as e:
                logger.warning(f"[BASE] ETF {code} 获取基准数据失败: {e}")

            # ETF 固定仓位 95%
            result['position'] = 0.95

        return result

    def _compute_hedge(self, code: str, us_symbol: str, nav: float, position: float, fx: float) -> Optional[float]:
        """
        当数据库中 hedge 缺失时，通过 T-1 数据动态推演 hedge
        hedge = (US_prev_close * FX_mid) / (NAV * position)
        fx 参数由调用方根据基金类型传入（LOF→中间价，ETF→在岸价）
        """
        if nav <= 0 or position <= 0:
            return None
        try:
            conn = self.db._get_conn()
            # 获取最近的 usa_etf_daily_prices
            df_us = pd.read_sql(
                "SELECT price, netvalue, date FROM usa_etf_daily_prices "
                "WHERE symbol=? AND (price>0 OR netvalue>0) ORDER BY date DESC LIMIT 1",
                conn, params=(us_symbol,)
            )
            if df_us.empty:
                # 也试试带 ^ 前缀的符号
                df_us = pd.read_sql(
                    "SELECT price, netvalue, date FROM usa_etf_daily_prices "
                    "WHERE symbol=? AND (price>0 OR netvalue>0) ORDER BY date DESC LIMIT 1",
                    conn, params=(f"^{us_symbol}",)
                )
            conn.close()

            if not df_us.empty:
                us_prev = float(df_us.iloc[0].get('netvalue') or df_us.iloc[0].get('price') or 0)
                if us_prev > 0 and fx > 0:
                    return (us_prev * fx) / (nav * position)
        except Exception as e:
            logger.debug(f"[HEDGE] 计算 {code} 对冲值失败: {e}")
        return None

    # ─── 核心: 批量获取实时价格和估值 ──────────────────

    def get_rotation_prices(self) -> Dict[str, Any]:
        """
        获取所有轮动基金实时价格和估值
        返回结构:
        {
            "funds": { "162411": { price, rt_val, rt_premium, ... }, ... },
            "fx_spot": 7.2512,      # 在岸价（ETF 用）
            "fx_mid": 7.2010,       # 中间价（LOF 用）
            "us_prices": { "XOP": 152.3, ... },
            "update_time": "..."
        }
        """
        groups = self.get_rotation_list()
        fx_spot = self.get_realtime_fx_spot()   # 在岸价 → ETF
        fx_mid = self.get_fx_mid()               # 中间价 → LOF

        # 收集所有需要行情的代码
        all_codes = set()
        code_to_group = {}  # code -> (group_id, type)
        for g in groups:
            for f in g['funds']:
                all_codes.add(f['code'])
                code_to_group[f['code']] = (g['group_id'], f['type'])

        # 获取各分组的美股价格
        us_prices = {}
        for gid, sym in GROUP_US_MAP.items():
            price = self._get_us_price(sym)
            if price > 0:
                us_prices[sym] = price

        # A股实时价格（LOF + ETF）
        cn_prices = {}
        if self.market_data_service:
            for code in all_codes:
                try:
                    q = self.market_data_service.get_realtime_quote(code)
                    if q and q.get('price', 0) > 0:
                        cn_prices[code] = q['price']
                except Exception as e:
                    logger.debug(f"[CN] {code} 获取A股行情失败: {e}")

        # 逐一计算估值
        result_funds = {}
        for code in all_codes:
            gid, ftype = code_to_group[code]
            us_sym = GROUP_US_MAP.get(gid, 'SPY')
            us_price = us_prices.get(us_sym, 0.0)

            # [AI-2026-07-08] LOF → 中间价，ETF → 在岸价
            fx = fx_mid if ftype == 'LOF' else fx_spot

            # 基准数据
            base = self._get_fund_base_data(code, ftype, gid)
            nav = base['nav']
            position = base['position']
            hedge = base['hedge']

            price = cn_prices.get(code, 0.0)

            # 计算实时估值
            rt_val = 0.0
            rt_premium = 0.0

            if nav > 0 and us_price > 0 and fx > 0:
                # 如果 hedge 缺失，动态计算（用同类型汇率）
                if hedge is None or hedge <= 0:
                    hedge = self._compute_hedge(code, us_sym, nav, position, fx)

                if hedge and hedge > 0:
                    rt_val = nav * (1.0 - position) + (us_price * fx) / hedge
                    if price > 0 and rt_val > 0:
                        rt_premium = round((price / rt_val - 1) * 100, 3)

            result_funds[code] = {
                'price': round(price, 3) if price > 0 else 0,
                'nav': round(nav, 4),
                'position': round(position, 4),
                'hedge': round(hedge, 4) if hedge else None,
                'rt_val': round(rt_val, 4) if rt_val > 0 else 0,
                'rt_premium': rt_premium,
                'type': ftype,
                'group_id': gid,
                'us_symbol': us_sym,
            }

        return {
            'funds': result_funds,
            'fx_spot': round(fx_spot, 4),
            'fx_mid': round(fx_mid, 4),
            'us_prices': us_prices,
            'update_time': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    # ─── 历史轮动数据 ──────────────────────────────

    def get_group_history(self, group_id: int) -> List[Dict[str, Any]]:
        """
        获取某分组的 LOF 历史折溢价数据（轮动分析用）
        返回每个交易日 LOF vs ETF 的对比
        """
        groups = self.get_rotation_list()
        target_group = None
        for g in groups:
            if g['group_id'] == group_id:
                target_group = g
                break
        if not target_group:
            return []

        # 找到该分组的 LOF
        lof_code = None
        for f in target_group['funds']:
            if f['type'] == 'LOF':
                lof_code = f['code']
                break
        if not lof_code:
            return []

        conn = self.db._get_conn()
        try:
            # 取 LOF 历史数据
            hist = pd.read_sql(
                "SELECT date, price, COALESCE(nav, 0) as nav, "
                "COALESCE(premium, 0) as premium "
                "FROM unified_fund_history "
                "WHERE fund_code=? AND date >= date('now', '-90 days') "
                "ORDER BY date DESC",
                conn, params=(lof_code,)
            )
            if hist.empty:
                return []

            # 也取 ETF 的价格（用于对比）
            etf_codes = [f['code'] for f in target_group['funds'] if f['type'] == 'ETF']
            etf_history = {}
            if etf_codes:
                codes_str = ','.join(f"'{c}'" for c in etf_codes)
                etf_df = pd.read_sql(
                    f"SELECT fund_code, date, price, COALESCE(nav, 0) as nav "
                    f"FROM unified_fund_history "
                    f"WHERE fund_code IN ({codes_str}) AND date >= date('now', '-90 days') "
                    f"ORDER BY date DESC",
                    conn
                )
                if not etf_df.empty:
                    for _, row in etf_df.iterrows():
                        date = row['date']
                        if date not in etf_history:
                            etf_history[date] = {}
                        etf_history[date][row['fund_code']] = {
                            'price': float(row['price']) if pd.notna(row['price']) else 0,
                            'nav': float(row['nav']) if pd.notna(row['nav']) else 0,
                        }

            result = []
            for _, row in hist.iterrows():
                date = row['date']
                funds_data = [{
                    'fund_code': lof_code,
                    'type': 'LOF',
                    'price': float(row['price']) if pd.notna(row['price']) else 0,
                    'nav': float(row['nav']) if pd.notna(row['nav']) else 0,
                    'premium': float(row['premium']) if pd.notna(row['premium']) else None
                }]
                # 添加同日期 ETF 数据
                if date in etf_history:
                    for etf_code in etf_codes:
                        if etf_code in etf_history[date]:
                            ed = etf_history[date][etf_code]
                            etf_premium = None
                            if ed['price'] > 0 and ed['nav'] > 0:
                                etf_premium = round((ed['price'] / ed['nav'] - 1) * 100, 3)
                            funds_data.append({
                                'fund_code': etf_code,
                                'type': 'ETF',
                                'price': ed['price'],
                                'nav': ed['nav'],
                                'premium': etf_premium
                            })

                result.append({'date': date, 'funds': funds_data})

            return result
        finally:
            conn.close()
