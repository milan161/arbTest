<template>
  <div class="holding-analysis-page">
    <n-card :bordered="false" class="shadow-soft" size="small">
      <template #header>
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px;">
          <div style="display: flex; align-items: center; gap: 12px;">
            <n-button text size="small" @click="router.push('/dashboard')" style="color: #64748b; padding: 0 4px;">
              ← 返回主看板
            </n-button>
            <n-icon size="20" color="#2563eb"><PieChart /></n-icon>
            <span style="font-size: 16px; font-weight: bold;">季报持仓分析</span>
            <n-tag size="small" type="info">{{ fundCode }}</n-tag>
            <span style="font-size: 14px; color: #475569;">{{ fundName || fundCode }}</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 12px; color: #64748b;">报告期:</span>
            <n-button
              v-for="p in periods"
              :key="p.period"
              size="small"
              :type="currentPeriod === p.period ? 'primary' : 'default'"
              :ghost="currentPeriod !== p.period"
              :style="currentPeriod === p.period ? { background: '#2563eb', borderColor: '#2563eb', color: '#fff' } : {}"
              @click="switchPeriod(p.period)"
            >
              {{ p.period }}
            </n-button>
          </div>
        </div>
      </template>

      <div v-if="loading" style="text-align: center; padding: 40px; color: #999;">
        <n-spin size="small" />
        <span style="margin-left: 8px;">加载中...</span>
      </div>

      <n-empty v-else-if="error" :description="error" style="padding: 40px;" />

      <template v-else-if="holdings.length > 0">
        <!-- 顶部概览：报告日期 + 披露持仓数 + 地区分布 + 总权重 + 底层期货 -->
        <n-grid :cols="24" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
          <n-gi :span="4">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">报告截止日</div>
              <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ reportDate || '-' }}</div>
            </n-card>
          </n-gi>
          <n-gi :span="4">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">披露持仓数</div>
              <div style="font-size: 16px; font-weight: bold; color: #1e293b;">{{ holdings.length }} 只</div>
            </n-card>
          </n-gi>
          <n-gi :span="5">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b; margin-bottom: 4px;">地区分布</div>
              <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <div v-for="r in regionDistribution" :key="r.region" style="display: flex; align-items: center; gap: 3px;">
                  <span style="font-weight: 600; color: #1e293b; font-size: 11px;">{{ regionLabel(r.region) }}</span>
                  <span style="font-size: 13px; font-weight: bold; color: #2563eb;">{{ r.pct.toFixed(1) }}%</span>
                </div>
              </div>
            </n-card>
          </n-gi>
          <n-gi :span="5">
            <n-card size="small" class="stat-card" content-style="padding: 10px;">
              <div style="font-size: 11px; color: #64748b;">总权重（前十大）</div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">{{ totalWeight.toFixed(2) }}%</div>
            </n-card>
          </n-gi>
          <n-gi :span="6">
            <n-card
              size="small"
              class="stat-card"
              content-style="padding: 10px; cursor: pointer;"
              style="transition: background 0.2s;"
              :style="penetrationReady ? { background: '#f0f9ff', border: '1px solid #bae6fd' } : { background: '#f8fafc' }"
              @click="penetrationReady ? goToPenetration() : null"
              @mouseenter="penetrationReady = true"
              @mouseleave="penetrationReady = false"
            >
              <div style="font-size: 11px; color: #64748b; margin-bottom: 4px;">底层期货（点击穿透）</div>
              <div v-if="penetrationData" style="display: flex; gap: 12px; flex-wrap: wrap;">
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #ea580c;">{{ wtiPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">WTI (CL)</div>
                </div>
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #7c3aed;">{{ brentPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">Brent (B)</div>
                </div>
                <div>
                  <div style="font-size: 15px; font-weight: bold; color: #16a34a;">{{ penetratedPct.toFixed(1) }}%</div>
                  <div style="font-size: 10px; color: #64748b;">已穿透</div>
                </div>
              </div>
              <div v-else style="font-size: 13px; color: #94a3b8;">—</div>
            </n-card>
          </n-gi>
        </n-grid>

        <!-- 季报持仓实时估值 -->
        <n-card v-if="valuation" size="small" class="shadow-soft" style="margin-bottom: 16px; background: #f8fafc;">
          <template #header>
            <div style="font-size: 14px; font-weight: bold;">季报持仓法实时估值</div>
          </template>
          <n-grid :cols="24" :x-gap="12" :y-gap="12">
            <n-gi :span="6">
              <div style="font-size: 12px; color: #64748b;">报告期净值</div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">{{ valuation.report_nav != null ? valuation.report_nav.toFixed(4) : '-' }}</div>
            </n-gi>
            <n-gi :span="6">
              <div style="font-size: 12px; color: #64748b;">季报持仓实时估值</div>
              <div style="font-size: 18px; font-weight: bold;" :style="{ color: valuation.realtime_nav != null ? '#2563eb' : '#94a3b8' }">
                {{ valuation.realtime_nav != null ? valuation.realtime_nav.toFixed(4) : '数据不足' }}
              </div>
            </n-gi>
            <n-gi :span="6">
              <div style="font-size: 12px; color: #64748b;">累计涨跌贡献</div>
              <div style="font-size: 18px; font-weight: bold;" :style="{ color: priceColor(valuation.total_change_pct * 100) }">
                {{ valuation.total_change_pct != null ? formatPercent(valuation.total_change_pct * 100, 2) : '-' }}
              </div>
            </n-gi>
            <n-gi :span="6">
              <div style="font-size: 12px; color: #64748b;">有效权重覆盖</div>
              <div style="font-size: 18px; font-weight: bold; color: #1e293b;">
                {{ valuation.valid_weight_sum != null ? (valuation.valid_weight_sum * 100).toFixed(2) + '%' : '-' }}
              </div>
            </n-gi>
          </n-grid>
          <div v-if="valuation.components && valuation.components.some((c: any) => c.status !== 'ok')" style="margin-top: 10px; font-size: 11px; color: #64748b;">
            注：部分底层标的缺少报告日收盘价或实时行情，仅使用有效标的计算估值。
          </div>
        </n-card>

        <!-- 前十大持仓表 -->
        <n-card size="small" class="shadow-soft" style="margin-bottom: 16px;">
          <template #header>
            <div style="font-size: 14px; font-weight: bold;">前十大持仓</div>
          </template>
          <n-data-table
            :columns="holdingColumns"
            :data="holdings"
            :summary="holdingSummary"
            size="small"
            bordered
            :pagination="false"
            style="max-height: 500px;"
          />
        </n-card>

        <!-- 退出 / 新进前十 — 并排 -->
        <n-grid :cols="24" :x-gap="12" :y-gap="12" style="margin-bottom: 16px;">
          <n-gi :span="12" v-if="exited.length > 0">
            <n-card size="small" class="shadow-soft" style="background: #fff7ed;">
              <template #header>
                <div style="font-size: 13px; font-weight: bold; color: #9a3412;">本期已退出前十（上期 {{ prevPeriod }}）</div>
              </template>
              <div v-for="(item, idx) in exited" :key="idx" style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #ffedd5;">
                <span style="font-size: 12px;">
                  <span v-if="item.symbol" style="font-weight: 600; margin-right: 6px;">{{ item.symbol }}</span>
                  {{ item.name }}
                </span>
                <span style="font-size: 12px; color: #64748b;">{{ item.weight != null ? (item.weight * 100).toFixed(2) + '%' : '-' }}</span>
              </div>
            </n-card>
          </n-gi>
          <n-gi :span="12" v-if="newIn.length > 0">
            <n-card size="small" class="shadow-soft" style="background: #f0fdf4;">
              <template #header>
                <div style="font-size: 13px; font-weight: bold; color: #166534;">本期新进前十</div>
              </template>
              <div v-for="(item, idx) in newIn" :key="idx" style="display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid #dcfce7;">
                <span style="font-size: 12px;">
                  <span v-if="item.symbol" style="font-weight: 600; margin-right: 6px;">{{ item.symbol }}</span>
                  {{ item.name }}
                </span>
                <span style="font-size: 12px; color: #64748b;">{{ item.weight != null ? (item.weight * 100).toFixed(2) + '%' : '-' }}</span>
              </div>
            </n-card>
          </n-gi>
        </n-grid>
      </template>

      <n-empty v-else description="暂无持仓数据" style="padding: 40px;" />
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NCard, NTag, NIcon, NEmpty, NSpin, NButton, NDataTable, NGrid, NGi
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { PieChart } from 'lucide-vue-next'
import { getFundHoldingPeriods, getFundHoldings, getFundHoldingValuation, getFundPenetration } from '../api'
import { formatPercent, priceColor } from '../utils'

const route = useRoute()
const router = useRouter()

const fundCode = computed(() => (route.query.code as string) || '')
const fundName = computed(() => (route.query.name as string) || '')
const currentPeriod = ref('')

const loading = ref(false)
const error = ref('')
const periods = ref<any[]>([])
const holdings = ref<any[]>([])
const regionDistribution = ref<any[]>([])
const prevPeriod = ref('')
const exited = ref<any[]>([])
const newIn = ref<any[]>([])
const reportDate = ref('')
const valuation = ref<any>(null)
const penetrationData = ref<any>(null)
const penetrationReady = ref(false)

// [AI-2026-09-03] 地区列直接显示英文缩写（US/UK/HK…），与东哥口径一致
const regionLabel = (region: string) => region || '其他'

// 总权重
const totalWeight = computed(() => {
  return holdings.value.reduce((s: number, r: any) => s + (typeof r.weight === 'number' ? r.weight : 0), 0) * 100
})

// 穿透数据展示
const wtiPct = computed(() => {
  if (!penetrationData.value?.summary?.by_variety?.WTI) return 0
  return Number(penetrationData.value.summary.by_variety.WTI)
})
const brentPct = computed(() => {
  if (!penetrationData.value?.summary?.by_variety?.Brent) return 0
  return Number(penetrationData.value.summary.by_variety.Brent)
})
const penetratedPct = computed(() => {
  if (!penetrationData.value?.summary?.total_penetrated) return 0
  return Number(penetrationData.value.summary.total_penetrated)
})

// 跳转到穿透分析页
const goToPenetration = () => {
  if (!fundCode.value || !currentPeriod.value) return
  router.push({
    path: '/penetration',
    query: { fund_code: fundCode.value, period: currentPeriod.value }
  })
}

// [AI-2026-09-03] 持仓表合计行：前 6 列合并为"总权重"，权重列求和，市值列求和
const holdingSummary = (pageData: any[]) => {
  const w = pageData.reduce((s: number, r: any) => s + (typeof r.weight === 'number' ? r.weight : 0), 0)
  const mvVals = pageData.map((r: any) => r.market_value).filter((v: any) => typeof v === 'number')
  const mv = mvVals.length > 0 ? mvVals.reduce((a: number, b: number) => a + b, 0) : null
  return {
    display_order: { colSpan: 6, value: h('strong', '总权重') },
    market_value: { value: h('strong', mv != null ? Math.round(mv).toLocaleString() : '-') },
    weight: { value: h('strong', (w * 100).toFixed(2) + '%') },
  }
}

const holdingColumns: DataTableColumns<any> = [
  { title: '序号', key: 'display_order', width: 50, align: 'center' },
  { title: '代码', key: 'symbol', width: 80, align: 'center', render(row: any) {
    return h('span', { style: 'font-family: monospace; font-weight: 600;' }, row.symbol || '-')
  }},
  { title: '名称', key: 'name', ellipsis: { tooltip: true } },
  { title: '地区', key: 'region', width: 80, align: 'center', render(row: any) {
    return regionLabel(row.region)
  }},
  { title: '货币', key: 'currency', width: 60, align: 'center' },
  { title: '管理人', key: 'manager', ellipsis: { tooltip: true }, render(row: any) {
    return row.manager || '-'
  }},
  { title: '市值(元)', key: 'market_value', width: 140, align: 'right', render(row: any) {
    return row.market_value != null ? Math.round(row.market_value).toLocaleString() : '-'
  }},
  { title: '权重', key: 'weight', width: 90, align: 'right', render(row: any) {
    return h('span', { style: 'font-weight: 600;' }, row.weight != null ? (row.weight * 100).toFixed(2) + '%' : '-')
  }},
  { title: '相比上期变动', key: 'change', width: 110, align: 'right', render(row: any) {
    if (row.prev_weight == null) return '-'
    const delta = (row.weight || 0) - row.prev_weight
    const sign = delta >= 0 ? '+' : ''
    // 红涨绿跌（中国股市惯例）
    const color = delta >= 0 ? '#dc2626' : '#16a34a'
    return h('span', { style: `font-weight: 600; color: ${color};` }, `${sign}${(delta * 100).toFixed(2)}%`)
  }},
]

const loadPeriods = async () => {
  if (!fundCode.value) return
  try {
    const res = await getFundHoldingPeriods(fundCode.value)
    if (res.data?.status === 'ok') {
      periods.value = res.data.data || []
      // 默认选中最新一期；若 URL 已带 period 则优先
      const urlPeriod = route.query.period as string
      if (urlPeriod && periods.value.some((p: any) => p.period === urlPeriod)) {
        currentPeriod.value = urlPeriod
      } else if (periods.value.length > 0) {
        currentPeriod.value = periods.value[0].period
      }
    }
  } catch (e: any) {
    error.value = `获取报告期失败: ${e?.message || e}`
  }
}

const loadData = async () => {
  if (!fundCode.value || !currentPeriod.value) return
  loading.value = true
  error.value = ''
  try {
    const [holdingsRes, valuationRes, penetrationRes] = await Promise.all([
      getFundHoldings(fundCode.value, currentPeriod.value),
      getFundHoldingValuation(fundCode.value, currentPeriod.value),
      getFundPenetration(fundCode.value, currentPeriod.value),
    ])

    if (holdingsRes.data?.status === 'ok') {
      const d = holdingsRes.data.data || {}
      holdings.value = d.holdings || []
      regionDistribution.value = d.region_distribution || []
      prevPeriod.value = d.prev_period || ''
      exited.value = d.exited || []
      newIn.value = d.new_in || []
      reportDate.value = d.report_date || ''
    } else {
      error.value = holdingsRes.data?.message || '获取持仓失败'
    }

    if (valuationRes.data?.status === 'ok') {
      valuation.value = valuationRes.data.data || null
    }

    if (penetrationRes.data?.status === 'ok') {
      penetrationData.value = penetrationRes.data.data || null
    } else if (penetrationRes.data?.fund_code) {
      // 穿透API直接返回数据（无status包装）
      penetrationData.value = penetrationRes.data || null
    } else {
      penetrationData.value = null
    }
  } catch (e: any) {
    error.value = `加载失败: ${e?.message || e}`
  } finally {
    loading.value = false
  }
}

const switchPeriod = (period: string) => {
  currentPeriod.value = period
  router.replace({ query: { ...route.query, period } })
  loadData()
}

watch(fundCode, () => {
  loadPeriods().then(() => loadData())
})

watch(currentPeriod, () => {
  if (currentPeriod.value) loadData()
})

onMounted(() => {
  loadPeriods().then(() => loadData())
})
</script>

<style scoped>
.holding-analysis-page {
  padding: 12px;
  color: #1f2937;
}
.shadow-soft {
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  border-radius: 8px;
  border: 1px solid #e5edf7;
}
.stat-card {
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e5edf7;
}
</style>
