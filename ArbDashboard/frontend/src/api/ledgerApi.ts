/**
 * 实盘对账 API
 */
import client from './client'

/** 获取交易记录 */
export function getTrades(status: string = 'ACTIVE') {
  return client.get('/api/ledger/trades', { params: { status } })
}

/** 新增套利对 */
export function addTrade(data: Record<string, any>) {
  return client.post('/api/ledger/trades/add', data)
}

/** 关闭交易 */
export function closeTrade(tradeId: number) {
  return client.post(`/api/ledger/trades/close/${tradeId}`)
}

/** 获取基金费率 */
export function getFundFees(code: string) {
  return client.get(`/api/config/fees/${code}`)
}

/** 新增/修改基金费率 */
export function upsertFundFee(data: Record<string, any>) {
  return client.post('/api/config/fees/upsert', data)
}

/** 获取券商赎回费率列表 */
export function getBrokerFees() {
  return client.get('/api/ledger/broker_fees')
}

/** 新增券商赎回费率 */
export function addBrokerFee(data: Record<string, any>) {
  return client.post('/api/ledger/broker_fees/add', data)
}

/** 删除券商赎回费率 */
export function deleteBrokerFee(feeId: number) {
  return client.post(`/api/ledger/broker_fees/delete/${feeId}`)
}

// ===== V9.2 套利对账本 =====

/** 获取套利对列表 */
export function getPairs(status?: string) {
  const params: Record<string, string> = {}
  if (status) params.status = status
  return client.get('/api/ledger/pairs', { params })
}

/** 新增套利对 */
export function addPair(data: Record<string, any>) {
  return client.post('/api/ledger/pairs/add', data)
}

/** 更新套利对 */
export function updatePair(pairId: number, data: Record<string, any>) {
  return client.post(`/api/ledger/pairs/update/${pairId}`, data)
}

/** 删除套利对 */
export function deletePair(pairId: number) {
  return client.post(`/api/ledger/pairs/delete/${pairId}`)
}

/** 自动记录交易（QMT执行回调） */
export function autoRecordTrade(data: Record<string, any>) {
  return client.post('/api/ledger/auto-record', data)
}

/** 获取券商赎回费率（自动关联填入） */
export function getFeeRate(fundCode: string, broker: string = '') {
  return client.get('/api/ledger/fee-rate', { params: { fund_code: fundCode, broker } })
}

// ===== [AI-2026-08-16] 赎回提醒（OPEN 笔推算可优惠赎回日 / unfinished 待净值）=====
/** 查询赎回提醒：OPEN 笔的可优惠赎回日/倒计时/告警级别 + unfinished 待净值提示 */
export function getLedgerAlerts() {
  return client.get('/api/ledger/alerts')
}

// ===== [AI-2026-08-16] 导入 V7 Excel 账本（upsert，不删除已有记录）=====
/** 上传 v7 Excel 套利账本，解析并 upsert 到数据库。返回 { inserted, updated, skipped, errors } */
export function importV7Ledger(file: File) {
  const form = new FormData()
  form.append('file', file)
  return client.post('/api/ledger/import-v7', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}
