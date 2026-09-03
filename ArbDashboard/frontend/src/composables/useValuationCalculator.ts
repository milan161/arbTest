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
import { ref, computed, reactive, watch, onMounted } from 'vue'
import { getFundValuationMeta, getRealtimeQuote, getRealtimeCalc, getRealtimeFuturesCalc } from '../api'

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
  // [AI-2026-07-20] 默认改为 100 股（实盘测试用小单，避免误下大单）
  const targetLofQty = ref(100)
  const targetLotsFuture = ref(1)
  const targetLotsPureFuture = ref(1)

  // ============================================================
  // 3. Computed 属性
  // ============================================================

  /** 是否为现金管理基金（债券ETF） */
  const isCashManagement = computed(() =>
    ['511880', '511360', '511520'].includes(fundCode.value),
  )

  /** 是否为复杂业务分类（黄金原油、QDII欧美、QDII日本） */
  const isComplexCategory = computed(() => {
    if (isCashManagement.value) return false
    const cat = meta.value?.fund_config?.category || ''
    const simpleCategories = ['QDII 亚洲', 'QDII亚洲', '国内LOF', '指数LOF', '白银', '其他']
    return !simpleCategories.includes(cat)
  })

  /** 是否为白银基金 */
  const isSilver = computed(() => fundCode.value === '161226')

  /** [AI-2026-08-28] 白银参考估值: NAV(T-2) × (AG0实时价 / AG0昨结算) */
  const ag0Val = computed(() => {
    if (!isSilver.value) return 0
    const bd = meta.value?.base_data || {}
    const fq = meta.value?.future_quote as any
    const nav = parseFloat(bd.nav) || 0
    const agPrice = parseFloat(fq?.price || fq?.bid || 0)
    const agSettle = parseFloat(fq?.settlement || fq?.ask || 0)
    if (nav <= 0 || agPrice <= 0 || agSettle <= 0) return 0
    return nav * (agPrice / agSettle)
  })

  /** [AI-2026-08-28] 白银溢价率 */
  const ag0Premium = computed(() => {
    if (!isSilver.value) return 0
    if (ag0Val.value <= 0 || simLofPrice.value <= 0) return 0
    return (simLofPrice.value / ag0Val.value - 1) * 100
  })

  /** [AI-2026-07-29] 是否为 QDII日本基金（纯期货估值，无需ETF/NKY盘口）
   *  改读 category（业务分类），与 valuation_method 估值词表(etf/basket/index)解耦，单一真相源 */
  const isQDIIJapan = computed(() => {
    const category = meta.value?.fund_config?.category || ''
    return category === 'QDII日本'
  })

  // [AI-2026-07-23] QDII日本基金默认显示纯期货估值
  onMounted(() => {
    if (isQDIIJapan.value) {
      showPureFut.value = true
    }
  })
  watch(isQDIIJapan, (val) => {
    if (val) showPureFut.value = true
  })

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
    // Priority 2: realtime_quotes keys (过滤掉基金自身代码—它是A股价格，不是估值标的)
    const rqKeys = Object.keys(meta.value?.realtime_quotes || {}).filter((sym) => sym !== fundCode.value)
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
  // [AI-2026-07-17] 修复：不再 fallback 到 future_quote.source（期货数据源误标为外盘源）
  // 只检查估值标的（非基金自身代码）的实时行情来源
  const foreignSource = computed(() => {
    if (!meta.value) return '等待行情...'
    if (fundCode.value === '161226') {
      return meta.value.future_quote?.source || '等待 SSE...'
    }
    const quotes = meta.value.realtime_quotes
    if (quotes) {
      for (const key in quotes) {
        if (key === fundCode.value) continue  // 跳过基金自身代码（A股来源）
        if (quotes[key] && quotes[key].source) {
          return quotes[key].source
        }
      }
      // 有外盘标的key但全无数据 → 获取中
      for (const key in quotes) {
        if (key === fundCode.value) continue
        return '等待数据...'
      }
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

  // [AI-2026-08-05] etfVal 改为后端封装驱动（recalcBackend 填充），删除前端手算公式。
  const etfVal = ref(0)

  // [AI-2026-08-05] futCalibVal 改为后端封装驱动（recalcBackend 填充），删除前端手算公式。
  const futCalibVal = ref(0)

  // [AI-2026-08-05] pureFutVal 改为后端封装驱动（recalcBackend 填充），删除前端手算公式。
  const pureFutVal = ref(0)

  // [AI-2026-08-05] 后端封装估值重算：把当前手填 what-if 输入发往 canonical 引擎，回填三个估值 ref。
  // 失败策略：后端 422/缺数据 → 置 0（模板显示 '-'）；网络异常 → 保留上次好值（绝不兜底假数）。
  let recalcTimer: any = null
  const scheduleRecalc = () => {
    if (recalcTimer) clearTimeout(recalcTimer)
    recalcTimer = setTimeout(() => {
      void recalcBackend()
    }, 250)
  }

  const recalcBackend = async () => {
    if (!meta.value || !fundCode.value) return
    const code = fundCode.value
    const fx = parseFloat(latestExchangeRateInput.value as any) || 0
    const lof = parseFloat(simLofPrice.value as any) || 0
    try {
      // ETF 模式（主估值面板常显，只要有篮子成分价就重算）
      if (Object.keys(testEtfPrices).length > 0) {
        const r = await getRealtimeCalc({ code, lof_price: lof, fx, etfs: JSON.stringify(testEtfPrices) })
        if (r.data.status === 'ok' && r.data.rt_val && r.data.rt_val > 0) etfVal.value = r.data.rt_val
        else etfVal.value = 0
      }
      // 期货校准模式
      if (showFutCalib.value && isComplexCategory.value) {
        const fp = parseFloat(testFutPrice.value as any)
        const cb = parseFloat(testFutCalib.value as any)
        if (fp > 0 && cb > 0) {
          const r = await getRealtimeFuturesCalc({
            code, mode: 'calib', futures_price: fp, calibration: cb, lof_price: lof, fx,
          })
          if (r.data.status === 'ok' && r.data.rt_val && r.data.rt_val > 0) futCalibVal.value = r.data.rt_val
          else futCalibVal.value = 0
        } else futCalibVal.value = 0
      }
      // 纯期货模式
      if (showPureFut.value && isComplexCategory.value) {
        const fp = parseFloat(testFutPrice.value as any)
        if (fp > 0) {
          const r = await getRealtimeFuturesCalc({
            code, mode: 'pure', futures_price: fp, lof_price: lof, fx,
          })
          if (r.data.status === 'ok' && r.data.rt_val && r.data.rt_val > 0) pureFutVal.value = r.data.rt_val
          else pureFutVal.value = 0
        } else pureFutVal.value = 0
      }
    } catch (e) {
      // 网络异常：保留上次好值，不兜底
      console.warn('[recalcBackend] 后端估值请求失败，保留上次结果', e)
    }
  }

  // 手动输入 → 防抖重算（轮询由 pollRealtime 直接调 recalcBackend 实时刷新）
  watch(
    [() => testFutPrice.value, () => testFutCalib.value, () => simLofPrice.value, () => latestExchangeRateInput.value],
    () => scheduleRecalc(),
  )
  watch(testEtfPrices, () => scheduleRecalc(), { deep: true })
  // 面板切换（期货校准/纯期货显隐、复杂分类）立即重算
  watch([showFutCalib, showPureFut, isComplexCategory], () => scheduleRecalc())

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

    // 对冲敞口必须用净值 NAV（不是 LOF 市价）——见 docs/004-2 第九节已定位 bug
    const baseNav = parseFloat(bd.nav) || simLofPrice.value
    const navBasedExposure = finalLofQty * baseNav * pos

    // 一篮子拆解——恒定对冲比 H 魔法（与 Excel 四步法一致，不依赖实时 ETF 价，且不踩 cleanSym 折叠 bug）
    // H = [(Σ wᵢ·base_priceᵢ)·fx_base / nav] / position；qtyᵢ = round(LOF_qty · wᵢ / H)
    let portfolioBreakdown: any[] = []
    const portfolio = cfg.valuation_portfolio || cfg.hedging_portfolio || []
    if (portfolio.length > 1) {
      const fxBase = parseFloat(bd.exchange_rate) || parseFloat(latestExchangeRateInput.value) || 0
      const getBasePrice = (sym: string): number =>
        parseFloat(bd[sym]) || parseFloat(bd[sym.replace(/^\^/, '')]) || 0
      // 1) 基准日校准值 C 与恒定 H（全部用基准价，零实时价依赖）
      let sumWBp = 0
      let basisValid = true
      for (const p of portfolio) {
        const w = (parseFloat(p.weight) || 0) / 100.0
        const bp = getBasePrice(p.symbol || '')
        if (!(bp > 0) || !(w > 0)) { basisValid = false; break }
        sumWBp += w * bp
      }
      if (basisValid && fxBase > 0 && baseNav > 0 && pos > 0 && sumWBp > 0) {
        const C = (sumWBp * fxBase) / baseNav   // 基准日篮子校准值（RMB/LOF）
        const H = C / pos                        // 恒定对冲比 H
        // 2) 每个 ETF 数量 = round(LOF_qty · 权重 / H)
        for (const p of portfolio) {
          const w = (parseFloat(p.weight) || 0) / 100.0
          if (!(w > 0)) continue
          const qty = Math.round(finalLofQty * w / H)
          portfolioBreakdown.push({
            symbol: p.symbol || '',
            qty: String(qty),
            isShort: qty < 0,
          })
        }
      }
    }

    return {
      lofQty: finalLofQty,
      etfQty: finalEtfQty,
      exposure: navBasedExposure,
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

    // [AI-2026-07-12] 用四舍五入取整 GLD 股数（Woody 基准），避免浮点漂移
    const gldSharesPerContract = Math.round(calib * multiplier)
    const displayHedgeValue = etfHedge * gldSharesPerContract
    if (displayHedgeValue <= 0) return null

    const rawLofQty = targetLotsFuture.value * displayHedgeValue
    const finalLofQty = Math.round(rawLofQty / 100) * 100
    const pos = positionRatio.value
    // [AI-2026-08-06] 对冲敞口必须用净值 NAV（不是 LOF 市价）——与 etf_hedge 路径保持一致
    const baseNav = parseFloat(bd.nav) || simLofPrice.value
    const exposure = finalLofQty * baseNav * pos

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

    // [AI-2026-07-12] 与期货校准保持一致，用四舍五入取整 GLD 股数
    const gldSharesPerContract = Math.round(calib * multiplier)
    const displayHedgeValue = etfHedge * gldSharesPerContract
    if (displayHedgeValue <= 0) return null

    const finalLofQty = Math.round((targetLotsPureFuture.value * displayHedgeValue) / 100) * 100
    const pos = positionRatio.value
    // [AI-2026-08-06] 对冲敞口必须用净值 NAV（不是 LOF 市价）——与 etf_hedge 路径保持一致
    const baseNav = parseFloat(bd.nav) || simLofPrice.value
    const exposure = finalLofQty * baseNav * pos

    return { lofQty: finalLofQty, hedgeValue: displayHedgeValue, exposure }
  })

  // ============================================================
  // 6. 数据获取
  // ============================================================
  // [AI-2026-08-27] 元数据就绪回调：供父页面注册，在 fetchValuationMeta 成功后立即触发（用于依赖 meta.realtime_quotes 的后续计算）
  let _onMetaReady: (() => void) | null = null
  const setOnMetaReady = (fn: () => void) => { _onMetaReady = fn }

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

        // [AI-2026-07-13] 修复：LOF 价每次轮询都跟随最新卖一价更新，但用户手动编辑时不覆盖
        const lofInputEl = document.activeElement as HTMLElement
        const isLofInputFocused = lofInputEl && lofInputEl.tagName === 'INPUT' && lofInputEl.closest('[data-role="lof-price"]')
        if (!isLofInputFocused && depth.ask[0] > 0) {
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
        // [AI-2026-08-05] 元数据就绪后触发后端封装估值重算（首发）
        scheduleRecalc()
        // [AI-2026-08-27] 通知父页面元数据已就绪（父页面可在此触发依赖 realtime_quotes 的二次计算）
        _onMetaReady?.()
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
    // [AI-2026-08-05] 每次轮询后用最新实时价刷新后端封装估值
    await recalcBackend()
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
    ag0Val,
    ag0Premium,
    isQDIIJapan,
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
    setOnMetaReady,
    pollRealtime,
    recalcBackend,
    resetInitialized,

    // Polling
    startPolling,
    stopPolling,
  }
}
