<template>
  <div class="lazy-container">
    <n-grid :cols="24" :x-gap="12" :y-gap="12">
      <!-- 顶部：标题 + 执行器控制 -->
      <n-gi :span="24">
        <n-card class="shadow-soft header-card">
          <div class="flex-between">
            <div class="flex-center gap-4">
              <n-icon size="28" color="#6366f1"><LazyIcon /></n-icon>
              <div>
                <div class="header-title">懒人交易终端</div>
                <div class="header-subtitle">私有交易通道 | 手动执行</div>
              </div>
              <n-tag :bordered="false" round :type="executorRunning ? 'success' : 'error'" class="status-badge">
                <template #icon><n-icon><Activity /></n-icon></template>
                {{ executorRunning ? '信号检测: 运行中' : '信号检测: 停止' }}
              </n-tag>
            </div>
            <n-space>
              <n-button :type="executorRunning ? 'error' : 'success'" secondary @click="toggleExecutor" :loading="toggling">
                <template #icon><n-icon><Power /></n-icon></template>
                {{ executorRunning ? '停止检测' : '开启检测' }}
              </n-button>
            </n-space>
          </div>
        </n-card>
      </n-gi>

      <!-- 左列：下单面板 -->
      <n-gi :span="8">
        <n-card title="手动执行" :bordered="false" class="shadow-soft full-height">
          <n-form label-placement="top">
            <n-form-item label="基金代码">
              <n-select v-model:value="orderForm.code" :options="fundOptions" filterable />
            </n-form-item>
            <n-form-item label="方向">
              <n-radio-group v-model:value="orderForm.direction">
                <n-radio value="open">开仓（买LOF+空ETF）</n-radio>
                <n-radio value="close">平仓（卖LOF+平ETF）</n-radio>
              </n-radio-group>
            </n-form-item>
            <n-form-item label="LOF数量">
              <n-input-number v-model:value="orderForm.lofQty" :min="100" :step="1000" style="width: 100%" />
            </n-form-item>
            <n-form-item label="ETF数量">
              <n-input-number v-model:value="orderForm.etfQty" :min="1" :step="10" style="width: 100%" />
            </n-form-item>
            <n-button type="primary" block @click="executeOrder" :loading="executing"
              :disabled="!orderForm.code">
              <template #icon><n-icon><Send /></n-icon></template>
              执行懒人下单
            </n-button>
            <n-alert v-if="orderResult" :type="orderResult.success ? 'success' : 'error'" closable class="mt-4">
              {{ orderResult.msg }}
            </n-alert>
          </n-form>
        </n-card>

        <n-card title="默认订单参数" :bordered="false" class="shadow-soft mt-card">
          <n-table size="small" :bordered="false" :single-line="false">
            <thead>
              <tr><th>基金</th><th>LOF</th><th>ETF</th></tr>
            </thead>
            <tbody>
              <tr><td>162411 (华宝油气)</td><td>34,000 股</td><td>100 XOP</td></tr>
              <tr><td>164701 (黄金)</td><td>3,000 股</td><td>30 GLD</td></tr>
              <tr><td>160723 (嘉实原油)</td><td>3,000 股</td><td>30 GLD</td></tr>
            </tbody>
          </n-table>
        </n-card>
      </n-gi>

      <!-- 中列：信号日志 -->
      <n-gi :span="10">
        <n-card title="信号日志" :bordered="false" class="shadow-soft full-height">
          <div class="log-terminal">
            <div v-if="logs.length === 0" class="log-empty">等待执行...</div>
            <div v-for="(log, index) in logs" :key="index" class="log-line">
              <span class="l-time">[{{ log.time }}]</span>
              <span :class="['l-level', log.level.toLowerCase()]">[{{ log.level }}]</span>
              <span class="l-msg">{{ log.message }}</span>
            </div>
          </div>
        </n-card>
      </n-gi>

      <!-- 右列：系统状态 milestones -->
      <n-gi :span="6">
        <n-card title="系统里程碑" :bordered="false" class="shadow-soft full-height">
          <div v-if="milestones.length === 0" class="log-empty">等待系统事件...</div>
          <div v-for="m in milestones" :key="m.time + m.message" class="milestone-item">
            <n-tag :type="m.level === 'SUCCESS' ? 'success' : m.level === 'WARNING' ? 'warning' : 'info'"
              size="tiny" lazy style="margin-right: 6px; flex-shrink: 0;">
              {{ m.level }}
            </n-tag>
            <span class="m-time">{{ m.time }}</span>
            <span class="m-msg">{{ m.message }}</span>
          </div>
        </n-card>
      </n-gi>
    </n-grid>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, h } from 'vue'
import {
  NCard, NGrid, NGi, NTag, NButton, NIcon, NSpace, NForm, NFormItem,
  NInputNumber, NSelect, NRadio, NRadioGroup, NAlert, NTable,
  useMessage
} from 'naive-ui'
import { Power, Activity, Send, Bot as LazyIcon } from 'lucide-vue-next'
import { getSignalDetectorStatus, toggleSignalDetector as toggleDetectorApi, getSignalDetectorLogs } from '../api'
import { getMilestones } from '../api/systemApi'

const message = useMessage()
const executorRunning = ref(false)
const toggling = ref(false)
const logs = ref<any[]>([])
const milestones = ref<any[]>([])
const executing = ref(false)
const orderResult = ref<{ success: boolean; msg: string } | null>(null)

const orderForm = ref({
  code: '162411',
  direction: 'open' as 'open' | 'close',
  lofQty: 34000,
  etfQty: 100,
  price: 0,
})

const fundOptions = [
  { label: '162411 华宝油气 (→ XOP)', value: '162411' },
  { label: '162415 华宝油气2 (→ XOP)', value: '162415' },
  { label: '164701 汇添富黄金 (→ GLD)', value: '164701' },
  { label: '160723 嘉实原油 (→ GLD)', value: '160723' },
]

let timer: any = null

const fetchExecutorStatus = async () => {
  try {
    const res = await getSignalDetectorStatus()
    executorRunning.value = res.data.running
  } catch { /* mute */ }
}

const fetchLogs = async () => {
  try {
    const res = await getSignalDetectorLogs()
    logs.value = res.data.logs || []
  } catch { /* mute */ }
}

const fetchMilestones = async () => {
  try {
    const res = await getMilestones()
    milestones.value = res.data.milestones || []
  } catch { /* mute */ }
}

const fetchAll = () => {
  fetchExecutorStatus()
  fetchLogs()
  fetchMilestones()
}

const toggleExecutor = async () => {
  toggling.value = true
  const action = executorRunning.value ? 'stop' : 'start'
  try {
    const res = await toggleDetectorApi(action)
    executorRunning.value = res.data.running
    message.success(executorRunning.value ? '信号检测已启动' : '信号检测已停止')
  } catch (e) {
    message.error('操作失败')
  } finally {
    toggling.value = false
  }
}

const executeOrder = async () => {
  executing.value = true
  orderResult.value = null
  try {
    const { code, direction, lofQty, etfQty } = orderForm.value
    // 调用 lazy_trader 的 API
    const { default: client } = await import('../api/client')
    const res = await client.post('/api/lazy_place_order', {
      fund_code: code,
      direction: direction === 'open' ? 'open' : 'close',
      quantity: lofQty,
      etf_quantity: etfQty,
      mode: 'safe',
      price: 0,
      lof_price: 0,
    })
    orderResult.value = { success: true, msg: JSON.stringify(res.data.results || res.data) }
  } catch (e: any) {
    orderResult.value = { success: false, msg: e?.message || '执行失败' }
  } finally {
    executing.value = false
  }
}

onMounted(() => {
  fetchAll()
  timer = setInterval(fetchAll, 5000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.lazy-container { padding: 16px; background-color: #0f0e1a; min-height: 100vh; }
.header-card { padding: 8px 16px; border-radius: 16px; margin-bottom: 12px;
  background: linear-gradient(135deg, #1e1b3a 0%, #0f0e1a 100%); border: 1px solid #2d2a4a; }
.header-title { font-size: 20px; font-weight: 800; color: #e2dff5; }
.header-subtitle { font-size: 12px; color: #8b86b5; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex-center { display: flex; align-items: center; }
.gap-4 { gap: 16px; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3); border-radius: 12px;
  background: #1a1833; border: 1px solid #2d2a4a; }
.full-height { height: 420px; overflow-y: auto; }
.mt-card { margin-top: 12px; }
.mt-4 { margin-top: 12px; }
.log-terminal {
  background-color: #0a0918; border-radius: 8px; padding: 12px; height: 340px;
  overflow-y: auto; font-family: 'Fira Code', monospace; font-size: 12px;
}
.log-line { margin-bottom: 4px; display: flex; gap: 8px; border-bottom: 1px solid #1e1c3a; padding-bottom: 2px; }
.l-time { color: #5c5794; flex-shrink: 0; }
.l-level.info { color: #6366f1; font-weight: bold; }
.l-level.warning { color: #f59e0b; }
.l-level.error { color: #ef4444; }
.l-msg { color: #c8c4e6; }
.log-empty { color: #3d3870; text-align: center; margin-top: 180px; }
.milestone-item { display: flex; align-items: flex-start; gap: 4px; margin-bottom: 8px; font-size: 12px; flex-wrap: wrap; }
.m-time { color: #5c5794; flex-shrink: 0; font-size: 11px; }
.m-msg { color: #c8c4e6; word-break: break-all; }
</style>
