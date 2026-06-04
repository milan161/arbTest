<template>
  <n-layout has-sider position="absolute" style="height: 100vh">
    <n-layout-sider
      bordered
      collapse-mode="width"
      :collapsed-width="64"
      :width="240"
      :collapsed="collapsed"
      show-trigger
      @collapse="collapsed = true"
      @expand="collapsed = false"
      style="background-color: #fff"
    >
      <div class="logo">
        <img src="@/assets/vue.svg" alt="logo" />
        <span v-if="!collapsed">ArbNext</span>
      </div>
      <n-menu
        v-model:value="activeKey"
        :collapsed="collapsed"
        :collapsed-width="64"
        :collapsed-icon-size="22"
        :options="menuOptions"
      />
    </n-layout-sider>
    <n-layout>
      <n-layout-header bordered style="padding: 12px 24px; display: flex; justify-content: space-between; align-items: center; background-color: rgba(255, 255, 255, 0.8); backdrop-filter: blur(10px);">
        <n-text strong style="font-size: 18px">{{ currentTitle }}</n-text>
        <div style="display: flex; gap: 16px; align-items: center">
          <n-tag type="success" round>实时行情已连接</n-tag>
          <n-avatar round size="small" src="https://07akioni.oss-cn-beijing.aliyuncs.com/07akioni.jpeg" />
        </div>
      </n-layout-header>
      <n-layout-content content-style="padding: 24px; background-color: #f0f2f5;">
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
import { ref, h, computed } from 'vue'
import { RouterLink } from 'vue-router'
import { 
  NLayout, 
  NLayoutSider, 
  NLayoutHeader, 
  NLayoutContent, 
  NMenu, 
  NText, 
  NTag, 
  NAvatar, 
  NIcon 
} from 'naive-ui'
import { 
  LayoutDashboard, 
  LineChart, 
  Settings, 
  Database
} from 'lucide-vue-next'

const collapsed = ref(false)
const activeKey = ref('dashboard')

const currentTitle = computed(() => {
  const titles: Record<string, string> = {
    'dashboard': '套利看板',
    'analysis': '深度分析',
    'data': '数据管理',
    'settings': '系统配置'
  }
  return titles[activeKey.value] || 'Dashboard'
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
    label: () => h(RouterLink, { to: '/analysis' }, { default: () => '深度分析' }),
    key: 'analysis',
    icon: renderIcon(LineChart)
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
  }
]
</script>

<style scoped>
.logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 12px;
  color: #333;
  font-size: 20px;
  font-weight: bold;
}
.logo img {
  height: 32px;
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
