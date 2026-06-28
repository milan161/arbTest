import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import Dashboard from '../views/Dashboard.vue'

/**
 * 懒加载 LazyTerminal.vue，文件不存在时降级为 Developing 页面
 * - 本地开发：LazyTerminal.vue 存在 → 正常加载
 * - 开源用户：LazyTerminal.vue 不存在 → 显示"功能开发中"
 */
const LazyTerminal = () => import('../views/LazyTerminal.vue').catch(() => import('../views/Developing.vue'))

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: MainLayout,
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: Dashboard
        },
        {
          path: 'analysis',
          name: 'Analysis',
          component: () => import('../views/Analysis.vue')
        },
        {
          path: 'auto-trade',
          name: 'AutoTrade',
          component: () => import('../views/AutoTrade.vue')
        },
        {
          path: 'data',
          name: 'Data',
          component: () => import('../views/Data.vue')
        },
        {
          path: 'ledger',
          name: 'Ledger',
          component: () => import('../views/Ledger.vue')
        },
        {
          path: 'settings',
          name: 'Settings',
          component: () => import('../views/Settings.vue')
        },
        {
          path: 'etf-rotation',
          name: 'ETFRotation',
          component: () => import('../views/ETFRotation.vue')
        },
        {
          path: 'lazymode',
          name: 'LazyMode',
          component: () => import('../views/DongGeSecret.vue')
        },
        {
          path: 'lazy',
          name: 'LazyTerminal',
          component: LazyTerminal
        },
        {
          path: 'developing',
          name: 'Developing',
          component: () => import('../views/Developing.vue')
        }
      ]
    }
  ]
})

export default router
