import { createRouter, createWebHistory } from 'vue-router'
import MainLayout from '../layouts/MainLayout.vue'
import Dashboard from '../views/Dashboard.vue'

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
          path: 'data',
          name: 'Data',
          component: () => import('../views/Placeholder.vue')
        },
        {
          path: 'settings',
          name: 'Settings',
          component: () => import('../views/Placeholder.vue')
        }
      ]
    }
  ]
})

export default router
