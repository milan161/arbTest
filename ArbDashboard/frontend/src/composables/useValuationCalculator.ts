/**
 * useValuationCalculator - 共享估值计算器逻辑
 *
 * Analysis.vue 和 LazyMode.vue 共用此 composable，
 * 统一管理：
 * - reactive 状态（meta, depth, simLofPrice, testEtfPrices 等）
 * - computed 属性（etfVal, futCalibVal, pureFutVal 等）
 * - 数据获取（fetchValuationMeta, fetchRealtimeDepth）
 * - 轮询控制（startPolling / stopPolling）
 *
 * 价格初始化（2026-07-08 修复）：
 * - LOF价 → depth.ask[0]（卖一价）
 * - ETF价 → quoteObj.bid（买一价）
 */
import { ref, computed, reactive, watch } from 'vue'
import { getFundValuationMeta, getRealtimeQuote } from '../api'

export function useValuationCalculator() {
  // ============================================================
  // 1. 输入
  // ============================================================
  const fundCode = ref('')

  // ============================================================
  // 2. Reactive 状态
  // ============================================================
  const meta = ref<any>(null)
  const depth = reactive({
    ask: [0, 0, 0, 0, 0] as number[],
    ask_vol: [0, 0, 0, 0, 0] as number[],
    bid: [0, 0, 0, 0, 0] as number[],
    bid_vol: [0, 0, 0, 0, 0] as number[],
    source: '',
    price: 0,
  })
  const simLofPrice = ref(0)
  const testEtfPrices = reactive<Record<string, number>>({})
  const testFutPrice = ref(0)
  const testFutCalib = ref(1.0)
  const latestExchangeRateInput = ref(0)
  const isLofPriceInitialized = ref(false)
  const isHedgePriceInitialized = ref(false)
  const showFutCalib = ref(false)
  const showPureFut = ref(false)

  // LOF 买入股数（Analysis.vue 原名 targetCapitalEtf, LazyMode.vue 原名 targetLofQty）
  const targetLofQty = ref(60000)
  const targetLotsFuture = ref(1)
  const targetLotsPureFuture = ref(1)

  // ============================================================
  // 3. Computed 属性
  // ============================================================

  /** 是否为现金管理基金（债券ETF） */
  const isCashManagement = computed(() =>
    ['511880', '511360', '511520'].includes(fundCode.value),
  )

  /** 是否为复杂业务分类（黄金原油、纯ETF、QDII欧美、混合跨境） */
  const isComplexCategory = computed(() => {
    if (isCashManagement.value) return false
    const cat = meta.value?.fund_config?.category || ''
    const simpleCategories = ['QDII 亚洲', 'QDII亚洲', '国内LOF', '指数LOF', '白银', '其他']
    return !simpleCategories.includes(cat)
  })

  /** 是否为白银基金 */
  const isSilver = computed(() => fundCode.value === '161226')

  /** 基础仓位比率 */
  const positionRatio = computed(() => {
    if (!meta.value) return 0.95
    const bd = meta.value.base_data || {}
    const cfg = meta.value.fund_config || {}
    if (bd.position !== undefined && bd.position !== null && !isNaN(parseFloat(bd.position))) {
      return parseFloat(bd.position)
    }
    if (cfg.position !== undefined && cfg.position !== null && !isNaN(parseFloat(cfg.position))) {
      return parseFloat(cfg.position) / 100.0
    }
    return 0.95
  })

  /** 估值标的下拉列表（去重） */
  const uniqueValuationSymbols = computed(() => {
    // Priority 1: valuation_portfolio
    if (meta.value?.fund_config?.valuation_portfolio?.length > 0) {
      const seen = new Set()
      const result: any[] = []
      for (const item of meta.value.fund_config.valuation_portfolio) {
        if (!item.symbol) continue
        const baseSym = item.symbol.replace(/^\^/, '').split('-')[0].toUpperCase()
        if (!seen.has(baseSym)) {
          seen.add(baseSym)
          result.push({
            symbol: baseSym,
            currency: item.currency || 'USD',
          })
        }
      }
      return result
    }
    // Priority 2: realtime_quotes keys
    const rqKeys = Object.keys(meta.value?.realtime_quotes || {})
    if (rqKeys.length > 0) {
      return rqKeys.map((sym) => ({ symbol: sym.toUpperCase(), currency: 'USD' }))
    }
    // Priority 3: trade_etf
    if (meta.value?.fund_config?.trade_etf) {
      return [{ symbol: meta.value.fund_config.trade_etf.toUpperCase(), currency: 'USD' }]
    }
    return []
  })

  /** 基准日 ETF 收盘价文本 */
  const baseEtfsText = computed(() => {
    if (!meta.value || !meta.value.base_data || !meta.value.fund_config) return '-'
    const bd = meta.value.base_data
    const cfg = meta.value.fund_config
    const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
    return portfolio
      .map((item: any) => {
        let sym = item.symbol || ''
        for (const suffix of ['-EU', '-JP', '-HK']) {
          if (sym.endsWith(suffix) && !sym.startsWith('^')) {
            sym = '^' + sym
            break
          }
        }
        const cleanSym = sym.replace(/^\^/, '')
        const caretSym = sym.startsWith('^') ? sym : '^' + sym
        const price =
          bd[caretSym] !== undefined
            ? bd[caretSym]
            : bd[cleanSym] !== undefined
              ? bd[cleanSym]
              : 0
        return `${sym}: ${Number(price).toFixed(2)} (${Number(item.weight).toFixed(1)}%)`
      })
      .join(' | ')
  })

  /** 实时 ETF 价格文本 */
  const realtimeEtfsText = computed(() => {
    if (!meta.value || !meta.value.realtime_quotes) return '-'
    return Object.entries(meta.value.realtime_quotes)
      .map(([sym, quoteObj]) => {
        const price =
          quoteObj && typeof quoteObj === 'object'
            ? (quoteObj as any).price
            : quoteObj
        return `${sym}: ${price ? Number(price).toFixed(2) : '-'}`
      })
      .join(' | ')
  })

  /** 外盘数据源文本 */
  const foreignSource = computed(() => {
    if (!meta.value) return '等待行情...'
    if (fundCode.value === '161226') {
      return meta.value.future_quote?.source || '等待 SSE...'
    }
    const quotes = meta.value.realtime_quotes
    if (quotes) {
      for (const key in quotes) {
        if (quotes[key] && quotes[key].source) {
          return quotes[key].source
        }
      }
    }
    if (meta.value.future_quote && meta.value.future_quote.source) {
      return meta.value.future_quote.source
    }
    return '未连接 IB/富途'
  })

  /** LOF 盘口数据源文本 */
  const localDepthSource = computed(() => {
    if (!depth.source) return '等待行情...'
    const s = depth.source.toLowerCase()
    if (s.includes('tongdaxin') || s.includes('tdx')) return '通达信'
    if (s.includes('yinhe')) return '银河QMT'
    if (s.includes('guojin') || s.includes('gj')) return '国金QMT'
    if (s.includes('sina')) return '新浪'
    if (s.includes('tencent')) return '腾讯'
    return depth.source
  })

  /** 汇率名称 */
  const rateHeaderName = computed(() => {
    if (!meta.value || !meta.value.fund_config) return '汇率'
    const currency = meta.value.fund_config.valuation_portfolio?.[0]?.currency || 'USD'
    return `${currency}/CNY 汇率`
  })

  // ============================================================
  // 4. ETF 实时估值计算
  // ============================================================

  /** ETF 实时估值 */
  const etfVal = computed(() => {
    if (!meta.value || !meta.value.base_data) return 0
    const bd = meta.value.base_data
    const cfg = meta.value.fund_config

    const baseNav = parseFloat(bd.nav) || 0
    const pos = positionRatio.value
    const currentFx = parseFloat(latestExchangeRateInput.value as any) || 0
    const baseFx = parseFloat(bd.exchange_rate) || 0

    if (baseNav <= 0 || currentFx <= 0) return 0

    const bHedge = parseFloat(bd.hedge) || 0
    const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []

    // 单个标的：直接公式
    if (bHedge > 0 && portfolio.length === 1) {
      const p = portfolio[0]
      const sym = p.symbol || ''
      const cleanSym = sym.replace(/^\^/, '').split('-')[0].toUpperCase()
      const cPrice = parseFloat(testEtfPrices[cleanSym] as any) || 0
      if (cPrice > 0) {
        return baseNav * (1.0 - pos) + (cPrice * currentFx) / bHedge
      }
    }

    // basket 为空时，用 trade_etf 兜底
    if (bHedge > 0 && portfolio.length === 0 && cfg.trade_etf) {
      const cleanSym = cfg.trade_etf.replace(/^\^/, '').toUpperCase()
      const cPrice = parseFloat(testEtfPrices[cleanSym] as any) || 0
      if (cPrice > 0) {
        return baseNav * (1.0 - pos) + (cPrice * currentFx) / bHedge
      }
    }

    // 多标的：加权变化率
    if (portfolio.length > 0) {
      const fxChange = currentFx / (baseFx || 1.0)
      let wChange = 0.0

      for (const p of portfolio) {
        const fullSym = p.symbol || ''
        const cleanSymKey = fullSym.replace(/^\^/, '')
        const caretSymKey = '^' + cleanSymKey
        const bPrice =
          parseFloat(
            bd[caretSymKey] !== undefined
              ? bd[caretSymKey]
              : bd[cleanSymKey] !== undefined
                ? bd[cleanSymKey]
                : bd[fullSym] || 0,
          ) || 0
        const cleanSym = fullSym.replace(/^\^/, '').split('-')[0].toUpperCase()
        const cPrice = parseFloat(testEtfPrices[cleanSym] as any) || 0
        const weight = (parseFloat(p.weight) || 0) / 100.0

        if (cPrice > 0 && bPrice > 0 && weight != 0) {
          wChange += (cPrice / bPrice) * weight
        }
      }

      if (wChange !== 0) {
        const netRatio = pos * (wChange * fxChange - 1.0)
        return baseNav * (1.0 + netRatio)
      }
    }

    return 0
  })

  /** 期货校准实时估值 */
  const futCalibVal = computed(() => {
    if (!meta.value || !meta.value.base_data) return 0
    const bd = meta.value.base_data
    const cfg = meta.value.fund_config

    const baseNav = parseFloat(bd.nav) || 0
    const pos = positionRatio.value
    const todayExchangeRate = parseFloat(latestExchangeRateInput.value as any) || 0
    const baseExchangeRate = parseFloat(bd.exchange_rate) || 0

    const futPrice = parseFloat(testFutPrice.value as any) || 0
    const calib = parseFloat(testFutCalib.value as any) || 0

    if (baseNav <= 0 || todayExchangeRate <= 0 || futPrice <= 0 || calib <= 0) return 0

    const equivSpot = futPrice / calib
    const category = cfg.category || ''
    const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []

    if (category === '指数') {
      let equivEtf = 0
      const mainAnchorSymbol = portfolio[0]?.symbol || ''
      const cleanMainSym = mainAnchorSymbol.replace(/^\^/, '')
      const caretMainSym = '^' + cleanMainSym
      const baseEtfPrice =
        parseFloat(
          bd[caretMainSym] !== undefined
            ? bd[caretMainSym]
            : bd[cleanMainSym] !== undefined
              ? bd[cleanMainSym]
              : bd[mainAnchorSymbol] || 0,
        ) || 0
      const baseIndexPrice = parseFloat(bd.index_close) || 0

      if (baseIndexPrice > 0 && baseEtfPrice > 0) {
        equivEtf = equivSpot * (baseEtfPrice / baseIndexPrice)
      } else if (parseFloat(bd.calibration) > 0 && baseEtfPrice > 0) {
        const derivedBaseIndexPrice = parseFloat(bd.calibration) / calib
        equivEtf = equivSpot * (baseEtfPrice / derivedBaseIndexPrice)
      }

      const hedgeValue = parseFloat(bd.hedge) || 0
      const etfCalibration = hedgeValue > 0 && pos > 0 ? hedgeValue * pos : 0

      if (etfCalibration > 0 && equivEtf > 0) {
        return baseNav * (1.0 - pos) + (pos / etfCalibration) * (equivEtf * todayExchangeRate)
      } else {
        if (baseIndexPrice > 0) {
          const spotChangeRate = equivSpot / baseIndexPrice
          const exchangeRateChange = todayExchangeRate / baseExchangeRate
          return baseNav * (1 + pos * (spotChangeRate * exchangeRateChange - 1))
        }
      }
    } else {
      let weightedFuturesChangeRate = 0.0
      let totalValidWeight = 0.0
      const validEtfs: any[] = []

      for (const item of portfolio) {
        if (item.weight <= 0 || item.weight < 0.02 || item.symbol.includes('SLV')) {
          continue
        }
        validEtfs.push(item)
        totalValidWeight += item.weight
      }

      if (totalValidWeight > 0) {
        for (const vItem of validEtfs) {
          const cleanVSym = vItem.symbol.replace(/^\^/, '')
          const caretVSym = '^' + cleanVSym
          const baseEtfPrice =
            parseFloat(
              bd[caretVSym] !== undefined
                ? bd[caretVSym]
                : bd[cleanVSym] !== undefined
                  ? bd[cleanVSym]
                  : bd[vItem.symbol] || 0,
            ) || 0
          if (baseEtfPrice > 0) {
            const etfChangeRate = equivSpot / baseEtfPrice
            const normalizedWeight = vItem.weight / totalValidWeight
            weightedFuturesChangeRate += etfChangeRate * normalizedWeight
          }
        }
        const exchangeRateChange = todayExchangeRate / baseExchangeRate
        return baseNav * (1 + pos * (weightedFuturesChangeRate * exchangeRateChange - 1))
      }
    }

    return 0
  })

  /** 纯期货实时估值 */
  const pureFutVal = computed(() => {
    if (!meta.value || !meta.value.base_data) return 0
    const bd = meta.value.base_data

    const baseNav = parseFloat(bd.nav) || 0
    const pos = positionRatio.value
    const todayExchangeRate = parseFloat(latestExchangeRateInput.value as any) || 0
    const baseExchangeRate = parseFloat(bd.exchange_rate) || 0

    const futPrice = parseFloat(testFutPrice.value as any) || 0
    const baseFuturePrice = parseFloat(bd.calibration) || 0

    if (
      baseNav <= 0 ||
      todayExchangeRate <= 0 ||
      futPrice <= 0 ||
      baseFuturePrice <= 0 ||
      baseExchangeRate <= 0
    )
      return 0

    const futureChangeRate = futPrice / baseFuturePrice
    const exchangeRateChange = todayExchangeRate / baseExchangeRate
    return baseNav * (1 + pos * (futureChangeRate * exchangeRateChange - 1))
  })

  /** ETF 实时溢价率 */
  const derivedEtfPremium = computed(() => {
    if (etfVal.value <= 0 || simLofPrice.value <= 0) return 0
    return (simLofPrice.value / etfVal.value - 1) * 100
  })

  /** 期货校准溢价率 */
  const derivedFutPremium = computed(() => {
    if (futCalibVal.value <= 0 || simLofPrice.value <= 0) return 0
    return (simLofPrice.value / futCalibVal.value - 1) * 100
  })

  /** 纯期货溢价率 */
  const derivedPureFutPremium = computed(() => {
    if (pureFutVal.value <= 0 || simLofPrice.value <= 0) return 0
    return (simLofPrice.value / pureFutVal.value - 1) * 100
  })

  /** 等价 ETF 价格（期货校准后） */
  const equivEtfPrice = computed(() => {
    const futPrice = parseFloat(testFutPrice.value as any) || 0
    const calib = parseFloat(testFutCalib.value as any) || 0
    if (futPrice > 0 && calib > 0) {
      return futPrice / calib
    }
    return 0
  })

  /** 投入金额（从 LOF 股数反算） */
  const syncedCapital = computed(() => {
    const pos = positionRatio.value
    if (targetLofQty.value <= 0 || simLofPrice.value <= 0 || pos <= 0) return 0
    return Math.round(targetLofQty.value * simLofPrice.value)
  })

  // ============================================================
  // 5. 对冲数量计算
  // ============================================================

  /** ETF 对冲数量 */
  const lofQtyEtf = computed(() => {
    if (targetLofQty.value <= 0 || etfVal.value <= 0 || simLofPrice.value <= 0) return null
    const bd = meta.value?.base_data
    if (!bd) return null
    const cfg = meta.value.fund_config
    const pos = positionRatio.value

    const etfHedge = parseFloat(bd.hedge) || 0
    if (etfHedge <= 0) return null

    const finalLofQty = Math.round(targetLofQty.value / 100) * 100
    const finalEtfQty = Math.max(1, Math.round(finalLofQty / etfHedge))

    const targetInvestment = finalLofQty * simLofPrice.value

    // 一篮子拆解
    let portfolioBreakdown: any[] = []
    const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
    if (portfolio.length > 1) {
      const targetExposureRMB = finalLofQty * simLofPrice.value * pos
      const currentFx = parseFloat(latestExchangeRateInput.value) || 0
      if (currentFx > 0) {
        const targetExposureUSD = targetExposureRMB / currentFx
        for (const p of portfolio) {
          const fullSym = p.symbol || ''
          const cleanSym = fullSym.replace(/^\^/, '').split('-')[0].toUpperCase()
          const cPrice = parseFloat(testEtfPrices[cleanSym]) || 0
          const weight = (parseFloat(p.weight) || 0) / 100.0
          if (cPrice > 0 && weight != 0) {
            const qty = (targetExposureUSD * weight) / cPrice
            portfolioBreakdown.push({
              symbol: fullSym,
              qty: qty.toFixed(1),
              isShort: qty < 0,
            })
          }
        }
      }
    }

    return {
      lofQty: finalLofQty,
      etfQty: finalEtfQty,
      exposure: targetInvestment * pos,
      breakdown: portfolioBreakdown,
    }
  })

  /** 期货校准对冲数量 */
  const lofQtyFuture = computed(() => {
    if (targetLotsFuture.value <= 0 || !meta.value || !meta.value.base_data) return null
    const bd = meta.value.base_data
    const cfg = meta.value.fund_config
    const etfHedge = parseFloat(bd.hedge) || 0
    const calib = parseFloat(testFutCalib.value as any) || 1.0

    let multiplier = 1
    const tradeFutureSym = cfg.trade_future || ''
    if (tradeFutureSym.includes('MGC')) multiplier = 10
    else if (tradeFutureSym.includes('GC')) multiplier = 100
    else if (tradeFutureSym.includes('MCL')) multiplier = 100
    else if (tradeFutureSym.includes('CL')) multiplier = 1000
    else if (tradeFutureSym.includes('MNQ')) multiplier = 2
    else if (tradeFutureSym.includes('NQ')) multiplier = 20
    else if (tradeFutureSym.includes('MES')) multiplier = 5
    else if (tradeFutureSym.includes('ES')) multiplier = 50
    else if (tradeFutureSym.toUpperCase().includes('AG')) multiplier = 15

    const displayHedgeValue = etfHedge * calib * multiplier
    if (displayHedgeValue <= 0) return null

    const rawLofQty = (targetLotsFuture.value * displayHedgeValue) / simLofPrice.value
    const finalLofQty = Math.round(rawLofQty / 100) * 100
    const pos = positionRatio.value
    const exposure = finalLofQty * simLofPrice.value * pos

    return { lofQty: finalLofQty, hedgeValue: displayHedgeValue, exposure }
  })

  /** 纯期货对冲数量 */
  const lofQtyPureFuture = computed(() => {
    if (targetLotsPureFuture.value <= 0 || !meta.value || !meta.value.base_data) return null
    const bd = meta.value.base_data
    const cfg = meta.value.fund_config
    const etfHedge = parseFloat(bd.hedge) || 0
    const calib = parseFloat(bd.calibration) || 1.0

    let multiplier = 1
    const tradeFutureSym = cfg.trade_future || ''
    if (tradeFutureSym.includes('MGC')) multiplier = 10
    else if (tradeFutureSym.includes('GC')) multiplier = 100
    else if (tradeFutureSym.includes('MCL')) multiplier = 100
    else if (tradeFutureSym.includes('CL')) multiplier = 1000
    else if (tradeFutureSym.includes('MNQ')) multiplier = 2
    else if (tradeFutureSym.includes('NQ')) multiplier = 20
    else if (tradeFutureSym.includes('MES')) multiplier = 5
    else if (tradeFutureSym.includes('ES')) multiplier = 50
    else if (tradeFutureSym.toUpperCase().includes('AG')) multiplier = 15

    const displayHedgeValue = etfHedge * calib * multiplier
    if (displayHedgeValue <= 0) return null

    const finalLofQty = Math.round((targetLotsPureFuture.value * displayHedgeValue) / 100) * 100
    const pos = positionRatio.value
    const exposure = finalLofQty * simLofPrice.value * pos

    return { lofQty: finalLofQty, hedgeValue: displayHedgeValue, exposure }
  })

  // ============================================================
  // 6. 数据获取
  // ============================================================

  /** 获取 LOF 实时盘口深度 */
  const fetchRealtimeDepth = async () => {
    if (!fundCode.value) return
    try {
      const res = await getRealtimeQuote(fundCode.value)
      if (res.data.status === 'ok') {
        const q = res.data.data
        depth.ask = q.ask || [0, 0, 0, 0, 0]
        depth.ask_vol = q.ask_vol || [0, 0, 0, 0, 0]
        depth.bid = q.bid || [0, 0, 0, 0, 0]
        depth.bid_vol = q.bid_vol || [0, 0, 0, 0, 0]
        depth.source = q.source || ''
        depth.price = q.price || 0

        // [AI-2026-07-08] 修复：LOF 价初始化使用卖一价 (ask[0]) 而非最新成交价
        if (!isLofPriceInitialized.value && depth.ask[0] > 0) {
          simLofPrice.value = depth.ask[0]
          isLofPriceInitialized.value = true
        }
      }
    } catch (e) {
      /* ignore */
    }
  }

  /** 获取估值元数据 */
  const fetchValuationMeta = async () => {
    if (!fundCode.value) return
    try {
      const res = await getFundValuationMeta(fundCode.value)
      if (res.data.status === 'ok') {
        meta.value = res.data
        latestExchangeRateInput.value = res.data.latest_exchange_rate || 7.0

        // [AI-2026-07-08] 修复：ETF 初始化使用买一价 (bid) 而非最新成交价
        for (const [sym, quoteObj] of Object.entries(res.data.realtime_quotes)) {
          const qObj = quoteObj as any
          const inputEl = document.activeElement as HTMLElement
          const isInputFocused =
            inputEl && inputEl.tagName === 'INPUT' && inputEl.getAttribute('data-sym') === sym

          if (!isInputFocused && qObj) {
            // 优先用 bid (买一价)，没有则用 price
            const bidVal = typeof qObj === 'object' ? qObj.bid : null
            const priceVal = typeof qObj === 'object' ? qObj.price : qObj
            const newVal = bidVal || priceVal || 0
            if (newVal) {
              testEtfPrices[sym] = Number(newVal)
            }
          } else if (!testEtfPrices[sym]) {
            let defaultPrice =
              parseFloat(res.data.base_data[sym]) ||
              parseFloat(res.data.base_data['^' + sym]) ||
              0
            if (!defaultPrice && res.data.base_data) {
              const matchedKey = Object.keys(res.data.base_data).find((k) => {
                const cleanK = k.replace(/^\^/, '').split('-')[0].toUpperCase()
                return cleanK === sym.toUpperCase()
              })
              if (matchedKey) {
                defaultPrice = parseFloat(res.data.base_data[matchedKey]) || 0
              }
            }
            testEtfPrices[sym] = defaultPrice
          }
        }

        // hedgePrice 初始化：用 trade_etf 的 bid
        const tradeEtf = res.data.fund_config?.trade_etf
        if (tradeEtf && res.data.realtime_quotes[tradeEtf]) {
          const qObj = res.data.realtime_quotes[tradeEtf]
          if (qObj && typeof qObj === 'object') {
            if (!isHedgePriceInitialized.value && (qObj as any).bid > 0) {
              // hedgePrice 由各页面自己管理，这里只在 composable 标记已初始化
              isHedgePriceInitialized.value = true
            }
          }
        }

        const bd = res.data.base_data
        testFutCalib.value = bd.calibration || 1.0

        // [AI-2026-07-08] 修复：LOF 价兜底用 卖一价(ask) > depth.price > currentPrice > t1 > close
        if (!isLofPriceInitialized.value) {
          if (depth.ask[0] > 0) {
            simLofPrice.value = depth.ask[0]
            isLofPriceInitialized.value = true
          } else if (depth.price > 0) {
            simLofPrice.value = depth.price
            isLofPriceInitialized.value = true
          } else if (res.data.t1_data && res.data.t1_data.price > 0) {
            simLofPrice.value = res.data.t1_data.price
            isLofPriceInitialized.value = true
          } else if (bd.close > 0) {
            simLofPrice.value = bd.close
            isLofPriceInitialized.value = true
          }
        }

        // 债券 ETF 额外数据
        if (res.data.avg_daily_growth !== undefined) {
          meta.value.avg_daily_growth = res.data.avg_daily_growth
        }
        if (res.data.bond_etf_method !== undefined) {
          meta.value.bond_etf_method = res.data.bond_etf_method
        }
        if (res.data.treasury_index_pct !== undefined) {
          meta.value.treasury_index_pct = res.data.treasury_index_pct
        }
        if (res.data.estimated_nav !== undefined) {
          meta.value.estimated_nav = res.data.estimated_nav
        }
        if (res.data.latest_nav !== undefined) {
          meta.value.latest_nav = res.data.latest_nav
        }
        if (res.data.latest_nav_date !== undefined) {
          meta.value.latest_nav_date = res.data.latest_nav_date
        }
      }
    } catch (e) {
      console.error('Failed to fetch valuation meta:', e)
    }
  }

  /** 轮询回调 */
  let pollCount = 0
  const pollRealtime = async () => {
    if (!fundCode.value) return
    await fetchRealtimeDepth()
    await fetchValuationMeta()
    pollCount++
  }

  // ============================================================
  // 7. 轮询控制
  // ============================================================
  let realtimeTimer: any = null

  const startPolling = () => {
    stopPolling()
    realtimeTimer = setInterval(pollRealtime, 3000)
  }

  const stopPolling = () => {
    if (realtimeTimer) {
      clearInterval(realtimeTimer)
      realtimeTimer = null
    }
  }

  const resetInitialized = () => {
    isLofPriceInitialized.value = false
    isHedgePriceInitialized.value = false
    simLofPrice.value = 0
    // 清空 ETF 价格数组
    for (const key of Object.keys(testEtfPrices)) {
      delete testEtfPrices[key]
    }
  }

  // ============================================================
  // ⚠️ 下面是由各页面自己管理的状态（不在 composable 中）
  // 这些需要在每个页面单独定义：
  // - lofBroker, orderVol, hedgeVol, hedgePrice, autoLog
  // - navDate, t2Nav, t1StaticVal, calibrationValue
  // - intradayData, basketData, currentPrice 等
  // - 规则引擎相关（LazyMode 特有）
  // ============================================================

  return {
    // Input
    fundCode,

    // State
    meta,
    depth,
    simLofPrice,
    testEtfPrices,
    testFutPrice,
    testFutCalib,
    latestExchangeRateInput,
    isLofPriceInitialized,
    isHedgePriceInitialized,
    showFutCalib,
    showPureFut,
    targetLofQty,
    targetLotsFuture,
    targetLotsPureFuture,

    // Computed
    isCashManagement,
    isComplexCategory,
    isSilver,
    positionRatio,
    uniqueValuationSymbols,
    baseEtfsText,
    realtimeEtfsText,
    foreignSource,
    localDepthSource,
    rateHeaderName,
    etfVal,
    futCalibVal,
    pureFutVal,
    derivedEtfPremium,
    derivedFutPremium,
    derivedPureFutPremium,
    equivEtfPrice,
    syncedCapital,
    lofQtyEtf,
    lofQtyFuture,
    lofQtyPureFuture,

    // Data fetching
    fetchRealtimeDepth,
    fetchValuationMeta,
    pollRealtime,
    resetInitialized,

    // Polling
    startPolling,
    stopPolling,
  }
}
