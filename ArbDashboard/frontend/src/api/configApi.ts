/**
 * 配置 API（数据源、基金配置）
 */
import client from './client'

/** 获取数据源配置列表 */
export function getDataSources(module: string = 'realtime_market') {
  return client.get('/api/config/data_sources', { params: { module } })
}

/** 更新数据源配置 */
export function updateDataSource(data: {
  module?: string
  source_name: string
  priority?: number
  is_active?: boolean
  config?: Record<string, any>
}) {
  return client.post('/api/config/data_sources/update', data)
}

/** 批量更新优先级 */
export function updateDataSourcesPriority(module: string, priorities: Array<{ source_name: string; priority: number }>) {
  return client.post('/api/config/data_sources/priority', { module, priorities })
}

/** 获取所有基金配置（YAML） */
export function getFundConfigs() {
  return client.get('/api/config/funds')
}

/** 新增/修改基金配置 */
export function upsertFundConfig(data: Record<string, any>) {
  return client.post('/api/config/funds/upsert', data)
}

/** 删除基金配置 */
export function deleteFundConfig(code: string) {
  return client.delete(`/api/config/funds/${code}`)
}

/** 导出基金配置为 YAML 文件 */
export function exportFundConfig() {
  return client.get('/api/config/funds/export', { responseType: 'blob' })
}

/** 导入基金配置 YAML 文件 */
export function importFundConfig(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return client.post('/api/config/funds/import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 获取 IB 核心套利标的列表 */
export function getIbCoreSymbols() {
  return client.get('/api/config/ib_core_symbols')
}

/** 更新 IB 核心套利标的列表 */
export function postIbCoreSymbols(symbols: string[]) {
  return client.post('/api/config/ib_core_symbols', { symbols })
}

/** 获取是否跳过QDII亚洲/国内LOF指数实时抓取 */
export function getSkipQdiiAsiaIndex() {
  return client.get('/api/config/app_settings/skip_qdii_asia_index')
}

/** 更新跳过QDII亚洲/国内LOF指数设置 */
export function postSkipQdiiAsiaIndex(data: { skip: boolean }) {
  return client.post('/api/config/app_settings/skip_qdii_asia_index', data)
}

/** 回补缺失指数历史数据 */
export function postBackfillIndices(days?: number) {
  return client.post('/api/config/app_settings/backfill_indices', { days: days || 30 })
}
