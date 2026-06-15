/**
 * 基金数据 API
 */
import client from './client'

/** 看板统一数据 */
export function getDashboard(params?: { watchlist?: string; category?: string }) {
  return client.get('/api/dashboard', { params })
}

/** 基金历史对账数据 */
export function getFundHistory(code: string) {
  return client.get(`/api/fund/${code}/history`)
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
