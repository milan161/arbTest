import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import Dashboard from '../views/Dashboard.vue'

const privateViews = import.meta.glob('../private/*.vue')

const loadPrivateView = (name: string) => {
  const path = `../private/${name}.vue`
  if (privateViews[path]) {
    return privateViews[path]
  }
  return () => import('../views/Placeholder.vue')
}

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
          component: loadPrivateView('AutoTrade')
        },
        {
          path: 'data',
          name: 'Data',
          component: loadPrivateView('Data')
        },
        {
          path: 'ledger',
          name: 'Ledger',
          component: loadPrivateView('Ledger')
        },
        {
          path: 'settings',
          name: 'Settings',
          component: loadPrivateView('Settings')
        }
      ]
    }
  ]
})

export default router
