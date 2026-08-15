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

// ===== [AI-2026-08-15] IB 真实成交同步（替代手动 Excel）=====

/** 解析 IB 网页导出的活动账单 CSV 并入库（盈透API无法查历史，改走CSV） */
export function syncIbExecutions() {
  return client.post('/api/ledger/ib-sync', {})
}

/** 查询已同步的 IB 成交流水 */
export function getIbExecutions(days: number = 0) {
  return client.get('/api/ledger/ib-executions', { params: { days } })
}

/** 获取券商赎回费率 */
export function getFeeRate(fundCode: string, broker: string = '') {
  return client.get('/api/ledger/fee-rate', { params: { fund_code: fundCode, broker } })
}

// ===== [AI-2026-08-15] 华宝(通达信)历史成交导入（替代手动Excel）=====

/** 扫描导入目录最新txt并解析入库（code：源头过滤，只导入该基金代码，防无关交易入库） */
export function syncTdxExecutions(code?: string) {
  return client.post('/api/ledger/tdx-sync', { code })
}

/** 查询已导入的华宝成交流水 */
export function getTdxExecutions(params?: { code?: string; category?: string; days?: number }) {
  return client.get('/api/ledger/tdx-executions', { params })
}

// ===== [AI-2026-08-15] 银河QMT历史成交（经桥接策略 QUERY_DEALS 实时查询）=====
/** 触发银河QMT历史成交查询并入库（start_date 形如 20260601） */
/** 扫描导入目录最新"*银河*.txt"并解析入库（通达信导出的银河账户历史成交，与华宝同套路） */
export function syncQmtExecutions() {
  return client.post('/api/ledger/qmt-sync')
}

/** 查询已入库的银河QMT成交流水 */
export function getQmtExecutions(params?: { code?: string; days?: number }) {
  return client.get('/api/ledger/qmt-executions', { params })
}

// ===== [AI-2026-08-15] 手动配对对账 =====

/** 汇总三源所有未配对交易 */
export function getUnpairedTrades() {
  return client.get('/api/ledger/unpaired-trades')
}

/** 手动配对：勾选最多4条腿，force=true 跳过对冲校验 */
export function matchPair(legKeys: string[], force = false) {
  return client.post('/api/ledger/pair-match', { leg_keys: legKeys, force })
}

/** 查询已配对的套利对列表 */
export function getMatchedPairs() {
  return client.get('/api/ledger/matched-pairs')
}

/** 撤销配对（释放腿回待配对区） */
export function unmatchPair(pairId: number) {
  return client.post('/api/ledger/unmatch-pair', { pair_id: pairId })
}

// ===== Excel Import =====

/** 解析Excel文件返回预览数据 */
export function importExcelPreview(filePath: string) {
  return client.post('/api/ledger/import-excel', { file_path: filePath })
}

/** 确认导入Excel数据 */
export function confirmExcelImport(pairs: Record<string, any>[]) {
  return client.post('/api/ledger/import-excel/confirm', { pairs })
}

