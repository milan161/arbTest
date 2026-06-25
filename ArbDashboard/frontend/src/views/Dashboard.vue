<template>
  <div class="dashboard">
    <n-grid :cols="24" :x-gap="10" :y-gap="10">
      <!-- 引擎状态 -->
      <n-gi :span="8">
        <n-card size="small" :bordered="false" class="stat-card">
          <div style="text-align: center; width: 100%; display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 4px; height: 100%;">
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; width: 100%;">
                <n-tag :type="engineRunning ? 'info' : 'warning'" size="small" round style="font-weight: bold; cursor: pointer; justify-content: center;" @click="router.push('/auto-trade')">
                  <template #icon><n-icon><Bot /></n-icon></template>
                  {{ engineRunning ? '自动交易: 开启' : '自动交易: 暂停' }}
                </n-tag>
                <n-tag :type="hasTdx ? 'success' : 'warning'" size="small" round
                    :style="{ fontWeight: 'bold', justifyContent: 'center', cursor: hasTdx ? 'default' : 'pointer' }"
                    @click="reconnectWithGuard(hasTdx, '通达信', reconnectTdx)">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    通达信
                </n-tag>
                <div style="display: flex; gap: 4px; justify-content: center;">
                    <n-tag :type="hasIb ? 'success' : 'warning'" size="small" round
                        :style="{ fontWeight: 'bold', flex: 1, justifyContent: 'center', cursor: hasIb ? 'default' : 'pointer' }"
                        @click="reconnectWithGuard(hasIb, 'IB', reconnectIB)">
                        <template #icon><n-icon><Zap /></n-icon></template>
                        IB
                    </n-tag>
                </div>
                
                <n-tag :type="hasGalaxy ? 'success' : 'warning'" size="small" round
                    :style="{ fontWeight: 'bold', justifyContent: 'center', cursor: hasGalaxy ? 'default' : 'pointer' }"
                    @click="reconnectWithGuard(hasGalaxy, '银河QMT', reconnectGalaxy)">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    银河QMT
                </n-tag>
                <n-tag :type="hasGuojin ? 'success' : 'warning'" size="small" round
                    :style="{ fontWeight: 'bold', justifyContent: 'center', cursor: hasGuojin ? 'default' : 'pointer' }"
                    @click="reconnectWithGuard(hasGuojin, '国金QMT', reconnectGuojin)">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    国金QMT
                </n-tag>
                <n-tag :type="hasFutu ? 'success' : 'warning'" size="small" round
                    :style="{ fontWeight: 'bold', justifyContent: 'center', cursor: hasFutu ? 'default' : 'pointer' }"
                    @click="reconnectWithGuard(hasFutu, '富途', reconnectFutu)">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    富途
                </n-tag>
            </div>
            <n-text style="font-size: 11px; font-weight: bold; font-family: 'SimHei', 'Microsoft YaHei', sans-serif; white-space: nowrap; margin-top: 2px; color: #555; letter-spacing: 0.5px;">点击切换启动/停止</n-text>
          </div>
        </n-card>
      </n-gi>

      <!-- 系统里程碑日志 - 占据2/3宽度 -->
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
            <n-tabs type="bar" v-model:value="currentTab" animated style="flex: 1;" class="custom-tabs">
              <n-tab-pane name="自选" tab="我的自选" />
              <n-tab-pane name="黄金原油" tab="黄金原油" />
              <n-tab-pane name="QDII欧美" tab="QDII欧美" />
              <n-tab-pane name="QDII亚洲" tab="QDII亚洲" />
              <n-tab-pane name="国内LOF" tab="国内LOF" />
              <n-tab-pane name="白银" tab="白银" />
              <n-tab-pane name="现金管理" tab="现金管理" />
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
        <div><strong>跟踪标的：</strong> {{ selectedFund.idx_name || selectedFund.related_index || '-' }} ({{ selectedFund.idx_code || selectedFund.related_index || '-' }})</div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed, watch, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import {
  NGrid, NGi, NCard, NIcon, NText, NInput,
  NButton, NDataTable, NTag, useMessage, NTabs, NTabPane, NModal
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { Zap, Bot, Star, StarOff, History } from 'lucide-vue-next'

// --- 新架构导入 ---
import { useFundStore, useMarketStore, useAppStore } from '../store'
import { formatPrice, formatValuation, formatPercent, formatPremium,
         formatVolume, formatShares, formatSharesChange, formatTurnoverRate,
         formatIndexPrice, priceColor, shortDate, cleanFundName } from '../utils'
import { getFundHistory } from '../api'

const router = useRouter()
const message = useMessage()

// ===== Stores =====
const fundStore = useFundStore()
const marketStore = useMarketStore()
const appStore = useAppStore()

// ===== 从 Store 解构响应式状态（保持与模板同名的变量，避免改模板） =====
const { tableData, loading, currentTab, searchKeyword, watchlist,
        filteredTableData, fundHistory, dashboardMeta } = storeToRefs(fundStore)
const { engineRunning, milestones } = storeToRefs(appStore)
const { overview: marketOverview, hasTdx, hasIb, hasIbNotRunning,
        hasGalaxy, hasGuojin, hasFutu } = storeToRefs(marketStore)

// ===== 本地状态（无需进 Store） =====
const showHistoryModal = ref(false)
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
const reconnectIB = async () => {
  appStore.reconnectingIB = true
  try {
    const data = await appStore.reconnectIB()
    if (data.status === 'ok') {
      message.success('IB 重连成功！')
      fetchData()
    } else {
      message.error('IB 重连失败，请确保 TWS 已运行。')
    }
  } catch (e: any) {
    message.error('重连请求失败: ' + e.message)
  } finally {
    appStore.reconnectingIB = false
  }
}

const reconnectEngine = async (sourceLabel: string, reconnectFn: () => Promise<any>) => {
  try {
    const data = await reconnectFn()
    if (data.status === 'ok') {
      message.success(`${sourceLabel} 重连成功！`)
      setTimeout(fetchData, 500)
    } else {
      message.warning(`${sourceLabel} 重连未就绪: ${data.message}`)
    }
  } catch (e: any) {
    message.error(`${sourceLabel} 重连异常: ${e.message}`)
  }
}

/**
 * 带"已连接→跳过"守卫的 reconnect 包装。
 * 已连接的源：不执行重连、不弹消息、不改光标（cursor: default）。
 */
const reconnectWithGuard = (isConnected: boolean, label: string, fn: () => void) => {
  if (isConnected) return
  fn()
}

const reconnectTdx = () => reconnectEngine('通达信', () => marketStore.reconnectTdx())
const reconnectGalaxy = () => reconnectEngine('银河QMT', () => marketStore.reconnectGalaxy())
const reconnectGuojin = () => reconnectEngine('国金QMT', () => marketStore.reconnectGuojin())
const reconnectFutu = () => reconnectEngine('富途', () => marketStore.reconnectFutu())

const openHistory = async (fund: any) => {
  selectedFund.value = fund
  showHistoryModal.value = true
  await fundStore.fetchFundHistory(fund.fund_code)
}

const pagination = { pageSize: 100 }

const toggleWatchlist = (code: string) => fundStore.toggleWatchlist(code)

const rowProps = (row: any) => {
  return {}
}

const fetchData = async (isSilent = false) => {
  if (!isSilent && filteredTableData.value.length === 0) loading.value = true
  try {
    await Promise.all([
      fundStore.fetchDashboard(isSilent),
      marketStore.fetchOverview(),
      appStore.fetchSystemStatus()
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

onMounted(() => {
  // 每次进 Dashboard 都默认显示 我的自选（从其他页面返回时重置）
  currentTab.value = '自选'
  fetchData()
  setupRefreshTimer()
})
onUnmounted(() => { if (refreshTimer) clearInterval(refreshTimer) })

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
    title: '代码', key: 'fund_code', width: 42, fixed: 'left', align: 'center',
    sorter: (a: any, b: any) => a.fund_code.localeCompare(b.fund_code),
    render(row: any) { return h(NText, { code: true, class: 'code-cell' }, { default: () => row.fund_code || '-' }) }
  },
  {
    title: '名称', key: 'fund_name', width: 68, fixed: 'left', align: 'center', ellipsis: { tooltip: true },
    render(row: any) {
      return h('span', { class: 'fund-name-cell' }, cleanFundName(row.fund_name))
    }
  },
  {
    title: '现价', key: 'price', width: 38, align: 'center',
    sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render(row: any) { return h('span', { class: 'num-cell' }, formatPrice(row.price)) }
  },
  {
    title: '涨跌幅', key: 'price_change', width: 54, align: 'center',
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
    key: 'rt_val_display', width: 58, align: 'center',
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
    title: '实时溢价', key: 'rt_premium', width: 52, align: 'center',
    render(row: any) {
      if (!row.rt_val || !row.price) return h('span', { class: 'num-cell muted' }, '-')
      const p = (row.price / row.rt_val - 1) * 100
      return h('span', { class: 'num-cell strong compact', style: { color: priceColor(p) } }, formatPremium(p))
    }
  },
  {
    title: 'T-2/1日净值', key: 'nav', width: 52, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatValuation(row.nav)) }
  },
  {
    title: '净值日期', key: 'nav_date', width: 40, align: 'center',
    render(row: any) { return h(NText, { depth: 3, class: 'date-cell' }, { default: () => shortDate(row.nav_date) }) }
  },
  {
    title: () => h('div', { class: 'col-title-wrapper' }, [
      h('div', { style: 'font-size: 12px; font-weight: bold;' }, '静态估值'),
      h('div', { style: 'font-size: 9px; color: #64748b; margin-top: 1px;' }, '点击看历史记录')
    ]),
    key: 'static_val_display', width: 60, align: 'center',
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
    title: '静态溢价', key: 'static_premium', width: 52, align: 'center',
    sorter: (a: any, b: any) => (a.static_premium || 0) - (b.static_premium || 0),
    render(row: any) {
      if (!row.static_premium) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(row.static_premium) } }, formatPremium(row.static_premium))
    }
  },
  {
    title: '成交额(万)', key: 'volume', width: 56, align: 'right',
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
    title: '指数价', key: 'index_close', width: 48, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatIndexPrice(row.index_close)) }
  },
  {
    title: '指数涨跌', key: 'index_pct', width: 54, align: 'center',
    render(row: any) {
      if (!row.index_pct) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(Number(row.index_pct)) } }, formatPercent(Number(row.index_pct), 2))
    }
  },

  {
    title: '申购', key: 'purchase_status', width: 46, align: 'center',
    render(row: any) {
      const status = row.purchase_status || '未知'
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

    const baseCols: DataTableColumns<any> = [
        { title: '日期', key: 'date', width: 85, align: 'center', render(row: any) {
            const d = shortDate(row.date)
            const label = isCash ? getWeekendLabel(row.date, selectedFund.value?.fund_code || '') : ''
            if (label) {
                return h('span', { style: 'color: #d97706; font-weight: 600;' }, d + label)
            }
            return d
        }},
        // 现金管理不显示汇率，其他TAB汇率紧挨日期
        ...(isCash ? [] : [
            { title: '汇率', key: 'usd_cny_mid', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.usd_cny_mid, row.usd_cny_mid_chg) } },
        ]),
        { title: '净值', key: 'nav', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.nav, row.nav_chg) } },
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
        { title: '收盘价', key: 'price', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.price, row.price_chg, 3) } },
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
                { title: '静态估值', key: 'static_val', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.static_val, row.static_val_chg) } },
                { title: '估值误差', key: 'val_error_pct', width: 85, align: 'center', render(row: any) { const v = (row.static_val || 0) - (row.nav || 0); if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { class: 'num-cell', style: { color: priceColor(v), fontWeight: 'bold' } }, v.toFixed(4)) } },
                { title: '误差率', key: 'val_error_rate', width: 78, align: 'center', render(row: any) { const nav = row.nav || 0; if (nav === 0) return '-'; const v = ((row.static_val || 0) - nav) / nav * 100; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { class: 'num-cell', style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(3) + '%') } },
              ]
            : [
                { title: '静态估值', key: 'static_val', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.static_val, row.static_val_chg) } },
                { title: '估值误差', key: 'val_error_pct', width: 85, align: 'center', render(row: any) { const v = row.val_error_pct || 0; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { style: { color: priceColor(v), fontWeight: 'bold' } }, formatPercent(v, 4)) } },
                { title: '误差率', key: 'val_error_rate', width: 78, align: 'center', render(row: any) { const nav = row.nav || 0; if (nav === 0) return '-'; const v = ((row.static_val || 0) - nav) / nav * 100; if (v === 0) return h('span', { class: 'num-cell muted' }, '-'); return h('span', { style: { color: priceColor(v), fontWeight: '500' } }, v.toFixed(3) + '%') } },
                { title: '静态溢价', key: 'static_premium', width: 85, align: 'center', render(row: any) { const v = row.static_premium || 0; if (v === 0) return '-'; return h('span', { style: { color: priceColor(v) } }, formatPremium(v)) } },
              { title: '指数价', key: 'index_close', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.index_close, row.index_close_chg) } },
              { title: '指数涨跌', key: 'index_pct', width: 85, align: 'center', render(row: any) { if (row.index_pct == null) return '-'; return h('span', { style: { color: priceColor(row.index_pct), fontWeight: '500' } }, row.index_pct.toFixed(2) + '%') } },
              ],
        // 现金管理不显示份额/新增/换手率
        ...(isCash ? [] : [
            { title: '份额(万)', key: 'shares', width: 85, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatShares(row.shares)) } },
            { title: '新增(万)', key: 'shares_added', width: 80, align: 'center', render(row: any) { return h('span', { style: { color: priceColor(Number(row.shares_added || 0)), fontSize: '11px' } }, formatSharesChange(row.shares_added)) } },
            { title: '换手率', key: 'turnover_rate', width: 80, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatTurnoverRate(row.turnover_rate)) } },
        ]),
    ]

    if (fundHistory.value.length > 0) {
        const knownKeys = ['date', 'price', 'nav', 'static_val', 'static_premium', 'calibration', 'usd_cny_mid', 'turnover_amt', 'price_change', 'price_chg', 'nav_chg', 'static_val_chg', 'usd_cny_mid_chg', 'index_close', 'index_pct', 'idx_close', 'idx_pct', 'val_error_pct', 'shares', 'shares_added', 'turnover_rate', 'volume', 'valuation_error', 'hkd_cny_mid', 'latest_nav', 'futures_close', 'futures_pct']
        // Scan ALL rows to find dynamic keys (first row may lack data, e.g. 06-19 has no XOP_price)
        const dynamicKeys = new Set<string>()
        for (const row of fundHistory.value) {
            for (const key of Object.keys(row)) {
                if (!knownKeys.includes(key) && !key.endsWith('_chg') && typeof row[key] === 'number') {
                    dynamicKeys.add(key)
                }
            }
        }
        dynamicKeys.forEach(key => {
            let title = key
            const priceMatch = key.match(/^(.+)_price$/)
            if (priceMatch) {
                title = priceMatch[1] + '价格'
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
  const t2Tabs = ['QDII欧美', '黄金原油', '混合跨境']
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
      { title: '实时成交价(AG0)', key: 'ag0_price', width: 100, align: 'center', render(row: any) { return h('span', { class: 'num-cell' }, row.ag0_price ? row.ag0_price.toFixed(0) : '-') } },
      { title: '昨结算价(AG0)', key: 'ag0_settlement', width: 100, align: 'center', render(row: any) { return h('span', { class: 'num-cell muted' }, row.ag0_settlement ? row.ag0_settlement.toFixed(0) : '-') } }
    )
  }

  const hideIndexTabs = ['黄金原油', 'QDII欧美', '白银']
  if (hideIndexTabs.includes(currentTab.value)) {
    return cols.filter(c => c.key !== 'related_index' && c.key !== 'index_close' && c.key !== 'index_pct')
  }

  // 现金管理TAB：隐藏份额/新增/换手率/指数价/指数涨跌幅/申购/赎回/测试价/溢价率
  // 并重命名列 + 添加债券ETF专属列
  if (currentTab.value === '现金管理') {
    // 过滤掉不需要的列
    cols = cols.filter(c => !['shares', 'shares_added', 'turnover_rate', 'index_close', 'index_pct', 'purchase_status', 'redemption_status', 'static_val_display', 'static_premium', 'rt_premium'].includes(c.key))
    
    // 重命名列
    cols.forEach(col => {
      if (col.key === 'nav') col.title = '最新净值'
      if (col.key === 'rt_val_display') col.title = '估值'
    })
    
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
    
    // 日均增长放在净值日期之后
    const navDateIndex = cols.findIndex(c => c.key === 'nav_date')
    if (navDateIndex >= 0) {
      cols.splice(navDateIndex + 1, 0,
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
:deep(.n-data-table-th.col-rt-val) {
  background-color: #e0f2fe !important;
}
:deep(.n-data-table-th.col-static-val) {
  background-color: #ffedd5 !important;
}
</style>
