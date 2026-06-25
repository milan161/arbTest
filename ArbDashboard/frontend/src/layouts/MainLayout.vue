<template>
  <n-layout has-sider position="absolute" style="height: 100vh">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="180"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
      style="background-color: #ffffff; display: flex; flex-direction: column;"
    >
      <div class="logo">
        <n-avatar 
          round 
          :size="32" 
          color="#3B82F6" 
          style="font-weight: bold; color: white;"
        >
          ARB
        </n-avatar>
        <span v-if="!collapsed" class="logo-text">ArbNext</span>
      </div>
      
      <div style="flex-grow: 1; overflow-y: auto;">
        <n-menu
          v-model:value="activeKey"
          :collapsed="collapsed"
          :collapsed-width="64"
          :collapsed-icon-size="22"
          :options="menuOptions"
          class="custom-menu"
        />
      </div>

      <!-- 时钟移到左下角 -->
      <div v-if="!collapsed" class="sidebar-footer">
        <div class="time-box-sidebar">
          <div class="date">{{ currentDate }}</div>
          <div class="time">{{ currentTime }}</div>
        </div>
        <div class="exchange-rates">
          <div class="rate-group">
            <div class="rate-label">美元/人民币 (中间价)</div>
            <div class="rate-row">
              <span class="rate-value">{{ rates.usd_cny_mid || '-' }}</span>
              <span :class="['rate-change', rates.usd_change >= 0 ? 'up' : 'down']">
                {{ formatChange(rates.usd_change) }}
              </span>
            </div>
          </div>
          <div class="rate-group" style="margin-top: 10px;">
            <div class="rate-label">港币/人民币 (中间价)</div>
            <div class="rate-row">
              <span class="rate-value">{{ rates.hkd_cny_mid || '-' }}</span>
              <span :class="['rate-change', rates.hkd_change >= 0 ? 'up' : 'down']">
                {{ formatChange(rates.hkd_change) }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height: 30px; display: flex; align-items: center; justify-content: flex-end; padding: 0 20px; background: #ffffff;">
          <div v-if="showDataAlert" class="nav-alert-bar">
            <n-icon size="14" color="#d97706"><AlertTriangle /></n-icon>
            <span>{{ navAlertText }}</span>
            <router-link to="/data" style="color: #d97706; font-weight: 700; margin-left: 6px; text-decoration: underline;">前往更新 →</router-link>
          </div>
        </n-layout-header>
        <n-layout-content content-style="padding: 10px; background-color: #f6f8fb; height: calc(100vh - 30px); overflow: auto;">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>

<script setup lang="ts">
import { ref, h, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import { 
  NLayout, 
  NLayoutSider, 
  NLayoutHeader, 
  NLayoutContent, 
  NMenu, 
  NAvatar, 
  NIcon,
  NText,
  NDivider
} from 'naive-ui'
import { 
  LayoutDashboard, 
  LineChart, 
  Settings, 
  Database,
  Bot,
  Activity,
  BookOpen,
  AlertTriangle,
  Repeat,
  Cpu,
} from 'lucide-vue-next'

const collapsed = ref(false)
const activeKey = ref('dashboard')

const currentDate = ref('')
const currentTime = ref('')
const showDataAlert = ref(false)
const navAlertText = ref('')
const rates = ref({
  usd_cny_mid: '',
  hkd_cny_mid: '',
  usd_change: 0,
  hkd_change: 0
})
let timer: any = null

const updateTime = () => {
  const now = new Date()
  currentDate.value = now.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  currentTime.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

const formatChange = (val: number) => {
  if (val === undefined || val === null) return '-'
  const sign = val >= 0 ? '+' : ''
  return `${sign}${val.toFixed(2)}%`
}

const fetchRates = async () => {
  try {
    const res = await fetch('/api/market/overview')
    const data = await res.json()
    if (data.status === 'ok') {
      rates.value.usd_cny_mid = data.data?.rates?.usd_cny_mid || '-'
      rates.value.hkd_cny_mid = data.data?.rates?.hkd_cny_mid || '-'
      rates.value.usd_change = data.data?.usd_change || 0
      rates.value.hkd_change = data.data?.hkd_change || 0
      console.log('汇率数据:', rates.value)
    }
  } catch (e) {
    console.error('获取汇率失败', e)
  }
}

const fetchNavAlert = async () => {
  try {
    const res = await fetch('/api/system/nav-status')
    const data = await res.json()
    if (data.status === 'ok') {
      const todayUpdated = data.data.today_updated
      const lastTime = data.data.last_updated_time
      // 15:00 之后还没更新过净值 → 显示提醒
      const now = new Date()
      const hour = now.getHours()
      const minute = now.getMinutes()
      const isWeekend = now.getDay() === 0 || now.getDay() === 6
      if (!isWeekend && hour >= 15 && !todayUpdated) {
        showDataAlert.value = true
        navAlertText.value = '今日净值尚未补采，部分基金可能显示过期数据'
      } else if (!isWeekend && hour >= 15 && todayUpdated) {
        showDataAlert.value = true
        navAlertText.value = `今日净值已更新 (${lastTime})`
      } else {
        showDataAlert.value = false
      }
    }
  } catch (e) { /* ignore */ }
}

onMounted(() => {
  updateTime()
  fetchRates()
  fetchNavAlert()
  timer = setInterval(() => {
    updateTime()
  }, 1000) // 时钟每秒更新
  // 每 5 分钟刷新净值状态
  setInterval(fetchNavAlert, 300000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

function renderIcon(icon: any) {
  return () => h(NIcon, null, { default: () => h(icon) })
}

const menuOptions = [
  {
    label: () => h(RouterLink, { to: '/dashboard' }, { default: () => '套利看板' }),
    key: 'dashboard',
    icon: renderIcon(LayoutDashboard)
  },
  {
    label: () => h(RouterLink, { to: '/analysis' }, { default: () => '实时沙盘' }),
    key: 'analysis',
    icon: renderIcon(LineChart)
  },
  {
    label: () => h(RouterLink, { to: '/auto-trade' }, { default: () => '信号监视' }),
    key: 'auto-trade',
    icon: renderIcon(Activity)
  },
  {
    label: () => h(RouterLink, { to: '/ledger' }, { default: () => '盘后对账' }),
    key: 'ledger',
    icon: renderIcon(BookOpen)
  },
  {
    label: () => h(RouterLink, { to: '/etf-rotation' }, { default: () => 'ETF轮动' }),
    key: 'etf-rotation',
    icon: renderIcon(Repeat)
  },
  {
    label: () => h(RouterLink, { to: '/data' }, { default: () => '数据管理' }),
    key: 'data',
    icon: renderIcon(Database)
  },
  {
    label: () => h(RouterLink, { to: '/settings' }, { default: () => '系统配置' }),
    key: 'settings',
    icon: renderIcon(Settings)
  },
  {
    label: () => h(RouterLink, { to: '/lazymode' }, { default: () => '我的交易' }),
    key: 'lazymode',
    icon: renderIcon(Bot)
  }
]
</script>

<style scoped>
.logo { height: 58px; display: flex; align-items: center; padding: 0 14px; gap: 10px; }
.logo-text { font-size: 18px; font-weight: 800; background: linear-gradient(120deg, #1d4ed8, #0891b2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.sidebar-footer { padding: 14px; border-top: 1px solid #edf1f7; background: #fbfdff; }
.time-box-sidebar { display: flex; flex-direction: column; align-items: center; }
.time-box-sidebar .date { font-size: 11px; color: #7b8a9b; }
.time-box-sidebar .time { font-size: 14px; font-weight: bold; color: #2563eb; font-family: monospace; }
.exchange-rates { margin-top: 15px; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; }
.rate-group { display: flex; flex-direction: column; }
.rate-label { font-size: 11px; color: #64748b; margin-bottom: 4px; white-space: nowrap; font-weight: 500; }
.rate-row { display: flex; align-items: baseline; justify-content: space-between; gap: 4px; }
.rate-value { font-size: 16px; font-weight: 800; color: #1e293b; font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.rate-change { font-size: 12px; font-weight: 700; }
.rate-change.up { color: #ef4444; }
.rate-change.down { color: #22c55e; }
:deep(.n-menu-item-content--selected) { background-color: #eff6ff !important; }
:deep(.n-menu-item-content--selected .n-menu-item-content-header a) { color: #2563eb !important; }
:deep(.n-menu-item-content) { border-radius: 8px; margin: 2px 8px; color: #526173; font-weight: 650; }
.nav-alert-bar {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #92400e;
  background: #fffbeb; border: 1px solid #fde68a;
  padding: 2px 12px; border-radius: 12px;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
