<template>
  <div style="max-width: 1080px; margin: 0 auto; padding: 4px 2px 40px;">
    <!-- 顶部操作条 -->
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
      <div>
        <h2 style="margin: 0; font-size: 20px; font-weight: 800; color: #1f2937;">后台维护</h2>
        <n-text depth="3" style="font-size: 12px;">
          报告生成：{{ report.generated_at || '—' }}
          <span v-if="report.today"> · 基准日 {{ report.today }}</span>
        </n-text>
      </div>
      <div style="display: flex; align-items: center; gap: 12px;">
        <n-space align="center" :size="6">
          <n-switch v-model:value="autoRefresh" size="small" />
          <n-text style="font-size: 12px; color: #6b7280;">自动刷新(120s)</n-text>
        </n-space>
          <n-button size="small" type="primary" :loading="loading" @click="loadData">
          <template #icon><n-icon><RefreshCw /></n-icon></template>
          刷新
        </n-button>
      </div>
    </div>

    <n-spin :show="loading && !report.local">
      <!-- 健康概览 -->
      <n-card title="程序健康概览" size="small" style="margin-bottom: 12px;">
        <n-grid :cols="2" :x-gap="12" :y-gap="10" responsive="screen" item-responsive>
          <n-gi span="2 m:1">
            <div class="kv">
              <span class="k">本地后端运行时长</span>
              <span class="v">{{ fmtUptime(report.uptime_seconds) }}</span>
            </div>
            <div class="kv">
              <span class="k">H5(ARM) 可达性</span>
              <span class="v">
                <n-tag v-if="report.h5 && !report.h5_error" type="success" size="small" round>可达</n-tag>
                <n-tag v-else type="error" size="small" round>不可达</n-tag>
                <n-text v-if="report.h5_error" depth="3" style="font-size: 11px; margin-left: 6px;">{{ report.h5_error }}</n-text>
              </span>
            </div>
          </n-gi>
          <n-gi span="2 m:1">
            <div class="kv">
              <span class="k">本地数据最旧滞后</span>
              <span class="v"><n-tag :type="worstLocal.type" size="small" round>{{ worstLocal.label }}</n-tag></span>
            </div>
            <div class="kv">
              <span class="k">H5 数据最旧滞后</span>
              <span class="v">
                <n-tag v-if="report.h5" :type="worstH5.type" size="small" round>{{ worstH5.label }}</n-tag>
                <n-text v-else depth="3" style="font-size: 11px;">—</n-text>
              </span>
            </div>
          </n-gi>
        </n-grid>
        <n-alert v-if="hasProblem" type="warning" style="margin-top: 10px;" :show-icon="true">
          检测到数据滞后或缺失，请检查对应采集/同步链路（见下表）。
        </n-alert>
      </n-card>

      <!-- 数据源对比 -->
      <n-card title="各数据源最新日期（本地 vs H5/ARM）" size="small">
        <n-table :bordered="false" :single-line="false" size="small" style="font-size: 12px;">
          <thead>
            <tr>
              <th style="width: 26%;">数据源</th>
              <th style="width: 27%;">本地最新</th>
              <th style="width: 27%;">H5(ARM) 最新</th>
              <th style="width: 20%;">对比 / 状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.key">
              <td style="font-weight: 600; color: #374151;">{{ row.label }}</td>
              <td>
                <span :style="{ color: row.local.type === 'error' ? '#dc2626' : row.local.type === 'warning' ? '#d97706' : '#16a34a' }">
                  {{ row.local.date || '—' }}
                </span>
                <n-tag v-if="row.local.tag" :type="row.local.type" size="tiny" round style="margin-left: 4px;">{{ row.local.tag }}</n-tag>
              </td>
              <td>
                <span v-if="report.h5" :style="{ color: row.h5.type === 'error' ? '#dc2626' : row.h5.type === 'warning' ? '#d97706' : '#16a34a' }">
                  {{ row.h5.date || '—' }}
                </span>
                <n-text v-else depth="3" style="font-size: 11px;">—</n-text>
                <n-tag v-if="report.h5 && row.h5.tag" :type="row.h5.type" size="tiny" round style="margin-left: 4px;">{{ row.h5.tag }}</n-tag>
              </td>
              <td>
                <n-tag :type="row.diff.type" size="small" round>{{ row.diff.label }}</n-tag>
              </td>
            </tr>
          </tbody>
        </n-table>
        <n-text depth="3" style="display: block; margin-top: 10px; font-size: 11px; line-height: 1.6;">
          · 颜色：<span style="color:#16a34a;">绿=新鲜(≤1工作日)</span> /
          <span style="color:#d97706;">橙=轻微滞后(2-3工作日)</span> /
          <span style="color:#dc2626;">红=严重滞后/缺失</span>（已剔除周末，避免休市误报）。<br>
          · 「H5(ARM)」= 线上 H5 所连的 ARM 数据库；若显示「不可达」说明当前网络无法 SSH 到 arm（换到家中/公司网络再试）。<br>
          · 缺失字段一律显示「—」，绝不拿旧值/默认值填补（SUPREME 铁律）。
        </n-text>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import {
  NCard, NTable, NTag, NButton, NIcon, NSpace, NText, NGrid, NGi, NSpin, NSwitch, NAlert
} from 'naive-ui'
import { RefreshCw } from 'lucide-vue-next'

// 数据源展示顺序与中文名
const SOURCE_ORDER: { key: string; label: string }[] = [
  { key: 'lof_price', label: 'LOF/A股 价格' },
  { key: 'lof_nav', label: 'LOF 净值' },
  { key: 'static_val', label: '静态估值' },
  { key: 'us_etf', label: '美股ETF价格' },
  { key: 'fx_mid', label: '汇率(中间价)' },
  { key: 'fx_spot', label: '汇率(在岸价)' },
  { key: 'futures', label: '期货' },
  { key: 'fund_factors', label: '基金因子(woody)' },
  { key: 'index_hist', label: '指数(N225等)' },
  { key: 'vps_sync_date', label: 'VPS同步(东京)' },
]

const report = ref<any>({ local: {}, h5: null })
const loading = ref(false)
const autoRefresh = ref(true)
let timer: any = null

// —— 工作日滞后计算（剔除周末，避免休市误报）——
function workdaysBehind(dateStr: string | null, today: string): number | null {
  if (!dateStr || !today) return null
  const d = new Date(dateStr.slice(0, 10) + 'T00:00:00')
  const t = new Date(today + 'T00:00:00')
  if (isNaN(d.getTime()) || isNaN(t.getTime())) return null
  let cnt = 0
  while (d < t) {
    d.setDate(d.getDate() + 1)
    const wd = d.getDay()
    if (wd !== 0 && wd !== 6) cnt++
  }
  return cnt
}

function assess(dateStr: string | null, today: string) {
  const b = workdaysBehind(dateStr, today)
  if (b === null) return { date: dateStr || '', tag: '缺失', type: 'error' as const }
  if (b <= 1) return { date: dateStr || '', tag: '新鲜', type: 'success' as const }
  if (b <= 3) return { date: dateStr || '', tag: `滞后${b}天`, type: 'warning' as const }
  return { date: dateStr || '', tag: `滞后${b}天`, type: 'error' as const }
}

// 给 VPS 同步附加时间
function cellDate(key: string, obj: any, withTime = false) {
  const d = obj ? obj[key] : null
  if (!d) return d
  if (withTime && key === 'vps_sync_date' && obj.vps_sync_time) return `${d} ${obj.vps_sync_time}`
  return d
}

const rows = computed(() => {
  const today = report.value.today
  const L = report.value.local || {}
  const H = report.value.h5 || {}
  return SOURCE_ORDER.map(s => {
    const lDate = cellDate(s.key, L, true)
    const hDate = cellDate(s.key, H, true)
    const local = assess(lDate, today)
    const h5 = assess(hDate, today)
    // 对比：都缺失 / 仅一方 / 一致性
    let diff: { label: string; type: 'success' | 'warning' | 'error' | 'default' }
    const lb = workdaysBehind(lDate, today)
    const hb = workdaysBehind(hDate, today)
    if (lb === null && hb === null) diff = { label: '都缺失', type: 'error' }
    else if (lb === null) diff = { label: '仅H5有', type: 'warning' }
    else if (hb === null) diff = { label: '仅本地有', type: 'warning' }
    else if (Math.abs(lb - hb) <= 1) diff = { label: '基本一致', type: 'success' }
    else if (lb > hb) diff = { label: `本地新${lb - hb}天`, type: 'warning' }
    else diff = { label: `H5新${hb - lb}天`, type: 'warning' }
    return { key: s.key, label: s.label, local, h5, diff }
  })
})

function worstOf(side: 'local' | 'h5') {
  const today = report.value.today
  const obj = side === 'local' ? report.value.local : report.value.h5
  if (!obj) return { label: '—', type: 'default' as const }
  let maxB = 0
  let missing = false
  for (const s of SOURCE_ORDER) {
    const d = cellDate(s.key, obj, true)
    const b = workdaysBehind(d, today)
    if (b === null) missing = true
    else if (b > maxB) maxB = b
  }
  if (missing) return { label: '存在缺失', type: 'error' as const }
  if (maxB <= 1) return { label: '全部新鲜', type: 'success' as const }
  if (maxB <= 3) return { label: `最旧滞后${maxB}天`, type: 'warning' as const }
  return { label: `最旧滞后${maxB}天`, type: 'error' as const }
}

const worstLocal = computed(() => worstOf('local'))
const worstH5 = computed(() => worstOf('h5'))

const hasProblem = computed(() => {
  return worstLocal.value.type !== 'success' || (report.value.h5 && worstH5.value.type !== 'success')
})

function fmtUptime(sec: number) {
  if (!sec || sec < 0) return '—'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}天${h}小时${m}分`
  if (h > 0) return `${h}小时${m}分`
  return `${m}分`
}

async function loadData() {
  loading.value = true
  try {
    const res = await fetch('/api/system/maintenance-report?t=' + Date.now(), { cache: 'no-store' })
    const data = await res.json()
    if (data.status === 'ok') {
      report.value = data
    } else {
      report.value = { local: {}, h5: null, _error: data.message }
    }
  } catch (e: any) {
    report.value = { local: {}, h5: null, _error: e.message }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
  timer = setInterval(() => { if (autoRefresh.value) loadData() }, 120000)
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.kv { display: flex; align-items: center; justify-content: space-between; padding: 5px 0; border-bottom: 1px dashed #f0f0f0; }
.kv:last-child { border-bottom: none; }
.k { font-size: 12px; color: #6b7280; }
.v { font-size: 13px; font-weight: 600; color: #1f2937; display: flex; align-items: center; }
</style>
