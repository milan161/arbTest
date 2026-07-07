/**
 * 公共下单逻辑 composable
 * 实时沙盘 (Analysis.vue) 和 懒人页面 (LazyMode.vue) 共用
 */
import { useMessage, useDialog } from 'naive-ui'
import { addTrade } from '../api/ledgerApi'
import { placeOrder } from '../api/tradingApi'

export function useOrderLogic() {
  const message = useMessage()
  const dialog = useDialog()

  // ========== LOF 下单函数（共用） ==========
  const sendLofOrder = async (action, fundCode, fundName, lofPrice, lofQty, broker) => {
    if (!lofPrice || !lofQty) {
      message.warning('请输入价格和数量')
      return
    }
    
    const brokerName = broker === 'yinhe_qmt' ? '银河QMT' : (broker === 'tdx' ? '通达信' : '国金QMT')
    const actionName = action === 'BUY' ? '买入' : '卖出'
    
    dialog.warning({
      title: '确认下单',
      content: `您将向 [${brokerName}] 发起实盘委托，请确认参数：\n\n` +
        `・ 标的代码: ${fundCode}\n` +
        `・ 委托方向: ${actionName}\n` +
        `・ 委托价格: ￥${lofPrice.toFixed(3)}\n` +
        `・ 委托数量: ${lofQty} 股`,
      positiveText: '确认发送',
      negativeText: '取消',
      onPositiveClick: async () => {
        message.loading('正在发送委托指令，请稍候...')
        try {
          const res = await placeOrder({ action, code: fundCode, volume: lofQty, price: lofPrice, broker })
          if (res.data.status === 'ok') {
            message.success(`下单结果: ${res.data.message}`)
            await addTrade({
              fund_code: fundCode, fund_name: fundName, action,
              volume: lofQty, price: lofPrice,
              hedge_symbol: '', hedge_price: 0, hedge_vol: 0,
            })
          } else {
            message.error(`下单失败: ${res.data.message}`)
            dialog.error({
              title: '下单失败',
              content: `券商/通道接口返回错误: ${res.data.message}`,
            })
          }
        } catch (e) {
          message.error(`接口调用异常: ${e.message || e}`)
        }
      },
    })
  }

  // ========== IB 下单函数（共用） ==========
  // mode: 'safe' = 保守吃买一, 'peg' = 内卷减一分排队
  const sendIbOrder = async (action, tradeEtf, hedgePrice, hedgeVol, fundCode, mode = 'safe') => {
    if (!tradeEtf) {
      message.warning('未检测到交易标的')
      return
    }
    
    const modeName = mode === 'peg' ? '🤺 减一分排队' : '🛡️ 立即吃买一'
    
    dialog.warning({
      title: '确认下单',
      content: `您将向 [IB (盈透证券)] 发起实盘委托，请确认参数：\n\n` +
        `・ 标的代码: ${tradeEtf}\n` +
        `・ 委托方向: ${action === 'BUY' ? '买入' : '卖出'}\n` +
        `・ 委托价格: $${hedgePrice.toFixed(2)}\n` +
        `・ 委托数量: ${hedgeVol}`,
      positiveText: '确认发送',
      negativeText: '取消',
      onPositiveClick: async () => {
        message.loading('正在发送委托指令，请稍候...')
        try {
          // [AI-2026-06-26] IB 下单改为走 LazyTrader lazy_place_order API
          const { default: client } = await import('../api/client')
          const payload = {
            mode: mode,
            direction: action === 'BUY' ? 'close' : 'open',
            fund_code: fundCode || '162411',
            underlying_symbol: tradeEtf,
            quantity: 0,
            etf_quantity: hedgeVol,
            price: hedgePrice,
            lof_price: 0,
          }
          console.log('[sendIbOrder] payload:', payload)
          const res = await client.post('/api/private/lazy_place_order', payload)
          console.log('[sendIbOrder] response:', res.data)
          if (res.data.status === 'ok') {
            message.success(`${modeName} IB下单成功: ${JSON.stringify(res.data.data || res.data)}`)
          } else {
            message.error(`IB下单失败: ${res.data.message || JSON.stringify(res.data)}`)
            dialog.error({
              title: 'IB下单失败',
              content: `券商/通道接口返回错误: ${res.data.message || JSON.stringify(res.data)}`,
            })
          }
        } catch (e) {
          message.error(`接口调用异常: ${e.message || e}`)
        }
      },
    })
  }

  // ========== 直接 IB 下单函数（实时沙盘专用，不走 LazyTrader） ==========
  const sendDirectIbOrder = async (action, symbol, price, quantity) => {
    if (!symbol || !quantity || !price) {
      message.warning('请输入标的、价格和数量')
      return
    }
    const actionName = action === 'BUY' ? '买入' : '卖出'
    dialog.warning({
      title: '确认下单',
      content: `您将向 [IB (盈透证券)] 发起实盘委托，请确认参数：\n\n` +
        `・ 标的代码: ${symbol}\n` +
        `・ 委托方向: ${actionName}\n` +
        `・ 委托价格: $${price.toFixed(2)}\n` +
        `・ 委托数量: ${quantity}`,
      positiveText: '确认发送',
      negativeText: '取消',
      onPositiveClick: async () => {
        message.loading('正在发送委托指令，请稍候...')
        try {
          const { default: client } = await import('../api/client')
          const res = await client.post('/api/trading/ib_order', {
            action, symbol, quantity, price,
          })
          if (res.data.status === 'ok') {
            message.success(`IB下单成功: ${res.data.message}`)
          } else {
            message.error(`IB下单失败: ${res.data.message}`)
            dialog.error({
              title: 'IB下单失败',
              content: `IB接口返回错误: ${res.data.message}`,
            })
          }
        } catch (e) {
          message.error(`接口调用异常: ${e.message || e}`)
        }
      },
    })
  }

  return { sendLofOrder, sendIbOrder, sendDirectIbOrder }
}
