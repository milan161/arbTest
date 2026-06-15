/**
 * 系统 API
 */
import client from './client'

/** 系统运行里程碑日志 */
export function getMilestones() {
  return client.get('/api/system/milestones')
}

/** 重新连接 IB */
export function reconnectIB() {
  return client.post('/api/system/reconnect_ib')
}

/** 重启国内行情引擎 */
export function reconnectEngine() {
  return client.post('/api/system/reconnect_engine')
}

/** 触发后台任务（011/012 等） */
export function triggerTask(task: string) {
  return client.post(`/api/system/trigger/${task}`)
}

/** 健康检查 */
export function getHealth() {
  return client.get('/api/health')
}

/** 获取净值更新状态 */
export function getNavStatus() {
  return client.get('/api/system/nav-status')
}

/** 获取数据同步状态（Woody/汇率/期货/份额） */
export function getDataStatus() {
  return client.get('/api/system/data-status')
}

/** 获取交易账号列表 */
export function getAccounts() {
  return client.get('/api/system/accounts')
}

/** 保存交易账号列表 */
export function saveAccounts(accounts: Record<string, string>) {
  return client.post('/api/system/accounts', { accounts })
}
