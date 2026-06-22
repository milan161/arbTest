"""
511520 估值算法回测脚本 (使用用户提供的历史数据)

目标：找最优 T2609 期货转换系数
公式：预估净值 = 最新净值 + 日均票息(0.0082) + T2609涨跌幅 × 系数 × 0.01
"""
import statistics
from typing import List, Dict

DAILY_COUPON = 0.0082  # 日均票息 (万分之0.7/天 × 117面值)

# 用户提供的历史数据
# 格式: (日期, 净值, 期货涨幅%)
HISTORY_DATA = [
    ('2026-06-18', 117.8132, None),      # 期货数据缺失
    ('2026-06-17', 117.7667, 0.037),
    ('2026-06-16', 117.6770, 0.128),
    ('2026-06-15', 117.4645, 0.007),
    ('2026-06-12', 117.4510, 0.035),
    ('2026-06-11', 117.3182, -0.065),
    ('2026-06-10', 117.4175, -0.137),
    ('2026-06-09', 117.5471, -0.083),
    ('2026-06-08', 117.6445, -0.081),
    ('2026-06-05', 117.7293, -0.051),
    ('2026-06-04', 117.8248, 0.069),
    ('2026-06-03', 117.7601, -0.065),
    ('2026-06-02', 117.8340, 0.060),
    ('2026-06-01', 117.8529, 0.009),
    ('2026-05-29', 117.8040, 0.069),
    ('2026-05-28', 117.7857, 0.067),
    ('2026-05-27', 117.7501, 0.104),
    ('2026-05-26', 117.5498, 0.012),
    ('2026-05-25', 117.3910, 0.060),
]


def backtest_coefficient(data: List[tuple], coefficient: float) -> Dict:
    """回测指定系数"""
    errors = []
    details = []
    
    for i in range(len(data) - 1):
        today_date, today_nav, today_futures_pct = data[i]
        yesterday_date, yesterday_nav, _ = data[i + 1]
        
        # 跳过期货数据缺失的天
        if today_futures_pct is None:
            continue
        
        latest_nav = yesterday_nav
        actual_nav = today_nav
        
        # 新算法: 最新净值 + 日均票息 + 期货方向修正
        # 修正: futures_adj = latest_nav × t_pct% × coefficient
        estimated = latest_nav + DAILY_COUPON + latest_nav * today_futures_pct / 100 * coefficient
        
        error = estimated - actual_nav
        error_pct = abs(error / actual_nav) * 100
        
        errors.append(error_pct)
        details.append({
            'date': today_date,
            'latest_nav': latest_nav,
            'actual_nav': actual_nav,
            't_pct': today_futures_pct,
            'estimated': round(estimated, 4),
            'error': round(error, 4),
            'error_pct': round(error_pct, 4),
        })
    
    if not errors:
        return {'mae': 999, 'max_error': 999, 'median': 999, 'within_005': 0, 'within_010': 0, 'details': []}
    
    mae = statistics.mean(errors)
    max_error = max(errors)
    median_error = statistics.median(errors)
    within_005 = sum(1 for e in errors if e <= 0.05) / len(errors) * 100
    within_010 = sum(1 for e in errors if e <= 0.10) / len(errors) * 100
    
    return {
        'mae': round(mae, 4),
        'max_error': round(max_error, 4),
        'median': round(median_error, 4),
        'within_005': round(within_005, 1),
        'within_010': round(within_010, 1),
        'details': details,
    }


def main():
    print("=" * 70)
    print("511520 估值算法回测 (新公式: 票息 + T2609期货)")
    print("=" * 70)
    print(f"日均票息: {DAILY_COUPON} (万分之0.7/天)")
    print(f"数据范围: {HISTORY_DATA[-1][0]} ~ {HISTORY_DATA[0][0]}")
    print(f"有效回测天数: {sum(1 for d in HISTORY_DATA if d[2] is not None)}")
    print()
    
    # 测试不同系数
    coefficients = [0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0, 1.2, 1.5]
    results = []
    
    print(f"{'系数':>6} {'MAE':>8} {'最大误差':>10} {'中位数':>8} {'<=0.05%':>8} {'<=0.10%':>9}")
    print("-" * 60)
    
    for coeff in coefficients:
        result = backtest_coefficient(HISTORY_DATA, coeff)
        results.append((coeff, result))
        print(f"{coeff:>6.2f} {result['mae']:>7.4f}% {result['max_error']:>9.4f}% "
              f"{result['median']:>7.4f}% {result['within_005']:>7.1f}% {result['within_010']:>8.1f}%")
    
    # 找最优系数 (MAE最小)
    best_coeff, best_result = min(results, key=lambda x: x[1]['mae'])
    print()
    print("=" * 70)
    print(f"最优系数: {best_coeff:.2f}")
    print(f"  MAE: {best_result['mae']:.4f}%")
    print(f"  最大误差: {best_result['max_error']:.4f}%")
    print(f"  中位数: {best_result['median']:.4f}%")
    print(f"  <=0.05%: {best_result['within_005']:.1f}%")
    print(f"  <=0.10%: {best_result['within_010']:.1f}%")
    print("=" * 70)
    
    # 打印所有天明细
    print(f"\n所有回测天明细 (系数={best_coeff:.2f}):")
    print(f"{'日期':<12} {'前日NAV':>10} {'实际NAV':>10} {'T2609%':>8} {'预估NAV':>10} {'误差':>10} {'误差率':>10}")
    print("-" * 75)
    for d in best_result['details']:
        print(f"{d['date']:<12} {d['latest_nav']:>10.4f} {d['actual_nav']:>10.4f} "
              f"{d['t_pct']:>7.3f}% {d['estimated']:>10.4f} {d['error']:>10.4f} {d['error_pct']:>9.4f}%")
    
    # 对比旧算法
    print("\n" + "=" * 70)
    print("旧算法 (159649+期货离散) 对比:")
    print("  MAE: 0.0665% (方案A)")
    print("  <=0.10%: 76.4%")
    print()
    print(f"新算法 (票息+T2609 系数={best_coeff:.2f}):")
    print(f"  MAE: {best_result['mae']:.4f}%")
    print(f"  <=0.10%: {best_result['within_010']:.1f}%")
    print("=" * 70)


if __name__ == '__main__':
    main()
