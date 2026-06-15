/**
 * 应用全局状态 Store
 * - 引擎状态、系统里程碑、数据源状态
 * - IB 重连、引擎重启等系统操作
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export const useAppStore = defineStore('app', () => {
  // ---- state ----
  const engineRunning = ref(false)
  const milestones = ref<any[]>([])
  const reconnectingIB = ref(false)
  const reconnectingEngine = ref(false)

  // ---- actions ----
  async function fetchSystemStatus() {
    try {
      const [milestoneRes, engineRes] = await Promise.all([
        api.getMilestones(),
        api.getAutoTradeStatus()
      ])
      if (milestoneRes.data?.status === 'ok') {
        milestones.value = milestoneRes.data.data || []
      }
      if (engineRes.data?.status === 'ok') {
        engineRunning.value = engineRes.data.running
      }
    } catch (err) {
      console.error('获取系统状态失败', err)
    }
  }

  async function reconnectIB() {
    reconnectingIB.value = true
    try {
      const res = await api.reconnectIB()
      return res.data
    } finally {
      reconnectingIB.value = false
    }
  }

  async function reconnectEngine() {
    reconnectingEngine.value = true
    try {
      const res = await api.reconnectEngine()
      return res.data
    } finally {
      reconnectingEngine.value = false
    }
  }

  async function triggerTask(task: string) {
    try {
      const res = await api.triggerTask(task)
      return res.data
    } catch (err) {
      console.error('触发任务失败', err)
      return { status: 'error', message: '触发失败' }
    }
  }

  return {
    engineRunning, milestones,
    reconnectingIB, reconnectingEngine,
    fetchSystemStatus,
    reconnectIB, reconnectEngine,
    triggerTask
  }
})
