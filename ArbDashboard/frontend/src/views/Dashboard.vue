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
                <n-tag :type="hasTdx ? 'success' : 'error'" size="small" round style="font-weight: bold; justify-content: center; cursor: pointer;" @click="reconnectEngine">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    通达信
                </n-tag>
                <div style="display: flex; gap: 4px; justify-content: center;">
                    <n-tag :type="hasIb ? 'success' : 'warning'" size="small" round style="font-weight: bold; flex: 1; justify-content: center; cursor: pointer;" @click="reconnectIB">
                        <template #icon><n-icon><Zap /></n-icon></template>
                        IB
                    </n-tag>
                </div>
                
                <n-tag :type="hasGalaxy ? 'success' : 'error'" size="small" round style="font-weight: bold; justify-content: center; cursor: pointer;" @click="reconnectEngine">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    银河QMT
                </n-tag>
                <n-tag :type="hasGuojin ? 'success' : 'error'" size="small" round style="font-weight: bold; justify-content: center; cursor: pointer;" @click="reconnectEngine">
                    <template #icon><n-icon><Zap /></n-icon></template>
                    国金QMT
                </n-tag>
                <n-tag :type="hasFutu ? 'success' : 'error'" size="small" round style="font-weight: bold; justify-content: center; cursor: pointer;" @click="reconnectEngine">
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
            </n-tabs>
            <n-input v-model:value="searchKeyword" placeholder="搜索代码/名称..." class="search-input" size="small" clearable />
          </div>

          <n-data-table
            :columns="columns"
            :data="filteredTableData"
            :loading="loading"
            :pagination="pagination"
            flex-height
            style="height: calc(100vh - 200px);"
            :scroll-x="tableScrollX"
            virtual-scroll
            size="small"
            bordered
            :row-props="rowProps"
          />
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 历史对账详情弹窗 -->
    <n-modal v-model:show="showHistoryModal" preset="card" :title="`[历史记录] ${selectedFund?.fund_code} - ${selectedFund?.fund_name}`" style="width: 95%; max-width: 1500px;">
      <div v-if="selectedFund" style="margin-bottom: 16px; display: flex; gap: 24px; font-size: 14px; background: #f8fafc; padding: 12px; border-radius: 8px;">
        <div><strong>关联指数：</strong> {{ selectedFund.idx_name || '-' }} ({{ selectedFund.idx_code || '-' }})</div>
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
        filteredTableData, fundHistory } = storeToRefs(fundStore)
const { engineRunning, milestones } = storeToRefs(appStore)
const { overview: marketOverview, hasTdx, hasIb, hasIbNotRunning,
        hasGalaxy, hasGuojin, hasFutu } = storeToRefs(marketStore)

// ===== 本地状态（无需进 Store） =====
const showHistoryModal = ref(false)
const selectedFund = ref<any>(null)
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

const reconnectEngine = async () => {
  try {
    message.loading('正在重启国内行情引擎...', { duration: 1500 })
    const data = await appStore.reconnectEngine()
    if (data.status === 'ok') {
      message.success('国内行情引擎重启成功！')
      setTimeout(fetchData, 1000)
    }
  } catch (e: any) {
    message.error('重启引擎失败: ' + e.message)
  }
}

const openHistory = async (fund: any) => {
  selectedFund.value = fund
  showHistoryModal.value = true
  await fundStore.fetchFundHistory(fund.fund_code)
}

const pagination = { pageSize: 100 }

const toggleWatchlist = (code: string) => fundStore.toggleWatchlist(code)

const rowProps = (row: any) => {
  return {
    style: 'cursor: pointer;',
    onClick: () => {
      router.push({
        path: '/analysis',
        query: { code: row.fund_code, name: row.fund_name }
      })
    }
  }
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
    title: '代码', key: 'fund_code', width: 68, fixed: 'left', align: 'center',
    sorter: (a: any, b: any) => a.fund_code.localeCompare(b.fund_code),
    render(row: any) { return h(NText, { code: true, class: 'code-cell' }, { default: () => row.fund_code || '-' }) }
  },
  {
    title: '名称', key: 'fund_name', width: 118, fixed: 'left', align: 'center', ellipsis: { tooltip: true },
    render(row: any) {
      return h('span', { class: 'fund-name-cell' }, cleanFundName(row.fund_name))
    }
  },
  {
    title: '现价', key: 'price', width: 64, align: 'center',
    sorter: (a: any, b: any) => (a.price || 0) - (b.price || 0),
    render(row: any) { return h('span', { class: 'num-cell' }, formatPrice(row.price)) }
  },
  {
    title: '涨跌幅', key: 'price_change', width: 82, align: 'center',
    sorter: (a: any, b: any) => (a.price_change || 0) - (b.price_change || 0),
    render(row: any) {
      const chg = row.price_change || 0
      if (chg === 0 && (!row.price || row.price === 0)) return '-'
      return h('span', { class: 'num-cell strong', style: { color: priceColor(chg) } }, formatPercent(chg, 2))
    }
  },
  {
    title: '实时估值', key: 'rt_val_display', width: 78, align: 'center',
    render(row: any) {
      if (row.rt_val && row.rt_val > 0) return h('span', { class: 'num-cell strong' }, row.rt_val.toFixed(4))
      return h('span', { class: 'num-cell muted' }, '-')
    }
  },
  {
    title: '实时溢价', key: 'rt_premium', width: 82, align: 'center',
    render(row: any) {
      if (!row.rt_val || !row.price) return h('span', { class: 'num-cell muted' }, '-')
      const p = (row.price / row.rt_val - 1) * 100
      return h('span', { class: 'num-cell strong compact', style: { color: priceColor(p) } }, formatPremium(p))
    }
  },
  {
    title: 'T-2/1日净值', key: 'nav', width: 82, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatValuation(row.nav)) }
  },
  {
    title: '净值日期', key: 'nav_date', width: 66, align: 'center',
    render(row: any) { return h(NText, { depth: 3, class: 'date-cell' }, { default: () => shortDate(row.nav_date) }) }
  },
  {
    title: '静态估值', key: 'static_val_display', width: 78, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatValuation(row.static_val)) }
  },
  {
    title: '静态溢价', key: 'static_premium', width: 82, align: 'center',
    sorter: (a: any, b: any) => (a.static_premium || 0) - (b.static_premium || 0),
    render(row: any) {
      if (!row.static_premium) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(row.static_premium) } }, formatPremium(row.static_premium))
    }
  },
  {
    title: '成交额(万)', key: 'volume', width: 100, align: 'right',
    sorter: (a: any, b: any) => (a.volume || 0) - (b.volume || 0),
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatVolume(row.volume)) }
  },
  {
    title: '份额(万)', key: 'shares', width: 72, align: 'right',
    sorter: (a: any, b: any) => (a.shares || 0) - (b.shares || 0),
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatShares(row.shares)) }
  },
  {
    title: '新增(万)', key: 'shares_added', width: 68, align: 'right',
    sorter: (a: any, b: any) => (a.shares_added || 0) - (b.shares_added || 0),
    fixedHeader: true,
    render(row: any) {
      const added = row.shares_added || 0
      return h('span', { class: 'num-cell compact', style: { color: priceColor(added) } }, formatSharesChange(row.shares_added))
    }
  },
  {
      title: '换手率', key: 'turnover_rate', width: 64, align: 'center',
      render(row: any) { return h('span', { class: 'num-cell muted' }, formatTurnoverRate(row.turnover_rate)) }
  },
  {
    title: '指数价', key: 'index_close', width: 72, align: 'center',
    render(row: any) { return h('span', { class: 'num-cell muted' }, formatIndexPrice(row.index_close)) }
  },
  {
    title: '指数涨跌幅', key: 'index_pct', width: 82, align: 'center',
    render(row: any) {
      if (!row.index_pct) return '-'
      return h('span', { class: 'num-cell compact', style: { color: priceColor(Number(row.index_pct)) } }, formatPercent(Number(row.index_pct), 2))
    }
  },

  {
    title: '申购', key: 'purchase_status', width: 68, align: 'center',
    render(row: any) {
      const status = row.purchase_status || '未知'
      const isOk = status.includes('开放')
      return h(NTag, { type: isOk ? 'success' : 'warning', size: 'small', round: true, class: 'status-pill' }, { default: () => status })
    }
  },
  {
    title: '赎回',
    key: 'redemption_status',
    width: 68,
    align: 'center',
    render(row: any) {
      const status = row.redemption_status || '未知'
      const isOk = status.includes('开放')
      return h(NTag, { type: isOk ? 'success' : 'warning', size: 'small', round: true, class: 'status-pill' }, { default: () => status })
    }
  },
  {
    title: '验算',
    key: 'actions',
    width: 60,
    fixed: 'right',
    align: 'center',
    render(row: any) {
      return h(NButton, {
        quaternary: true,
        circle: true,
        size: 'tiny',
        type: 'info',
        onClick: (e: MouseEvent) => {
          e.stopPropagation()
          openHistory(row)
        }
      }, { default: () => h(NIcon, null, { default: () => h(History, { style: { color: '#0284c7' } }) }) })
    }
  }
  ]

const historyColumns = computed<DataTableColumns<any>>(() => {
    const renderValWithChg = (val: number, chg: number, precision: number = 4) => {
        if (!val || val === 0) return '-'
        return h('div', { style: 'display: flex; flex-direction: column; align-items: center;' }, [
            h('span', { style: 'font-weight: 500;' }, val.toFixed(precision)),
            chg ? h('span', { style: { fontSize: '10px', color: priceColor(chg), lineHeight: '1' } }, formatPercent(chg, 2)) : null
        ])
    }

    const baseCols: DataTableColumns<any> = [
        { title: '日期', key: 'date', width: 70, align: 'center', render(row: any) { return shortDate(row.date) } },
        { title: '汇率', key: 'usd_cny_mid', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.usd_cny_mid, row.usd_cny_mid_chg) } },
        { title: '净值', key: 'nav', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.nav, row.nav_chg) } },
        { title: '收盘价', key: 'price', width: 85, align: 'center', render(row: any) { return renderValWithChg(row.price, row.price_chg, 3) } },
        { title: '静态估值', key: 'static_val', width: 95, align: 'center', render(row: any) { return renderValWithChg(row.static_val, row.static_val_chg) } },
        { 
            title: '估值误差', key: 'val_error_pct', width: 85, align: 'center',
            render(row: any) {
                const val = row.val_error_pct || 0
                if (val === 0) return '-'
                return h('span', { style: { color: priceColor(val), fontWeight: 'bold' } }, formatPercent(val, 4))
            }
        },
        { 
            title: '静态溢价', key: 'static_premium', width: 85, align: 'center',
            render(row: any) {
                const val = row.static_premium || 0
                if (val === 0) return '-'
                return h('span', { style: { color: priceColor(val) } }, formatPremium(val))
            }
        },
        { title: '份额(万)', key: 'shares', width: 85, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatShares(row.shares)) } },
        { 
            title: '新增(万)', key: 'shares_added', width: 80, align: 'center',
            render(row: any) { 
                return h('span', { style: { color: priceColor(Number(row.shares_added || 0)), fontSize: '11px' } }, formatSharesChange(row.shares_added))
            }
        },
        { title: '换手率', key: 'turnover_rate', width: 80, align: 'center', render(row: any) { return h('span', { style: 'font-size: 12px;' }, formatTurnoverRate(row.turnover_rate)) } }
    ]

    if (fundHistory.value.length > 0) {
        const firstRow = fundHistory.value[0]
        const knownKeys = ['date', 'price', 'nav', 'static_val', 'static_premium', 'calibration', 'usd_cny_mid', 'turnover_amt', 'price_change', 'price_chg', 'nav_chg', 'static_val_chg', 'usd_cny_mid_chg', 'index_close', 'index_pct', 'val_error_pct', 'shares', 'shares_added', 'turnover_rate', 'volume', 'valuation_error', 'hkd_cny_mid', 'latest_nav']
        Object.keys(firstRow).forEach(key => {
            if (!knownKeys.includes(key) && !key.endsWith('_chg') && (typeof firstRow[key] === 'number' || firstRow[key] === null)) {
                baseCols.push({
                    title: key, key: key, width: 90, align: 'center',
                    render(row: any) { return renderValWithChg(row[key], row[`${key}_chg`], 4) }
                })
            }
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
  return cols
})

const tableScrollX = computed(() => {
  return columns.value.reduce((total, col: any) => total + Number(col.width || 80), 0)
})
</script>

<style scoped>
.dashboard { color: #1f2937; }
:deep(.n-data-table),
:deep(.n-data-table-wrapper),
:deep(.n-data-table-base-table),
:deep(.n-data-table-base-table-body),
:deep(.n-data-table-table),
:deep(.n-data-table-tbody),
:deep(.n-scrollbar-container),
:deep(.n-scrollbar-content) {
  background: #ffffff !important;
}
:deep(.n-data-table-tr) {
  background-color: #ffffff !important;
}
:deep(.n-data-table-td) {
  padding: 3px 4px !important;
  color: #1f2937 !important;
  background-color: #ffffff !important;
  border-color: #edf1f7 !important;
}
:deep(.n-data-table-th) {
  padding: 5px 4px !important;
  background-color: #eef5ff !important;
}
:deep(.n-data-table-tr:nth-child(even) .n-data-table-td) { background-color: #fbfdff !important; }
:deep(.n-data-table-tr:hover .n-data-table-td) { background-color: #f6faff !important; }

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
</style>
