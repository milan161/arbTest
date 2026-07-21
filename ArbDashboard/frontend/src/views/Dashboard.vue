<template>
  <div class="dashboard">
    <n-grid :cols="24" :x-gap="10" :y-gap="10">
      <!-- 时钟+汇率（引擎状态已移到侧边栏） -->
      <n-gi :span="8">
        <n-card size="small" :bordered="false" class="stat-card">
          <div style="display: flex; flex-direction: column; gap: 2px; padding: 2px 0;">
            <div style="display: flex; align-items: baseline; gap: 12px; white-space: nowrap;">
              <span style="font-weight: 600; font-size: 14px;">{{ currentDate }} <span class="time">{{ currentTime }}</span></span>
              <span style="color: #64748b; font-size: 12px;">USD/CNY</span>
              <span style="font-weight: bold; font-size: 13px;">{{ rates.usd_cny_mid || '-' }}</span>
              <span :class="['rate-change', rates.usd_change >= 0 ? 'up' : 'down']" style="font-size: 11px;">{{ formatChange(rates.usd_change) }}</span>
            </div>
            <div style="display: flex; align-items: baseline; gap: 12px; white-space: nowrap; font-size: 12px;">
              <span style="color: #64748b; width: 86px; display: inline-block;">HKD/CNY</span>
              <span style="font-weight: bold; margin-right: 2px;">{{ rates.hkd_cny_mid || '-' }}</span>
              <span :class="['rate-change', rates.hkd_change >= 0 ? 'up' : 'down']" style="font-size: 11px; margin-right: 8px;">{{ formatChange(rates.hkd_change) }}</span>
              <span style="color: #64748b;">JPY/CNY</span>
              <span style="font-weight: bold; margin-right: 2px;">{{ rates.jpy_cny_mid || '-' }}</span>
              <span :class="['rate-change', rates.jpy_change >= 0 ? 'up' : 'down']" style="font-size: 11px;">{{ formatChange(rates.jpy_change) }}</span>
            </div>
          </div>
        </n-card>
      </n-gi>

      <!-- 系统里程碑日志 -->
      <n-gi :span="16">
        <n-card size="small" :bordered="false" class="stat-card log-card" content-style="padding: 0; position: relative;">
          <n-button quaternary circle size="tiny" @click="fetchData" style="position: absolute; right: 4px; top: 4px; z-index: 10;">
            <template #icon><n-icon><Zap /></n-icon></template>
          </n-button>
          <!-- 过期数据指示器 -->
          <div v-if="dashboardMeta.stale || dashboardMeta.error" style="position: absolute; left: 8px; top: 4px; z-index: 10;">
            <n-tag type="warning" size="tiny" round>
              {{ dashboardMeta.error ? '数据异常' : '数据已延迟' }}
              <template v-if="dashboardMeta.compute_ms > 0"> ({{ dashboardMeta.compute_ms }}ms)</template>
            </n-tag>
          </div>
          <div class="milestone-scroll-box" style="padding-top: 4px; height: 100%;">
             <div class="milestone-grid">
                <div v-for="(m, i) in milestones" :key="i" class="milestone-cell">
                   <span class="m-time">{{ m.time }}</span>
                   <span class="m-msg" :class="(m.level || 'info').toLowerCase()">{{ m.message }}</span>
                </div>
             </div>
             <div v-if="milestones.length === 0" class="text-center text-gray-400 py-4" style="font-size: 10px;">
                等待系统汇报...
             </div>
          </div>
        </n-card>
      </n-gi>

      <!-- Main Table -->
      <n-gi :span="24">
        <n-card :bordered="false" class="main-card" content-style="padding: 0;">
          <div class="table-toolbar">
            <!-- [AI-2026-07-09] TAB 改为动态：从数据库分类生成，新增分类（如 QDII日本）自动出现 -->
            <n-tabs type="bar" v-model:value="currentTab" animated style="flex: 1;" class="custom-tabs">
              <n-tab-pane v-for="tab in dashboardTabs" :key="tab" :name="tab" :tab="tab === '自选' ? '我的自选' : tab" />
            </n-tabs>
            <n-input v-model:value="searchKeyword" placeholder="搜索代码/名称..." class="search-input" size="small" clearable />
          </div>

          <div class="table-scroll-wrapper">
            <n-data-table
              :columns="columns"
              :data="filteredTableData"
              :loading="loading"
              :pagination="pagination"
              style="min-width: 1500px;"
              size="small"
              bordered
              :row-props="rowProps"
            />
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 历史对账详情弹窗 -->
    <n-modal v-model:show="showHistoryModal" preset="card" :title="`[历史记录] ${selectedFund?.fund_code} - ${selectedFund?.fund_name}`" style="width: 95%; max-width: 1500px;">
      <div v-if="selectedFund && !isCashManagementFund" style="margin-bottom: 16px; display: flex; gap: 24px; font-size: 14px; background: #f8fafc; padding: 12px; border-radius: 8px;">
        <div>
          <strong>跟踪标的：</strong> 
          {{ getIdxDisplayName(selectedFund) }}
        </div>
        <div><strong>申购费率：</strong> {{ selectedFund.purchase_fee || '-' }}</div>
        <div><strong>赎回费率：</strong> {{ selectedFund.redemption_fee || '-' }}</div>
      </div>
      <div class="history-table-wrapper">
        <n-data-table
          :columns="historyColumns"
          :data="fundHistory"
          size="small"
          flex-height
          style="height: 600px;"
          bordered
          :scroll-x="historyColumns.length * 105"
        />
      </div>
    </n-modal>

    <!-- 白银比价弹窗 -->
    <n-modal v-model:show="showSilverRatioModal" preset="card" title="白银比价监控 (161226)" style="width: 90%; max-width: 1200px;">
      <SilverRatio />
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed, watch, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  NGrid, NGi, NCard, NIcon, NText, NInput,
  NButton, NDataTable, NTag, NTabs, NTabPane, NModal
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { Zap, Star, StarOff, History } from 'lucide-vue-next'

// --- 新架构导入 ---
import { useFundStore, useMarketStore, useAppStore } from '../store'
import { formatPrice, formatValuation, formatPercent, formatPremium,
         formatVolume, formatShares, formatSharesChange, formatTurnoverRate,
         formatIndexPrice, priceColor, shortDate, cleanFundName } from '../utils'
import { getFundHistory } from '../api'
import SilverRatio from './SilverRatio.vue'

const router = useRouter()

// ===== Stores =====
const fundStore = useFundStore()
const marketStore = useMarketStore()
const appStore = useAppStore()

// ===== 从 Store 解构响应式状态（保持与模板同名的变量，避免改模板） =====
const { tableData, loading, currentTab, searchKeyword, watchlist,
        filteredTableData, fundHistory, dashboardMeta, dashboardTabs } = storeToRefs(fundStore)
const { milestones } = storeToRefs(appStore)

// ===== 本地状态（无需进 Store） =====
const showHistoryModal = ref(false)
const showSilverRatioModal = ref(false)
const selectedFund = ref<any>(null)
const isCashManagementFund = computed(() => {
  return ['511880', '511360', '511520'].includes(selectedFund.value?.fund_code)
})
let refreshTimer: any = null

// ===== Watch 自选持久化 =====
watch(watchlist, (newVal) => {
  localStorage.setItem('watchlist', JSON.stringify(newVal))
}, { deep: true })

// ===== 方法 =====
const openHistory = async (fund: any) => {
  selectedFund.value = fund
  showHistoryModal.value = true
  await fundStore.fetchFundHistory(fund.fund_code)
}

/**
 * 获取指数显示名称（中文名 + 代码）
 * 例如："中证新能源汽车指数 (399417)"
 */
const getIdxDisplayName = (fund: any) => {
  const idxName = fund.idx_name || ''
  const idxCode = fund.idx_code || fund.related_index || ''
  
  // 如果有中文名，显示"中文名 (代码)"
  if (idxName && idxName !== idxCode) {
    return `${idxName} (${idxCode})`
  }
  // 否则只显示代码
  return idxCode || '-'
}

const pagination = { pageSize: 100 }

const toggleWatchlist = (code: string) => fundStore.toggleWatchlist(code)

const rowProps = (row: any) => {
  return {}
}

const fetchData = async (isSilent = false) => {
  if (!isSilent && filteredTableData.value.length === 0) loading.value = true
  try {
    // [AI-2026-07-07] fetchRates 加入 fetchData，确保汇率随定时刷新自动更新（原来只在 onMounted 取一次）
    await Promise.all([
      fundStore.fetchDashboard(isSilent),
      marketStore.fetchOverview(),
      appStore.fetchSystemStatus(),
      fetchRates()
    ])
  } catch (err) { console.error('获取数据失败', err) } finally { loading.value = false }
}

const setupRefreshTimer = () => {
  if (refreshTimer) clearInterval(refreshTimer)
  const interval = fundStore.refreshInterval
  refreshTimer = setInterval(() => fetchData(true), interval)
}

watch(currentTab, () => {
  // [V8.1] 保留旧数据不闪白，后台静默刷新；filteredTableData 自动切换分类
  fetchData(true)
  setupRefreshTimer()
})

// [交换位置] 时钟 + 汇率：从侧边栏移入 Dashboard
const currentDate = ref('')
const currentTime = ref('')
const rates = ref({
  usd_cny_mid: '',
  hkd_cny_mid: '',
  jpy_cny_mid: '',
  usd_change: 0,
  hkd_change: 0,
  jpy_change: 0
})
let clockTimer: any = null

const updateTime = () => {
  const now = new Date()
  currentDate.value = now.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  currentTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

const formatChange = (val: number) => {
  if (val === undefined || val === null) return '-'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

const fetchRates = async () => {
  try {
    const res = await fetch('/api/market/overview')
    const data = await res.json()
    if (data.status === 'ok') {
      rates.value.usd_cny_mid = data.data?.rates?.usd_cny_mid || '-'
      rates.value.hkd_cny_mid = data.data?.rates?.hkd_cny_mid || '-'
      rates.value.jpy_cny_mid = data.data?.rates?.jpy_cny_mid || '-'
      rates.value.usd_change = data.data?.usd_change || 0
      rates.value.hkd_change = data.data?.hkd_change || 0
      rates.value.jpy_change = data.data?.jpy_change || 0
    }
  } catch (e) {
    console.error('获取汇率失败', e)
  }
}

onMounted(() => {
  // [AI-2026-06-28] 取消重置 TAB，由 fundStore 从 localStorage 恢复上次浏览的 TAB
  // [AI-2026-07-09] 拉取数据库动态分类，生成主看板 TAB
  fundStore.fetchCategories()
  fetchData()
  setupRefreshTimer()
  // [交换位置] 时钟 + 汇率
  updateTime()
  fetchRates()
  clockTimer = setInterval(updateTime, 1000)
})
onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (clockTimer) clearInterval(clockTimer)
})

const allColumns: DataTableColumns<any> = [
  {
    title: '★', key: 'watchlist', width: 34, fixed: 'left', align: 'center',
    render(row: any) {
      const isSelected = watchlist.value.includes(row.fund_code)
      return h(NIcon, {
        size: 16, color: isSelected ? '#f1c40f' : '#ddd', style: 'cursor: pointer;',
        onClick: (e: MouseEvent) => { e.stopPropagation(); toggleWatchlist(row.fund_code) }
      }, { default: () => isSelected ? h(Star) : h(StarOff) })
    }
  },
  {
    title: '代码', key: 'fund_code', width: 65, fixed: 'left', align: 'center',
    sorter: (a: any, b: any) => a.fund_code.localeCompare(b.fund_code),
    render(row: any) { return h(NText, { code: true, class: 'code-cell' }, { default: () => row.fund_code || '-' }) }
  },
  {
    title: '名称', key: 'fund_name', width: 90, fixed: 'left', align: 'center', ellipsis: { tooltip: true },
    render(row: any) {
      return h('span', { class: 'fund-name-cell clickable-cell',
        onClick: () => { selectedFund.value = row; showHistoryModal.value = true; fundStore.fetchFundHistory(row.fund_code) }
      }, cleanFundName(row.fund_name))
    }
  },
  {
    title: '现价', key: 'price', width: 62, align: 'center',
    sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render(row: any) { return h('span', { class: 'num-cell' }, formatPrice(row.price)) }
  },
  {
    title: '涨跌幅', key: 'price_change', width: 66, align: 'center',
    sorter: (a: any, b: any) => (a.price_change || 0) - (b.price_change || 0),
    render(row: any) {
      const chg = row.price_change || 0
      if (chg === 0 && (!row.price || row.price === 0)) return '-'
      return h('span', { class: 'num-cell strong', style: { color: priceColor(chg) } }, formatPercent(chg, 2))
    }
  },
  {
    title: () => h('div', { class: 'col-title-wrapper' }, [
      h('div', { style: 'font-size: 12px; font-weight: bold;' }, '实时估值'),
      h('div', { style: 'font-size: 9px; color: #64748b; margin-top: 1px;' }, '点击进实盘')
    ]),
    key: 'rt_val_display', width: 80, align: 'center',
    className: 'col-rt-val',
    render(row: any) {
      const val = row.rt_val && row.rt_val > 0 ? row.rt_val.toFixed(4) : '-'
      return h('span', { 
        class: 'num-cell strong clickable-cell',
        onClick: () => router.push({ path: '/analysis', query: { code: row.fund_code, name: row.fund_name } })
      }, val)
    }
  },
  {
    title: '实时溢价', key: 'rt_premium', width: 80, align: 'center',
    render(row: any) {
      if (!row.rt_val || !row.price) return h('span', { class: 'num-cell muted' }, '-')
      const p = (row.price / row.rt_val - 1) * 100
      return h('span', { class: 'num-cell strong compact', style: { color: priceColor(p) } }, formatPremium(p))
    }
  },
  {
    title: 'T-2/1日净值', key: 'nav', width: 66, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatValuation(row.nav)) }
  },
  {
    title: '净值日期', key: 'nav_date', width: 60, align: 'center',
    render(row: any) { return h(NText, { depth: 3, class: 'date-cell' }, { default: () => shortDate(row.nav_date) }) }
  },
  {
    title: () => h('div', { class: 'col-title-wrapper' }, [
      h('div', { style: 'font-size: 12px; font-weight: bold;' }, '静态估值'),
      h('div', { style: 'font-size: 9px; color: #64748b; margin-top: 1px;' }, '点击看历史记录')
    ]),
    key: 'static_val_display', width: 82, align: 'center',
    className: 'col-static-val',
    render(row: any) {
      const val = formatValuation(row.static_val)
      return h('span', { 
        class: 'num-cell strong clickable-cell',
        onClick: () => { selectedFund.value = row; showHistoryModal.value = true; fundStore.fetchFundHistory(row.fund_code) }
      }, val)
    }
  },
  {
    title: '静态溢价', key: 'static_premium', width: 80, align: 'center',
    sorter: (a: any, b: any) => (a.static_premium || 0) - (b.static_premium || 0),
    render(row: any) {
      if (!row.static_premium) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(row.static_premium) } }, formatPremium(row.static_premium))
    }
  },
  {
    title: '成交额(万)', key: 'volume', width: 68, align: 'right',
    sorter: (a: any, b: any) => (a.volume || 0) - (b.volume || 0),
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatVolume(row.volume)) }
  },
  {
    title: '份额(万)', key: 'shares', width: 52, align: 'right',
    sorter: (a: any, b: any) => (a.shares || 0) - (b.shares || 0),
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatShares(row.shares)) }
  },
  {
    title: '新增(万)', key: 'shares_added', width: 48, align: 'right',
    sorter: (a: any, b: any) => (a.shares_added || 0) - (b.shares_added || 0),
    fixedHeader: true,
    render(row: any) {
      const added = row.shares_added || 0
      return h('span', { class: 'num-cell compact', style: { color: priceColor(added) } }, formatSharesChange(row.shares_added))
    }
  },
  {
      title: '换手率', key: 'turnover_rate', width: 48, align: 'center',
      render(row: any) { return h('span', { class: 'num-cell muted' }, formatTurnoverRate(row.turnover_rate)) }
  },
  {
    title: '指数价', key: 'index_close', width: 80, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatIndexPrice(row.index_close)) }
  },
  {
    title: '指数涨跌', key: 'index_pct', width: 66, align: 'center',
    render(row: any) {
      if (!row.index_pct) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(Number(row.index_pct)) } }, formatPercent(Number(row.index_pct), 2))
    }
  },
  {
    title: '指数名称', key: 'index_name', width: 80, align: 'center',
    render(row: any) {
      const name = row.idx_name || row.related_index || '-'
      return h('span', { class: 'num-cell muted', style: 'font-size: 11px;' }, name)
    }
  },

  {
    title: '申购', key: 'purchase_status', width: 56, align: 'center',
    render(row: any) {
      const status = row.purchase_status || '未知'
      const limit = row.purchase_limit  // 日累计限定金额（元）
      let shortText = status
      let type = 'warning'
      // [AI-2026-06-26] 修复"限大额"不显示具体金额：原逻辑status.includes('开放')优先判断但"限大额"不包含"开放"
      if (status.includes('限大额') || status.includes('限制')) {
        // 限购 → 显示具体金额（如限50万），不再显示模糊的"限大额"
        shortText = formatPurchaseLimit(limit)
        type = 'warning'
      } else if (status.includes('开放')) {
        shortText = '开放'
        type = 'success'
      } else if (status.includes('暂停')) {
        shortText = '暂停'
        type = 'default'
      }
      return h(NTag, { type, size: 'small', round: true, class: 'status-pill' }, { default: () => shortText })
    }
  },
  {
    title: '赎回',
    key: 'redemption_status',
    width: 46,
    align: 'center',
    render(row: any) {
      const status = row.redemption_status || '未知'
      let shortText = status
      let type = 'warning'
      if (status.includes('开放')) {
        if (status.includes('限大额')) {
          shortText = '限大额'
          type = 'warning'
        } else {
          shortText = '开放'
          type = 'success'
        }
      } else {
        shortText = '暂停'
        type = 'warning'
      }
      return h(NTag, { type, size: 'small', round: true, class: 'status-pill' }, { default: () => shortText })
    }
  },
  ]

// 通用数值渲染函数，historyColumns 和 columns 共享
const renderValWithChg = (val: number, chg: number, precision: number = 4) => {
    if (!val || val === 0) return h('span', { style: 'color: #999;' }, '-')
    const valStr = val.toFixed(precision)
    if (chg == null || chg === 0) {
        return h('span', { style: 'font-weight: 500;' }, valStr)
    }
    const color = chg > 0 ? '#dc2626' : '#16a34a'
    const arrow = chg > 0 ? '▲' : '▼'
    const chgStr = (chg > 0 ? '+' : '') + chg.toFixed(2) + '%'
    return h('span', {}, [
        h('span', { style: 'font-weight: 500;' }, valStr),
        h('span', { style: `color: ${color}; font-size: 11px; margin-left: 3px;` }, `${arrow}${chgStr}`)
    ])
}

// [AI-2026-06-26] 新增：格式化申购限额，解决"限大额"无具体数量问题
const formatPurchaseLimit = (limit: number | null | undefined): string => {
  if (limit == null || limit === 0) return '限大额'
  if (limit >= 1e8 && limit % 1e8 === 0) return `限${limit / 1e8}亿`
  if (limit >= 1e4 && limit % 1e4 === 0) return `限${limit / 1e4}万`
  if (limit >= 1000) return `限${Math.round(limit / 100) / 10}千`
  return `限${limit}`
}

const historyColumns = computed<DataTableColumns<any>>(() => {
    const isCash = isCashManagementFund.value
    const is511360 = computed(() => selectedFund.value?.fund_code === '511360')
    const is511520 = computed(() => selectedFund.value?.fund_code === '511520')

    // [现金管理] 计算每日增加（nav - 昨日nav）
    const dailyIncrements = computed(() => {
        const history = fundHistory.value
        if (history.length === 0) return {}
        const result: Record<string, number> = {}
        // history是按日期降序排列的，[0]是最新
        for (let i = 0; i < history.length - 1; i++) {
            const curr = history[i]
            const next = history[i + 1]
            if (curr.nav != null && next.nav != null) {
                result[curr.date] = curr.nav - next.nav
            }
        }
        return result
    })

    // [现金管理] 日期列：511880标记周五, 511360标记周一
    const getWeekendLabel = (dateStr: string, fundCode: string) => {
        try {
            const d = new Date(dateStr)
            if (fundCode === '511360' && d.getDay() === 1) return ' 周一'
            if (fundCode !== '511360' && d.getDay() === 5) return ' 周五'
        } catch {}
        return ''
    }

    // [AI-2026-07-04] 判断是否有 hedge 数据（单ETF基金使用魔法公式需要）
    const hasHedge = fundHistory.value.some(r => r.hedge != null && r.hedge > 0)

    const baseCols: DataTableColumns<any> = [
        { title: '日期', key: 'date', width: 85, align: 'center', render(row: any) {
            const d = shortDate(row.date)
            const label = isCash ? getWeekendLabel(row.date, selectedFund.value?.fund_code || '') : ''
            if (label) {
                return h('span', { style: 'color: #d97706; font-weight: 600;' }, d + label)
            }
            return d
        }},
        // 现金管理及国内LOF不显示汇率（国内LOF为纯A股，无汇率影响）
        ...(isCash || selectedFund.value?.category === '国内LOF' ? [] : [
            { title: '汇率', key: 'usd_cny_mid', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.usd_cny_mid, row.usd_cny_mid_chg) } },
        ]),
        { title: '净值', key: 'nav', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.nav, row.nav_chg) } },
        // [现金管理] 在净值后插入"每日增加"列
        ...(isCash ? [{
            title: '每日增加', key: 'daily_inc', width: 78, align: 'center',
            render(row: any) {
                const inc = dailyIncrements.value[row.date]
                if (inc == null || inc === 0) return '-'
                const color = inc >= 0 ? '#16a34a' : '#dc2626'
                return h('span', { class: 'num-cell compact', style: { color } }, (inc >= 0 ? '+' : '') + inc.toFixed(4))
            }
        }] : []),
        { title: '收盘价', key: 'price', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.price, row.price_chg, 3) } },
        // 现金管理：折价几根毛/溢价在静态估值左侧；否则放静态估值右侧
        ...isCash
            ? [
                { title: '折价几根毛', key: 'yield_per_wan', width: 90, align: 'center', render(row: any) { const v = ((row.nav || 0) - (row.price || 0)) * 100; if (v === 0) return '-'; return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(2)) } },
                { title: '溢价', key: 'rt_premium', width: 90, align: 'center', render(row: any) { const nav = row.nav || 0; if (nav === 0) return '-'; const v = ((row.price || 0) / nav - 1); return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, (v * 100).toFixed(3) + '%') } },
                // 511360 专属: 国债指数 + 涨幅
                ...(is511360.value ? [
                    { title: '指数', key: 'idx_close', width: 78, align: 'center', render(row: any) { return row.idx_close ? h('span', { class: 'num-cell' }, row.idx_close.toFixed(2)) : '-' } },
                    { title: '指数涨幅', key: 'idx_pct', width: 78, align: 'center', render(row: any) { if (row.idx_pct == null) return '-'; return h('span', { style: { color: priceColor(row.idx_pct), fontWeight: '500' } }, row.idx_pct.toFixed(3) + '%') } },
                ] : []),
                // 511520 专属: 国债期货 + 涨幅
                ...(is511520.value ? [
                    { title: '期货', key: 'futures_close', width: 78, align: 'center', render(row: any) { return row.futures_close ? h('span', { class: 'num-cell' }, row.futures_close.toFixed(3)) : '-' } },
                    { title: '期货涨幅', key: 'futures_pct', width: 78, align: 'center', render(row: any) { if (row.futures_pct == null) return '-'; return h('span', { style: { color: priceColor(row.futures_pct), fontWeight: '500' } }, row.futures_pct.toFixed(3) + '%') } },
                ] : []),
                { title: '静态估值', key: 'static_val', width: 105, align: 'center', render(row: any) { return renderValWithChg(row.static_val, row.static_val_chg) } },
                // [AI-2026-07-07] 修复：static_val为null时不显示-100%，直接返回'-'
                { title: '估值误差', key: 'val_error_pct', width: 85, align: 'center', render(row: any) { if (row.static_val == null || row.nav == null) return h('span', { class: 'num-cell muted' }, '-'); const v = row.static_val - row.nav; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { class: 'num-cell', style: { color: priceColor(v), fontWeight: 'bold' } }, v.toFixed(4)) } },
                { title: '误差率', key: 'val_error_rate', width: 78, align: 'center', render(row: any) { if (row.static_val == null || row.nav == null || row.nav === 0) return '-'; const v = (row.static_val - row.nav) / row.nav * 100; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { class: 'num-cell', style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(3) + '%') } },
              ]
            : [
                { title: '静态估值', key: 'static_val', width: 105, align: 'center', render(row: any) { return renderValWithChg(row.static_val, row.static_val_chg) } },
                // [AI-2026-07-07] 修复同上：static_val为null时显示'-'
                { title: '估值误差', key: 'val_error_pct', width: 85, align: 'center', render(row: any) { if (row.static_val == null || row.nav == null) return h('span', { class: 'num-cell muted' }, '-'); const v = row.static_val - row.nav; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { style: { color: priceColor(v), fontWeight: 'bold' } }, v.toFixed(4)) } },
                { title: '误差率', key: 'val_error_rate', width: 78, align: 'center', render(row: any) { if (row.static_val == null || row.nav == null || row.nav === 0) return '-'; const v = (row.static_val - row.nav) / row.nav * 100; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(3) + '%') } },
                { title: '静态溢价', key: 'static_premium', width: 85, align: 'center', render(row: any) { const v = row.static_premium || 0; if (v === 0) return '-'; return h('span', { style: { color: priceColor(v) } }, formatPremium(v)) } },
                // [AI-2026-07-04] 单ETF基金（魔法公式）显示对冲值
                ...(hasHedge ? [{ title: '对冲值', key: 'hedge', width: 95, align: 'center', render(row: any) { return row.hedge ? h('span', { class: 'num-cell' }, row.hedge.toFixed(2)) : '-' } }] : []),
              ],
        // QDII亚洲 / QDII日本 / 国内LOF / 指数型基金 专属：指数价 + 指数涨跌
        ...(['QDII亚洲', 'QDII日本', '国内LOF'].includes(selectedFund.value?.category || '') || selectedFund.value?.sub_category?.includes('指数') ? [
            { title: '指数价', key: 'index_close', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.index_close, row.index_close_chg) } },
            { title: '指数涨跌', key: 'index_pct', width: 85, align: 'center', render(row: any) { if (row.index_pct == null) return '-'; return h('span', { style: { color: priceColor(row.index_pct), fontWeight: '500' } }, row.index_pct.toFixed(2) + '%') } },
        ] : []),
        // 现金管理不显示份额/新增/换手率
        ...(isCash ? [] : [
            { title: '份额(万)', key: 'shares', width: 85, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatShares(row.shares)) } },
            { title: '新增(万)', key: 'shares_added', width: 80, align: 'center', render(row: any) { return h('span', { style: { color: priceColor(Number(row.shares_added || 0)), fontSize: '11px' } }, formatSharesChange(row.shares_added)) } },
            { title: '换手率', key: 'turnover_rate', width: 80, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatTurnoverRate(row.turnover_rate)) } },
        ]),
    ]

    if (fundHistory.value.length > 0) {
        const knownKeys = ['date', 'price', 'nav', 'static_val', 'static_premium', 'calibration', 'usd_cny_mid', 'turnover_amt', 'price_change', 'price_chg', 'nav_chg', 'static_val_chg', 'usd_cny_mid_chg', 'index_close', 'index_pct', 'idx_close', 'idx_pct', 'val_error_pct', 'shares', 'shares_added', 'turnover_rate', 'volume', 'valuation_error', 'hkd_cny_mid', 'jpy_cny_mid', 'latest_nav', 'futures_close', 'futures_pct', 'hedge']
        // Scan ALL rows to find dynamic keys (first row may lack data, e.g. 06-19 has no XOP_price)
        const dynamicKeys = new Set<string>()
        for (const row of fundHistory.value) {
            for (const key of Object.keys(row)) {
                if (!knownKeys.includes(key) && !key.endsWith('_chg') && typeof row[key] === 'number') {
                    dynamicKeys.add(key)
                }
            }
        }
        
        // [AI] 如果是指数类基金，不显示底层的 SPY/QQQ 动态列，只看指数
        const isIndexFund = selectedFund.value?.sub_category?.includes('指数');
        
        dynamicKeys.forEach(key => {
            if (isIndexFund && key.endsWith('_price')) {
                return; // 跳过指数基金的动态 ETF 列
            }
            
            let title = key
            const priceMatch = key.match(/^(.+)_price$/)
            if (priceMatch) {
                // [AI-2026-07-21] 单主ETF基金（如162411→XOP）显示净值；多篮子基金（如161116→GLD+^GLD-EU）显示价格
                const firstRow = fundHistory.value.length > 0 ? fundHistory.value[0] : null
                const isSingleEtf = firstRow !== null && 'is_single_etf' in firstRow ? firstRow.is_single_etf : true  // 旧后端无此字段时兼容
                title = priceMatch[1] + (isSingleEtf ? '净值' : '价格')
            }
            baseCols.push({
                title: title, key: key, width: 95, align: 'center',
                render(row: any) { return renderValWithChg(row[key], row[`${key}_chg`], 2) }
            })
        })
    }
    return baseCols
})

const columns = computed<DataTableColumns<any>>(() => {
  // 深拷贝以便动态修改表头
  let cols = allColumns.map(c => ({...c}))

  // 1. 动态重命名净值日期列
  const t1Tabs = ['QDII亚洲', '国内LOF', '白银']
  const t2Tabs = ['QDII欧美', 'QDII日本', '黄金原油']  // [AI-2026-07-09] 混合跨境已并入QDII欧美；QDII日本同属T-2
  const navCol = cols.find(c => c.key === 'nav')
  if (navCol) {
    if (t1Tabs.includes(currentTab.value)) navCol.title = 'T-1日净值'
    else if (t2Tabs.includes(currentTab.value)) navCol.title = 'T-2日净值'
    else navCol.title = 'T-2/1日净值'
  }

  // [V7.0] 白银 TAB 专属列与重命名
  if (currentTab.value === '白银') {
    cols.forEach(col => {
      if (col.key === 'rt_val_display') col.title = '参考估值'
      if (col.key === 'rt_premium') col.title = '参考溢价'
      if (col.key === 'static_val_display') col.title = '官方估值'
      if (col.key === 'static_premium') col.title = '官方溢价'
    })
    
    const staticPremIndex = cols.findIndex(c => c.key === 'static_premium')
    cols.splice(staticPremIndex + 1, 0, 
      { title: () => h('div', { style: 'line-height: 1.3; text-align: center;' }, [h('div', {}, '实时成交价'), h('div', { style: 'font-size: 10px; color: #64748b;' }, '(AG0)')]), key: 'ag0_price', width: 100, align: 'center', render(row: any) { return h('span', { class: 'num-cell' }, row.ag0_price ? row.ag0_price.toFixed(0) : '-') } },
      { title: () => h('div', { style: 'line-height: 1.3; text-align: center;' }, [h('div', {}, '昨结算价'), h('div', { style: 'font-size: 10px; color: #64748b;' }, '(AG0)')]), key: 'ag0_settlement', width: 100, align: 'center', render(row: any) { return h('span', { class: 'num-cell muted' }, row.ag0_settlement ? row.ag0_settlement.toFixed(0) : '-') } },
      { title: () => h('div', { style: 'line-height: 1.3; text-align: center;' }, [h('div', {}, '实时估值'), h('div', { style: 'font-size: 10px; color: #64748b;' }, '(SI)')]), key: 'si_val', width: 100, align: 'center', className: 'col-si-val', render(row: any) { return h('span', { class: 'num-cell clickable-cell', style: { cursor: 'pointer', color: '#2563eb' }, onClick: () => { showSilverRatioModal.value = true } }, row.si_val != null ? row.si_val.toFixed(4) : '-') } },
      { title: () => h('div', { style: 'line-height: 1.3; text-align: center;' }, [h('div', {}, '实时溢价'), h('div', { style: 'font-size: 10px; color: #64748b;' }, '(SI)')]), key: 'si_premium', width: 95, align: 'center', render(row: any) { const v = row.si_premium; if (v == null) return '-'; return h('span', { class: 'num-cell', style: { color: priceColor(v) } }, formatPremium(v)) } }
    )
  }

  const hideIndexTabs = ['黄金原油', 'QDII欧美', '白银']
  if (hideIndexTabs.includes(currentTab.value)) {
    return cols.filter(c => c.key !== 'related_index' && c.key !== 'index_close' && c.key !== 'index_pct' && c.key !== 'index_name')
  }

  // 现金管理TAB：隐藏份额/新增/换手率/指数价/指数涨跌幅/申购/赎回/测试价/溢价率
  // 并重命名列 + 添加债券ETF专属列
  if (currentTab.value === '现金管理') {
    // 过滤掉不需要的列
    cols = cols.filter(c => !['shares', 'shares_added', 'turnover_rate', 'index_close', 'index_pct', 'index_name', 'purchase_status', 'redemption_status', 'static_premium', 'rt_premium'].includes(c.key))
    
    // 重命名列
    cols.forEach(col => {
      if (col.key === 'nav') col.title = '最新净值'
      if (col.key === 'rt_val_display') col.title = '估值'
    })
    
    // [AI-2026-07-03] static_val_display（静态估值）移到净值日期右侧
    const svIdx = cols.findIndex(c => c.key === 'static_val_display')
    let staticValCol = null
    if (svIdx >= 0) {
      staticValCol = cols.splice(svIdx, 1)[0]
      staticValCol.title = '静态估值'
      staticValCol.width = 60
    }
    
    // 估值列之后插入折价几根毛和溢价（基于估值计算，不用净值）
    const rtValIndex = cols.findIndex(c => c.key === 'rt_val_display')
    if (rtValIndex >= 0) {
      cols.splice(rtValIndex + 1, 0,
        { title: '折价几根毛', key: 'yield_per_wan', width: 80, align: 'center',
          render(row: any) { const v = ((row.rt_val || 0) - (row.price || 0)) * 100; if (v === 0) return '-'; return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(2)) }
        },
        { title: '溢价', key: 'rt_premium_calc', width: 80, align: 'center',
          render(row: any) { const val = row.rt_val || 0; if (val === 0) return '-'; const v = ((row.price || 0) / val - 1); return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, (v * 100).toFixed(3) + '%') }
        }
      )
    }
    
    // 静态估值 + 日均增长 + 国债指数 + 国债期货 放在净值日期之后
    const navDateIndex = cols.findIndex(c => c.key === 'nav_date')
    if (navDateIndex >= 0) {
      const insertAfter: any[] = []
      if (staticValCol) insertAfter.push(staticValCol)
      insertAfter.push(
        { title: '日均增长', key: 'avg_daily_growth', width: 72, align: 'center',
          render(row: any) {
            const g = row.avg_daily_growth
            if (g == null || g === 0) return '-'
            return h('span', { class: 'num-cell compact', style: { color: priceColor(g) } }, (g * 10000).toFixed(1) + '万')
          }
        },
        { title: '国债指数', key: 'treasury_index_price', width: 80, align: 'center',
          render(row: any) {
            const p = row.treasury_index_price
            if (p == null) return '-'
            return h('span', { class: 'num-cell compact', style: { color: '#1f2937' } }, p.toFixed(2))
          }
        },
        { title: '国债期货', key: 'futures_pct', width: 80, align: 'center',
          render(row: any) {
            const fp = row.futures_pct
            if (fp == null) return '-'
            return h('span', { class: 'num-cell compact', style: { color: priceColor(fp) } }, (fp > 0 ? '+' : '') + fp.toFixed(3) + '%')
          }
        }
      )
      cols.splice(navDateIndex + 1, 0, ...insertAfter)
    }
    return cols
  }

  return cols
})

const tableScrollX = computed(() => {
  const minRequired = columns.value.reduce((total, col: any) => total + Number(col.width || 80), 0)
  // 深度压缩后列宽总和约900px，设置底线确保水平滚动在窄屏下可用
  return Math.max(1500, minRequired)
})
</script>

<style scoped>
.dashboard { 
  color: #1f2937;
  width: 100%;
  max-width: 100vw;
  min-width: 0;
  box-sizing: border-box;
}
:deep(.n-data-table),
:deep(.n-data-table-wrapper),
:deep(.n-data-table-base-table),
:deep(.n-data-table-base-table-body),
:deep(.n-data-table-table),
:deep(.n-data-table-tbody),
:deep(.n-scrollbar-container),
:deep(.n-scrollbar-content) {
  background: #ffffff !important;
  border-spacing: 0 !important;
}
:deep(.n-data-table-tr) {
  background-color: #ffffff !important;
}
:deep(.n-data-table-td) {
  padding: 2px 2px !important;
  color: #1f2937 !important;
  background-color: #ffffff !important;
  border-color: #f0f4f8 !important;
  border-width: 1px 0 !important;
}
:deep(.n-data-table-th) {
  padding: 3px 2px !important;
  background-color: #eef5ff !important;
  border-width: 1px 0 !important;
}
:deep(.n-data-table-tr:nth-child(even) .n-data-table-td) { background-color: #fbfdff !important; }
:deep(.n-data-table-tr:hover .n-data-table-td) { background-color: #f6faff !important; }
:deep(.n-data-table-cell) {
  padding: 0 !important;
}

.table-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid #e5edf7;
  background: #ffffff;
}
.search-input { width: 170px; margin-left: 12px; flex-shrink: 0; }
.stat-card {
  background: #ffffff;
  border: 1px solid #e5edf7;
  border-radius: 8px;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  height: 84px;
}
.log-card { overflow: hidden; border: 1px solid #e5edf7; }
.log-header { display: flex; align-items: center; justify-content: space-between; padding: 6px 10px; border-bottom: 1px solid #eef3f9; }
.milestone-scroll-box { height: 56px; overflow-y: scroll !important; padding: 4px 10px; }
.milestone-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 4px 12px; }
.milestone-cell { display: flex; align-items: flex-start; gap: 6px; font-size: 10px; line-height: 1.4; }
.milestone-item { font-size: 11px; margin-bottom: 4px; display: flex; align-items: flex-start; gap: 8px; line-height: 1.4; }
.m-time { color: #8a98aa; flex-shrink: 0; font-family: "Fira Code", Consolas, monospace; }
.m-msg { color: #425466; word-break: break-all; text-align: left; }
.m-msg.error { color: #dc2626; font-weight: bold; }
.m-msg.warning { color: #d97706; }
.m-msg.success { color: #16a34a; font-weight: bold; }
.stat-card:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08); }
.main-card {
  border-radius: 8px;
  background-color: #fff;
  border: 1px solid #e5edf7;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  overflow: hidden;
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
}
.code-cell {
  font-family: "Fira Code", Consolas, monospace;
  font-size: 12px;
  font-weight: 700;
  color: #1f2937;
}
.fund-name-cell {
  color: #1f2937;
  font-size: 12px;
  font-weight: 700;
}
.num-cell {
  font-family: "Inter", "Fira Code", Consolas, sans-serif;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  color: #1f2937;
}
.num-cell.strong { font-weight: 750; }
.num-cell.muted { color: #64748b; }
.num-cell.compact { font-size: 12px; }
.date-cell, .index-cell { font-size: 11px; color: #64748b; }
.clickable-cell { cursor: pointer; text-decoration: underline; color: #2563eb !important; }
.clickable-cell:hover { color: #1d4ed8 !important; }
.col-title-wrapper { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 2px 0; width: 100%; }
.bg-blue-light { background-color: #dbeafe; }
.bg-orange-light { background-color: #ffedd5; }
.status-pill { font-size: 10px; padding-inline: 5px !important; }
:deep(.n-tabs .n-tabs-tab) {
  padding: 6px 10px;
  color: #526173;
  font-weight: 650;
}
:deep(.n-tabs .n-tabs-tab--active) { color: #2563eb !important; background-color: #eef6ff !important; border-radius: 6px 6px 0 0; }
:deep(.n-tabs .n-tabs-bar) { background-color: #2563eb !important; }
:deep(.n-data-table-th) {
  background-color: #eef5ff !important;
  color: #21395c !important;
  font-size: 12px;
  font-weight: 800 !important;
  border-bottom: 1px solid #dfe8f4 !important;
  text-align: center !important;
}
:deep(.n-data-table-th__title-container) { display: inline-flex !important; align-items: center !important; justify-content: center !important; width: 100% !important; }
:deep(.n-data-table-sorter) { margin-left: 2px !important; display: inline-flex !important; }
:deep(.n-data-table .n-data-table-td--fixed-left),
:deep(.n-data-table .n-data-table-th--fixed-left),
:deep(.n-data-table .n-data-table-td--fixed-right),
:deep(.n-data-table .n-data-table-th--fixed-right) {
  background-color: #ffffff !important;
  box-shadow: none !important;
}
:deep(.n-data-table .n-data-table-th--fixed-left) {
  background-color: #eef5ff !important;
}
:deep(.n-data-table .n-data-table-th--fixed-right) {
  background-color: #fff1f2 !important; /* 粉红色背景 */
  color: #e11d48 !important; /* 玫瑰红文字 */
}
/* 滚动条加粗：方便鼠标点击（水平+垂直） */
:deep(.n-scrollbar-rail) {
  width: 14px !important;
  height: 14px !important;
  right: 1px;
  bottom: 1px;
  opacity: 0.8;
}
:deep(.n-scrollbar-rail--vertical) {
  width: 14px !important;
}
:deep(.n-scrollbar-rail--horizontal) {
  height: 14px !important;
}
:deep(.n-scrollbar-thumb) {
  width: 10px !important;
  height: 10px !important;
  border-radius: 5px !important;
  background-color: #cbd5e1 !important;
  cursor: pointer !important;
}
:deep(.n-scrollbar-thumb:hover) {
  width: 10px !important;
  height: 10px !important;
  background-color: #94a3b8 !important;
}
:deep(.n-scrollbar-rail:hover .n-scrollbar-thumb) {
  background-color: #94a3b8 !important;
}

/* 表格外层容器：固定高度，同时处理水平和垂直滚动 */
.table-scroll-wrapper {
  width: 100%;
  height: calc(100vh - 220px);
  overflow: auto;
}

/* 整列底色 - 覆盖奇偶行交替背景 */
:deep(.n-data-table-tr:nth-child(even) .n-data-table-td.col-rt-val),
:deep(.n-data-table-tr:nth-child(odd) .n-data-table-td.col-rt-val) {
  background-color: #f0f9ff !important;
}
:deep(.n-data-table-tr:nth-child(even) .n-data-table-td.col-static-val),
:deep(.n-data-table-tr:nth-child(odd) .n-data-table-td.col-static-val) {
  background-color: #fff7ed !important;
}
:deep(.n-data-table-tr:nth-child(even) .n-data-table-td.col-si-val),
:deep(.n-data-table-tr:nth-child(odd) .n-data-table-td.col-si-val) {
  background-color: #f0fdf4 !important;
}
:deep(.n-data-table-th.col-rt-val) {
  background-color: #e0f2fe !important;
}
:deep(.n-data-table-th.col-static-val) {
  background-color: #ffedd5 !important;
}
:deep(.n-data-table-th.col-si-val) {
  background-color: #dcfce7 !important;
}

/* [交换位置] 时钟 + 汇率样式 */
.date { font-size: 11px; color: #7b8a9b; }
.time { font-size: 14px; font-weight: bold; color: #2563eb; font-family: monospace; }
.exchange-rates { margin-top: 15px; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; }
.rate-group { display: flex; flex-direction: column; }
.rate-label { font-size: 11px; color: #64748b; margin-bottom: 4px; white-space: nowrap; font-weight: 500; }
.rate-row { display: flex; align-items: baseline; justify-content: space-between; gap: 4px; }
.rate-value { font-size: 16px; font-weight: 800; color: #1e293b; font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.rate-change { font-size: 12px; font-weight: 700; }
.rate-change.up { color: #ef4444; }
.rate-change.down { color: #22c55e; }
</style>
