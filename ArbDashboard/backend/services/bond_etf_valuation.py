"""
债券ETF盘中估值服务 (511880/511360/511520)

估值方法:
  - 511880 (银华日利ETF): 日均增长法 (30日均增长 + 最新净值)
    货币基金, 净值稳定增长, 日均增长法精度高
    周末: 周五包含周六日(跳3倍日增长)

  - 511360 (短融ETF): 国债指数 000012 方向判断 + 日均增长兜底
    短期融资券价格随资金面波动, 用国债指数判断方向
    参考规则: 000012涨→NAV+, 大跌→NAV-
    周末: 周一包含周六日

  - 511520 (政金债ETF): 日均增长法 + 国债指数方向修正
    中长期政金债, 波动较大, 日均增长不稳定
    国债指数作为日内方向参考

数据源:
  - 历史净值: 天天基金 API
  - 实时价格: TDX/QMT (已有 market_data_service)
  - 国债指数: 新浪财经 / TDX
"""
import logging
import requests
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Manual BP overrides (in-memory, resets on restart)
# Structure: {code: {"bp_7y": float, "bp_10y": float, "date": str}}
_manual_bp_overrides: Dict[str, Dict[str, Any]] = {}


def set_manual_bp(code: str, bp_7y: float, bp_10y: float):
    """Store manual BP override for a fund"""
    from datetime import date
    _manual_bp_overrides[code] = {
        "bp_7y": bp_7y,
        "bp_10y": bp_10y,
        "date": date.today().isoformat(),
    }
    logger.info("[BondETF] Manual BP set for %s: 7Y=%s, 10Y=%s", code, bp_7y, bp_10y)


def get_manual_bp(code: str) -> Optional[Dict[str, Any]]:
    """Get manual BP override for a fund (returns None if not set or expired)"""
    from datetime import date
    override = _manual_bp_overrides.get(code)
    if not override:
        return None
    today = date.today().isoformat()
    if override.get("date") != today:
        # Expired (different day)
        _manual_bp_overrides.pop(code, None)
        return None
    return override


def clear_manual_bp(code: str):
    """Clear manual BP override for a fund"""
    _manual_bp_overrides.pop(code, None)
    logger.info("[BondETF] Manual BP cleared for %s", code)


# ── 基金元信息 ──
BOND_ETF_META = {
    '511880': {
        'name': '银华日利ETF',
        'type': 'money_market',
        'weekend_on': 'friday',       # 周末体现在周五
    },
    '511360': {
        'name': '短融ETF海富通',
        'type': 'short_bond',
        'weekend_on': 'monday',       # 周末体现在周一
        'daily_coupon': 0.003,        # 底仓票息: 短融年化~1.2%, 每天~0.003元
        'idx_coefficient': 0.07,      # 国债指数敏感度: 000012每涨1%, NAV多涨0.007
    },
    '511520': {
        'name': '政金债ETF富国',
        'type': 'mid_bond',
        'weekend_on': 'monday',       # 周末体现在周一（同511360）
        'daily_coupon': 0.02,         # 日均票息: 7-10年国开债年化~2.5%, 每天~0.02元
    },
}

NAV_CACHE_TTL = 1800  # 净值缓存30分钟


class BondETFValuation:
    """债券ETF估值器"""

    def __init__(self, db=None, market_data_service=None):
        self.db = db
        self.market_data_service = market_data_service
        self._nav_cache: Dict[str, tuple] = {}
        self._growth_cache: Dict[str, tuple] = {}
        self._idx_cache: Dict[str, tuple] = {}
        self._cache_lock = threading.Lock()
        self._init_bp_table()

    def _init_bp_table(self):
        """初始化国开债BP数据表"""
        if not self.db:
            return
        try:
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cdb_yield_bp (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    cdb_7y_bp REAL,
                    cdb_10y_bp REAL,
                    treasury_7y_bp REAL,
                    treasury_10y_bp REAL,
                    note TEXT,
                    created_at TEXT DEFAULT (datetime('now', 'localtime')),
                    UNIQUE(date)
                )
            """)
            conn.commit()
        except Exception as e:
            logger.warning(f"[BondETF] 初始化BP数据表失败: {e}")

    def save_bp_data(self, date: str, cdb_7y_bp: float = None, cdb_10y_bp: float = None,
                     treasury_7y_bp: float = None, treasury_10y_bp: float = None,
                     note: str = None) -> bool:
        """保存国开债BP数据（手动输入）"""
        if not self.db:
            return False
        try:
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO cdb_yield_bp 
                (date, cdb_7y_bp, cdb_10y_bp, treasury_7y_bp, treasury_10y_bp, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (date, cdb_7y_bp, cdb_10y_bp, treasury_7y_bp, treasury_10y_bp, note))
            conn.commit()
            logger.info(f"[BondETF] 保存BP数据: {date} 国开7Y={cdb_7y_bp}BP 国开10Y={cdb_10y_bp}BP")
            return True
        except Exception as e:
            logger.error(f"[BondETF] 保存BP数据失败: {e}")
            return False

    def get_bp_data(self, date: str) -> Optional[Dict]:
        """获取指定日期的BP数据"""
        if not self.db:
            return None
        try:
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, cdb_7y_bp, cdb_10y_bp, treasury_7y_bp, treasury_10y_bp, note
                FROM cdb_yield_bp WHERE date = ?
            """, (date,))
            row = cursor.fetchone()
            if row:
                return {
                    'date': row[0],
                    'cdb_7y_bp': row[1],
                    'cdb_10y_bp': row[2],
                    'treasury_7y_bp': row[3],
                    'treasury_10y_bp': row[4],
                    'note': row[5],
                }
        except Exception as e:
            logger.error(f"[BondETF] 获取BP数据失败: {e}")
        return None

    def get_recent_bp_data(self, days: int = 10) -> List[Dict]:
        """获取最近N天的BP数据"""
        if not self.db:
            return []
        try:
            conn = self.db._get_conn()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT date, cdb_7y_bp, cdb_10y_bp, treasury_7y_bp, treasury_10y_bp, note
                FROM cdb_yield_bp ORDER BY date DESC LIMIT ?
            """, (days,))
            rows = cursor.fetchall()
            return [
                {
                    'date': r[0], 'cdb_7y_bp': r[1], 'cdb_10y_bp': r[2],
                    'treasury_7y_bp': r[3], 'treasury_10y_bp': r[4], 'note': r[5]
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"[BondETF] 获取BP历史失败: {e}")
        return []

    # ══════════════════════════════════════════
    # 1. NAV 历史获取
    # ══════════════════════════════════════════
    def _fetch_nav_history(self, code: str, days: int = 30) -> List[Dict]:
        """从天天基金 API 获取净值历史"""
        url = f"https://api.fund.eastmoney.com/f10/lsjz?callback=jQuery&fundCode={code}&pageIndex=1&pageSize={days}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': f'https://fundf10.eastmoney.com/jjjz_{code}.html',
        }
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            text = resp.text
            start = text.find('{')
            end = text.rfind('}') + 1
            if start < 0 or end <= start:
                logger.warning(f"[BondETF] {code} API格式异常")
                return []
            data = json.loads(text[start:end])
            records = data.get('Data', {}).get('LSJZList', [])
            result = []
            for r in records:
                date_str = r.get('FSRQ', '')
                nav = r.get('DWJZ')
                if date_str and nav:
                    try:
                        result.append({'date': date_str, 'nav': float(nav)})
                    except ValueError:
                        continue
            return result
        except Exception as e:
            logger.error(f"[BondETF] 获取 {code} 净值失败: {e}")
            return []

    def get_nav_history(self, code: str, days: int = 30) -> List[Dict]:
        cache_key = f"{code}_{days}"
        with self._cache_lock:
            cached = self._nav_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < NAV_CACHE_TTL:
                return cached[1]
        records = self._fetch_nav_history(code, days)
        if records:
            with self._cache_lock:
                self._nav_cache[cache_key] = (time.monotonic(), records)
        return records

    def get_latest_nav(self, code: str) -> Optional[float]:
        records = self.get_nav_history(code, days=5)
        return records[0]['nav'] if records else None

    def get_latest_nav_date(self, code: str) -> Optional[str]:
        records = self.get_nav_history(code, days=5)
        return records[0]['date'] if records else None

    # ══════════════════════════════════════════
    # 2. 日均增长计算 (仅用于511880)
    # ══════════════════════════════════════════
    def calc_avg_daily_growth(self, code: str, days: int = 20) -> Optional[float]:
        """
        计算日均净值增长 (正确处理周末效应)
        
        关键逻辑: 511880周五收盘价已包含周六+周日收益
        - 周四→周五(delta=1): 变化=3天收益 → 日均=change/3
        - 周五→周一(delta=3): 变化=仅周一收益 → 日均=change/1
        """
        meta = BOND_ETF_META.get(code)
        if not meta:
            return None

        cache_key = f"{code}_{days}"
        with self._cache_lock:
            cached = self._growth_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < NAV_CACHE_TTL:
                return cached[1]

        records = self.get_nav_history(code, days=days + 10)
        if len(records) < 3:
            return None

        weekend_on = meta.get('weekend_on')
        daily_rates = []

        # 从旧到新遍历 (records[-1]最旧, records[0]最新)
        for i in range(len(records) - 1, 0, -1):
            older = records[i]
            newer = records[i - 1]
            nav_change = newer['nav'] - older['nav']

            try:
                d1 = datetime.strptime(older['date'], '%Y-%m-%d')
                d2 = datetime.strptime(newer['date'], '%Y-%m-%d')
                delta_days = (d2 - d1).days
            except ValueError:
                delta_days = 1

            # 正确计算每个NAV对的实际计息天数
            if weekend_on == 'friday':
                # 511880: 周五包含周末收益
                if delta_days >= 3:
                    # 周五→周一: 变化=仅周一收益(1天)
                    accrual_days = 1
                elif d2.weekday() == 4:
                    # 周四→周五: 变化=周五+周六+周日(3天)
                    accrual_days = 3
                else:
                    accrual_days = 1
            elif weekend_on == 'monday':
                # 511360/511520: 周一包含周末收益
                if delta_days >= 3:
                    # 周五→周一: 变化=周五+周六+周日(3天)
                    accrual_days = 3
                else:
                    accrual_days = 1
            else:
                accrual_days = max(delta_days, 1)

            daily_rates.append(nav_change / accrual_days)

        if not daily_rates:
            return None

        # 用最近 N 天的数据, 排除极端异常值 (5倍标准差以外)
        recent = daily_rates[-min(len(daily_rates), days):]
        if len(recent) >= 4:
            mean = sum(recent) / len(recent)
            std = (sum((x - mean) ** 2 for x in recent) / len(recent)) ** 0.5
            filtered = [x for x in recent if abs(x - mean) < 5 * std]
            if len(filtered) >= 3:
                recent = filtered

        avg = sum(recent) / len(recent)

        with self._cache_lock:
            self._growth_cache[cache_key] = (time.monotonic(), avg)
        return avg

    # ══════════════════════════════════════════
    # 3. 国债指数 000012 获取（腾讯接口 + 新浪降级）
    # ══════════════════════════════════════════
    def _get_treasury_index_data(self) -> Optional[Dict]:
        """获取国债指数000012实时行情"""
        idx_cache_key = '000012'
        with self._cache_lock:
            cached = self._idx_cache.get(idx_cache_key)
            if cached and time.monotonic() - cached[0] < 60:  # 1分钟缓存
                return cached[1]

        result = None
        # [优先级1] 新浪实时接口
        try:
            url = "http://hq.sinajs.cn/list=s_sh000012"
            headers = {'Referer': 'https://finance.sina.com.cn/'}
            resp = requests.get(url, headers=headers, timeout=3, proxies={"http": None, "https": None})
            if resp.status_code == 200 and '="' in resp.text:
                parts = resp.text.split('"')[1].split(',')
                if len(parts) >= 6:
                    name = parts[0]
                    current = float(parts[1]) if parts[1].replace('.', '', 1).lstrip('-').isdigit() else 0
                    change = float(parts[2]) if parts[2].replace('.', '', 1).lstrip('-').isdigit() else 0
                    pct_str = parts[3] if len(parts) > 3 else '0'
                    pct = float(pct_str) if pct_str.replace('.', '', 1).lstrip('-').isdigit() else 0
                    prev_close = current - change if change != 0 else current
                    if current > 0:
                        result = {
                            'name': name,
                            'price': current,
                            'prev_close': round(prev_close, 4),
                            'pct_change': round(pct, 3),
                        }
                        logger.info(f"[BondETF] 新浪接口获取国债指数: 最新={current}, 昨收={prev_close}, 涨跌幅={pct}%")
        except Exception as e:
            logger.warning(f"[BondETF] 新浪国债指数失败: {e}")

        # [优先级2] 腾讯实时接口 (降级)
        if not result:
            try:
                url = "http://qt.gtimg.cn/q=sh000012"
                headers = {"Referer": "https://finance.qq.com/", "User-Agent": "Mozilla/5.0"}
                resp = requests.get(url, headers=headers, timeout=3, proxies={"http": None, "https": None})
                if resp.status_code == 200:
                    resp.encoding = 'gbk'
                    fields = resp.text.split('"')[1].split('~')
                    if len(fields) > 32:
                        current = float(fields[3]) if fields[3] else 0
                        prev_close = float(fields[4]) if fields[4] else 0
                        pct = float(fields[32]) if fields[32] else 0
                        if current > 0:
                            result = {
                                'name': fields[1] if len(fields) > 1 else '国债指数',
                                'price': current,
                                'prev_close': prev_close,
                                'pct_change': round(pct, 3),
                            }
                            logger.info(f"[BondETF] 腾讯接口获取国债指数: 最新={current}, 昨收={prev_close}, 涨跌幅={pct}%")
            except Exception as e:
                logger.warning(f"[BondETF] 腾讯国债指数失败: {e}")

        # [优先级3] TDX 降级
        if not result and self.market_data_service:
            try:
                q = self.market_data_service.get_realtime_quote('000012')
                if q and q.get('price') and q.get('prev_close'):
                    pct = (q['price'] / q['prev_close'] - 1) * 100
                    result = {
                        'price': q['price'],
                        'prev_close': q['prev_close'],
                        'pct_change': round(pct, 3),
                    }
            except Exception:
                pass

        if result:
            with self._cache_lock:
                self._idx_cache[idx_cache_key] = (time.monotonic(), result)
        return result

    def get_treasury_history(self, days: int = 30) -> List[Dict]:
        """
        获取国债指数000012历史K线数据（用于511360/511520净值估算）
        
        返回: [{'date': '2026-05-06', 'open': 227.09, 'close': 226.93, 'high': 227.09, 'low': 226.91, 'volume': 43717250}]
        """
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000012,day,,,{days},qfq"
        try:
            resp = requests.get(url, timeout=5, proxies={"http": None, "https": None})
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            sh_data = data.get("data", {}).get("sh000012", {})
            day_data = sh_data.get("day", [])
            
            if not day_data:
                return []
            
            result = []
            for item in day_data:
                if len(item) >= 6:
                    result.append({
                        'date': item[0],
                        'open': float(item[1]),
                        'close': float(item[2]),
                        'high': float(item[3]),
                        'low': float(item[4]),
                        'volume': float(item[5]),
                    })
            
            # 按日期降序（最新在前）
            return result
        except Exception as e:
            logger.error(f"[BondETF] 获取国债指数历史失败: {e}")
            return []

    def _get_treasury_pct(self) -> Optional[float]:
        """获取国债指数涨跌幅(%)"""
        data = self._get_treasury_index_data()
        return data.get('pct_change') if data else None

    # ══════════════════════════════════════════
    # 3.5 国债期货 T2609 获取（新浪接口）
    # ══════════════════════════════════════════
    def _get_treasury_futures_data(self) -> Optional[Dict]:
        """
        获取国债期货实时行情 (T2609=10年期, TF2609=5年期)
        新浪接口: hq.sinajs.cn/list=CFF_RE_T2609
        期货收盘时间15:15, 比债券市场15:00晚15分钟, 信号更及时
        """
        with self._cache_lock:
            cached = self._idx_cache.get('futures_t')
            if cached and time.monotonic() - cached[0] < 30:  # 30秒缓存
                return cached[1]

        result = None
        try:
            url = "https://hq.sinajs.cn/list=CFF_RE_T2609,CFF_RE_TF2609"
            headers = {
                'Referer': 'https://finance.sina.com.cn',
                'User-Agent': 'Mozilla/5.0'
            }
            resp = requests.get(url, headers=headers, timeout=5, proxies={"http": None, "https": None})
            if resp.status_code != 200:
                return None

            # 解析 T2609 (10年期)
            t_data = {}
            for line in resp.text.strip().split('\n'):
                if 'CFF_RE_T2609' in line and '="' in line:
                    fields = line.split('"')[1].split(',')
                    if len(fields) >= 10:
                        latest = float(fields[0])    # 最新价
                        yest_settle = float(fields[1])  # 昨结算
                        open_p = float(fields[2]) if fields[2] else latest  # 开盘
                        high = float(fields[3]) if fields[3] else latest
                        low = float(fields[4]) if fields[4] else latest
                        if yest_settle > 0:
                            pct = (latest - yest_settle) / yest_settle * 100
                            t_data = {
                                'contract': 'T2609',
                                'name': '10年期国债期货',
                                'latest': latest,
                                'yest_settle': yest_settle,
                                'open': open_p,
                                'high': high,
                                'low': low,
                                'pct_change': round(pct, 4),
                            }

                # 解析 TF2609 (5年期) 作为辅助
                if 'CFF_RE_TF2609' in line and '="' in line:
                    fields = line.split('"')[1].split(',')
                    if len(fields) >= 10:
                        latest = float(fields[0])
                        yest_settle = float(fields[1])
                        if yest_settle > 0:
                            pct = (latest - yest_settle) / yest_settle * 100
                            t_data['tf_latest'] = latest
                            t_data['tf_yest_settle'] = yest_settle
                            t_data['tf_pct'] = round(pct, 4)

            if t_data:
                result = t_data
                logger.info(
                    f"[BondETF] 国债期货 T2609: {t_data.get('latest')}, "
                    f"昨结={t_data.get('yest_settle')}, 涨跌={t_data.get('pct_change')}%"
                    + (f", TF2609涨跌={t_data.get('tf_pct')}%" if 'tf_pct' in t_data else "")
                )
        except Exception as e:
            logger.warning(f"[BondETF] 国债期货数据获取失败: {e}")

        if result:
            with self._cache_lock:
                self._idx_cache['futures_t'] = (time.monotonic(), result)
        return result

    def _get_futures_adjustment(self, code: str, futures_data: Dict) -> float:
        """
        根据国债期货涨跌幅计算NAV调整量
        期货涨→债券涨→NAV+; 期货跌→债券跌→NAV-
        T2609(10年期)久期约8年, TF2609(5年期)久期约4年
        511520跟踪国开债, 久期约5-7年, 取T和TF的均值
        """
        t_pct = futures_data.get('pct_change', 0)
        tf_pct = futures_data.get('tf_pct')

        # 511520用T和TF的均值 (久期匹配)
        if tf_pct is not None:
            avg_pct = (t_pct + tf_pct) / 2
        else:
            avg_pct = t_pct

        # 久期估算: T2609久期~8年, TF2609久期~4年, 511520国开债久期~6年
        # 期货价格变动1% ≈ 债券价格变动0.6% (久期比率 6/10)
        # 但ETF不可能像期货那样波动, 取1/3保守系数
        bond_equiv = avg_pct * 0.35  # 保守系数

        # 映射到调整量
        is_mid = (code == '511520')
        if is_mid:
            if bond_equiv > 0.05:   return 0.015
            if bond_equiv > 0.02:   return 0.008
            if bond_equiv > 0.01:   return 0.004
            if bond_equiv > 0:      return 0.002
            if bond_equiv < -0.05:  return -0.015
            if bond_equiv < -0.02:  return -0.008
            if bond_equiv < -0.01:  return -0.004
            if bond_equiv < 0:      return -0.002
        else:
            # 511360: 短久期, 期货参考价值小, 仅大幅波动时参考
            if abs(bond_equiv) > 0.05:
                return round(bond_equiv * 0.1, 4)  # 极端行情微调
        return 0.0

    # ══════════════════════════════════════════
    # 4. 511360/511520 国债指数方向估值
    # ══════════════════════════════════════════
    def _get_index_adjustment(self, code: str, idx_pct: Optional[float]) -> float:
        """
        根据国债指数涨跌幅计算NAV调整量
        511360(短融): 精细刻度, 0.002~0.010
        511520(政金债): 更粗刻度, 0.005~0.020 (久期更长)
        """
        if idx_pct is None:
            return 0.0
        is_mid = (code == '511520')
        if is_mid:
            if idx_pct > 0.15:   return 0.020
            if idx_pct > 0.08:   return 0.010
            if idx_pct > 0.03:   return 0.005
            if idx_pct > 0:      return 0.002
            if idx_pct < -0.15:  return -0.020
            if idx_pct < -0.08:  return -0.010
            if idx_pct < -0.03:  return -0.005
            if idx_pct < 0:      return -0.002
        else:
            # 511360: 精细刻度
            if idx_pct > 0.12:   return 0.010
            if idx_pct > 0.06:   return 0.006
            if idx_pct > 0.03:   return 0.004
            if idx_pct > 0:      return 0.002
            if idx_pct < -0.12:  return -0.010
            if idx_pct < -0.06:  return -0.006
            if idx_pct < -0.03:  return -0.004
            if idx_pct < 0:      return -0.002
        return 0.0

    def _estimate_with_treasury_index(self, code: str) -> Dict[str, Any]:
        """
        日均增长(30日) + 国债指数方向 双重信号

        回测显示(20d):
        511360: 日增长+0.0026, σ=0.0020 → 日均增长可靠, 国债指数微调
        511520: 日增长+0.0041, σ=0.087 → 日均增长不稳定, 国债指数参考价值大
        
        新增: 使用国债指数历史K线数据辅助验证日均增长的合理性
        """
        meta = BOND_ETF_META.get(code, {})
        latest_nav = self.get_latest_nav(code)
        latest_date = self.get_latest_nav_date(code)
        idx_pct = self._get_treasury_pct()

        result = {
            'latest_nav': latest_nav,
            'latest_nav_date': latest_date,
            'treasury_index_pct': idx_pct,
            'estimated_nav': None,
            'method': 'unknown',
        }

        if latest_nav is None:
            return result

        # 始终用算法计算预估值（即使今天净值已公布）
        estimated = latest_nav

        # 步骤1: 日均增长 (20日均线, 更灵敏响应近期趋势)
        avg_growth = self.calc_avg_daily_growth(code, days=20)
        result['avg_daily_growth'] = avg_growth
        if avg_growth is not None:
            try:
                last_dt = datetime.strptime(latest_date, '%Y-%m-%d')
            except (ValueError, TypeError):
                last_dt = None
            if last_dt:
                current_dt = last_dt + timedelta(days=1)
                while current_dt.strftime('%Y-%m-%d') <= today:
                    if current_dt.weekday() >= 5:
                        current_dt += timedelta(days=1)
                        continue
                    estimated += avg_growth
                    current_dt += timedelta(days=1)

        # 步骤2: 国债指数日内方向修正
        if idx_pct is not None:
            adjustment = self._get_index_adjustment(code, idx_pct)
            estimated += adjustment
            if adjustment != 0:
                result['index_adjustment'] = adjustment

        # 步骤3: [新增] 用国债指数历史K线验证日均增长的合理性
        # 如果国债指数近期持续上涨，适当上调预估净值；反之下调
        try:
            treasury_hist = self.get_treasury_history(days=30)
            if treasury_hist and len(treasury_hist) >= 5:
                # 取最近5天国债指数均值 vs 30天前均值
                recent_5 = [d['close'] for d in treasury_hist[:5]]
                older_5 = [d['close'] for d in treasury_hist[25:30]] if len(treasury_hist) >= 30 else []
                
                if older_5 and all(v > 0 for v in recent_5 + older_5):
                    recent_avg = sum(recent_5) / len(recent_5)
                    older_avg = sum(older_5) / len(older_5)
                    idx_trend = (recent_avg / older_avg - 1) * 100  # 百分比
                    
                    # 如果国债指数趋势明显(>0.1%)，微调预估净值
                    if idx_trend > 0.1 and code != '511880':  # 511880不受国债指数影响
                        # 微调幅度: 国债指数趋势的10% (保守)
                        trend_adj = avg_growth * 0.1 if avg_growth else 0
                        estimated += trend_adj
                        result['treasury_trend_pct'] = round(idx_trend, 3)
                        result['treasury_adjustment'] = round(trend_adj, 4)
        except Exception as e:
            logger.debug(f"[BondETF] 国债指数趋势验证跳过: {e}")

        result['estimated_nav'] = round(estimated, 4)
        result['method'] = 'hybrid'
        return result

    # ══════════════════════════════════════════
    # 5. 对外接口
    # ══════════════════════════════════════════
    def get_valuation(self, code: str) -> Dict[str, Any]:
        """统一估值入口 - 全部使用日均增长法"""
        return self.estimate_today_nav(code)

    def estimate_today_nav(self, code: str) -> Dict[str, Any]:
        """统一估值入口 - 511880用日均增长法, 511360用国债指数跟踪法"""
        meta = BOND_ETF_META.get(code)
        if not meta:
            return {'error': f'未知基金代码 {code}'}

        latest_nav = self.get_latest_nav(code)
        latest_date = self.get_latest_nav_date(code)

        result = {
            'latest_nav': latest_nav,
            'latest_nav_date': latest_date,
            'estimated_nav': None,
            'method': 'unknown',
        }

        if latest_nav is None:
            return result

        # 始终用算法计算预估值（即使今天净值已公布）
        today = datetime.now().strftime('%Y-%m-%d')

        # ══ 511360: 日均票息 + 国债指数连续公式 ══
        # 公式: estimated = prev_nav + daily_coupon + idx_pct × idx_coefficient
        if code == '511360':
            daily_coupon = meta.get('daily_coupon', 0.003)
            idx_coeff = meta.get('idx_coefficient', 0.07)
            idx_pct = self._get_treasury_pct()
            result['treasury_index_pct'] = idx_pct

            if idx_pct is None:
                result['estimated_nav'] = latest_nav + daily_coupon
                result['daily_coupon'] = daily_coupon
                result['method'] = 'coupon_only_no_index'
                return result

            # 连续公式: 底仓票息 + 指数敏感度 × 涨跌幅
            idx_adj = round(idx_pct * idx_coeff, 4)
            result['index_adjustment'] = idx_adj
            result['daily_coupon'] = daily_coupon
            result['idx_coefficient'] = idx_coeff
            estimated = latest_nav + daily_coupon + idx_adj
            result['estimated_nav'] = round(estimated, 4)
            result['method'] = 'coupon+treasury_linear'
            return result

        # ══ 511520: 日均票息 + T2609期货方向修正 ══
        if code == '511520':
            daily_coupon = meta.get('daily_coupon', 0.02)

            # Check manual BP override first (from Choice terminal input)
            manual_bp = get_manual_bp(code)
            futures_adj = 0.0
            if manual_bp:
                # Manual override: convert BP to NAV adjustment
                # 10Y BP change: 1bp = 0.01% of NAV
                bp_10y = manual_bp.get('bp_10y', 0)
                futures_adj = latest_nav * (bp_10y / 10000)
                result['bp_source'] = 'manual'
                result['bp_7y'] = manual_bp.get('bp_7y', 0)
                result['bp_10y'] = bp_10y
                logger.info("[511520] Using manual BP: 7Y=%s, 10Y=%s, adj=%.4f",
                           manual_bp.get('bp_7y', 0), bp_10y, futures_adj)
            else:
                # Auto: use T2609 futures data
                futures_data = self._get_treasury_futures_data()
                if futures_data:
                    result['futures_pct'] = futures_data.get('pct_change')
                    t_pct = futures_data.get('pct_change', 0)
                    futures_adj = latest_nav * t_pct / 100 * 1.0
                    result['futures_coefficient'] = 1.0
                    result['bp_source'] = 'futures'
                else:
                    result['bp_source'] = 'none'

            # Formula: latest_nav + daily_coupon + futures_adj
            estimated = latest_nav + daily_coupon + futures_adj
            result['daily_coupon'] = daily_coupon
            result['futures_adjustment'] = futures_adj
            result['estimated_nav'] = round(estimated, 4)
            result['method'] = 'coupon+futures_T2609'
            return result

        # ══ 511880/其他: 日均增长法 ══
        avg_growth = self.calc_avg_daily_growth(code)
        result['avg_daily_growth'] = avg_growth

        if avg_growth is None:
            result['estimated_nav'] = latest_nav
            result['method'] = 'latest_only'
            return result

        estimated = latest_nav
        weekend_on = meta.get('weekend_on')

        try:
            last_dt = datetime.strptime(latest_date, '%Y-%m-%d')
        except (ValueError, TypeError):
            result['estimated_nav'] = latest_nav
            return result

        current_dt = last_dt + timedelta(days=1)
        while current_dt.strftime('%Y-%m-%d') <= today:
            if current_dt.weekday() >= 5:
                current_dt += timedelta(days=1)
                continue

            daily_gain = avg_growth
            if weekend_on == 'friday' and current_dt.weekday() == 4:
                daily_gain = avg_growth * 3
            elif weekend_on == 'monday' and current_dt.weekday() == 0:
                daily_gain = avg_growth * 3

            estimated += daily_gain
            current_dt += timedelta(days=1)

        result['estimated_nav'] = round(estimated, 4)
        result['method'] = 'estimated'
        return result

    def get_premium_data(self, code: str, market_price: Optional[float] = None) -> Dict[str, Any]:
        """获取完整折溢价数据"""
        val = self.get_valuation(code)
        result = {
            'fund_code': code,
            'fund_name': BOND_ETF_META.get(code, {}).get('name', ''),
            'estimated_nav': val.get('estimated_nav'),
            'latest_nav': val.get('latest_nav'),
            'latest_nav_date': val.get('latest_nav_date'),
            'avg_daily_growth': val.get('avg_daily_growth'),
            'method': val.get('method'),
            'treasury_index_pct': val.get('treasury_index_pct'),
            'index_adjustment': val.get('index_adjustment'),
            'market_price': market_price,
            'premium': None,
            'premium_pct': None,
        }
        if market_price and val.get('estimated_nav') and val['estimated_nav'] > 0:
            premium_pct = (market_price / val['estimated_nav'] - 1) * 100
            result['premium'] = round(market_price - val['estimated_nav'], 4)
            result['premium_pct'] = round(premium_pct, 3)
        return result


# ── 全局单例 ──
_instance = None

def get_bond_etf_valuation(db=None, market_data_service=None) -> BondETFValuation:
    global _instance
    if _instance is None:
        _instance = BondETFValuation(db, market_data_service)
    return _instance
