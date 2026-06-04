<template>
  <div class="analysis-page">
    <n-page-header @back="router.push('/')">
      <template #title>
        深度分析: {{ fundName }} ({{ fundCode }})
      </template>
      <template #extra>
        <n-space>
          <n-button @click="fetchHistory">刷新数据</n-button>
        </n-space>
      </template>
    </n-page-header>

    <n-grid :cols="24" :x-gap="12" :y-gap="12" style="margin-top: 16px">
      <!-- Chart Card -->
      <n-gi :span="24">
        <n-card :bordered="false" title="历史溢价率走势" class="chart-card">
          <v-chart class="chart" :option="chartOption" autoresize />
        </n-card>
      </n-gi>

      <!-- Stats Card -->
       <n-gi :span="8">
        <n-space vertical :size="12">
          <n-card :bordered="false" title="溢价统计 (最近30次)" size="small">
            <n-list small>
              <n-list-item>
                <n-text depth="3">最高溢价</n-text>
                <template #suffix>
                  <n-text type="error" strong>{{ maxPremium.toFixed(2) }}%</n-text>
                </template>
              </n-list-item>
              <n-list-item>
                <n-text depth="3">最低溢价</n-text>
                <template #suffix>
                  <n-text type="success" strong>{{ minPremium.toFixed(2) }}%</n-text>
                </template>
              </n-list-item>
              <n-list-item>
                <n-text depth="3">平均溢价</n-text>
                <template #suffix>
                  <n-text strong>{{ avgPremium.toFixed(2) }}%</n-text>
                </template>
              </n-list-item>
            </n-list>
          </n-card>

          <n-card :bordered="false" title="成分股拆解" size="small">
            <n-empty v-if="basketData.length === 0" description="暂无成分股数据" size="small" />
            <n-list v-else small>
              <n-list-item v-for="asset in basketData" :key="asset.underlying_symbol">
                <n-text strong>{{ asset.underlying_symbol }}</n-text>
                <template #suffix>
                  <n-text depth="3">{{ (asset.weight * 100).toFixed(2) }}%</n-text>
                </template>
              </n-list-item>
            </n-list>
          </n-card>
        </n-space>
      </n-gi>
      
      <n-gi :span="16">
        <n-card :bordered="false" title="历史详情数据" size="small">
           <n-table :single-line="false" size="small">
            <thead>
              <tr>
                <th>日期</th>
                <th>价格</th>
                <th>净值</th>
                <th>溢价率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in historyData.slice().reverse().slice(0, 10)" :key="item.date">
                <td>{{ item.date }}</td>
                <td>{{ item.price.toFixed(3) }}</td>
                <td>{{ item.nav.toFixed(3) }}</td>
                <td>
                  <n-text :type="item.premium > 0 ? 'error' : 'success'">
                    {{ (item.premium * 100).toFixed(2) }}%
                  </n-text>
                </td>
              </tr>
            </tbody>
          </n-table>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { 
  NPageHeader, NGrid, NGi, NCard, NSpace, NButton, 
  NList, NListItem, NText, NTable, NEmpty
} from 'naive-ui'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { 
  TitleComponent, 
  TooltipComponent, 
  GridComponent, 
  LegendComponent,
  DataZoomComponent
} from 'echarts/components'
import VChart from 'vue-echarts'
import axios from 'axios'

// Register ECharts components
use([
  CanvasRenderer,
  LineChart,
  TitleComponent,
  TooltipComponent,
  GridComponent,
  LegendComponent,
  DataZoomComponent
])

const route = useRoute()
const router = useRouter()
const fundCode = computed(() => route.query.code as string)
const fundName = computed(() => route.query.name as string)

interface HistoryItem {
  date: string
  price: number
  nav: number
  premium: number
}

interface BasketItem {
  underlying_symbol: string
  weight: number
  date: string
}

const historyData = ref<HistoryItem[]>([])
const basketData = ref<BasketItem[]>([])
const loading = ref(false)

const fetchHistory = async () => {
  if (!fundCode.value) return
  loading.value = true
  try {
    const res = await axios.get(`/api/fund/${fundCode.value}/history`)
    if (res.data.status === 'ok') {
      historyData.value = res.data.data
    }
  } catch (err) {
    console.error('Failed to fetch history', err)
  } finally {
    loading.value = false
  }
}

const fetchBasket = async () => {
  if (!fundCode.value) return
  try {
    const res = await axios.get(`/api/fund/${fundCode.value}/basket`)
    if (res.data.status === 'ok') {
      basketData.value = res.data.data
    }
  } catch (err) {
    console.error('Failed to fetch basket', err)
  }
}

const chartOption = computed(() => {
  const dates = historyData.value.map(item => item.date)
  const premiums = historyData.value.map(item => (item.premium * 100).toFixed(2))
  const prices = historyData.value.map(item => item.price.toFixed(3))

  return {
    tooltip: {
      trigger: 'axis',
      formatter: (params: any) => {
        let res = `${params[0].name}<br/>`
        params.forEach((p: any) => {
          res += `${p.marker} ${p.seriesName}: ${p.value}${p.seriesName === '溢价率' ? '%' : ''}<br/>`
        })
        return res
      }
    },
    legend: {
      data: ['溢价率', '价格']
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates
    },
    yAxis: [
      {
        type: 'value',
        name: '溢价率 (%)',
        position: 'left',
        splitLine: { show: false }
      },
      {
        type: 'value',
        name: '价格',
        position: 'right',
        splitLine: { show: true }
      }
    ],
    dataZoom: [
      { type: 'inside', start: 0, end: 100 },
      { type: 'slider', start: 0, end: 100 }
    ],
    series: [
      {
        name: '溢价率',
        type: 'line',
        data: premiums,
        smooth: true,
        itemStyle: { color: '#ef4444' },
        areaStyle: {
          opacity: 0.1,
          color: '#ef4444'
        }
      },
      {
        name: '价格',
        type: 'line',
        yAxisIndex: 1,
        data: prices,
        smooth: true,
        itemStyle: { color: '#3b82f6' }
      }
    ]
  }
})

const maxPremium = computed(() => Math.max(...historyData.value.map(i => i.premium * 100), 0))
const minPremium = computed(() => Math.min(...historyData.value.map(i => i.premium * 100), 0))
const avgPremium = computed(() => {
  if (historyData.value.length === 0) return 0
  const sum = historyData.value.reduce((acc, i) => acc + i.premium * 100, 0)
  return sum / historyData.value.length
})

onMounted(() => {
  fetchHistory()
  fetchBasket()
})
</script>

<style scoped>
.chart {
  height: 400px;
}
.chart-card {
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}
.analysis-page {
  padding: 12px;
}
</style>
