/**
 * 基金数据 API
 */
import client from './client'

/** 看板统一数据 */
export function getDashboard(
  params?: { watchlist?: string; category?: string },
  signal?: AbortSignal
) {
  return client.get('/api/dashboard', { params, signal })
}

/** 基金历史对账数据 */
export function getFundHistory(code: string) {
  return client.get(`/api/fund/${code}/history`)
}

/** 动态基金分类（主看板 TAB 用） */
export function getCategories() {
  return client.get('/api/config/categories')
}

/** 基金分时数据（曲线图用） */
export function getFundIntraday(code: string, date?: string) {
  return client.get(`/api/fund/${code}/intraday`, { params: { date } })
}

/** 基金篮子权重 */
export function getFundBasket(code: string) {
  return client.get(`/api/fund/${code}/basket`)
}

/** 基金估值元数据（深度分析页用） */
export function getFundValuationMeta(code: string) {
  return client.get(`/api/fund/${code}/valuation_meta`)
}

/** 市场概览（汇率、活跃数据源、统计） */
export function getMarketOverview() {
  return client.get('/api/market/overview')
}

/** 单只标的实时行情 */
export function getRealtimeQuote(code: string) {
  return client.get(`/api/market/realtime/${code}`)
}

/** 历史净值 */
export function getHistoricalNav(code: string, startDate?: string) {
  return client.get(`/api/market/historical/nav/${code}`, { params: { start_date: startDate } })
}

/** 历史价格 */
export function getHistoricalPrice(code: string, startDate?: string) {
  return client.get(`/api/market/historical/price/${code}`, { params: { start_date: startDate } })
}

/** 幽灵做市商实时计算 */
export function getLazyCalc(fundCode: string) {
  return client.get('/api/private/lazy_calc', { params: { fund_code: fundCode } })
}

/** 幽灵做市商下单 */
export function postLazyPlaceOrder(mode: string, fundCode: string, params?: {
  price?: number,
  lof_price?: number,
  quantity?: number,
  etf_quantity?: number,
  underlying_symbol?: string,
}) {
  return client.post('/api/private/lazy_place_order', { mode, fund_code: fundCode, ...params })
}

/** 幽灵做市商 - 诊断状态 */
export function getLazyStatus() {
  return client.get('/api/private/lazy_status')
}

/** 幽灵模拟器 - 获取状态 */
export function getLazySimStatus() {
  return client.get('/api/private/lazy_simulate/status')
}

/** 幽灵模拟器 - 控制(start/stop/reset/force_signal) */
export function postLazySimControl(action: string, extras?: Record<string, any>) {
  return client.post('/api/private/lazy_simulate/control', { action, ...extras })
}

/** 债券ETF - 设置手动BP覆盖 */
export function postBpOverride(code: string, bp7y: number, bp10y: number) {
  return client.post('/api/bond/bp-override', { code, bp_7y: bp7y, bp_10y: bp10y })
}

/** 债券ETF - 获取今日BP覆盖 */
export function getBpOverride(code: string) {
  return client.get('/api/bond/bp-override', { params: { code } })
}

/** 债券ETF - 清除BP覆盖 */
export function clearBpOverride(code: string) {
  return client.post('/api/bond/bp-override/clear', { code })
}

/** 白银比价数据（161226 沪银/SI 比价） */
export function getSilverRatio() {
  return client.get('/api/silver/ratio')
}
