/**
 * 交易 API
 */
import client from './client'

/** 获取真实持仓 */
export function getPositions() {
  return client.get('/api/trading/positions')
}

/** 获取账户余额 */
export function getBalance() {
  return client.get('/api/trading/balance')
}

/** 手动下单 */
export function placeOrder(params: {
  action: string
  code: string
  volume: number
  price: number
  broker?: string
  account_id?: string
}) {
  return client.post('/api/trading/order', params)
}
