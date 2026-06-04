<template>
  <div class="dashboard">
    <n-grid :cols="24" :x-gap="12" :y-gap="12">
      <!-- Top Stats -->
      <n-gi :span="6">
        <n-card title="美元/人民币" size="small" :bordered="false" class="stat-card">
          <n-statistic :value="marketOverview.rates?.usd_cny_mid || 0" :precision="4">
            <template #prefix>
              <n-icon><RefreshCw /></n-icon>
            </template>
            <template #suffix>
              <n-text :type="marketOverview.usd_change >= 0 ? 'success' : 'error'" style="font-size: 14px">
                {{ marketOverview.usd_change >= 0 ? '+' : '' }}{{ (marketOverview.usd_change * 100).toFixed(2) }}%
              </n-text>
            </template>
          </n-statistic>
        </n-card>
      </n-gi>
      <n-gi :span="6">
        <n-card title="港币/人民币" size="small" :bordered="false" class="stat-card">
          <n-statistic :value="marketOverview.rates?.hkd_cny_mid || 0" :precision="4">
             <template #suffix>
              <n-text depth="3" style="font-size: 14px">中间价</n-text>
            </template>
          </n-statistic>
        </n-card>
      </n-gi>
      <n-gi :span="6">
        <n-card title="监控品种" size="small" :bordered="false" class="stat-card">
          <n-statistic :value="marketOverview.stats?.fund_count || 0">
            <template #suffix>个</template>
          </n-statistic>
        </n-card>
      </n-gi>
      <n-gi :span="6">
        <n-card title="系统健康度" size="small" :bordered="false" class="stat-card">
          <n-progress type="line" :percentage="marketOverview.stats?.system_health || 0" :status="(marketOverview.stats?.system_health || 0) > 90 ? 'success' : 'warning'" processing />
        </n-card>
      </n-gi>

      <!-- Main Table -->
      <n-gi :span="24">
        <n-card :bordered="false" title="实时套利监控 (LOF + JSL 聚合)" class="main-card">
          <template #header-extra>
            <n-space>
              <n-button-group size="small">
                <n-button type="warning" ghost @click="triggerTask('011')">
                  <template #icon><n-icon><Zap /></n-icon></template>
                  更新因子
                </n-button>
                <n-button type="info" ghost @click="triggerTask('012')">
                  <template #icon><n-icon><Zap /></n-icon></template>
                  重新估值
                </n-button>
              </n-button-group>
              <n-divider vertical />
              <n-radio-group v-model:value="premiumFilter" name="premium-filter" size="small">
                <n-radio-button value="all">全部</n-radio-button>
                <n-radio-button value="discount">折价</n-radio-button>
                <n-radio-button value="premium">溢价</n-radio-button>
              </n-radio-group>
              <n-input v-model:value="searchKeyword" placeholder="搜索代码/名称..." style="width: 200px" />
              <n-button type="primary" secondary @click="fetchData">
                <template #icon><n-icon><RefreshCw /></n-icon></template>
                立即刷新
              </n-button>
            </n-space>
          </template>
          <n-data-table
            :columns="columns"
            :data="filteredTableData"
            :loading="loading"
            :pagination="pagination"
            :max-height="600"
            virtual-scroll
          />
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, h, computed } from 'vue'
import { useRouter } from 'vue-router'
import { 
  NGrid, 
  NGi, 
  NCard, 
  NStatistic, 
  NIcon, 
  NText, 
  NProgress, 
  NSpace, 
  NInput, 
  NButton, 
  NDataTable,
  NTag,
  NRadioGroup,
  NRadioButton,
  useMessage,
  NButtonGroup,
  NDivider
} from 'naive-ui'
import type { DataTableColumns } from 'naive-ui'
import { RefreshCw, ChartBar, Zap } from 'lucide-vue-next'
import axios from 'axios'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const tableData = ref<any[]>([])
const searchKeyword = ref('')
const premiumFilter = ref('all')
const marketOverview = ref({
  rates: { usd_cny_mid: 0, hkd_cny_mid: 0 } as any,
  usd_change: 0,
  stats: { fund_count: 0, system_health: 0 } as any
})

const triggerTask = async (task: string) => {
  try {
    const res = await axios.post(`/api/system/trigger/${task}`)
    if (res.data.status === 'ok') {
      message.success(res.data.message)
    }
  } catch (err) {
    message.error('任务启动失败')
  }
}

const filteredTableData = computed(() => {
  let data = tableData.value || []
  
  // Keyword filter
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    data = data.filter((item: any) => 
      (item.fund_code || '').toLowerCase().includes(kw) || 
      (item.fund_name || '').toLowerCase().includes(kw)
    )
  }
  
  // Premium filter
  if (premiumFilter.value === 'discount') {
    data = data.filter((item: any) => (item.premium || 0) < 0)
  } else if (premiumFilter.value === 'premium') {
    data = data.filter((item: any) => (item.premium || 0) > 0)
  }
  
  return data
})

const pagination = {
  pageSize: 20
}

const columns: DataTableColumns<any> = [
  {
    title: '代码',
    key: 'fund_code',
    width: 100,
    render(row: any) {
      return h(NText, { code: true }, { default: () => row.fund_code || '-' })
    }
  },
  {
    title: '基金名称',
    key: 'fund_name',
    width: 180,
    ellipsis: { tooltip: true }
  },
  {
    title: '价格',
    key: 'price',
    sorter: 'default',
    render(row: any) {
      const price = row.price || 0
      return h(NText, { type: 'info', strong: true }, { default: () => price.toFixed(3) })
    }
  },
  {
    title: '估值/净值',
    key: 'nav',
    render(row: any) {
      const nav = row.nav || 0
      return nav.toFixed(3)
    }
  },
  {
    title: '溢价率',
    key: 'premium',
    sorter: (a: any, b: any) => (a.premium || 0) - (b.premium || 0),
    render(row: any) {
      const premium = row.premium || 0
      const type = premium > 0 ? 'error' : 'success'
      return h(NTag, { type, size: 'small', bordered: false }, { default: () => (premium * 100).toFixed(2) + '%' })
    }
  },
  {
    title: '校准因子',
    key: 'calibration',
    render(row: any) {
      const cal = row.calibration || 0
      return h(NText, { depth: 3 }, { default: () => cal.toFixed(4) })
    }
  },
  {
    title: '申购状态',
    key: 'purchase_status',
    render(row: any) {
      const status = row.purchase_status || '未知'
      const isOk = status.includes('开放')
      return h(NTag, { type: isOk ? 'success' : 'warning', size: 'small', round: true }, { default: () => status })
    }
  },
  {
    title: '操作',
    key: 'actions',
    width: 100,
    render(row: any) {
      return h(
        NButton,
        {
          size: 'small',
          type: 'primary',
          quaternary: true,
          onClick: () => router.push({ name: 'Analysis', query: { code: row.fund_code, name: row.fund_name } })
        },
        { 
          icon: () => h(NIcon, null, { default: () => h(ChartBar) }),
          default: () => '分析' 
        }
      )
    }
  }
]

const fetchData = async () => {
  loading.value = true
  try {
    const [dashRes, marketRes] = await Promise.all([
      axios.get('/api/dashboard'),
      axios.get('/api/market/overview')
    ])
    
    if (dashRes.data && dashRes.data.status === 'ok') {
      tableData.value = dashRes.data.data || []
    }
    if (marketRes.data && marketRes.data.status === 'ok') {
      marketOverview.value = marketRes.data.data || marketOverview.value
    }
  } catch (err) {
    console.error('Failed to fetch data', err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchData()
  // Auto refresh every 30s
  setInterval(fetchData, 30000)
})
</script>

<style scoped>
.stat-card {
  background: #fff;
  border-radius: 12px;
  transition: transform 0.3s ease;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}
.stat-card:hover {
  transform: translateY(-4px);
}
.main-card {
  border-radius: 12px;
  background-color: #fff;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}
</style>
