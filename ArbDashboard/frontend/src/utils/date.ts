/**
 * 日期工具函数
 */

/** 获取今天的 YYYY-MM-DD 格式字符串 */
export function today(): string {
  const d = new Date()
  return d.toISOString().slice(0, 10)
}

/** 格式化日期为 YYYY-MM-DD */
export function formatDate(date: Date | string | number): string {
  if (typeof date === 'string' && date.includes('-')) {
    return date.slice(0, 10)
  }
  const d = date instanceof Date ? date : new Date(date)
  return d.toISOString().slice(0, 10)
}

/** 判断当前是否为周末（周六或周日） */
export function isWeekend(): boolean {
  const day = new Date().getDay()
  return day === 0 || day === 6
}

/** 判断当前时间是否在 A 股交易时段内 */
export function isATradingTime(): boolean {
  const now = new Date()
  const h = now.getHours()
  const m = now.getMinutes()
  const wd = now.getDay()
  // 周末休市
  if (wd === 0 || wd === 6) return false
  // 上午 9:30 - 11:30
  if ((h === 9 && m >= 30) || h === 10 || (h === 11 && m <= 30)) return true
  // 下午 13:00 - 15:00
  if (h === 13 || (h === 14 && m <= 59) || (h === 15 && m === 0)) return true
  return false
}

/** 日期截短为 MM-DD */
export function shortDate(dateStr: string): string {
  return dateStr ? dateStr.slice(5, 10) : '-'
}

/** 判断是否为今天 */
export function isToday(dateStr: string): boolean {
  return dateStr?.startsWith(today())
}
