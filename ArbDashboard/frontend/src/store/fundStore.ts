/**
 * 基金数据 Store
 * - 看板列表、分类/TAB 筛选、自选管理
 * - 历史数据、分时数据、篮子权重
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '../api'

export interface FundItem {
  fund_code: string
  fund_name: string
  category: string
  price: number
  nav: number
  static_val: number
  static_premium: number
  rt_val: number | null
  rt_premium: number | null
  volume: number
  shares: number
  shares_added: number
  turnover_rate: number
  price_change: number
  prev_close: number
  nav_date: string
  index_close: number
  index_pct: number
  purchase_status: string
  redemption_status: string
  purchase_fee: string
  redemption_fee: string
  idx_code: string
  idx_name: string
  related_index: string
  pos_ratio: number
  [key: string]: any
}

/** TAB 分类映射（与后端 fund_service.py 保持一致） */
export const TAB_CATEGORIES: Record<string, string[]> = {
  '黄金原油': ['黄金原油', '黄金', '原油'],
  'QDII欧美': ['纯ETF', 'QDII 欧美', '混合跨境', 'QDII欧美'],
  'QDII亚洲': ['QDII 亚洲', 'QDII亚洲'],
  '国内LOF': ['指数LOF', '其他', '国内LOF', 'lof_domestic'],
  '白银': ['白银', '白银LOF'],
  '现金管理': ['债券/货币']
}

export const HIGH_FREQ_TABS = ['自选', '黄金原油', 'QDII欧美']

export const useFundStore = defineStore('fund', () => {
  // ---- state ----
  const tableData = ref<FundItem[]>([])
  const loading = ref(false)
  // 从 localStorage 恢复上次 TAB，默认"自选"
  const savedTab = typeof localStorage !== 'undefined' ? localStorage.getItem('dashboard_tab') : null
  const currentTab = ref(savedTab || '自选')
  const searchKeyword = ref('')
  const fundHistory = ref<any[]>([])
  const fundHistoryLoading = ref(false)
  const intradayData = ref<any[]>([])
  const basketData = ref<any[]>([])

  // ---- watchlist（持久化到 localStorage） ----
  const savedWatchlist = (() => {
    try {
      const w = JSON.parse(localStorage.getItem('watchlist') || '[]')
      return Array.isArray(w) ? w : []
    } catch {
      return []
    }
  })()
  const watchlist = ref<string[]>(savedWatchlist)

  // ---- getters ----
  /** 按当前 TAB + 搜索关键词过滤后的数据 */
  const filteredTableData = computed(() => {
    let data = tableData.value || []

    if (currentTab.value === '自选') {
      data = data.filter((item) => watchlist.value.includes(item.fund_code))
    } else {
      const categories = TAB_CATEGORIES[currentTab.value]
      if (categories) {
        data = data.filter((item) => categories.includes(item.category))
      }
    }

    if (searchKeyword.value) {
      const kw = searchKeyword.value.toLowerCase()
      data = data.filter(
        (item) =>
          (item.fund_code || '').toLowerCase().includes(kw) ||
          (item.fund_name || '').toLowerCase().includes(kw)
      )
    }

    return data
  })

  /** 刷新间隔（毫秒） */
  const refreshInterval = computed(() =>
    HIGH_FREQ_TABS.includes(currentTab.value) ? 3000 : 30000
  )

  // ---- actions ----
  function toggleWatchlist(code: string) {
    const idx = watchlist.value.indexOf(code)
    if (idx > -1) watchlist.value.splice(idx, 1)
    else watchlist.value.push(code)
    localStorage.setItem('watchlist', JSON.stringify(watchlist.value))
  }

  function isInWatchlist(code: string) {
    return watchlist.value.includes(code)
  }

  async function fetchDashboard(isSilent = false) {
    if (!isSilent && tableData.value.length === 0) loading.value = true
    try {
      const params: Record<string, string> = {}
      if (currentTab.value === '自选') {
        params.watchlist = watchlist.value.join(',')
      } else {
        params.category = currentTab.value
      }
      const res = await api.getDashboard(params)
      if (res.data?.status === 'ok') {
        tableData.value = res.data.data || []
      }
    } catch (err) {
      console.error('获取看板数据失败', err)
    } finally {
      loading.value = false
    }
  }

  async function fetchFundHistory(code: string) {
    fundHistoryLoading.value = true
    try {
      const res = await api.getFundHistory(code)
      if (res.data?.status === 'ok') {
        fundHistory.value = res.data.data || []
      }
    } catch (err) {
      console.error('获取历史数据失败', err)
      fundHistory.value = []
    } finally {
      fundHistoryLoading.value = false
    }
  }

  async function fetchIntraday(code: string, date?: string) {
    try {
      const res = await api.getFundIntraday(code, date)
      if (res.data?.status === 'ok') {
        intradayData.value = res.data.data || []
      }
    } catch (err) {
      console.error('获取分时数据失败', err)
      intradayData.value = []
    }
  }

  async function fetchBasket(code: string) {
    try {
      const res = await api.getFundBasket(code)
      if (res.data?.status === 'ok') {
        basketData.value = res.data.data || []
      }
    } catch (err) {
      console.error('获取篮子权重失败', err)
      basketData.value = []
    }
  }

  function setTab(tab: string) {
    currentTab.value = tab
    localStorage.setItem('dashboard_tab', tab)
    // [V8.1] 不再清空 tableData — 保留旧数据让 filteredTableData 直接过滤，
    // 用户看到的是已缓存的分类数据而非空白转圈。
    // 后台静默刷新会在 watch(currentTab) 中触发 fetchData(true)
  }

  return {
    tableData, loading, currentTab, searchKeyword,
    fundHistory, fundHistoryLoading,
    intradayData, basketData,
    watchlist,
    filteredTableData, refreshInterval,
    toggleWatchlist, isInWatchlist,
    fetchDashboard, fetchFundHistory, fetchIntraday, fetchBasket,
    setTab
  }
})
