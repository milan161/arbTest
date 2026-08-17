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
        </n-space>
      </div>
    </n-card>

    <!-- [AI-2026-08-16] 赎回提醒横幅：OPEN 笔推算可优惠赎回日 + unfinished 待净值 -->
    <div v-if="alerts" class="mb-4">
      <n-alert
        v-for="(a, i) in alerts.open_alerts"
        :key="'o' + a.id"
        :type="a.level === 'critical' ? 'error' : (a.level === 'warning' ? 'warning' : (a.level === 'notice' ? 'warning' : 'info'))"
        :title="`${a.fund_name}（${a.fund_code}）`"
        class="mb-2 alert-item"
        :show-icon="true"
      >
        <div class="alert-body">
          <span class="alert-msg">{{ a.message }}</span>
          <span class="alert-meta">赎回 LOF {{ a.buy_volume }} 份 ｜ 买平 ETF {{ a.short_volume }} 股</span>
        </div>
      </n-alert>
      <n-alert
        v-for="(a, i) in alerts.unfinished_alerts"
        :key="'u' + a.id"
        type="warning"
        :title="`${a.fund_name}（${a.fund_code}）`"
        class="mb-2 alert-item"
        :show-icon="true"
      >
        <div class="alert-body">
          <span class="alert-msg">{{ a.message }}</span>
          <span class="alert-meta">买入 {{ a.buy_date }} ｜ 赎回 {{ a.sell_date }}</span>
        </div>
      </n-alert>
      <n-alert
        v-if="alerts.open_count === 0 && alerts.unfinished_count === 0"
        type="success"
        title="暂无待处理项"
        :show-icon="true"
      >
        当前没有未赎回（OPEN）或已赎回待净值的配对。
      </n-alert>
    </div>

    <!-- 统计概览 -->
    <n-card class="shadow-soft mb-4">
      <n-grid :cols="24" :x-gap="12">
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">总盈亏(RMB)</div>
            <div class="stat-value" :class="totalPnl >= 0 ? 'text-green' : 'text-red'">{{ totalPnl.toFixed(2) }}</div>
          </div>
        </n-gi>
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">A股总盈亏</div>
            <div class="stat-value" :class="totalASharePnl >= 0 ? 'text-green' : 'text-red'">{{ Math.round(totalASharePnl).toLocaleString() }}</div>
          </div>
        </n-gi>
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">美股总盈亏(USD)</div>
            <div class="stat-value" :class="totalUsd >= 0 ? 'text-green' : 'text-red'">{{ totalUsd.toFixed(2) }}</div>
          </div>
        </n-gi>
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">未赎回 (OPEN)</div>
            <div class="stat-value" :class="openPairs.length ? 'text-red' : ''">{{ openPairs.length }}</div>
          </div>
        </n-gi>
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">已赎回待净值</div>
            <div class="stat-value" :class="unfinishedPairs.length ? 'text-orange' : ''">{{ unfinishedPairs.length }}</div>
          </div>
        </n-gi>
        <n-gi :span="4">
          <div class="stat-card">
            <div class="stat-label">已结项</div>
            <div class="stat-value text-green">{{ settledCount }}</div>
          </div>
        </n-gi>
      </n-grid>
    </n-card>

    <!-- 套利账本（按状态分页签） -->
    <n-card :bordered="false" class="shadow-soft mb-4">
      <n-tabs type="line" animated>
        <n-tab-pane name="open" :tab="`持仓未赎回 (${openPairs.length})`">
          <n-data-table :columns="pairColumns" :data="openPairs" size="small" bordered :row-class-name="pnlRowClass" :max-height="600" :scroll-x="1500" />
        </n-tab-pane>
        <n-tab-pane name="unfinished" :tab="`已赎回待净值 (${unfinishedPairs.length})`">
          <n-data-table :columns="pairColumns" :data="unfinishedPairs" size="small" bordered :row-class-name="pnlRowClass" :max-height="600" :scroll-x="1500" />
        </n-tab-pane>
        <n-tab-pane name="settled" :tab="`已结项 (${settledPairs.length})`">
          <n-data-table :columns="pairColumns" :data="settledPairs" size="small" bordered :row-class-name="pnlRowClass" :max-height="600" :scroll-x="1500" />
        </n-tab-pane>
      </n-tabs>
    </n-card>

    <!-- [AI-2026-08-16] 导入 V7 账本：从 Excel 一键导入（upsert，不影响程序内手动录入） -->
    <n-card class="shadow-soft mb-4">
      <n-space justify="space-between" align="center">
        <n-space align="center">
          <n-button type="primary" :loading="importing" @click="triggerImport">
            <template #icon><n-icon><Upload /></n-icon></template>
            导入 V7 账本
          </n-button>
          <n-text depth="3">从 Excel 套利账本导入（新增/更新，不删除已有记录）</n-text>
        </n-space>
        <n-tag v-if="importResult" :type="importResult.ok ? 'success' : 'error'">
          新增 {{ importResult.inserted }} · 更新 {{ importResult.updated }} · 跳过 {{ importResult.skipped }}
        </n-tag>
      </n-space>
      <input ref="fileInput" type="file" accept=".xlsx,.xls" style="display:none" @change="onFileChange" />
    </n-card>

    <!-- [AI-2026-08-16] 套利配对对账：直接展示 v7 干净账本数据（按状态着色，可编辑） -->
    <n-card class="shadow-soft mb-4" title="套利配对对账（全部）">
      <div class="flex-between mb-3 ledger-filter">
        <n-space>
          <n-input v-model:value="searchCode" placeholder="基金代码筛选，如 164701" clearable style="width: 220px" />
          <n-select v-model:value="searchMonth" :options="monthOptions" placeholder="开仓月份" clearable style="width: 160px" />
        </n-space>
        <n-text depth="3">共 {{ filteredAllPairs.length }} 条</n-text>
      </div>
      <n-data-table
        class="ledger-table"
        :columns="pairColumns"
        :data="filteredAllPairs"
        size="small"
        bordered
        :row-class-name="pnlRowClass"
        :max-height="700"
        :scroll-x="1500"
        :pagination="{ pageSize: 20 }"
      />
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
              <n-select v-model:value="form.status" :options="statusOptions" />
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
import { ref, onMounted, computed, h, watch } from 'vue'
import {
  NCard, NGrid, NGi, NTag, NButton, NDataTable, NIcon,
  useMessage, NSpace, NText, NTabs, NTabPane, NModal, NForm, NFormItem,
  NInput, NInputNumber, NDatePicker, NDivider, NSelect, NAlert
} from 'naive-ui'
import { BookOpen, Plus, Settings, Edit3, TrendingUp, TrendingDown, Upload } from 'lucide-vue-next'
import {
  getPairs, addPair, updatePair, deletePair,
  getBrokerFees, addBrokerFee, deleteBrokerFee
} from '../api'
import { getFeeRate, getLedgerAlerts, importV7Ledger } from '../api/ledgerApi'
import client from '../api/client'

const message = useMessage()
const allPairs = ref<any[]>([])
const showAddModal = ref(false)
const showFeeModal = ref(false)
const isEditing = ref(false)
const editingId = ref<number | null>(null)
const loading = ref(false)

// [AI-2026-08-16] 全部对账卡筛选：基金代码 + 开仓月份
const searchCode = ref('')
const searchMonth = ref<string | null>(null)
const monthOptions = computed(() => {
  const set = new Set<string>()
  for (const p of allPairs.value) {
    if (p.buy_date && typeof p.buy_date === 'string' && p.buy_date.length >= 7) {
      set.add(p.buy_date.slice(0, 7))
    }
  }
  return Array.from(set).sort().reverse().map(m => ({ label: m, value: m }))
})
const filteredAllPairs = computed(() => {
  const code = searchCode.value.trim().toLowerCase()
  const month = searchMonth.value
  return allPairs.value.filter(p => {
    if (code && !(p.fund_code || '').toLowerCase().includes(code)) return false
    if (month && !(p.buy_date || '').startsWith(month)) return false
    return true
  })
})

// [AI-2026-08-16] 导入 V7 账本：上传 Excel → 后端解析 upsert
const importing = ref(false)
const importResult = ref<{ ok: boolean; inserted: number; updated: number; skipped: number } | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const triggerImport = () => fileInput.value?.click()
const onFileChange = async (e: Event) => {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  importing.value = true
  importResult.value = null
  try {
    const res = await importV7Ledger(file)
    const data = res.data
    if (data?.status === 'ok') {
      const r = data.data || {}
      importResult.value = { ok: true, inserted: r.inserted || 0, updated: r.updated || 0, skipped: r.skipped || 0 }
      await fetchPairs()
      message.success(`导入完成：新增 ${r.inserted} · 更新 ${r.updated} · 跳过 ${r.skipped}`)
    } else {
      importResult.value = { ok: false, inserted: 0, updated: 0, skipped: 0 }
      message.error('导入失败：' + (data?.message || '未知错误'))
    }
  } catch (err: any) {
    importResult.value = { ok: false, inserted: 0, updated: 0, skipped: 0 }
    message.error('导入异常：' + (err?.message || err))
  } finally {
    importing.value = false
    if (target) target.value = ''
  }
}

// [AI-2026-08-16] 赎回提醒
const alerts = ref<any>(null)

// ===== Computed（按新状态分类：OPEN / unfinished / Closed / Final）=====
const openPairs = computed(() => allPairs.value.filter(p => p.status === 'OPEN'))
const unfinishedPairs = computed(() => allPairs.value.filter(p => p.status === 'unfinished'))
const settledPairs = computed(() => allPairs.value.filter(p => p.status === 'Closed'))
const settledCount = computed(() => settledPairs.value.length)

const totalPnl = computed(() => settledPairs.value.reduce((s, p) => s + (p.pnl_rmb || 0), 0))
const totalUsd = computed(() => settledPairs.value.reduce((s, p) => s + (p.pnl_usd || 0), 0))
const totalASharePnl = computed(() => settledPairs.value.reduce((s, p) => s + (p.a_share_pnl || 0), 0))

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

// 状态选项（与 v7 口径一致）
const statusOptions = [
  { label: '未赎回 (OPEN)', value: 'OPEN' },
  { label: '已赎回待净值 (unfinished)', value: 'unfinished' },
  { label: '结项 (已结项)', value: 'Closed' },
]

// ===== Form =====
const defaultForm = () => ({
  fund_code: '162411',
  fund_name: '华宝油气',
  broker_name: '银河',
  close_type: 'REDEEM',
  status: 'OPEN',
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
  // 券商自动填充：162411 华宝油气走华宝，其余默认银河
  form.value.broker_name = val === '162411' ? '华宝' : '银河'
  try {
    const res = await client.get(`/api/market/prev-close/${val}`)
    if (res.data?.status === 'ok' && res.data.price > 0) {
      form.value.buy_price = res.data.price
    }
  } catch {}
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
const usdRate = ref(0)  // 实时 USD/CNY 汇率，从后端获取

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
  // 汇率从后端实时获取，不再硬编码（旧值 7.2 偏高 ~6%）
  return computedAPnl.value + computedUPnl.value * (usdRate.value || 6.79)
})

// 自动计算金额（当价格或数量变化时）
const safeComputed = (a: number, b: number) => {
  if (a > 0 && b > 0) return +(a * b).toFixed(2)
  return 0
}

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

const loadAlerts = async () => {
  try {
    const res = await getLedgerAlerts()
    if (res.data?.status === 'ok') alerts.value = res.data.data
  } catch (e) { /* ignore */ }
}

const fetchUsdRate = async () => {
  try {
    const res = await client.get('/api/exchange-rate')
    if (res.data?.status === 'ok' && res.data.rate > 0) usdRate.value = res.data.rate
  } catch (e) { /* keep fallback */ }
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
      status: pair.status || 'OPEN',
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
    loadAlerts()
  } catch (e) {
    message.error('保存失败')
  }
}

const handleDelete = async (id: number) => {
  try {
    await deletePair(id)
    message.success('已删除')
    fetchPairs()
    loadAlerts()
  } catch (e) { message.error('删除失败') }
}

const handleClose = async (id: number) => {
  try {
    await updatePair(id, { status: 'Closed' })
    message.success('已标记结项')
    fetchPairs()
    loadAlerts()
  } catch (e) { message.error('操作失败') }
}

// ===== Table columns =====
const pnlRowClass = (row: any) => {
  if (!row.pnl_rmb) return ''
  return row.pnl_rmb >= 0 ? 'row-profit' : 'row-loss'
}

const fmt = (v: any, d: number = 2) => v !== null && v !== undefined && v !== 0 ? Number(v).toFixed(d) : '-'
const shortDate = (d: string) => d ? d.substring(5) : '-'

const statusTag = (s: string) => {
  const map: any = { 'OPEN': 'error', 'unfinished': 'warning', 'Closed': 'success' }
  const label: any = { 'OPEN': '未赎回', 'unfinished': '待净值', 'Closed': '结项' }
  return h(NTag, { type: map[s] || 'default', size: 'small' }, { default: () => label[s] || s || '-' })
}

const pairColumns = [
  { title: '序号', key: 'serial_no', width: 56, align: 'center' as const, fixed: 'left' as const,
    render: (r: any) => r.serial_no || '-' },
  { title: '基金', key: 'fund', width: 72, fixed: 'left' as const,
    render: (r: any) => {
      const found = fundList.find(f => f.code === r.fund_code)
      const code = found ? found.code : r.fund_code
      const name = found ? found.name : ''
      const children = [
        h(NText, { strong: true, style: 'font-size:13px;' }, { default: () => code })
      ]
      if (name) children.push(h('div', { style: 'font-size:12px; color:#666; margin-top:2px; line-height:1.25;' }, name))
      return h('div', { style: 'line-height:1.25; text-align:left; white-space:normal; word-break:break-all;' }, children)
    }
  },
  { title: '状态', key: 'status', width: 48, align: 'center' as const,
    render: (r: any) => statusTag(r.status) },
  // A股开仓
  { title: '开仓日', key: 'buy_date', width: 46, align: 'center' as const,
    render: (r: any) => r.buy_date ? shortDate(r.buy_date) : '-' },
  { title: '开仓价', key: 'buy_price', width: 50, align: 'center' as const,
    render: (r: any) => fmt(r.buy_price, 3) },
  { title: '数量', key: 'buy_volume', width: 52, align: 'center' as const,
    render: (r: any) => r.buy_volume ? Number(r.buy_volume).toLocaleString() : '-' },
  { title: '金额(RMB)', key: 'buy_amount', width: 82, align: 'right' as const,
    render: (r: any) => h(NText, { style: (r.buy_amount ? 'color:#e53e3e;' : '') + 'white-space:nowrap' }, { default: () => fmt(r.buy_amount, 0) }) },
  // A股平仓
  { title: '平仓日', key: 'sell_date', width: 46, align: 'center' as const,
    render: (r: any) => r.sell_date ? shortDate(r.sell_date) : '-' },
  { title: '平仓价', key: 'sell_price', width: 50, align: 'center' as const,
    render: (r: any) => fmt(r.sell_price, 3) },
  { title: '金额(RMB)', key: 'sell_amount', width: 82, align: 'right' as const,
    render: (r: any) => h(NText, { style: (r.sell_amount ? 'color:#16a34a;' : '') + 'white-space:nowrap' }, { default: () => fmt(r.sell_amount, 0) }) },
  // 美股做空
  { title: '对冲', key: 'hedge', width: 40, align: 'center' as const,
    render: (r: any) => r.hedge_symbol || '-' },
  { title: '空单价', key: 'short_price', width: 68, align: 'center' as const,
    render: (r: any) => r.short_price ? `$${fmt(r.short_price)}` : '-' },
  { title: '空单量', key: 'short_volume', width: 46, align: 'center' as const,
    render: (r: any) => r.short_volume || '-' },
  { title: '空金额(USD)', key: 'short_amount', width: 82, align: 'right' as const,
    render: (r: any) => h('span', { style: 'white-space:nowrap' }, fmt(r.short_amount)) },
  // 美股买平
  { title: '买平日', key: 'cover_date', width: 46, align: 'center' as const,
    render: (r: any) => r.cover_date ? shortDate(r.cover_date) : '-' },
  { title: '买平价', key: 'cover_price', width: 68, align: 'center' as const,
    render: (r: any) => r.cover_price ? `$${fmt(r.cover_price)}` : '-' },
  { title: '金额(USD)', key: 'cover_amount', width: 82, align: 'right' as const,
    render: (r: any) => h('span', { style: 'white-space:nowrap' }, fmt(r.cover_amount)) },
  // 盈亏汇总：未结项(OPEN/unfinished)显示空白，已结项(Closed)才显示数值
  { title: 'A股盈亏', key: 'a_share_pnl', width: 64, align: 'right' as const,
    render: (r: any) => {
      if (r.status !== 'Closed') return '-'
      if (r.a_share_pnl === null || r.a_share_pnl === undefined) return '-'
      return h(NText, { type: r.a_share_pnl >= 0 ? 'success' : 'error', strong: true },
        { default: () => fmt(r.a_share_pnl, 0) })
    }
  },
  { title: 'USD盈亏', key: 'pnl_usd', width: 64, align: 'right' as const,
    render: (r: any) => {
      if (r.status !== 'Closed') return '-'
      if (r.pnl_usd === null || r.pnl_usd === undefined) return '-'
      return h(NText, { type: r.pnl_usd >= 0 ? 'success' : 'error', strong: true },
        { default: () => fmt(r.pnl_usd, 0) })
    }
  },
  { title: '总盈亏(RMB)', key: 'pnl_rmb', width: 78, align: 'right' as const, fixed: 'right' as const,
    render: (r: any) => {
      if (r.status !== 'Closed') return '-'
      if (r.pnl_rmb === null || r.pnl_rmb === undefined) return '-'
      const color = r.pnl_rmb >= 0 ? '#16a34a' : '#e53e3e'
      return h('div', { style: `font-weight:700;color:${color}` }, [
        r.pnl_rmb >= 0 ? '+' : '',
        Number(r.pnl_rmb).toFixed(0)
      ])
    }
  },
  {
    title: '操作', key: 'ops', width: 80, align: 'center' as const, fixed: 'right' as const,
    render: (r: any) => h(NSpace, { size: 6, align: 'center' }, {
      default: () => [
        h(NButton, { size: 'tiny', quaternary: true, type: 'primary', onClick: () => openAddModal(r) },
          { default: () => '编辑' }),
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
  loadAlerts()
  fetchUsdRate()
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
.mb-2 { margin-bottom: 8px; }
.mt-4 { margin-top: 16px; }
.mt-8 { margin-top: 32px; }

.stat-card { text-align: center; padding: 8px 0; }
.stat-label { font-size: 14px; font-weight: 700; color: #475569; letter-spacing: 0.3px; }
.stat-value { font-size: 22px; font-weight: 800; }
/* 分页签文字加大加粗（黑体） */
:deep(.n-tabs-tab__label) { font-size: 15px; font-weight: 700; color: #1e293b; }
.text-green { color: #16a34a; }
.text-red { color: #e53e3e; }
.text-orange { color: #ea580c; }

.alert-item :deep(.n-alert__content) { width: 100%; }
.alert-item :deep(.n-alert__title) { font-weight: 800; font-size: 15px; }
.alert-body { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; font-size: 15px; font-weight: 700; }
.alert-msg { font-weight: 800; }
.alert-meta { color: #334155; font-weight: 700; }

:deep(.row-profit) td { background-color: #f0fdf4 !important; }
:deep(.row-loss) td { background-color: #fef2f2 !important; }

/* 套利配对对账表：数据行紧凑，列头保持默认可读性 */
.ledger-table :deep(.n-data-table-td) { padding: 3px 5px !important; }
/* 前两列（基金+状态）进一步收紧水平间距 */
.ledger-table :deep(tr > td:nth-child(1)),
.ledger-table :deep(tr > th:nth-child(1)) { padding-right: 2px !important; }
.ledger-table :deep(tr > td:nth-child(2)),
.ledger-table :deep(tr > th:nth-child(2)) { padding-left: 2px !important; }
.ledger-table :deep(.n-data-table-wrapper) { border-collapse: separate; border-spacing: 0; }
</style>
