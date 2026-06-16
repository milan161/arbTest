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
    },
    '511520': {
        'name': '政金债ETF富国',
        'type': 'mid_bond',
        'weekend_on': None,
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
        with self._cache_lock:
            cached = self._nav_cache.get(code)
            if cached and time.monotonic() - cached[0] < NAV_CACHE_TTL:
                return cached[1]
        records = self._fetch_nav_history(code, days)
        if records:
            with self._cache_lock:
                self._nav_cache[code] = (time.monotonic(), records)
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
    def calc_avg_daily_growth(self, code: str, days: int = 30) -> Optional[float]:
        """计算日均净值增长 (正确处理周末效应)"""
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

            if delta_days >= 3:
                # 跨周末: 日均 = nav_change / delta_days
                daily_rates.append(nav_change / delta_days)
            else:
                # 平日变化
                daily_rates.append(nav_change)

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
    # 3. 国债指数 000012 获取
    # ══════════════════════════════════════════
    def _get_treasury_index_data(self) -> Optional[Dict]:
        """获取国债指数000012实时行情"""
        idx_cache_key = '000012'
        with self._cache_lock:
            cached = self._idx_cache.get(idx_cache_key)
            if cached and time.monotonic() - cached[0] < 60:  # 1分钟缓存
                return cached[1]

        result = None
        # 优先级1: 新浪接口
        try:
            url = "http://hq.sinajs.cn/list=s_sh000012"
            headers = {'Referer': 'https://finance.sina.com.cn/'}
            resp = requests.get(url, headers=headers, timeout=3)
            if resp.status_code == 200 and '="' in resp.text:
                parts = resp.text.split('"')[1].split(',')
                if len(parts) >= 6:
                    name = parts[0]
                    # sh000012 格式: name,current,change,change%,volume,amount
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
        except Exception as e:
            logger.warning(f"[BondETF] 新浪国债指数失败: {e}")

        # 优先级2: TDX
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

    def _get_treasury_pct(self) -> Optional[float]:
        """获取国债指数涨跌幅(%)"""
        data = self._get_treasury_index_data()
        return data.get('pct_change') if data else None

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

        today = datetime.now().strftime('%Y-%m-%d')
        if latest_date == today:
            result['estimated_nav'] = latest_nav
            result['method'] = 'actual'
            return result

        estimated = latest_nav

        # 步骤1: 日均增长 (30日均线, 捕获票息carry)
        avg_growth = self.calc_avg_daily_growth(code, days=30)
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

        result['estimated_nav'] = round(estimated, 4)
        result['method'] = 'hybrid'
        return result

    # ══════════════════════════════════════════
    # 5. 对外接口
    # ══════════════════════════════════════════
    def get_valuation(self, code: str) -> Dict[str, Any]:
        """统一估值入口"""
        if code == '511880':
            # 货币基金: 日均增长法
            return self.estimate_today_nav(code)
        else:
            # 511360/511520: 国债指数方向 + 日均增长
            return self._estimate_with_treasury_index(code)

    def estimate_today_nav(self, code: str) -> Dict[str, Any]:
        """日均增长法 (主要适用于511880)"""
        meta = BOND_ETF_META.get(code)
        if not meta:
            return {'error': f'未知基金代码 {code}'}

        latest_nav = self.get_latest_nav(code)
        latest_date = self.get_latest_nav_date(code)
        avg_growth = self.calc_avg_daily_growth(code)

        result = {
            'latest_nav': latest_nav,
            'latest_nav_date': latest_date,
            'avg_daily_growth': avg_growth,
            'estimated_nav': None,
            'method': 'unknown',
        }

        if latest_nav is None:
            return result

        today = datetime.now().strftime('%Y-%m-%d')
        if latest_date == today:
            result['estimated_nav'] = latest_nav
            result['method'] = 'actual'
            return result

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
