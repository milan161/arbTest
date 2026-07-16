/**
 * 市场数据 Store
 * - 汇率、数据源状态、实时报价
 * - 各数据源独立重连
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '../api'

export interface MarketOverview {
  rates: {
    usd_cny_mid: number
    hkd_cny_mid: number
    [key: string]: any
  }
  usd_change: number
  hkd_change: number
  active_sources: string[]
  stats: {
    fund_count: number
    [key: string]: any
  }
}

export const useMarketStore = defineStore('market', () => {
  // ---- state ----
  const overview = ref<MarketOverview>({
    rates: { usd_cny_mid: 0, hkd_cny_mid: 0 },
    usd_change: 0,
    hkd_change: 0,
    active_sources: [],
    stats: { fund_count: 0 }
  })
  const loading = ref(false)

  // ---- getters ----
  const hasTdx = computed(() =>
    (overview.value?.active_sources || []).includes('tdx')
  )
  const hasIb = computed(() => {
    const sources = overview.value?.active_sources || []
    return sources.some((s) => s.includes('IB') && !s.includes('未运行'))
  })
  const hasIbNotRunning = computed(() => {
    const sources = overview.value?.active_sources || []
    return sources.some((s) => s.includes('IB (未运行)'))
  })
  const hasGalaxy = computed(() =>
    (overview.value?.active_sources || []).includes('galaxy')
  )
  const hasGuojin = computed(() =>
    (overview.value?.active_sources || []).includes('guojin')
  )
  const hasFutu = computed(() => {
    const sources = overview.value?.active_sources || []
    // [AI-2026-07-15] 与 IB 一致：排除 "未运行" 和 "无数据"
    return sources.some((s) => s.includes('富途') && !s.includes('未运行') && !s.includes('无数据'))
  })
  const hasFutuNoData = computed(() => {
    const sources = overview.value?.active_sources || []
    return sources.some((s) => s.includes('富途') && !s.includes('未运行') && s.includes('无数据'))
  })

  // ---- actions ----
  async function fetchOverview() {
    try {
      const res = await api.getMarketOverview()
      if (res.data?.status === 'ok') {
        overview.value = { ...overview.value, ...res.data.data }
      }
    } catch (err) {
      console.error('获取市场概览失败', err)
    }
  }

  async function reconnectTdx() {
    try {
      const res = await api.reconnectTdx()
      return res.data
    } catch (err: any) {
      return { status: 'error', message: err.message }
    }
  }

  async function reconnectGalaxy() {
    try {
      const res = await api.reconnectGalaxy()
      return res.data
    } catch (err: any) {
      return { status: 'error', message: err.message }
    }
  }

  async function reconnectGuojin() {
    try {
      const res = await api.reconnectGuojin()
      return res.data
    } catch (err: any) {
      return { status: 'error', message: err.message }
    }
  }

  async function reconnectFutu() {
    try {
      const res = await api.reconnectFutu()
      return res.data
    } catch (err: any) {
      return { status: 'error', message: err.message }
    }
  }

  return {
    overview, loading,
    hasTdx, hasIb, hasIbNotRunning, hasGalaxy, hasGuojin, hasFutu, hasFutuNoData,
    fetchOverview,
    reconnectTdx, reconnectGalaxy, reconnectGuojin, reconnectFutu
  }
})
