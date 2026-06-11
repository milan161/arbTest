import os
import sys
import pandas as pd
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

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
            funds_df = pd.read_sql_query("SELECT fund_code, fund_name, category, related_index FROM unified_fund_list", conn)
            if watchlist and not funds_df.empty:
                watchlist_strs = [str(w) for w in watchlist]
                funds_df = funds_df[funds_df['fund_code'].astype(str).isin(watchlist_strs)]
            
            status_df = pd.read_sql_query("SELECT fund_code, purchase_status, redemption_status FROM fund_purchase_status", conn)
            status_dict = status_df.set_index('fund_code').to_dict('index')
            
            if funds_df is None or funds_df.empty:
                logger.warning("未获取到基金列表，返回空数据")
                return []
            
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
                    if not valid_vals.empty:
                        metrics['static_val'] = valid_vals.iloc[0]['static_val']
                    
                    # 历史价格兜底
                    valid_prices = metrics_df.dropna(subset=['price'])
                    if not valid_prices.empty:
                        metrics['price'] = valid_prices.iloc[0]['price']
                        
                    # 恢复基本面的缺失字段 (成交额、份额、换手率等)
                    for col in ['volume', 'shares', 'shares_added', 'turnover_rate']:
                        valid_series = metrics_df.dropna(subset=[col])
                        metrics[col] = valid_series.iloc[0][col] if not valid_series.empty else 0
                        
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
                    calculator = self._get_calculator()
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
                
                # 状态
                st = status_dict.get(code, {})
                fund_dict['purchase_status'] = st.get('purchase_status', '未知')
                fund_dict['redemption_status'] = st.get('redemption_status', '未知')

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
