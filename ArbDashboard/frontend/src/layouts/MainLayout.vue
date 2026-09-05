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
          :theme-overrides="menuThemeOverrides"
          class="custom-menu"
        />
      </div>

      <div class="sidebar-footer">
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px;">
          <n-tag :type="hasTdx ? 'success' : 'warning'" size="small" round
            :style="{ fontWeight: 'bold', cursor: hasTdx ? 'default' : 'pointer', width: '100%', justifyContent: 'center' }"
            @click="reconnectWithGuard(hasTdx, '通达信', reconnectTdx)">
            <template #icon><n-icon><Zap /></n-icon></template>
            通达信
          </n-tag>
          <n-tag :type="hasIb ? 'success' : 'warning'" size="small" round
            :style="{ fontWeight: 'bold', cursor: 'pointer', width: '100%', justifyContent: 'center' }"
            @click="reconnectIB()">
            <template #icon><n-icon><Zap /></n-icon></template>
            IB
          </n-tag>
          <n-tag :type="hasGalaxy ? 'success' : 'warning'" size="small" round
            :style="{ fontWeight: 'bold', cursor: hasGalaxy ? 'default' : 'pointer', width: '100%', justifyContent: 'center' }"
            @click="reconnectWithGuard(hasGalaxy, '银河QMT', reconnectGalaxy)">
            <template #icon><n-icon><Zap /></n-icon></template>
            银河QMT
          </n-tag>
           <n-tag :type="hasFutu ? 'success' : 'warning'" size="small" round
              :style="{ fontWeight: 'bold', cursor: 'pointer', width: '100%', justifyContent: 'center' }"
              @click="reconnectFutu()">
              <template #icon><n-icon><Zap /></n-icon></template>
              富途
           </n-tag>
           <n-tag :type="hasGuojin ? 'success' : 'warning'" size="small" round
             :style="{ fontWeight: 'bold', cursor: hasGuojin ? 'default' : 'pointer', width: '100%', justifyContent: 'center' }"
             @click="reconnectWithGuard(hasGuojin, '国金QMT', reconnectGuojin)">
             <template #icon><n-icon><Zap /></n-icon></template>
             国金QMT
           </n-tag>
         </div>
      </div>
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="height: 30px; display: flex; align-items: center; justify-content: flex-end; padding: 0 20px; background: #ffffff;">
          <div v-if="showDataAlert" class="nav-alert-bar">
            <n-icon size="14" color="#d97706"><AlertTriangle /></n-icon>
            <span>{{ navAlertText }}</span>
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
import { storeToRefs } from 'pinia'
import { 
  NLayout, 
  NLayoutSider, 
  NLayoutHeader, 
  NLayoutContent, 
  NMenu, 
  NAvatar, 
  NIcon,
  NText,
  NTag,
  useMessage
} from 'naive-ui'
import { 
  LayoutDashboard, 
  Settings, 
  Activity,
  BookOpen,
  AlertTriangle,
  Repeat,
  Zap,
  ServerCog,
  PieChart,
} from 'lucide-vue-next'
import { useAppStore, useMarketStore } from '../store'

const collapsed = ref(false)
const activeKey = ref('dashboard')

// [AI-2026-08-07] 压缩菜单行高：naive-ui 菜单项高度由主题变量 itemHeight 控制(默认42px)，
// 单改 padding 无效(项高固定、内容垂直居中)，必须覆写 itemHeight 才能真正变矮。
const menuThemeOverrides = {
  itemHeight: '32px'
}

const showDataAlert = ref(false)
const navAlertText = ref('')

const message = useMessage()
const appStore = useAppStore()
const marketStore = useMarketStore()

const { hasTdx, hasIb, hasGalaxy, hasGuojin, hasFutu, hasFutuNoData } = storeToRefs(marketStore)



// ===== Reconnect 引擎状态 =====
const refreshStatus = () => marketStore.fetchOverview()

const reconnectIB = async () => {
  appStore.reconnectingIB = true
  try {
    const data = await appStore.reconnectIB()
    if (data.status === 'ok') {
      message.success('IB 重连成功！')
      refreshStatus()
    } else {
      message.error('IB 重连失败，请确保 TWS 已运行。')
    }
  } catch (e: any) {
    message.error('重连请求失败: ' + e.message)
  } finally {
    appStore.reconnectingIB = false
  }
}

const reconnectEngine = async (sourceLabel: string, reconnectFn: () => Promise<any>) => {
  try {
    const data = await reconnectFn()
    if (data.status === 'ok') {
      message.success(`${sourceLabel} 重连成功！`)
      refreshStatus()
    } else if (data.status === 'pending') {
      // [AI-2026-08-20] 异步重连：后端立即返回 pending，连接结果经状态栏轮询体现
      message.info(`${sourceLabel} ${data.message || '重连中，请稍候'}`)
      refreshStatus()
    } else {
      message.warning(`${sourceLabel} 重连未就绪: ${data.message}`)
    }
  } catch (e: any) {
    message.error(`${sourceLabel} 重连异常: ${e.message}`)
  }
}

const reconnectWithGuard = (isConnected: boolean, label: string, fn: () => void) => {
  if (isConnected) return
  fn()
}

const reconnectTdx = () => reconnectEngine('通达信', () => marketStore.reconnectTdx())
const reconnectGalaxy = () => reconnectEngine('银河QMT', () => marketStore.reconnectGalaxy())
const reconnectGuojin = () => reconnectEngine('国金QMT', () => marketStore.reconnectGuojin())
const reconnectFutu = () => reconnectEngine('富途', () => marketStore.reconnectFutu())

const fetchNavAlert = async () => {
  try {
    const res = await fetch('/api/system/nav-status')
    const data = await res.json()
    if (data.status === 'ok') {
      const todayUpdated = data.data.today_updated
      const lastTime = data.data.last_updated_time
      const now = new Date()
      const hour = now.getHours()
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
  fetchNavAlert()
  setInterval(fetchNavAlert, 300000)
  // [AI-2026-07-15] 定期刷新数据源连接状态，避免 IB/富途退出后标签仍显示绿色
  marketStore.fetchOverview()
  setInterval(() => marketStore.fetchOverview(), 30000)
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
    label: () => h(RouterLink, { to: '/penetration' }, { default: () => '穿透分析' }),
    key: 'penetration',
    icon: renderIcon(PieChart)
  },
  {
    label: () => h(RouterLink, { to: '/settings' }, { default: () => '系统配置' }),
    key: 'settings',
    icon: renderIcon(Settings)
  },
  {
    label: () => h(RouterLink, { to: '/maintenance' }, { default: () => '后台维护' }),
    key: 'maintenance',
    icon: renderIcon(ServerCog)
  }
]
</script>

<style scoped>
.logo { height: 46px; display: flex; align-items: center; padding: 0 14px; gap: 10px; }
.logo-text { font-size: 18px; font-weight: 800; background: linear-gradient(120deg, #1d4ed8, #0891b2); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.sidebar-footer { padding: 8px; border-top: 1px solid #edf1f7; background: #fbfdff; }
:deep(.n-menu-item-content--selected) { background-color: #eff6ff !important; }
:deep(.n-menu-item-content--selected .n-menu-item-content-header a) { color: #2563eb !important; }
:deep(.n-menu-item) { height: 32px !important; }
:deep(.n-menu-item-content) { border-radius: 8px; margin: 0 8px; color: #526173; font-weight: 650; }
.nav-alert-bar {
  display: flex; align-items: center; gap: 6px;
  font-size: 12px; color: #92400e;
  background: #fffbeb; border: 1px solid #fde68a;
  padding: 2px 12px; border-radius: 12px;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
