/**
 * 数字与格式工具函数
 * 集中管理所有数值精度、颜色逻辑、带符号格式化
 */

/** 基金名称清洗：去掉末尾的 LOF 后缀 */
export function cleanFundName(name: string): string {
  return (name || '')
    .replace(/LOF$/, '')
    .replace('国瑞白银期货', '白银期货')
}

/** 红色（涨/溢价） */
export const COLOR_UP = '#f44336'
/** 绿色（跌/折价） */
export const COLOR_DOWN = '#4caf50'
/** 灰色（无变化） */
export const COLOR_FLAT = '#888'
/** 灰色（次要文字） */
export const COLOR_MUTED = '#64748b'

/** 根据数值正负返回红/绿/灰色 */
export function priceColor(value: number): string {
  if (value > 0) return COLOR_UP
  if (value < 0) return COLOR_DOWN
  return COLOR_FLAT
}

/** 带 + 号的百分比格式化（如 "+1.23%" / "-0.45%"） */
export function formatPercent(value: number, precision: number = 2): string {
  if (value === 0) return '0.00%'
  const sign = value > 0 ? '+' : ''
  return sign + value.toFixed(precision) + '%'
}

/** 带颜色的百分比（返回 { text, color }） */
export function formatPercentWithColor(
  value: number,
  precision: number = 2
): { text: string; color: string } {
  return {
    text: formatPercent(value, precision),
    color: priceColor(value)
  }
}

/** 溢价率格式化（精确到 3 位小数，如 "+0.123%" / "-0.456%"） */
export function formatPremium(value: number): string {
  if (value === 0) return '0.000%'
  const sign = value > 0 ? '+' : ''
  return sign + value.toFixed(3) + '%'
}

/** 价格格式化（3 位小数） */
export function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || value <= 0) return '-'
  return value.toFixed(3)
}

/** 估值/净值格式化（4 位小数） */
export function formatValuation(value: number | null | undefined): string {
  if (value === null || value === undefined || value <= 0) return '-'
  return value.toFixed(4)
}

/** 成交额（万元）格式化 */
export function formatVolume(value: number | null | undefined): string {
  if (value === null || value === undefined || value <= 0) return '-'
  return Number(value).toFixed(2)
}

/** 份额格式化（整数） */
export function formatShares(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '-'
  return Number(value).toFixed(0)
}

/** 份额变动格式化（带 + 号） */
export function formatSharesChange(value: number | null | undefined): string {
  const v = Number(value || 0)
  if (v === 0) return '-'
  const sign = v > 0 ? '+' : ''
  return sign + v.toFixed(0)
}

/** 换手率格式化 */
export function formatTurnoverRate(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return '-'
  return Number(value).toFixed(2) + '%'
}

/** 指数价格格式化 */
export function formatIndexPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || value <= 0) return '-'
  return value.toFixed(2)
}

/** 日期截取（去掉年份，只显示 MM-DD） */
export function formatShortDate(dateStr: string | null | undefined): string {
  if (!dateStr || dateStr === '-') return '-'
  return dateStr.substring(5)
}

/** 申购/赎回状态标签类型映射 */
export function statusTagType(status: string): 'success' | 'warning' | 'default' {
  if (!status || status === '未知') return 'default'
  if (status.includes('开放')) return 'success'
  return 'warning'
}

/** 汇率变动格式化 */
export function formatFxChange(value: number): string {
  if (value === 0) return '0.00%'
  const sign = value > 0 ? '+' : ''
  return sign + value.toFixed(2) + '%'
}

/** 将 NaN / null / undefined 安全转换为 0 */
export function safeNumber(value: any, fallback: number = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}
