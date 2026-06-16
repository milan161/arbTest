<template>
  <div class="ledger-page p-6">
    <!-- 顶部：账本标题 + 按钮 -->
    <n-card class="shadow-soft header-card mb-4">
      <div class="flex-between">
        <div class="flex-center gap-4">
          <n-icon size="32" color="#16a34a"><BookOpen /></n-icon>
          <div>
            <div class="header-title">套利账本</div>
            <div class="header-subtitle">A股折价买入 + 美股做空对冲，每笔套利完整记录</div>
          </div>
        </div>
        <n-space>
          <n-button type="primary" @click="openAddModal">
            <template #icon><n-icon><Plus /></n-icon></template>
            交易记录
          </n-button>
          <n-button secondary type="warning" @click="showFeeModal = true">
            <template #icon><n-icon><Settings /></n-icon></template>
            赎回费率
          </n-button>
          <n-button secondary @click="clearTestData" :loading="clearingData">
            <template #icon><n-icon><Trash2 /></n-icon></template>
            清除测试数据
          </n-button>
          <n-button secondary @click="fetchPairs">
            <template #icon><n-icon><RefreshCw /></n-icon></template>
            刷新
          </n-button>
        </n-space>
      </div>
    </n-card>

    <!-- 统计概览条 -->
    <n-card class="shadow-soft mb-4">
      <n-grid :cols="24" :x-gap="12">
        <n-gi :span="6">
          <div class="stat-card">
            <div class="stat-label">活跃套利</div>
            <div class="stat-value">{{ activePairs.length }}</div>
          </div>
        </n-gi>
        <n-gi :span="6">
          <div class="stat-card">
            <div class="stat-label">已结项</div>
            <div class="stat-value">{{ closedPairs.length }}</div>
          </div>
        </n-gi>
        <n-gi :span="6">
          <div class="stat-card">
            <div class="stat-label">总盈亏(RMB)</div>
            <div class="stat-value" :class="totalPnl >= 0 ? 'text-green' : 'text-red'">{{ totalPnl.toFixed(2) }}</div>
          </div>
        </n-gi>
        <n-gi :span="6">
          <div class="stat-card">
            <div class="stat-label">总盈亏(USD)</div>
            <div class="stat-value" :class="totalUsd >= 0 ? 'text-green' : 'text-red'">{{ totalUsd.toFixed(2) }}</div>
          </div>
        </n-gi>
      </n-grid>
    </n-card>

    <!-- 主表格：套利对列表 -->
    <n-card :bordered="false" class="shadow-soft">
      <n-tabs type="line" animated>
        <n-tab-pane name="active" tab="活跃持仓">
          <n-data-table
            :columns="pairColumns"
            :data="activePairs"
            size="small"
            bordered
            :row-class-name="pnlRowClass"
            :max-height="600"
            :scroll-x="1400"
          />
        </n-tab-pane>
        <n-tab-pane name="closed" tab="已结项">
          <n-data-table
            :columns="pairColumns"
            :data="closedPairs"
            size="small"
            bordered
            :max-height="600"
            :scroll-x="1400"
          />
        </n-tab-pane>
      </n-tabs>
    </n-card>

    <!-- 录入/编辑 弹窗 -->
    <n-modal v-model:show="showAddModal" preset="card" :title="isEditing ? '编辑套利对' : '新增交易记录'" style="width: 960px; max-width: 98vw;">
      <n-form :model="form" label-placement="top" label-width="auto">
        <!-- 基金信息 -->
        <n-grid :cols="4" :x-gap="12">
          <n-gi>
            <n-form-item label="基金代码" required>
              <n-select v-model:value="form.fund_code" filterable tag :options="fundSelectOptions" placeholder="162411" @update:value="onFundChange" />
            </n-form-item>
          </n-gi>
          <n-gi :span="1">
            <n-form-item label="券商">
              <n-select v-model:value="form.broker_name" filterable tag :options="brokerOptions" placeholder="选择券商" @update:value="onBrokerChange" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="状态">
              <n-select v-model:value="form.status" :options="[{label:'持仓中',value:'ACTIVE'},{label:'已结项',value:'CLOSED'}]" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-divider title-placement="left">A股 买入/赎回</n-divider>
        <n-grid :cols="6" :x-gap="12">
          <n-gi :span="2">
            <n-form-item label="买入日期">
              <n-date-picker v-model:value="form.buy_ts" type="date" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买入单价">
              <n-input-number v-model:value="form.buy_price" :precision="4" :step="0.001" style="width:100%" placeholder="0.0000" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买入数量">
              <n-input-number v-model:value="form.buy_volume" :step="1000" style="width:100%" placeholder="份数" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买入金额(RMB)">
              <n-input-number v-model:value="form.buy_amount" :precision="2" style="width:100%" placeholder="自动计算" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="账号">
              <n-input v-model:value="form.buy_account" placeholder="5379" style="width:100%" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-grid :cols="6" :x-gap="12">
          <n-gi>
            <n-form-item label="平仓方式">
              <n-select v-model:value="form.close_type" :options="[
                {label:'基金赎回', value:'REDEEM'},
                {label:'市场卖出', value:'SELL'}
              ]" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="form.close_type === 'REDEEM' ? '赎回日期' : '卖出日期'">
              <n-date-picker v-model:value="form.sell_ts" type="date" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="form.close_type === 'REDEEM' ? '赎回单价' : '卖出单价'">
              <n-input-number v-model:value="form.sell_price" :precision="4" :step="0.001" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item :label="form.close_type === 'REDEEM' ? '赎回金额(RMB)' : '卖出金额(RMB)'">
              <n-input-number v-model:value="form.sell_amount" :precision="2" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="佣金/赎回费">
              <n-input-number v-model:value="form.redemption_fee" :precision="2" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买入备注">
              <n-input v-model:value="form.buy_notes" placeholder="新开仓0.8%+，XOP" />
            </n-form-item>
          </n-gi>
        </n-grid>
        <n-tag v-if="autoFeeRate > 0" type="info" size="small" style="margin-top:4px">
          当前{{ form.broker_name }}下 {{ form.fund_code }} 赎回费率: {{ autoFeeRate }}%
          （自动关联）
        </n-tag>

        <n-divider title-placement="left">美股 做空/买平 (IB)</n-divider>
        <n-grid :cols="6" :x-gap="12">
          <n-gi>
            <n-form-item label="对冲标的">
              <n-input v-model:value="form.hedge_symbol" placeholder="XOP / GLD" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="做空日期">
              <n-date-picker v-model:value="form.short_ts" type="date" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="做空价格($)">
              <n-input-number v-model:value="form.short_price" :precision="2" :step="0.01" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="做空数量">
              <n-input-number v-model:value="form.short_volume" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="做空金额(USD)">
              <n-input-number v-model:value="form.short_amount" :precision="2" style="width:100%" placeholder="自动计算" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <n-grid :cols="6" :x-gap="12">
          <n-gi>
            <n-form-item label="买平日期">
              <n-date-picker v-model:value="form.cover_ts" type="date" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买平价格($)">
              <n-input-number v-model:value="form.cover_price" :precision="2" :step="0.01" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="买平金额(USD)">
              <n-input-number v-model:value="form.cover_amount" :precision="2" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi>
            <n-form-item label="佣金(USD)">
              <n-input-number v-model:value="form.us_commission" :precision="2" style="width:100%" />
            </n-form-item>
          </n-gi>
          <n-gi :span="2">
            <n-form-item label="备注">
              <n-input v-model:value="form.notes" placeholder="已挂单 / 已成交" />
            </n-form-item>
          </n-gi>
        </n-grid>

        <div class="flex-between mt-4">
          <div>
            <n-tag type="info" v-if="computedPnlRmb !== null">
              A股盈亏: {{ computedAPnl.toFixed(2) }} &nbsp;|&nbsp; 美股盈亏: {{ computedUPnl.toFixed(2) }} USD
              &nbsp;|&nbsp; <strong>总盈亏: {{ computedPnlRmb.toFixed(2) }} RMB</strong>
            </n-tag>
          </div>
          <n-space>
            <n-button @click="showAddModal = false">取消</n-button>
            <n-button type="primary" @click="handleSubmit">{{ isEditing ? '保存修改' : '记录交易' }}</n-button>
          </n-space>
        </div>
      </n-form>
    </n-modal>

    <!-- 费率配置弹窗 -->
    <n-modal v-model:show="showFeeModal" preset="card" title="券商赎回费率设置" style="width: 800px; max-width: 95vw;">
      <div class="flex flex-col gap-6">
        <n-card size="small" class="bg-gray-50 dark:bg-gray-800/50">
          <n-grid :cols="24" :x-gap="12">
            <n-gi :span="4">
              <n-form-item label="类别" :show-feedback="false">
                <n-select v-model:value="newFee.category" filterable tag :options="categoryOptions" @update:value="onCategoryChange" />
              </n-form-item>
            </n-gi>
            <n-gi :span="9">
              <n-form-item label="基金代码" :show-feedback="false">
                <n-select v-model:value="newFee.fund_code" filterable tag :options="fundCodeOptions" />
              </n-form-item>
            </n-gi>
            <n-gi :span="5">
              <n-form-item label="券商" :show-feedback="false">
                <n-select v-model:value="newFee.broker_name" filterable tag :options="brokerOptions" />
              </n-form-item>
            </n-gi>
            <n-gi :span="6">
              <n-form-item label="赎回费率(%)" :show-feedback="false">
                <n-select v-model:value="newFee.fee_rate" filterable tag :options="feeRateOptions" />
              </n-form-item>
              <div class="flex justify-end mt-8">
                <n-button type="primary" size="medium" @click="submitFee" :loading="savingFee">添加</n-button>
              </div>
            </n-gi>
          </n-grid>
        </n-card>
        <n-data-table :columns="feeColumns" :data="fees" :loading="loadingFees" :bordered="false" size="small" />
      </div>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, h } from 'vue'
import {
  NCard, NGrid, NGi, NTag, NButton, NDataTable, NIcon,
  useMessage, NSpace, NText, NTabs, NTabPane, NModal, NForm, NFormItem,
  NInput, NInputNumber, NDatePicker, NDivider, NSelect
} from 'naive-ui'
import { BookOpen, Plus, RefreshCw, Settings, Trash2, Edit3, DollarSign, TrendingUp, TrendingDown } from 'lucide-vue-next'
import {
  getPairs, addPair, updatePair, deletePair, clearFakeData,
  getBrokerFees, addBrokerFee, deleteBrokerFee
} from '../api'
import { getFeeRate } from '../api/ledgerApi'
import client from '../api/client'

const message = useMessage()
const allPairs = ref<any[]>([])
const showAddModal = ref(false)
const showFeeModal = ref(false)
const clearingData = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)
const loading = ref(false)

// ===== Computed =====
const activePairs = computed(() => allPairs.value.filter(p => p.status === 'ACTIVE'))
const closedPairs = computed(() => allPairs.value.filter(p => p.status === 'CLOSED'))

const totalPnl = computed(() => {
  return allPairs.value.reduce((s, p) => s + (p.pnl_rmb || 0), 0)
})
const totalUsd = computed(() => {
  return allPairs.value.reduce((s, p) => s + (p.pnl_usd || 0), 0)
})

// ===== Fund options for select =====
const fundList = [
  { code: '162411', name: '华宝油气' }, { code: '161125', name: '标普500' },
  { code: '161130', name: '纳斯达克' }, { code: '161126', name: '标普医疗' },
  { code: '161127', name: '标普生物' }, { code: '161128', name: '标普科技' },
  { code: '164701', name: '汇添富黄金' }, { code: '160719', name: '嘉实原油' },
  { code: '161129', name: '易方达原油' }, { code: '501018', name: '南方原油' },
  { code: '164824', name: '印度基金' }, { code: '165513', name: '信诚四国' },
  { code: '160723', name: '嘉实原油' }, { code: '161815', name: '银华通胀' },
  { code: '160216', name: '国泰商品' }, { code: '161116', name: '白银基金' },
]
const fundSelectOptions = computed(() =>
  fundList.map(f => ({ label: `${f.code} ${f.name}`, value: f.code }))
)

// ===== Form =====
const defaultForm = () => ({
  fund_code: '162411',
  fund_name: '华宝油气',
  broker_name: '银河',
  close_type: 'REDEEM',
  status: 'ACTIVE',
  buy_ts: Date.now(),
  buy_price: 0,
  buy_volume: 0,
  buy_amount: 0,
  buy_account: '',
  sell_ts: null as number | null,
  sell_price: 0,
  sell_amount: 0,
  redemption_fee: 0,
  hedge_symbol: 'XOP',
  short_ts: null as number | null,
  short_price: 0,
  short_volume: 0,
  short_amount: 0,
  cover_ts: null as number | null,
  cover_price: 0,
  cover_amount: 0,
  us_commission: 0,
  buy_notes: '',
  sell_notes: '',
  notes: ''
})
const form = ref(defaultForm())

const onFundChange = async (val: string) => {
  const found = fundList.find(f => f.code === val)
  if (found) form.value.fund_name = found.name
  // 自动填入昨日收盘价
  try {
    const res = await client.get(`/api/market/prev-close/${val}`)
    if (res.data?.status === 'ok' && res.data.price > 0) {
      form.value.buy_price = res.data.price
    }
  } catch {}
  // 自动关联赎回费率
  refreshFeeRate()
}

const onBrokerChange = () => {
  refreshFeeRate()
}

const refreshFeeRate = async () => {
  if (!form.value.fund_code || !form.value.broker_name) return
  try {
    const res = await getFeeRate(form.value.fund_code, form.value.broker_name)
    if (res.data?.status === 'ok' && res.data.rate > 0) {
      autoFeeRate.value = res.data.rate
      if (form.value.close_type === 'REDEEM' && form.value.sell_amount > 0) {
        form.value.redemption_fee = +(form.value.sell_amount * res.data.rate / 100).toFixed(2)
      }
    }
  } catch {}
}

const autoFeeRate = ref(0)

const computedAPnl = computed(() => {
  const buyAmt = form.value.buy_amount || 0
  const sellAmt = form.value.sell_amount || 0
  const fee = form.value.redemption_fee || 0
  if (!buyAmt && !sellAmt) return 0
  return sellAmt - buyAmt - fee
})
const computedUPnl = computed(() => {
  const shortAmt = form.value.short_amount || 0
  const coverAmt = form.value.cover_amount || 0
  const comm = form.value.us_commission || 0
  if (!shortAmt && !coverAmt) return 0
  return (coverAmt - shortAmt) - comm
})
const computedPnlRmb = computed(() => {
  if (!computedAPnl.value && !computedUPnl.value) return null
  return computedAPnl.value + computedUPnl.value * 7.2
})

// 自动计算买入/卖出金额
const safeComputed = (a: number, b: number) => {
  if (a > 0 && b > 0) return +(a * b).toFixed(2)
  return 0
}

// 自动计算金额（当价格或数量变化时）
import { watch } from 'vue'

watch(() => [form.value.buy_price, form.value.buy_volume], () => {
  if (form.value.buy_price > 0 && form.value.buy_volume > 0) {
    form.value.buy_amount = +(form.value.buy_price * form.value.buy_volume).toFixed(2)
  }
})
watch(() => [form.value.sell_price, form.value.buy_volume], () => {
  if (form.value.sell_price > 0 && form.value.buy_volume > 0) {
    form.value.sell_amount = +(form.value.sell_price * form.value.buy_volume).toFixed(2)
  }
})
watch(() => [form.value.short_price, form.value.short_volume], () => {
  if (form.value.short_price > 0 && form.value.short_volume > 0) {
    form.value.short_amount = +(form.value.short_price * form.value.short_volume).toFixed(2)
  }
})
watch(() => [form.value.cover_price, form.value.short_volume], () => {
  if (form.value.cover_price > 0 && form.value.short_volume > 0) {
    form.value.cover_amount = +(form.value.cover_price * form.value.short_volume).toFixed(2)
  }
})
// 当卖出金额变化时自动计算赎回费
watch(() => [form.value.sell_amount, form.value.close_type, autoFeeRate.value], () => {
  if (form.value.close_type === 'REDEEM' && form.value.sell_amount > 0 && autoFeeRate.value > 0) {
    form.value.redemption_fee = +(form.value.sell_amount * autoFeeRate.value / 100).toFixed(2)
  }
})

// ===== API =====
const fetchPairs = async () => {
  loading.value = true
  try {
    const res = await getPairs()
    if (res.data?.status === 'ok') allPairs.value = res.data.data || []
  } catch (e) { message.error('获取账本失败') }
  finally { loading.value = false }
}

const openAddModal = (pair?: any) => {
  if (pair) {
    isEditing.value = true
    editingId.value = pair.id
    form.value = {
      fund_code: pair.fund_code || '162411',
      fund_name: pair.fund_name || '',
      broker_name: pair.broker_name || '',
      close_type: pair.close_type || 'REDEEM',
      status: pair.status || 'ACTIVE',
      buy_ts: pair.buy_date ? new Date(pair.buy_date).getTime() : Date.now(),
      buy_price: pair.buy_price || 0,
      buy_volume: pair.buy_volume || 0,
      buy_amount: pair.buy_amount || 0,
      buy_account: pair.buy_account || '',
      sell_ts: pair.sell_date ? new Date(pair.sell_date).getTime() : null,
      sell_price: pair.sell_price || 0,
      sell_amount: pair.sell_amount || 0,
      redemption_fee: pair.redemption_fee || 0,
      hedge_symbol: pair.hedge_symbol || 'XOP',
      short_ts: pair.short_date ? new Date(pair.short_date).getTime() : null,
      short_price: pair.short_price || 0,
      short_volume: pair.short_volume || 0,
      short_amount: pair.short_amount || 0,
      cover_ts: pair.cover_date ? new Date(pair.cover_date).getTime() : null,
      cover_price: pair.cover_price || 0,
      cover_amount: pair.cover_amount || 0,
      us_commission: pair.us_commission || 0,
      buy_notes: pair.buy_notes || '',
      sell_notes: pair.sell_notes || '',
      notes: pair.notes || ''
    }
  } else {
    isEditing.value = false
    editingId.value = null
    form.value = defaultForm()
  }
  showAddModal.value = true
}

const handleSubmit = async () => {
  const f = form.value
  const buyAmt = f.buy_amount || safeComputed(f.buy_price, f.buy_volume)
  const shortAmt = f.short_amount || safeComputed(f.short_price, f.short_volume)
  const payload: Record<string, any> = {
    fund_code: f.fund_code,
    fund_name: f.fund_name,
    broker_name: f.broker_name,
    close_type: f.close_type,
    status: f.status,
    buy_date: f.buy_ts ? new Date(f.buy_ts).toISOString().split('T')[0] : undefined,
    buy_price: f.buy_price || 0,
    buy_volume: f.buy_volume || 0,
    buy_amount: buyAmt,
    buy_account: f.buy_account,
    sell_date: f.sell_ts ? new Date(f.sell_ts).toISOString().split('T')[0] : undefined,
    sell_price: f.sell_price || 0,
    sell_amount: f.sell_amount || 0,
    redemption_fee: f.redemption_fee || 0,
    hedge_symbol: f.hedge_symbol,
    short_date: f.short_ts ? new Date(f.short_ts).toISOString().split('T')[0] : undefined,
    short_price: f.short_price || 0,
    short_volume: f.short_volume || 0,
    short_amount: shortAmt,
    cover_date: f.cover_ts ? new Date(f.cover_ts).toISOString().split('T')[0] : undefined,
    cover_price: f.cover_price || 0,
    cover_amount: f.cover_amount || 0,
    us_commission: f.us_commission || 0,
    buy_notes: f.buy_notes,
    sell_notes: f.sell_notes,
    notes: f.notes
  }
  try {
    if (isEditing.value && editingId.value) {
      await updatePair(editingId.value, payload)
      message.success('已更新')
    } else {
      await addPair(payload)
      message.success('记录成功')
    }
    showAddModal.value = false
    fetchPairs()
  } catch (e) {
    message.error('保存失败')
  }
}

const handleDelete = async (id: number) => {
  try {
    await deletePair(id)
    message.success('已删除')
    fetchPairs()
  } catch (e) { message.error('删除失败') }
}

const handleClose = async (id: number) => {
  try {
    await updatePair(id, { status: 'CLOSED' })
    message.success('已标记结项')
    fetchPairs()
  } catch (e) { message.error('操作失败') }
}

const clearTestData = async () => {
  clearingData.value = true
  try {
    const res = await clearFakeData()
    if (res.data?.status === 'ok') message.success(res.data.message)
    fetchPairs()
  } catch (e) { message.error('清除失败') }
  finally { clearingData.value = false }
}

// ===== Table columns =====
const pnlRowClass = (row: any) => {
  if (!row.pnl_rmb) return ''
  return row.pnl_rmb >= 0 ? 'row-profit' : 'row-loss'
}

const fmt = (v: any, d: number = 2) => v !== null && v !== undefined && v !== 0 ? Number(v).toFixed(d) : '-'
const shortDate = (d: string) => d ? d.substring(5) : '-'

const pairColumns = [
  { title: '基金', key: 'fund', width: 130, fixed: 'left' as const,
    render: (r: any) => {
      const found = fundList.find(f => f.code === r.fund_code)
      const label = found ? `${found.code} ${found.name}` : r.fund_code
      return h(NText, { strong: true }, { default: () => label })
    }
  },
  // A股买入
  { title: '买入日', key: 'buy_date', width: 70, align: 'center' as const,
    render: (r: any) => r.buy_date ? shortDate(r.buy_date) : '-' },
  { title: '买入价', key: 'buy_price', width: 70, align: 'center' as const,
    render: (r: any) => fmt(r.buy_price, 3) },
  { title: '数量', key: 'buy_volume', width: 70, align: 'center' as const,
    render: (r: any) => r.buy_volume ? Number(r.buy_volume).toLocaleString() : '-' },
  { title: '金额(RMB)', key: 'buy_amount', width: 100, align: 'right' as const,
    render: (r: any) => h(NText, { style: r.buy_amount ? 'color:#e53e3e' : '' }, { default: () => fmt(r.buy_amount) }) },
  // A股卖出
  { title: '卖出日', key: 'sell_date', width: 70, align: 'center' as const,
    render: (r: any) => r.sell_date ? shortDate(r.sell_date) : '-' },
  { title: '卖出价', key: 'sell_price', width: 70, align: 'center' as const,
    render: (r: any) => fmt(r.sell_price, 3) },
  { title: '金额(RMB)', key: 'sell_amount', width: 100, align: 'right' as const,
    render: (r: any) => h(NText, { style: r.sell_amount ? 'color:#16a34a' : '' }, { default: () => fmt(r.sell_amount) }) },
  // 美股做空
  { title: '对冲', key: 'hedge', width: 60, align: 'center' as const,
    render: (r: any) => r.hedge_symbol || '-' },
  { title: '空单价', key: 'short_price', width: 70, align: 'center' as const,
    render: (r: any) => r.short_price ? `$${fmt(r.short_price)}` : '-' },
  { title: '空单量', key: 'short_volume', width: 70, align: 'center' as const,
    render: (r: any) => r.short_volume || '-' },
  { title: '空金额(USD)', key: 'short_amount', width: 100, align: 'right' as const,
    render: (r: any) => fmt(r.short_amount) },
  // 美股买平
  { title: '买平日', key: 'cover_date', width: 70, align: 'center' as const,
    render: (r: any) => r.cover_date ? shortDate(r.cover_date) : '-' },
  { title: '买平价', key: 'cover_price', width: 70, align: 'center' as const,
    render: (r: any) => r.cover_price ? `$${fmt(r.cover_price)}` : '-' },
  { title: '金额(USD)', key: 'cover_amount', width: 100, align: 'right' as const,
    render: (r: any) => fmt(r.cover_amount) },
  // 盈亏汇总
  { title: 'A股盈亏', key: 'a_share_pnl', width: 100, align: 'right' as const,
    render: (r: any) => {
      if (r.a_share_pnl === null || r.a_share_pnl === undefined) return '-'
      return h(NText, { type: r.a_share_pnl >= 0 ? 'success' : 'error', strong: true },
        { default: () => fmt(r.a_share_pnl) })
    }
  },
  { title: 'USD盈亏', key: 'pnl_usd', width: 100, align: 'right' as const,
    render: (r: any) => {
      if (r.pnl_usd === null || r.pnl_usd === undefined) return '-'
      return h(NText, { type: r.pnl_usd >= 0 ? 'success' : 'error', strong: true },
        { default: () => fmt(r.pnl_usd) })
    }
  },
  { title: '总盈亏(RMB)', key: 'pnl_rmb', width: 120, align: 'right' as const, fixed: 'right' as const,
    render: (r: any) => {
      if (r.pnl_rmb === null || r.pnl_rmb === undefined) return '-'
      const color = r.pnl_rmb >= 0 ? '#16a34a' : '#e53e3e'
      return h('div', { style: `font-weight:700;color:${color}` }, [
        r.pnl_rmb >= 0 ? '+' : '',
        Number(r.pnl_rmb).toFixed(2)
      ])
    }
  },
  {
    title: '操作', key: 'ops', width: 140, align: 'center' as const, fixed: 'right' as const,
    render: (r: any) => h(NSpace, { size: 'small', justify: 'center' }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openAddModal(r) },
          { default: () => '编辑', icon: () => h(NIcon, null, { default: () => h(Edit3) }) }),
        r.status === 'ACTIVE'
          ? h(NButton, { size: 'tiny', secondary: true, type: 'success', onClick: () => handleClose(r.id) },
            { default: () => '结项' })
          : null,
        h(NButton, { size: 'tiny', quaternary: true, type: 'error', onClick: () => handleDelete(r.id) },
          { default: () => '删除' })
      ]
    })
  }
]

// ===== Fee management =====
const newFee = ref({ category: '黄金原油', fund_code: '164701', broker_name: '银河', fee_rate: '0.3316' })
const loadingFees = ref(false)
const savingFee = ref(false)
const fees = ref<any[]>([])

const categoryOptions = [
  { label: '黄金原油', value: '黄金原油' }, { label: 'QDII欧美', value: 'QDII欧美' },
  { label: 'QDII亚洲', value: 'QDII亚洲' }, { label: '国内LOF', value: '国内LOF' }, { label: '白银', value: '白银' }
]
const categoryToFunds: Record<string, {label:string, value:string}[]> = {
  '黄金原油': [{ label: '164701 (汇添富黄金)', value: '164701' }, { label: '160719 (嘉实原油)', value: '160719' }, { label: '161129 (易方达原油)', value: '161129' }, { label: '501018 (南方原油)', value: '501018' }],
  'QDII欧美': [{ label: '162411 (华宝油气)', value: '162411' }, { label: '161125 (标普500)', value: '161125' }, { label: '161130 (纳斯达克)', value: '161130' }, { label: '161128 (标普科技)', value: '161128' }, { label: '161126 (标普医疗)', value: '161126' }, { label: '161127 (标普生物)', value: '161127' }],
  'QDII亚洲': [{ label: '164824 (印度基金)', value: '164824' }, { label: '165513 (信诚四国)', value: '165513' }],
  '国内LOF': [{ label: '501018 (南方原油)', value: '501018' }],
  '白银': [{ label: '161116 (白银基金)', value: '161116' }]
}
const fundCodeOptions = computed(() => categoryToFunds[newFee.value.category] || [])
const onCategoryChange = (val: string) => {
  newFee.value.category = val
  const opts = categoryToFunds[val]
  if (opts?.length) newFee.value.fund_code = opts[0].value
}
const brokerOptions = [{ label: '银河', value: '银河' }, { label: '华宝', value: '华宝' }, { label: '国金', value: '国金' }]
const feeRateOptions = [{ label: '0.3316%', value: '0.3316' }, { label: '0.335%', value: '0.335' }, { label: '0.365%', value: '0.365' }, { label: '0.5%', value: '0.5' }, { label: '1.5%', value: '1.5' }]

const fetchFees = async () => {
  loadingFees.value = true
  try {
    const res = await getBrokerFees()
    if (res.data?.status === 'ok') fees.value = res.data.data
  } catch { message.error('获取费率失败') }
  finally { loadingFees.value = false }
}
const submitFee = async () => {
  if (!newFee.value.fund_code || !newFee.value.broker_name || !newFee.value.fee_rate) {
    message.warning('请填写完整费率信息')
    return
  }
  savingFee.value = true
  try {
    const res = await addBrokerFee(newFee.value)
    if (res.data?.status === 'ok') { message.success('添加成功'); fetchFees() }
    else message.error('添加失败: ' + res.data?.message)
  } catch { message.error('保存失败') }
  finally { savingFee.value = false }
}
const handleDeleteFee = async (id: number) => {
  try {
    const res = await deleteBrokerFee(id)
    if (res.data?.status === 'ok') { message.success('已删除'); fetchFees() }
  } catch { message.error('删除失败') }
}
const feeColumns = [
  { title: '类别', key: 'category' }, { title: '基金代码', key: 'fund_code' },
  { title: '券商', key: 'broker_name' }, { title: '赎回费率(%)', key: 'fee_rate', render: (row: any) => `${row.fee_rate}%` },
  { title: '更新时间', key: 'updated_at' },
  { title: '操作', key: 'actions', render: (row: any) => h(NButton, { size: 'small', type: 'error', quaternary: true, onClick: () => handleDeleteFee(row.id) }, { default: () => '删除' }) }
]

// ===== Init =====
onMounted(() => {
  fetchPairs()
  fetchFees()
})
</script>

<style scoped>
.ledger-page { background-color: #f8fafc; min-height: 100vh; padding: 20px; }
.header-card { padding: 12px 20px; border-radius: 16px; }
.header-title { font-size: 20px; font-weight: 800; color: #1e293b; }
.header-subtitle { font-size: 12px; color: #64748b; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04); border-radius: 12px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex-center { display: flex; align-items: center; }
.gap-4 { gap: 16px; }
.mb-4 { margin-bottom: 16px; }
.mt-4 { margin-top: 16px; }
.mt-8 { margin-top: 32px; }

.stat-card { text-align: center; padding: 8px 0; }
.stat-label { font-size: 12px; color: #64748b; }
.stat-value { font-size: 22px; font-weight: 800; }
.text-green { color: #16a34a; }
.text-red { color: #e53e3e; }

:deep(.row-profit) td { background-color: #f0fdf4 !important; }
:deep(.row-loss) td { background-color: #fef2f2 !important; }
</style>
