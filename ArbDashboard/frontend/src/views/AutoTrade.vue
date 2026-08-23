<template>
  <div class="auto-trade-container">
    <n-grid :cols="24" :x-gap="12" :y-gap="12">
      <!-- 顶部：规则引擎总控 -->
      <n-gi :span="24">
        <n-card class="shadow-soft header-card">
          <div class="flex-between">
            <div class="flex-center gap-4">
              <n-icon size="32" color="#6b21a8"><Zap /></n-icon>
              <div>
                <div class="header-title">自动化规则引擎</div>
                <div class="header-subtitle">套利阈值策略 · 单一策略管理入口（DB 驱动）</div>
              </div>
              <n-tag :bordered="false" round :type="ruleEngineRunning ? 'success' : 'error'" class="status-badge">
                <template #icon><n-icon><Activity /></n-icon></template>
                {{ ruleEngineRunning ? '运行中' : '停止' }}
              </n-tag>
            </div>
            <n-space>
              <n-button :type="ruleEngineRunning ? 'warning' : 'success'" secondary @click="toggleRuleEngine" :loading="ruleToggling" :disabled="true" title="临时禁用：开平仓逻辑待与SmartMonitor对齐，避免误操作">
                <template #icon><n-icon><Power /></n-icon></template>
                {{ ruleEngineRunning ? '停止引擎' : '启动引擎' }}
              </n-button>
            </n-space>
          </div>
        </n-card>
      </n-gi>

      <!-- 规则集合（按基金分组） -->
      <n-gi :span="24">
        <n-card :bordered="false" class="shadow-soft" style="background: #faf5ff; border: 1px solid #e9d5ff;">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <span @click="showRulePanel = !showRulePanel" style="cursor: pointer; font-weight: bold; font-size: 15px; color: #1e293b; user-select: none;">
                  {{ showRulePanel ? '▼' : '▶' }} 策略规则集合
                </span>
                <n-tag :type="ruleEngineRunning ? 'success' : 'error'" size="small" round>
                  {{ ruleEngineRunning ? '运行中' : '停止' }}
                </n-tag>
              </div>
              <n-button size="tiny" type="primary" @click="showAddRuleModal = true" :disabled="ruleEngineRunning">+ 新增规则</n-button>
            </div>
          </template>
          <div v-if="showRulePanel">
            <!-- 按基金分组显示 -->
            <div v-if="ruleGroups.length === 0" style="text-align: center; padding: 20px; color: #94a3b8; font-size: 13px;">
              暂无规则，点击「+ 新增规则」创建
            </div>
            <div v-for="group in ruleGroups" :key="group.fund_code" style="margin-bottom: 16px; border: 1px solid #e9d5ff; border-radius: 8px; overflow: hidden;">
              <!-- 组头 -->
              <div style="background: #f3e8ff; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; font-size: 13px;">
                <div style="display: flex; align-items: center; gap: 12px;">
                  <strong style="color: #1e293b;">{{ group.fund_code }}</strong>
                  <n-tag size="tiny" type="info" round>{{ group.hedge_symbol || '-' }}</n-tag>
                  <span style="color: #475569; font-size: 12px;">{{ group.rules.length }}条规则 | {{ group.running_count }}条启用</span>
                </div>
                <span v-if="group.currentSignal != null" style="font-family: monospace; font-weight: bold; font-size: 14px;"
                  :style="{ color: group.currentSignal < 0 ? '#d32f2f' : '#388e3c' }">
                  溢价率: {{ group.currentSignal.toFixed(3) }}%
                </span>
              </div>
              <!-- 规则行 -->
              <div v-for="rule in group.rules" :key="rule.id" style="display: flex; align-items: center; gap: 8px; padding: 6px 12px; border-bottom: 1px solid #f3e8ff; flex-wrap: wrap; font-size: 12px;"
                :style="{ background: rule.condition_met ? '#fef2f2' : 'transparent' }">
                <!-- 启用开关 -->
                <n-switch :value="!!rule.enabled" size="small" @update:value="(v) => updateRuleField(rule.id, 'enabled', v)" style="flex-shrink:0;" />
                <!-- 方向标签 -->
                <n-tag :type="rule.direction === 'open' ? 'info' : 'warning'" size="tiny" round style="flex-shrink:0; width: 36px; text-align: center;">
                  {{ rule.direction === 'open' ? '开' : '平' }}
                </n-tag>
                <!-- 条件阈值 -->
                <span style="display: flex; align-items: center; gap: 2px;">
                  <span style="color: #64748b;">溢价率</span>
                  <n-select :value="rule.condition" size="tiny" style="width: 75px;" :options="[{label:'<',value:'lt'},{label:'>',value:'gt'}]" @update:value="(v) => updateRuleField(rule.id, 'condition', v)" />
                  <n-input-number :value="rule.threshold" size="tiny" style="width: 130px;" :step="0.01" :precision="2" :min="-10" :max="10" placeholder="-0.69" @update:value="(v) => updateRuleField(rule.id, 'threshold', v)" />
                  <span style="color: #94a3b8;">%</span>
                </span>
                <!-- [AI-2026-08-23] LOF 数量（用户可设置，每笔固定股数） -->
                <span style="display: flex; align-items: center; gap: 4px;">
                  <span style="color: #64748b;">LOF</span>
                  <n-input-number :value="triggerQty[group.fund_code]?.lof_qty || group.lof_qty" size="tiny" style="width: 90px;" :step="100" :min="100" :max="999900" placeholder="10000" @update:value="(v) => updateLofQty(group.fund_code, v)" />
                  <span style="color: #94a3b8;">股</span>
                </span>
                <!-- 当前信号 + 状态 -->
                <span style="margin-left: auto; font-family: monospace; font-size: 11px; display: flex; align-items: center; gap: 6px;">
                  <span :style="{ color: rule.current_signal > rule.threshold ? '#d32f2f' : '#94a3b8' }">
                    sig={{ rule.current_signal?.toFixed(3) || '-' }}
                  </span>
                  <span v-if="rule.condition_met" style="color: #ef4444; font-weight: bold;">🔥 触发</span>
                  <span v-else style="color: #94a3b8;">等待</span>
                  <!-- 删除 -->
                  <n-button size="tiny" quaternary circle type="error" @click="deleteRule(rule.id)" style="margin-left: 4px;">
                    <template #icon><n-icon size="12"><Trash2 /></n-icon></template>
                  </n-button>
                </span>
              </div>
            </div>
            <!-- 引擎日志 -->
            <div style="margin-top: 8px;">
              <div style="font-size: 12px; color: #1e293b; font-weight: bold; margin-bottom: 4px; cursor: pointer;" @click="showEngineLog = !showEngineLog">
                {{ showEngineLog ? '▼' : '▶' }} 引擎日志 ({{ engineLogs.length }})
              </div>
              <div v-if="showEngineLog" style="background: #0a0a0a; border-radius: 4px; padding: 6px; max-height: 100px; overflow-y: auto; font-family: monospace; font-size: 11px; color: #00ff00;">
                <div v-for="(log, i) in engineLogs" :key="i" style="margin-bottom: 2px;">
                  <span style="color: #888;">{{ log.time }}</span>
                  <span :style="{ color: log.level === 'ERROR' ? '#ef4444' : log.level === 'WARNING' ? '#f59e0b' : '#3b82f6' }">[{{ log.level }}]</span>
                  {{ log.message }}
                </div>
                <div v-if="engineLogs.length === 0" style="color: #666;">等待引擎日志...</div>
              </div>
            </div>
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 新增规则弹窗 -->
    <n-modal v-model:show="showAddRuleModal" preset="card" title="新增规则" style="width: 560px;" :mask-closable="false">
      <n-form label-placement="left" label-width="80" size="medium">
        <n-form-item label="基金代码">
          <n-select :value="newRule.fund_code" filterable tag :options="fundRuleOptions" @update:value="(v) => { newRule.fund_code = v; autoHedge(v) }" placeholder="输入或选择代码" style="width: 200px;" />
        </n-form-item>
        <n-form-item label="对冲标的">
          <n-input :value="newRule.hedge_symbol" disabled style="color: #1e293b; font-weight: bold; width: 200px;" />
        </n-form-item>
        <n-form-item label="方向">
          <n-radio-group v-model:value="newRule.direction">
            <n-radio value="open">开仓（买LOF+空ETF）</n-radio>
            <n-radio value="close">平仓（卖LOF+平ETF）</n-radio>
          </n-radio-group>
        </n-form-item>
        <n-form-item label="LOF数量">
          <div style="display: flex; align-items: center; gap: 8px; width: 100%;">
            <n-input-number v-model:value="newRule.lof_qty" style="width: 160px;" :step="100" :min="100" :max="999900" placeholder="10000" />
            <span style="color: #94a3b8; white-space: nowrap;">股（必须是100的倍数）</span>
          </div>
        </n-form-item>
        <n-form-item label="条件">
          <div style="display: flex; align-items: center; gap: 8px; width: 100%;">
            <n-select v-model:value="newRule.condition" style="width: 120px;" :options="[{label:'溢价率<',value:'lt'},{label:'溢价率>',value:'gt'}]" />
            <n-input-number v-model:value="newRule.threshold" style="width: 160px;" :step="0.01" :precision="2" :min="-10" :max="10" placeholder="-0.69" />
            <span style="color: #94a3b8; white-space: nowrap;">%</span>
          </div>
        </n-form-item>
        <n-row justify="end" style="margin-top: 16px;">
          <n-button @click="showAddRuleModal = false" style="margin-right: 8px;">取消</n-button>
          <n-button type="primary" @click="submitNewRule" :disabled="!newRule.fund_code">保存</n-button>
        </n-row>
      </n-form>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, computed, h } from 'vue'
import {
  NCard, NGrid, NGi, NTag, NButton, NSwitch, NIcon,
  useMessage, NSpace, NModal, NForm, NFormItem,
  NInput, NInputNumber, NRadioGroup, NRadio, NSelect, NRow
} from 'naive-ui'
import { Power, Zap, Activity, Trash2 } from 'lucide-vue-next'
import { getFundValuationMeta } from '../api'

const message = useMessage()
const showRulePanel = ref(true)
const showEngineLog = ref(false)
const ruleEngineRunning = ref(false)
const ruleToggling = ref(false)
const rawRules = ref<any[]>([])
const engineLogs = ref<any[]>([])
const triggerQty = ref<Record<string, {lof_qty: number, etf_qty: number}>>({})
let ruleTimer: any = null

// 新增规则弹窗
const showAddRuleModal = ref(false)
const newRule = reactive({
  fund_code: '164701',
  hedge_symbol: 'GLD',
  direction: 'open' as 'open' | 'close',
  condition: 'gt' as 'gt' | 'lt',
  threshold: 0.50,
  lof_qty: 10000,  // [AI-2026-08-23] 可自定义每笔LOF股数
  etf_qty: 60,     // [AI-2026-08-23] ETF股数（自动推算）
})

// 按基金分组显示规则
const ruleGroups = computed(() => {
  const map = new Map<string, any>()
  for (const r of rawRules.value) {
    const fc = r.fund_code
    if (!map.has(fc)) {
      map.set(fc, {
        fund_code: fc,
        hedge_symbol: r.hedge_symbol || '',
        rules: [],
        running_count: 0,
        currentSignal: null,
        // [AI-2026-08-23] 读取交易数量配置
        lof_qty: triggerQty.value[fc]?.lof_qty || 10000,
        etf_qty: triggerQty.value[fc]?.etf_qty || 60,
      })
    }
    const g = map.get(fc)!
    g.rules.push(r)
    if (r.enabled) g.running_count++
    if (r.current_signal != null) g.currentSignal = r.current_signal
  }
  // 组内按方向+阈值排序，便于阅读
  for (const g of map.values()) {
    g.rules.sort((a: any, b: any) => (a.direction === b.direction ? a.threshold - b.threshold : (a.direction === 'open' ? -1 : 1)))
  }
  return Array.from(map.values())
})

// 基金下拉选项（套利基金静态列表）
const fundRuleOptions = computed(() => {
  return ['164701', '162411', '164824', '161125', '161130', '161116', '161226'].map(c => ({ label: c, value: c }))
})

// [AI-2026-08-23] 各基金默认 ETF 对冲数量（LOF股数变化时ETF股数按固定比例换算）
const groupDefaultEtfs: Record<string, number> = {
  '164701': 60,
  '162411': 100,
  '161116': 60,
  '161125': 30,
  '161130': 30,
}
const autoHedge = async (code: string) => {
  try {
    const res = await getFundValuationMeta(code)
    if (res.data?.status === 'ok') {
      const cfg = res.data.fund_config || {}
      newRule.hedge_symbol = cfg.trade_etf || ''
    }
  } catch { /* ignore */ }
}

// API：获取规则状态
const fetchRuleEngineStatus = async () => {
  try {
    const res = await fetch('/api/rule_engine/status')
    const data = await res.json()
    if (data.status === 'ok') {
      ruleEngineRunning.value = data.running
      rawRules.value = data.rules || []
      // [AI-2026-08-23] 存储交易数量配置
      if (data.trigger_qty) {
        triggerQty.value = data.trigger_qty
      }
    } else {
      // DASHBOARD_MODE 下 rule_engine 未加载（看板纯展示，禁真实下单）
      ruleEngineRunning.value = false
      rawRules.value = []
      triggerQty.value = {}
    }
  } catch { /* rule engine not loaded */ }
}

// API：更新 LOF 交易数量（用户自定义）
const updateLofQty = async (fundCode: string, qty: number) => {
  const etfQty = triggerQty.value[fundCode]?.etf_qty || groupDefaultEtfs[fundCode] || 60
  triggerQty.value[fundCode] = { lof_qty: qty, etf_qty: etfQty }
  try {
    await fetch('/api/rule_engine/trade_config', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fund_code: fundCode, lof_qty: qty, etf_qty: etfQty })
    })
  } catch { /* ignore */ }
}

// API：启动/停止引擎
const toggleRuleEngine = async () => {
  ruleToggling.value = true
  const action = ruleEngineRunning.value ? 'stop' : 'start'
  try {
    const res = await fetch('/api/rule_engine/toggle', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action })
    })
    const data = await res.json()
    if (data.status === 'ok') {
      ruleEngineRunning.value = data.running
      message.success(ruleEngineRunning.value ? '规则引擎已启动' : '规则引擎已停止')
    } else {
      message.error(data.message || '操作失败')
    }
  } catch (e: any) {
    message.error('操作失败: ' + (e.message || e))
  } finally {
    ruleToggling.value = false
  }
}

// API：更新规则字段（即时保存）
const updateRuleField = async (ruleId: number, field: string, value: any) => {
  // 先更新本地状态
  const rule = rawRules.value.find((r: any) => r.id === ruleId)
  if (rule) rule[field] = value
  try {
    await fetch(`/api/rule_engine/rule_update/${ruleId}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: value })
    })
  } catch { /* ignore */ }
}

// API：删除规则
const deleteRule = async (ruleId: number) => {
  if (!confirm('确定删除此规则？')) return
  try {
    await fetch(`/api/rule_engine/rule/${ruleId}`, { method: 'DELETE' })
    rawRules.value = rawRules.value.filter((r: any) => r.id !== ruleId)
    message.success('规则已删除')
  } catch { message.error('删除失败') }
}

// API：提交新增规则
const submitNewRule = async () => {
  // 阈值取负数：因为 rt_premium < -0.69 表示折价 0.69%
  const threshold = -(newRule.threshold || 0)
  const payload = {
    fund_code: newRule.fund_code,
    hedge_symbol: newRule.hedge_symbol,
    direction: newRule.direction,
    condition: newRule.condition,
    threshold: threshold,
    enabled: true,
    note: `${newRule.direction === 'open' ? '开仓' : '平仓'} 溢价率${newRule.condition === 'lt' ? '<' : '>'}${threshold.toFixed(2)}%`,
  }
  try {
    const res = await fetch('/api/rule_engine/rule_add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    const data = await res.json()
    if (data.status === 'ok') {
      message.success('规则已添加')
      // [AI-2026-08-23] 保存用户自定义的交易数量到后端
      triggerQty.value[newRule.fund_code] = {
        lof_qty: newRule.lof_qty,
        etf_qty: newRule.etf_qty,
      }
      // 同时保存到数据库
      try {
        await fetch('/api/rule_engine/trade_config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fund_code: newRule.fund_code, lof_qty: newRule.lof_qty, etf_qty: newRule.etf_qty })
        })
      } catch { /* ignore */ }
      showAddRuleModal.value = false
      fetchRuleEngineStatus()
    } else {
      message.error(data.message || '添加失败')
    }
  } catch { message.error('添加失败') }
}

onMounted(() => {
  fetchRuleEngineStatus()
  ruleTimer = setInterval(fetchRuleEngineStatus, 5000)
})
onUnmounted(() => {
  if (ruleTimer) clearInterval(ruleTimer)
})
</script>

<style scoped>
.auto-trade-container { padding: 16px; background-color: #f8fafc; min-height: 100vh; }
.header-card { padding: 8px 16px; border-radius: 16px; margin-bottom: 12px; }
.header-title { font-size: 20px; font-weight: 800; color: #1e293b; }
.header-subtitle { font-size: 12px; color: #64748b; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex-center { display: flex; align-items: center; }
.gap-4 { gap: 16px; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04); border-radius: 12px; }
</style>
