import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import Dashboard from '../views/Dashboard.vue'

/**
 * 懒加载 LazyMode.vue（private/），文件不存在时降级为 DongGeSecret 占位页
 * - 本地开发：LazyMode.vue 存在 → 正常加载（内部做角色判断）
 * - 开源用户：看不到 private/，路由指向 DongGeSecret.vue（锁页）
 */
const LazyMode = () => import('../private/LazyMode.vue').catch(() => import('../views/DongGeSecret.vue'))

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
          component: LazyMode
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
