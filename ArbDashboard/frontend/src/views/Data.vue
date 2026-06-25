<template>
  <div class="data-management p-6">
    <n-grid :cols="24" :x-gap="16" :y-gap="16">
      <!-- 左侧：数据同步状态 -->
      <n-gi :span="14">
        <n-card title="数据同步状态" class="shadow-soft">
          <template #header-extra>
            <n-tag v-if="morningReady" type="success" ghost size="small">清晨数据已完成</n-tag>
            <n-tag v-else type="warning" ghost size="small">等待 9:20 自动同步</n-tag>
          </template>

          <!-- 时间线说明 -->
          <n-alert type="info" :bordered="false" closable style="margin-bottom: 16px;">
            <template #header>每日数据更新时间线</template>
            <div style="font-size: 13px; line-height: 1.8;">
              <div><strong>9:20</strong> — Woody API、官方汇率、VPS 期货/份额数据就绪，<strong>系统自动刷新</strong></div>
              <div><strong>16:00~21:00</strong> — 基金净值分批发货，系统在 18:00 / 19:30 / 21:00 自动补跑，也支持手动触发</div>
            </div>
          </n-alert>

          <div class="data-status-grid">
            <div v-for="item in dataSources" :key="item.key" class="data-status-item">
              <div class="ds-left">
                <n-icon size="18" :color="item.synced ? '#16a34a' : '#d97706'">
                  <CheckCircle v-if="item.synced" />
                  <Clock v-else />
                </n-icon>
                <div class="ds-info">
                  <div class="ds-name">{{ item.label }}</div>
                  <div class="ds-desc">{{ item.desc }}</div>
                </div>
              </div>
              <div class="ds-right">
                <n-tag v-if="item.synced" type="success" size="tiny" round>已同步</n-tag>
                <n-tag v-else type="warning" size="tiny" round>等待中</n-tag>
              </div>
            </div>
          </div>

          <!-- 净值特殊处理：手动按钮 -->
          <n-divider title-placement="left">基金净值</n-divider>
          <div class="nav-action-card">
            <div class="nav-action-info">
              <div class="nav-title">净值补采</div>
              <div class="nav-desc">
                基金净值在每日 16:00~21:00 陆续发布。系统会在 18:00 / 19:30 / 21:00 自动尝试补采。
                <span v-if="navLastTime">上次更新: {{ navLastTime }}</span>
              </div>
            </div>
            <n-button type="warning" @click="triggerNavUpdate" :loading="navRunning">
              <template #icon><n-icon><RefreshCw /></n-icon></template>
              立即更新净值
            </n-button>
          </div>

          <n-divider title-placement="left">静态估值 (012)</n-divider>
          <div class="task-grid">
            <div v-for="task in manualTasks" :key="task.id" class="task-item">
              <div class="task-info">
                <div class="task-name">{{ task.name }}</div>
                <div class="task-desc">{{ task.desc }}</div>
              </div>
              <n-button :type="task.type" size="small" @click="triggerTask('012')" :loading="task.running">
                <template #icon><n-icon><Play /></n-icon></template>
                立即执行
              </n-button>
            </div>
          </div>

          <n-divider title-placement="left">系统自检</n-divider>
          <div class="task-grid">
            <div class="task-item">
              <div class="task-info">
                <div class="task-name">一键自检</div>
                <div class="task-desc">检查静态估值完整性、同步新鲜度、数据库健康</div>
              </div>
              <n-button type="primary" size="small" @click="runHealthCheck" :loading="healthRunning">
                <template #icon><n-icon><Activity /></n-icon></template>
                立即自检
              </n-button>
            </div>
            <!-- 自检结果 -->
            <n-collapse v-if="healthResult" :default-expanded-names="['result']" accordion>
              <n-collapse-item title="自检报告" name="result">
                <div class="health-result">
                  <n-tag :type="healthResult.status === 'healthy' ? 'success' : 'warning'" size="small" round>
                    {{ healthResult.status === 'healthy' ? '✅ 健康' : '⚠️ 异常' }}
                  </n-tag>
                  <div style="margin-top: 8px;">
                    <div v-if="healthResult.issues.length === 0" class="text-green-600 font-medium">无异常</div>
                    <div v-for="(issue, i) in healthResult.issues" :key="i" class="health-issue">
                      <n-icon size="14" color="#d97706" style="margin-right: 4px;"><AlertTriangle /></n-icon>
                      {{ issue }}
                    </div>
                  </div>
                  <n-divider />
                  <div class="health-stats">
                    <div>基金总数: {{ healthResult.stats.fund_count }}</div>
                    <div>数据总条数: {{ healthResult.stats.total_records }}</div>
                    <div>检查日期: {{ healthResult.stats.checked_dates?.join(', ') }}</div>
                  </div>
                </div>
              </n-collapse-item>
            </n-collapse>
          </div>

          <n-divider title-placement="left">执行日志终端</n-divider>
          <div class="terminal-box">
             <div v-if="taskLogs.length === 0" class="text-gray-500 italic">等待任务启动...</div>
             <div v-for="(log, i) in taskLogs" :key="i" class="log-line">
                <span class="text-blue-400">>>></span> {{ log }}
             </div>
          </div>
        </n-card>
      </n-gi>

      <!-- 右侧：基金配置（保持不变） -->
      <n-gi :span="10">
        <n-card title="核心基金配置" class="shadow-soft">
          <template #header-extra>
            <n-space>
              <n-button size="tiny" @click="handleImportClick">导入</n-button>
              <n-button size="tiny" @click="handleExportClick">导出</n-button>
            </n-space>
          </template>
          <div class="mb-3">
            <n-select v-model:value="selectedTab" :options="tabOptions" placeholder="选择基金分类" clearable style="width: 100%;" />
          </div>
          <div style="height: 260px; overflow-y: auto;">
            <n-list small hoverable clickable v-if="filteredFunds.length > 0">
              <n-list-item v-for="f in filteredFunds" :key="f.code" @click="editFund(f)">
                <div class="flex-between">
                  <div>
                    <n-text strong>{{ f.code }}</n-text>
                    <n-text depth="3" style="margin-left: 8px;">{{ f.name }}</n-text>
                  </div>
                  <span :style="getCategoryBadgeStyle(f.category)">{{ f.category }}</span>
                </div>
              </n-list-item>
            </n-list>
            <n-empty v-else description="该分类下暂无基金配置" />
          </div>
          <n-button block type="primary" style="margin-top: 12px;" @click="addNewFund">
             新增基金
          </n-button>
        </n-card>

        <n-card :bordered="false" class="shadow-soft private-card" style="margin-top: 16px;">
          <template #header>
             <div class="flex-center gap-2">
                <n-icon size="18" color="#64748b"><Database /></n-icon>
                <span>自留地</span>
             </div>
          </template>
          <div class="p-2 text-center" v-if="!isPrivateVisible">
            <n-button quaternary block @click="checkPrivateAccess">进入私有空间</n-button>
          </div>
          <div v-else class="p-2 animate-fade-in">
            <n-text depth="3" style="font-size: 11px; display: block; margin-bottom: 12px; color: #94a3b8;">
               * 该功能仅在本地环境且加载私有插件时可用
            </n-text>
            <n-form-item label="选择导出基金">
               <n-input v-model:value="exportCode" placeholder="输入 6 位代码" />
               <div class="flex gap-2 mt-2">
                  <n-button v-for="code in quickCodes" :key="code" size="small" secondary @click="exportCode = code">
                     {{ code }}
                  </n-button>
               </div>
            </n-form-item>
            <n-button type="primary" block style="margin-top: 10px;" @click="handleExport" :disabled="!exportCode">
              <template #icon><n-icon><FileDown /></n-icon></template>
              导出
            </n-button>
          </div>
        </n-card>
      </n-gi>
    </n-grid>

    <!-- 基金配置编辑弹窗（保持不变） -->
    <n-modal v-model:show="showFundModal" preset="card" :title="editMode ? '编辑基金参数' : '新增基金参数'" style="width: 600px;">
      <n-form :model="fundForm" label-placement="left" label-width="100">
         <n-grid :cols="2" :x-gap="12">
            <n-gi>
               <n-form-item label="基金代码">
                  <n-input v-model:value="fundForm.code" placeholder="如 162411" :disabled="editMode" />
               </n-form-item>
            </n-gi>
            <n-gi>
               <n-form-item label="基金名称">
                  <n-input v-model:value="fundForm.name" />
               </n-form-item>
            </n-gi>
            <n-gi>
               <n-form-item label="内盘分类">
                  <n-input v-model:value="fundForm.category" />
               </n-form-item>
            </n-gi>
            <n-gi>
               <n-form-item label="仓位(%)">
                  <n-input-number v-model:value="fundForm.holdings.equity_ratio" :step="0.1" style="width:100%" />
               </n-form-item>
            </n-gi>
            <n-gi>
               <n-form-item label="交易ETF">
                  <n-input v-model:value="fundForm.trade_etf" placeholder="如 XOP" />
               </n-form-item>
            </n-gi>
            <n-gi>
               <n-form-item label="交易期货">
                  <n-input v-model:value="fundForm.trade_future" />
               </n-form-item>
            </n-gi>
         </n-grid>
         <n-divider title-placement="left">实时估值篮子 (Portfolio)</n-divider>
         <div v-for="(item, index) in fundForm.valuation_portfolio" :key="index" class="portfolio-item">
            <n-space align="center">
               <n-input v-model:value="item.symbol" placeholder="标的" style="width:120px" />
               <n-input-number v-model:value="item.weight" placeholder="权重" style="width:100px" />
               <n-select v-model:value="item.anchor" :options="anchorOptions" style="width:120px" />
               <n-button quaternary circle type="error" @click="fundForm.valuation_portfolio.splice(index, 1)">
                  <template #icon><n-icon><Trash2 /></n-icon></template>
               </n-button>
            </n-space>
         </div>
         <n-button dashed block @click="fundForm.valuation_portfolio.push({symbol: '', weight: 100, anchor: 'US'})" style="margin-top:8px">
            + 添加估值成分
         </n-button>
         <div class="flex-end gap-2 mt-6">
            <n-button v-if="editMode" type="error" quaternary @click="handleDeleteFund">删除该基金</n-button>
            <n-space>
               <n-button @click="showFundModal = false">取消</n-button>
               <n-button type="primary" @click="handleSaveFund">保存到 YAML</n-button>
            </n-space>
         </div>
      </n-form>
    </n-modal>

    <!-- 导入 YAML 弹窗 -->
    <n-modal v-model:show="showImportModal" preset="card" title="导入基金配置" style="width: 500px;">
      <n-alert type="warning" :bordered="false" style="margin-bottom: 16px;">
        导入将<strong>覆盖</strong>当前所有基金配置，旧配置会自动备份为 .bak 文件。
      </n-alert>
      <n-upload
        :default-upload="false"
        accept=".yaml,.yml"
        :max="1"
        @change="handleFileChange"
      >
        <n-button>选择 YAML 文件</n-button>
      </n-upload>
      <div v-if="importFile" style="margin-top: 12px; padding: 8px 12px; background: #f0f9ff; border-radius: 6px;">
        <n-text>{{ importFile.name }}</n-text>
        <n-text depth="3" style="margin-left: 8px;">({{ (importFile.size / 1024).toFixed(1) }} KB)</n-text>
      </div>
      <div class="flex-end gap-2 mt-6">
        <n-button @click="showImportModal = false">取消</n-button>
        <n-button type="primary" @click="handleImportConfirm" :loading="importLoading" :disabled="!importFile">确认导入</n-button>
      </div>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  NCard, NGrid, NGi, NButton, NIcon, NTag, NDivider, NFormItem, NInput, useMessage, NSpace, NText,
  NList, NListItem, NEmpty, NModal, NForm, NInputNumber, NSelect, NAlert, NCollapse, NCollapseItem, NUpload
} from 'naive-ui'
import { Play, FileDown, Database, Trash2, HelpCircle, RefreshCw, CheckCircle, Clock, Activity, AlertTriangle } from 'lucide-vue-next'
import { triggerTask as triggerSystemTask, getFundConfigs, upsertFundConfig, deleteFundConfig, exportFundConfig, importFundConfig } from '../api'
import { TAB_CATEGORIES } from '../store/fundStore'
import { getDataStatus, getNavStatus, getSystemHealthCheck } from '../api/systemApi'
import client from '../api/client'

const message = useMessage()
const taskLogs = ref<string[]>([])
const exportCode = ref('')
const isPrivateVisible = ref(false)
const quickCodes = ['162411', '164701', '164824']

// 导入导出状态
const showImportModal = ref(false)
const importFile = ref<File | null>(null)
const importLoading = ref(false)

const handleImportClick = () => {
  importFile.value = null
  showImportModal.value = true
}

const handleFileChange = (data: { file: any; fileList: any[] }) => {
  importFile.value = data.file.file || null
}

const handleExportClick = async () => {
  try {
    const res = await exportFundConfig()
    const blob = new Blob([res.data], { type: 'application/x-yaml' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    const ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)
    link.setAttribute('download', `lof_config_${ts}.yaml`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success('配置已导出')
  } catch (e: any) {
    message.error('导出失败: ' + (e.message || '未知错误'))
  }
}

const handleImportConfirm = async () => {
  if (!importFile.value) return
  importLoading.value = true
  try {
    await importFundConfig(importFile.value)
    message.success('导入成功，配置已更新')
    showImportModal.value = false
    importFile.value = null
    fetchFundConfigs()
  } catch (e: any) {
    const errMsg = e?.response?.data?.message || e.message || '未知错误'
    message.error('导入失败: ' + errMsg)
  } finally {
    importLoading.value = false
  }
}

const tabOptions = [
  { label: '黄金原油', value: '黄金原油' },
  { label: 'QDII欧美', value: 'QDII欧美' },
  { label: 'QDII亚洲', value: 'QDII亚洲' },
  { label: '国内LOF', value: '国内LOF' },
  { label: '白银', value: '白银' },
  { label: '现金管理', value: '现金管理' }
]
const selectedTab = ref('')

const filteredFunds = computed(() => {
  if (!selectedTab.value) return fundConfigs.value
  const categories = TAB_CATEGORIES[selectedTab.value] || []
  if (categories.length === 0) return fundConfigs.value
  return fundConfigs.value.filter(f => categories.includes(f.category))
})

// 数据同步状态
const dataSources = ref<any[]>([])
const morningReady = ref(false)
const navLastTime = ref('')
const navRunning = ref(false)

// 自检状态
const healthRunning = ref(false)
const healthResult = ref<any>(null)

const runHealthCheck = async () => {
  healthRunning.value = true
  taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 系统自检启动...`)
  try {
    const res = await getSystemHealthCheck()
    healthResult.value = res.data
    taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 自检完成: ${res.data.issues.length} 项异常`)
    if (res.data.issues.length === 0) {
      message.success('系统自检通过 ✅')
    } else {
      message.warning(`发现 ${res.data.issues.length} 项异常`)
    }
  } catch (e: any) {
    message.error(`自检失败: ${e.message}`)
    taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 自检失败: ${e.message}`)
  } finally {
    healthRunning.value = false
  }
}

// 基金配置状态
const fundConfigs = ref<any[]>([])
const showFundModal = ref(false)
const editMode = ref(false)
const fundForm = reactive<any>({
  code: '', name: '', category: '',
  trade_etf: '', trade_future: '',
  holdings: { equity_ratio: 95.0 },
  valuation_portfolio: [],
  redemption_fee_rate: 0.5,
  commission_rate: 0
})

const anchorOptions = [
  { label: '美股收盘 (US)', value: 'US' },
  { label: '欧洲时刻 (EU)', value: 'EU' },
  { label: '日本时刻 (JP)', value: 'JP' },
  { label: '香港时刻 (HK)', value: 'HK' }
]

const manualTasks = reactive([
  {
    id: '012',
    name: '静态估值 (012)',
    desc: '根据历史原材料重算静态估值',
    type: 'info',
    running: false
  }
])

const getCategoryBadgeStyle = (cat: string) => {
    let textColor = '#4b5563';
    let bgColor = '#f3f4f6';
    if (cat.includes('黄金')) { textColor = '#d97706'; bgColor = '#fef3c7'; }
    else if (cat.includes('原油')) { textColor = '#475569'; bgColor = '#f1f5f9'; }
    else if (cat.includes('指数')) { textColor = '#2563eb'; bgColor = '#dbeafe'; }
    else if (cat.includes('跨境') || cat.includes('欧美') || cat.includes('亚洲') || cat.includes('纯ETF') || cat.includes('混合')) { textColor = '#dc2626'; bgColor = '#fee2e2'; }
    else if (cat.includes('白银')) { textColor = '#059669'; bgColor = '#d1fae5'; }
    return { color: textColor, backgroundColor: bgColor, padding: '3px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: 'bold', display: 'inline-block', lineHeight: '1.2' };
}

const fetchDataStatus = async () => {
  try {
    const res = await getDataStatus()
    if (res.data.status === 'ok') {
      const d = res.data.data
      morningReady.value = d.morning_ready
      const sources = d.sources
      dataSources.value = [
        { key: 'woody_lof_batch', label: 'Woody 因子', desc: 'QDII 基金估值因子数据', synced: sources.woody_lof_batch.synced },
        { key: 'official_exchange_rate', label: '官方汇率', desc: '美元/人民币中间价', synced: sources.official_exchange_rate.synced },
        { key: 'futures_data', label: '期货结算价', desc: '黄金/原油/白银/指数期货', synced: sources.futures_data.synced },
        { key: 'jsl_shares_data', label: '场内份额', desc: '深交所 LOF 基金份额数据', synced: sources.jsl_shares_data.synced }
      ]
    }
  } catch (e) { /* ignore */ }
}

const fetchNavStatus = async () => {
  try {
    const res = await getNavStatus()
    if (res.data.status === 'ok') {
      navLastTime.value = res.data.data.last_updated_time
        ? `${res.data.data.last_updated_date} ${res.data.data.last_updated_time}`
        : ''
    }
  } catch (e) { /* ignore */ }
}

const triggerNavUpdate = async () => {
  navRunning.value = true
  taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 净值更新启动...`)
  try {
    const res = await triggerSystemTask('nav')
    if (res.data.status === 'ok') {
      message.success('净值更新已后台运行（通常 10-30 秒完成）')
      taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 净值更新已后台运行`)
    } else {
      message.error(`启动失败: ${res.data.message}`)
    }
  } catch (e: any) {
    message.error(`启动失败: ${e.message}`)
    taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 净值更新启动失败: ${e.message}`)
  } finally {
    setTimeout(() => { navRunning.value = false }, 2000)
    setTimeout(() => fetchNavStatus(), 3000)
  }
}

const triggerTask = async (id: string) => {
  const task = manualTasks.find(t => t.id === id)
  if (!task) return
  task.running = true
  taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 任务 ${id} 启动...`)
  try {
    const res = await triggerSystemTask(id)
    if (res.data.status === 'ok') {
      message.success(`任务 ${id} 已后台运行`)
      taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 任务 ${id} 启动成功`)
    } else {
      message.error(`任务启动失败: ${res.data.message}`)
      taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 任务 ${id} 启动失败: ${res.data.message}`)
    }
  } catch (e: any) {
    const errorMsg = e.response?.data?.message || e.message || '未知错误'
    message.error(`任务启动失败: ${errorMsg}`)
    taskLogs.value.unshift(`[${new Date().toLocaleTimeString()}] 任务 ${id} 启动失败: ${errorMsg}`)
  } finally {
    setTimeout(() => { task.running = false }, 1500)
  }
}

const fetchFundConfigs = async () => {
  try {
    const res = await getFundConfigs()
    fundConfigs.value = res.data.data
  } catch (e) {
    message.error('获取基金列表失败')
  }
}

const addNewFund = () => {
  editMode.value = false
  Object.assign(fundForm, {
    code: '', name: '', category: '', trade_etf: '', trade_future: '',
    holdings: { equity_ratio: 95.0 },
    valuation_portfolio: [{ symbol: '', weight: 100, anchor: 'US' }]
  })
  showFundModal.value = true
}

const editFund = async (fund: any) => {
  editMode.value = true
  const baseData = JSON.parse(JSON.stringify(fund))
  Object.assign(fundForm, baseData)
  if (!fundForm.holdings) fundForm.holdings = { equity_ratio: 95.0 }
  if (!fundForm.valuation_portfolio) fundForm.valuation_portfolio = []
  showFundModal.value = true
}

const handleSaveFund = async () => {
  try {
    await upsertFundConfig(fundForm)
    message.success('配置已保存成功')
    showFundModal.value = false
    fetchFundConfigs()
  } catch (e) {
    message.error('保存失败')
  }
}

const handleDeleteFund = async () => {
  if (!confirm(`确定要删除 ${fundForm.code} 吗？`)) return
  try {
    const res = await deleteFundConfig(fundForm.code)
    if (res.data.status === 'ok') {
      message.success('已从配置中移除')
      showFundModal.value = false
      fetchFundConfigs()
    }
  } catch (e) {
    message.error('删除失败')
  }
}

const checkPrivateAccess = async () => {
  try {
    const res = await client.get('/api/private/status')
    if (res.data.loaded) isPrivateVisible.value = true
    else message.error('未挂载私有插件')
  } catch (e) { message.error('验证失败') }
}

const handleExport = async () => {
  try {
    message.loading('正在生成导出文件...')
    const res = await client.get(`/api/private/export/${exportCode.value}`, { responseType: 'blob' })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    link.setAttribute('download', `fund_export_${exportCode.value}_${new Date().toISOString().split('T')[0]}.csv`)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    message.success('导出成功')
  } catch (e: any) {
    // 尝试从 Blob 错误响应中提取真实错误信息
    const errData = e?.response?.data
    if (errData instanceof Blob) {
      try {
        const text = await errData.text()
        const json = JSON.parse(text)
        if (json?.message) {
          console.error('[导出失败]', json.message)
          message.error(`导出失败: ${json.message}`)
          return
        }
      } catch { /* ignore parse errors */ }
    }
    const errMsg = e?.response?.data?.message || e?.message || '未知错误'
    console.error('[导出失败]', errMsg)
    message.error(`导出失败: ${errMsg}`)
  }
}

onMounted(() => {
  fetchFundConfigs()
  fetchDataStatus()
  fetchNavStatus()
  // 每 60 秒刷新数据状态
  setInterval(fetchDataStatus, 60000)
})
</script>

<style scoped>
.data-status-grid { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.data-status-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #edf2f7;
}
.ds-left { display: flex; align-items: center; gap: 10px; }
.ds-info { }
.ds-name { font-weight: 600; color: #1e293b; font-size: 13px; }
.ds-desc { font-size: 11px; color: #64748b; }
.ds-right { flex-shrink: 0; }

.nav-action-card {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 14px; background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px;
}
.nav-title { font-weight: 700; color: #92400e; font-size: 14px; }
.nav-desc { font-size: 11px; color: #a16207; margin-top: 2px; }

.task-grid { display: flex; flex-direction: column; gap: 8px; }
.task-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 12px; background: #f9fafb; border-radius: 8px; border: 1px solid #edf2f7;
}
.task-name { font-weight: 600; color: #1e293b; font-size: 13px; }
.task-desc { font-size: 11px; color: #64748b; }
.terminal-box {
  background: #0f172a; color: #e2e8f0; padding: 12px; border-radius: 6px;
  height: 200px; overflow-y: auto; font-family: 'Fira Code', monospace; font-size: 13px;
}
.log-line { margin-bottom: 4px; border-bottom: 1px solid #1e293b; padding-bottom: 2px; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04); border-radius: 12px; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.flex-center { display: flex; align-items: center; }
.flex-end { display: flex; justify-content: flex-end; }
.private-card { border: 1px dashed #e2e8f0; }
.portfolio-item { padding: 8px; background: #f8fafc; border-radius: 6px; margin-bottom: 8px; }
.animate-fade-in { animation: fadeIn 0.3s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
.health-result { padding: 8px 0; font-size: 13px; }
.health-issue { display: flex; align-items: flex-start; padding: 4px 0; color: #92400e; }
.health-stats { font-size: 12px; color: #64748b; line-height: 1.8; }
</style>
