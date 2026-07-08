<template>
  <div class="etf-rotation">
    <!-- 顶部：美元在岸价 + 更新信息 -->
    <n-grid :cols="24" :x-gap="10" :y-gap="10" style="margin-bottom: 10px;">
      <n-gi :span="24">
        <n-card size="small" :bordered="false" class="fx-card">
          <div class="fx-bar">
            <div class="fx-item">
              <span class="fx-label">美元/人民币 (在岸价)</span>
              <span class="fx-value">{{ fxSpot || '获取中...' }}</span>
              <span class="fx-time">ETF 用</span>
            </div>
            <div class="fx-item">
              <span class="fx-label">美元/人民币 (中间价)</span>
              <span class="fx-value">{{ fxMid || '-' }}</span>
              <span class="fx-time">LOF 用</span>
            </div>
            <div class="fx-item">
              <span class="fx-label">数据源</span>
              <n-tag size="tiny" type="info" round>在岸价 新浪</n-tag>
              <n-tag size="tiny" type="warning" round style="margin-left: 4px;">中间价 PBOC 国家外汇管理局</n-tag>
            </div>
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 主内容区 -->
    <n-card :bordered="false" class="main-card" content-style="padding: 0;">
      <!-- 目标选择面板（溢价锁定卖出） -->
      <div class="target-panel" :class="{ 'has-target': targetFund }">
        <div v-if="!targetFund" class="target-empty">
          在下方列表中点击「设为卖出」锁定目标
        </div>
        <div v-else class="target-content">
          <div class="target-info">
            <div class="target-badge">
              <div class="target-name">{{ targetFund.name }}</div>
              <div class="target-code">{{ targetFund.code }}</div>
            </div>
            <div class="target-stats">
              <div class="ts-item">
                <span class="ts-label">盘口价格</span>
                <span class="ts-value mono">{{ fundPrice(targetFund.code) }}</span>
              </div>
              <div class="ts-item">
                <span class="ts-label">建议数量</span>
                <span class="ts-value mono primary">{{ suggestedQty }}</span>
              </div>
              <div class="ts-item">
                <span class="ts-label">实时溢价率</span>
                <span :class="['ts-value', 'mono', fundPremium(targetFund.code) > 0 ? 'up' : 'down']">
                  {{ fundPremiumText(targetFund.code) }}
                </span>
              </div>
            </div>
          </div>
          <n-button size="small" type="error" ghost @click="clearTarget">取消锁定</n-button>
        </div>
      </div>

      <!-- TAB 导航 -->
      <div class="tab-bar">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          :class="['tab-btn', { active: activeTab === tab.key }]"
          @click="switchTab(tab.key)"
        >{{ tab.label }}</button>
      </div>

      <!-- 分组内容 -->
      <div v-for="g in groups" :key="g.group_id" v-show="activeTab === 'g' + g.group_id" class="tab-content">
        <n-data-table
          :columns="tableColumns"
          :data="groupFunds(g.group_id)"
          :bordered="false"
          :single-line="false"
          size="small"
          class="rotation-table"
        />
      </div>

      <!-- 历史分析 TAB -->
      <div v-show="activeTab === 'history'" class="tab-content" style="padding: 16px;">
        <div class="history-toolbar">
          <n-select
            v-model:value="historyGroupId"
            :options="groupSelectOptions"
            style="width: 200px;"
            size="small"
          />
          <n-button size="small" type="primary" @click="fetchHistory" :loading="historyLoading">
            刷新数据
          </n-button>
        </div>
        <div v-if="historyLoading" class="history-loading">加载中...</div>
        <div v-else-if="historyData.length === 0" class="history-empty">请选择分组并点击刷新</div>
        <div v-else class="history-table-wrap">
          <table class="history-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>基金代码</th>
                <th>类型</th>
                <th>收盘价</th>
                <th>T-1净值</th>
                <th>溢价率</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="day in historyData" :key="day.date">
                <tr v-for="(fd, fi) in day.funds" :key="fd.fund_code + fi">
                  <td v-if="fi === 0" :rowspan="day.funds.length" class="date-cell">{{ day.date }}</td>
                  <td class="mono">{{ fd.fund_code }}</td>
                  <td>
                    <n-tag :type="fd.type === 'LOF' ? 'info' : 'success'" size="tiny" round>
                      {{ fd.type }}
                    </n-tag>
                  </td>
                  <td class="mono">{{ fd.price > 0 ? fd.price.toFixed(3) : '-' }}</td>
                  <td class="mono">{{ fd.nav > 0 ? fd.nav.toFixed(4) : '-' }}</td>
                  <td :class="['mono', getPremiumColor(fd.premium)]">
                    {{ fd.premium !== null && fd.premium !== undefined ? (fd.premium > 0 ? '+' : '') + fd.premium.toFixed(2) + '%' : '-' }}
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { NButton, NCard, NGrid, NGi, NTag, NSelect, NDataTable, NIcon } from 'naive-ui'
import type { DataTableColumn } from 'naive-ui'

// ─── 类型 ────────────────────────────────────────

interface Fund {
  group_id: number
  code: string
  name: string
  type: 'LOF' | 'ETF'
}

interface Group {
  group_id: number
  group_name: string
  funds: Fund[]
}

interface FundData {
  price: number
  nav: number
  position: number
  hedge: number | null
  rt_val: number
  rt_premium: number
  type: string
  group_id: number
  us_symbol: string
}

interface PricesResponse {
  funds: Record<string, FundData>
  fx_spot: number
  fx_mid: number
  us_prices: Record<string, number>
  update_time: string
}

interface HistoryFund {
  fund_code: string
  type: string
  price: number
  nav: number
  premium: number | null
}

interface HistoryDay {
  date: string
  funds: HistoryFund[]
}

// ─── 状态 ────────────────────────────────────────

const GROUP_NAMES: Record<number, string> = { 1: '油气', 2: '生物科技', 3: '标普500', 4: '纳指100' }

const groups = ref<Group[]>([])
const fundDataMap = ref<Record<string, FundData>>({})
const fxSpot = ref('')
const fxMid = ref('')
const updateTime = ref('')
const activeTab = ref('g1')
const targetFund = ref<{ code: string; name: string; groupId: number } | null>(null)
const suggestedQty = ref('')
const capital = ref(100000)
const historyGroupId = ref(1)
const historyData = ref<HistoryDay[]>([])
const historyLoading = ref(false)

let refreshTimer: any = null

const tabs = computed(() => [
  ...groups.value.map(g => ({ key: 'g' + g.group_id, label: g.group_name })),
  { key: 'history', label: '历史分析' }
])

const groupSelectOptions = computed(() =>
  groups.value.map(g => ({ label: g.group_name, value: g.group_id }))
)

// ─── 数据处理 ────────────────────────────────────

function groupFunds(groupId: number): any[] {
  const g = groups.value.find(x => x.group_id === groupId)
  if (!g) return []
  return g.funds.map(f => ({
    ...f,
    ...fundDataMap.value[f.code] || {},
    _price: fundDataMap.value[f.code]?.price || 0,
    _rt_val: fundDataMap.value[f.code]?.rt_val || 0,
    _rt_premium: fundDataMap.value[f.code]?.rt_premium || null,
    _hedge: fundDataMap.value[f.code]?.hedge || null,
    _nav: fundDataMap.value[f.code]?.nav || 0,
  }))
}

function fundPrice(code: string): string {
  const d = fundDataMap.value[code]
  return d ? d.price.toFixed(3) : '-'
}

function fundPremium(code: string): number {
  const d = fundDataMap.value[code]
  return d?.rt_premium || 0
}

function fundPremiumText(code: string): string {
  const d = fundDataMap.value[code]
  if (!d || d.rt_premium === null || d.rt_premium === 0) return '-'
  const sign = d.rt_premium > 0 ? '+' : ''
  return `${sign}${d.rt_premium.toFixed(2)}%`
}

function getPremiumColor(premium: number | null): string {
  if (premium === null || premium === undefined) return ''
  return premium > 0 ? 'up' : 'down'
}

function calculateQty(code: string): number {
  const d = fundDataMap.value[code]
  if (!d || d.price <= 0 || !d.hedge || d.hedge <= 0) return 0
  const temp = capital.value / d.price
  const usHedge = Math.round(temp / d.hedge)
  return Math.max(Math.round(usHedge * d.hedge / 100) * 100, 100)
}

// ─── API 调用 ────────────────────────────────────

async function fetchList() {
  try {
    const res = await fetch('/api/etf-rotation/list')
    const json = await res.json()
    if (json.status === 'ok') {
      groups.value = json.data || []
    }
  } catch (e) {
    console.error('获取ETF轮动列表失败', e)
  }
}

async function fetchPrices() {
  try {
    const res = await fetch('/api/etf-rotation/prices')
    const json = await res.json()
    if (json.status === 'ok') {
      const data: PricesResponse = json.data
      fundDataMap.value = data.funds || {}
      fxSpot.value = data.fx_spot > 0 ? data.fx_spot.toFixed(4) : '获取中...'
      fxMid.value = data.fx_mid > 0 ? data.fx_mid.toFixed(4) : '-'
      updateTime.value = data.update_time
      if (targetFund.value) {
        suggestedQty.value = String(calculateQty(targetFund.value.code) || '等待中')
      }
    }
  } catch (e) {
    console.error('获取ETF轮动价格失败', e)
  }
}

async function fetchHistory() {
  historyLoading.value = true
  try {
    const res = await fetch(`/api/etf-rotation/history/${historyGroupId.value}`)
    const json = await res.json()
    if (json.status === 'ok') {
      historyData.value = json.data || []
    }
  } catch (e) {
    console.error('获取历史轮动数据失败', e)
  } finally {
    historyLoading.value = false
  }
}

// ─── 操作 ────────────────────────────────────────

function switchTab(key: string) {
  activeTab.value = key
  if (key === 'history') {
    if (historyData.value.length === 0) fetchHistory()
  }
}

function setAsTarget(code: string, name: string, groupId: number) {
  targetFund.value = { code, name, groupId }
  suggestedQty.value = String(calculateQty(code) || '等待中')
}

function clearTarget() {
  targetFund.value = null
  suggestedQty.value = ''
}

// ─── 表格列定义 ──────────────────────────────────

const tableColumns: DataTableColumn[] = [
  { title: '基金代码', key: 'code', width: 100, className: 'mono' },
  { title: '基金简称', key: 'name', width: 140,
    render: (row: any) => [
      h(NTag, { size: 'tiny', type: row.type === 'LOF' ? 'info' : 'success', round: true }, { default: () => row.type }),
      ' ' + row.name
    ]
  },
  { title: '盘口价格', key: '_price', width: 100, className: 'mono',
    render: (row: any) => row._price > 0 ? row._price.toFixed(3) : '-'
  },
  { title: 'T-1净值', key: '_nav', width: 100, className: 'mono',
    render: (row: any) => row._nav > 0 ? row._nav.toFixed(4) : '-'
  },
  { title: '对冲值', key: '_hedge', width: 100, className: 'mono',
    render: (row: any) => row._hedge ? row._hedge.toFixed(4) : '计算中'
  },
  { title: '实时估值', key: '_rt_val', width: 110, className: 'mono',
    render: (row: any) => row._rt_val > 0 ? row._rt_val.toFixed(4) : '无基准'
  },
  { title: '实时溢价率', key: '_rt_premium', width: 110,
    render: (row: any) => {
      if (row._rt_premium === null || row._rt_premium === 0) return h('span', { class: 'mono' }, '-')
      const color = row._rt_premium > 0 ? '#dc2626' : '#16a34a'
      const sign = row._rt_premium > 0 ? '+' : ''
      return h('span', { class: 'mono', style: { color, fontWeight: 'bold' } }, `${sign}${row._rt_premium.toFixed(2)}%`)
    }
  },
  { title: '建议数量', key: 'code', width: 100,
    render: (row: any) => {
      const qty = calculateQty(row.code)
      return h('span', { class: 'mono', style: { color: '#2563eb', fontWeight: 'bold' } }, qty > 0 ? String(qty) : '等待中')
    }
  },
  { title: '操作', key: 'action', width: 110,
    render: (row: any) => {
      const isTarget = targetFund.value?.code === row.code
      return h(NButton, {
        size: 'tiny',
        type: isTarget ? 'error' : 'default',
        ghost: !isTarget,
        onClick: () => isTarget ? clearTarget() : setAsTarget(row.code, row.name, row.group_id)
      }, { default: () => isTarget ? '已锁定' : '设为卖出' })
    }
  },
]

// 修复 render 中 h 函数的引用
import { h } from 'vue'

// ─── 生命周期 ────────────────────────────────────

onMounted(() => {
  fetchList().then(() => {
    fetchPrices()
  })
  refreshTimer = setInterval(fetchPrices, 3000)
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.etf-rotation { padding: 0; }

.fx-card { background: #f0f9ff; border: 1px solid #bae6fd !important; }
.fx-bar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
.fx-item { display: flex; align-items: center; gap: 8px; }
.fx-label { font-size: 12px; color: #0369a1; font-weight: 600; }
.fx-value { font-size: 20px; font-weight: 800; color: #1e293b; font-family: 'Consolas', monospace; }
.fx-time { font-size: 11px; color: #94a3b8; }

.main-card { border-radius: 8px; }

.target-panel {
  background: #fff5f5; border: 2px solid #fecaca; border-radius: 8px;
  margin: 12px; padding: 16px; min-height: 60px;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.3s;
}
.target-panel.has-target { justify-content: space-between; }
.target-empty { color: #94a3b8; font-size: 13px; }
.target-content { display: flex; align-items: center; gap: 24px; width: 100%; justify-content: space-between; }
.target-info { display: flex; align-items: center; gap: 24px; }
.target-badge { text-align: center; }
.target-name { font-size: 16px; font-weight: bold; color: #dc2626; }
.target-code { font-size: 12px; color: #64748b; }
.target-stats { display: flex; gap: 24px; }
.ts-item { text-align: center; }
.ts-label { font-size: 11px; color: #94a3b8; display: block; }
.ts-value { font-size: 16px; font-weight: bold; }
.ts-value.primary { color: #2563eb; }
.ts-value.up { color: #dc2626; }
.ts-value.down { color: #16a34a; }

.tab-bar {
  display: flex; background: #f8fafc; border-bottom: 1px solid #e2e8f0;
  padding: 0 12px; gap: 0;
}
.tab-btn {
  padding: 10px 20px; border: none; background: none;
  font-size: 13px; font-weight: 600; color: #64748b;
  cursor: pointer; transition: 0.2s; border-bottom: 2px solid transparent;
}
.tab-btn:hover { color: #2563eb; background: #f1f5f9; }
.tab-btn.active { color: #2563eb; border-bottom-color: #2563eb; background: #fff; }

.tab-content { padding: 0; }

.rotation-table :deep(td.mono) { font-family: 'Consolas', monospace; font-weight: 600; font-size: 13px; }

.history-toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
.history-loading, .history-empty { text-align: center; padding: 40px; color: #94a3b8; }
.history-table-wrap { max-height: 500px; overflow-y: auto; }
.history-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.history-table th {
  background: #f8fafc; padding: 10px 12px; text-align: center;
  color: #64748b; border-bottom: 2px solid #e2e8f0; font-weight: 600;
  position: sticky; top: 0; z-index: 10;
}
.history-table td { padding: 10px 12px; text-align: center; border-bottom: 1px solid #e2e8f0; }
.history-table tr:hover td { background: #f0f7ff; }
.history-table .date-cell { background: #fef3c7; font-weight: bold; vertical-align: top; padding-top: 14px; }

.mono { font-family: 'Consolas', monospace; }
.up { color: #dc2626; font-weight: bold; }
.down { color: #16a34a; font-weight: bold; }
</style>
