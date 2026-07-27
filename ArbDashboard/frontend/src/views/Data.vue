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

          <!-- [AI-2026-07-10] 静态估值手动触发 -->
          <n-divider title-placement="left">静态估值</n-divider>
          <div class="nav-action-card">
            <div class="nav-action-info">
              <div class="nav-title">重算静态估值</div>
              <div class="nav-desc">
                基于最新因子/指数数据，重新计算所有基金的静态估值（含 QDII日本新基金）。
                <span v-if="staticValLastTime">上次计算: {{ staticValLastTime }}</span>
              </div>
            </div>
            <n-button type="primary" @click="triggerStaticValuation" :loading="staticValRunning">
              <template #icon><n-icon><RefreshCw /></n-icon></template>
              立即计算
            </n-button>
          </div>
        </n-card>
      </n-gi>
      <n-gi :span="10">
        <n-card title="核心基金配置" class="shadow-soft">
          <template #header-extra>
            <n-space>
              <n-button size="tiny" type="primary" secondary @click="showInventory = true">基金大盘点</n-button>
              <n-button size="tiny" @click="handleImportClick">导入</n-button>
              <n-button size="tiny" @click="handleExportClick">导出</n-button>
            </n-space>
          </template>
          <!-- 第一步：选择/输入基金分类 -->
          <div class="mb-3">
            <!-- [AI-2026-07-09] 允许用户输入新分类（如 QDII日本）：filterable + tag 模式；蓝色高亮边框让占位符更醒目 -->
            <n-select v-model:value="selectedTab" :options="tabOptions" placeholder="请点击选择基金分类（可输入新分类）" filterable tag
              class="category-select-highlight" style="width: 100%;" />
          </div>
          <!-- 第二步：在已确定分类下，修改已有基金或新增 -->
          <div v-if="selectedTab" style="margin-bottom: 8px;">
            <n-text depth="3" style="font-size: 12px;">
              当前分类：<n-text strong style="color: #2563eb;">{{ selectedTab }}</n-text>
               （点击上方列表项可修改，或点下方按钮新增该分类下的基金）
            </n-text>
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
            <n-empty v-else :description="selectedTab ? `「${selectedTab}」分类下暂无基金，点击下方新增` : '请先选择基金分类'" />
          </div>
          <n-button block type="primary" style="margin-top: 12px;" @click="addNewFund" :disabled="!selectedTab">
              新增基金到「{{ selectedTab || '请先选分类' }}」
          </n-button>
        </n-card>

        <!-- [AI-2026-07-09] 自留地 UI 改造：① 把"仅在本地..."小字移到标题"自留地"后面；② 删除"选择导出基金"label；③ 输入框宽度收窄到仅够8位代码 -->
        <n-card :bordered="false" class="shadow-soft private-card" style="margin-top: 16px;">
          <template #header>
             <div class="flex-center gap-2" style="flex-wrap: wrap;">
                <n-icon size="18" color="#64748b"><Database /></n-icon>
                <span>自留地</span>
                <n-text depth="3" style="font-size: 11px; color: #94a3b8;">
                  * 该功能仅在本地环境且加载私有插件时可用
                </n-text>
             </div>
          </template>
          <div class="p-2 text-center" v-if="!isPrivateVisible">
            <n-button quaternary block @click="checkPrivateAccess">进入私有空间</n-button>
          </div>
          <div v-else class="p-2 animate-fade-in">
            <n-form-item label-placement="top">
               <n-input v-model:value="exportCode" placeholder="输入 6 位代码" style="width: 110px;" />
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

        <!-- [AI-2026-07-13] 历史数据导出卡片 -->
        <n-card :bordered="false" class="shadow-soft" style="margin-top: 16px;">
          <template #header>
             <div class="flex-center gap-2" style="flex-wrap: wrap;">
                <n-icon size="18" color="#64748b"><Database /></n-icon>
                <span>历史数据导出</span>
                <n-text depth="3" style="font-size: 11px; color: #94a3b8;">
                  * 最新 10 天数据，供分享分析
                </n-text>
             </div>
          </template>
          <div class="p-2 text-center">
            <n-text depth="2" style="font-size: 13px; display: block; margin-bottom: 12px;">
              导出 <n-text strong>arb_master_share.db</n-text>，包含近 10 天的基金净值、估值、溢价等完整历史数据。
            </n-text>
            <n-button type="success" block @click="handleExportShareDb" :loading="exportShareDbLoading">
              <template #icon><n-icon><FileDown /></n-icon></template>
              导出十天数据库
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
             <!-- [AI-2026-07-09] 新增时自动带入第一步所选分类；编辑时允许修改分类 -->
             <n-gi>
                <n-form-item label="基金分类">
                   <n-input v-model:value="fundForm.category" placeholder="如 QDII欧美 / QDII日本" />
                </n-form-item>
             </n-gi>
             <n-gi>
                <n-form-item label="估值算法">
                   <n-select v-model:value="fundForm.valuation_method" :options="[
                      { label: '自适应 (默认推演)', value: '' },
                      { label: 'ETF净值 (etf)', value: 'etf' },
                      { label: '一篮子权重 (basket)', value: 'basket' },
                      { label: '纯指数 (index)', value: 'index' }
                   ]" />
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

    <!-- [AI-2026-07-27] 基金大盘点弹窗：全量基金 分类/估值算法(含兜底)/数据源/对冲方式(含兜底)/关键证据 -->
    <n-modal v-model:show="showInventory" preset="card" title="基金大盘点（全量配置一览）" style="width: 96%; max-width: 1280px;">
      <template #header-extra>
        <n-space>
          <n-button size="small" @click="exportInventoryCsv">
            <template #icon><n-icon><FileDown /></n-icon></template>导出 CSV
          </n-button>
          <n-button size="small" quaternary @click="showInventory = false">关闭</n-button>
        </n-space>
      </template>
      <div class="inv-controls">
        <n-space>
          <n-select v-model:value="invFilterCat" :options="invCatOptions" placeholder="全部分类" clearable style="width: 180px;" />
          <n-input v-model:value="invQuery" placeholder="搜索 代码 / 名称 / 算法..." style="width: 240px;" />
          <n-text depth="3">共 {{ inventoryRows.length }} 只 · 当前显示 {{ invFiltered.length }}</n-text>
        </n-space>
      </div>
      <div class="inv-table-wrap">
        <table class="inv-table">
          <thead>
            <tr>
              <th>分类(TAB)</th>
              <th>代码</th>
              <th>名称</th>
              <th>估值算法（静态 / 实时）</th>
              <th>数据源（静态 / 实时）</th>
              <th>对冲方式（主源 → 兜底）</th>
              <th>关键证据(篮子/ETF/指数)</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in invFiltered" :key="r.code">
              <td><span class="inv-tag" :style="getCategoryTextColor(r.cat)">{{ r.cat }}</span></td>
              <td class="inv-code">{{ r.code }}</td>
              <td>{{ r.name }}</td>
              <td>
                <template v-if="r.unified">
                  <div class="inv-algo">{{ r.staticAlgo }}</div>
                </template>
                <template v-else>
                  <div class="inv-algo">静态：{{ r.staticAlgo }}</div>
                  <div class="inv-algo">实时：{{ r.dynAlgo }}</div>
                </template>
              </td>
              <td>
                <template v-if="r.unified">
                  <div class="inv-algo">{{ r.staticSrc }}</div>
                </template>
                <template v-else>
                  <div class="inv-algo">静态：{{ r.staticSrc }}</div>
                  <div class="inv-sub">实时：{{ r.dynSrc }}</div>
                </template>
              </td>
              <td>
                <div class="inv-algo">{{ r.hedge }}</div>
                <div class="inv-sub">{{ r.hedgeFallback }}</div>
              </td>
              <td class="inv-ev">{{ r.evidence }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="inv-note">
        <strong>估值算法区分「静态估值 / 实时估值」</strong>：静态估值（step4 批量计算）按基金跟踪方式用指数公式或篮子/魔法公式；实时估值（看板推演）按对冲标的走魔法公式（Tier1 用 Woody hedge / Tier2 矩阵公式兜底）或 NK 期货标准公式。
        hedge = ETF净值×汇率/(基金净值×仓位)，可由公开数据自算（162411 实测与 Woody 值误差 0.000%）；Woody 另提供锚点 ETF 权重（yaml 配置）。
        Woody 三层链：<strong>VPS文件 → 直接访问API(Palmmicro) → woody网站(爬虫兜底)</strong>。
        其余数据源：指数点位走新浪/东财/Yahoo；ETF 实时价走 IB→富途→新浪；A股/指数/期货走 TDX→国金/银河QMT→腾讯→新浪。标注「待确认」的请以实际配置为准。
      </p>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  NCard, NGrid, NGi, NButton, NIcon, NTag, NDivider, NFormItem, NInput, useMessage, NSpace, NText,
  NList, NListItem, NEmpty, NModal, NForm, NInputNumber, NSelect, NAlert, NUpload
} from 'naive-ui'
import { Play, FileDown, Database, Trash2, HelpCircle, RefreshCw, CheckCircle, Clock } from 'lucide-vue-next'
import { triggerTask as triggerSystemTask, getFundConfigs, upsertFundConfig, deleteFundConfig, exportFundConfig, importFundConfig, getCategories } from '../api'
import { getDataStatus, getNavStatus } from '../api/systemApi'
import client from '../api/client'

const message = useMessage()
const exportCode = ref('')
const isPrivateVisible = ref(false)
const quickCodes = ['162411', '164701', '164824', '161116']
const exportShareDbLoading = ref(false)

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

// [AI-2026-07-09] 分类下拉框改为动态读取数据库分类（与主看板一致），不再硬编码，避免新增分类（如 QDII日本）不显示
const tabOptions = ref<{ label: string; value: string }[]>([])
// [AI-2026-07-09] 初值必须为 null（不能是空串），否则 n-select 会把 '' 当成"已选中空选项"而不显示 placeholder
const selectedTab = ref<string | null>(null)

const filteredFunds = computed(() => {
  if (!selectedTab.value) return fundConfigs.value
  // [AI-2026-07-09] 分类已简化，selectedTab 即数据库 category 值，直接精确过滤
  return fundConfigs.value.filter(f => f.category === selectedTab.value)
})

// 数据同步状态
const dataSources = ref<any[]>([])
const morningReady = ref(false)
const navLastTime = ref('')
const navRunning = ref(false)

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

// [AI-2026-07-27] 基金大盘点表格：不同 TAB 用不同字体颜色，便于一眼区分
const CATEGORY_TEXT_COLOR: Record<string, string> = {
  '黄金原油': '#d97706',   // 琥珀
  'QDII欧美': '#dc2626',   // 红
  'QDII日本': '#db2777',   // 粉
  'QDII亚洲': '#7c3aed',   // 紫
  '国内LOF': '#2563eb',    // 蓝
  '白银': '#059669',       // 绿
  '现金管理': '#64748b',   // 灰
}
const getCategoryTextColor = (cat: string) => {
  const c = CATEGORY_TEXT_COLOR[cat] || '#374151'
  return { color: c, fontWeight: 'bold', fontSize: '12px' }
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
  try {
    const res = await triggerSystemTask('nav')
    if (res.data.status === 'ok') {
      message.success('净值更新已后台运行（通常 10-30 秒完成）')
    } else {
      message.error(`启动失败: ${res.data.message}`)
    }
  } catch (e: any) {
    message.error(`启动失败: ${e.message}`)
  } finally {
    setTimeout(() => { navRunning.value = false }, 2000)
    setTimeout(() => fetchNavStatus(), 3000)
  }
}

// [AI-2026-07-10] 静态估值手动触发
const staticValLastTime = ref('')
const staticValRunning = ref(false)

const triggerStaticValuation = async () => {
  staticValRunning.value = true
  try {
    const res = await triggerSystemTask('012')
    if (res.data.status === 'ok') {
      message.success('静态估值计算已后台运行，请稍后刷新看板查看结果')
    } else {
      message.error(`启动失败: ${res.data.message}`)
    }
  } catch (e: any) {
    message.error(`启动失败: ${e.message}`)
  } finally {
    setTimeout(() => { staticValRunning.value = false }, 2000)
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

// [AI-2026-07-09] 动态拉取数据库分类，填充分类下拉框（与主看板一致，含 QDII日本 等新增分类）
const fetchCategories = async () => {
  try {
    const res = await getCategories()
    if (res.data?.status === 'ok' && Array.isArray(res.data.data)) {
      tabOptions.value = res.data.data.map((c: string) => ({ label: c, value: c }))
    }
  } catch (e) {
    console.error('获取分类失败', e)
  }
}

// [AI-2026-07-09] 强制先选基金分类才能新增：用上方 TAB 分类下拉(selectedTab)作为前置分类，
// 未选则提示，不打开弹窗；打开后自动带入分类并隐藏"内盘分类"手填框
const addNewFund = () => {
  if (!selectedTab.value) {
    message.warning('请先在上方「请点击选择基金分类」中选择一个分类，再新增基金')
    return
  }
  editMode.value = false
  Object.assign(fundForm, {
    code: '', name: '', category: selectedTab.value, trade_etf: '', trade_future: '',
    valuation_method: '',
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
    fetchCategories()  // [AI-2026-07-09] 新增/修改分类后立即刷新下拉框，保证新建分类（如 QDII日本）立即可见
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

const handleExportShareDb = async () => {
  exportShareDbLoading.value = true
  try {
    message.loading('正在生成十天数据库，请稍候...')
    const res = await client.get('/api/db/export_share', { responseType: 'blob', timeout: 120000 })
    const url = window.URL.createObjectURL(new Blob([res.data]))
    const link = document.createElement('a')
    link.href = url
    const filename = res.headers?.['content-disposition']
      ?.match(/filename=(.+)/)?.[1] || `arb_master_share_${new Date().toISOString().split('T')[0]}.db`
    link.setAttribute('download', filename)
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
    message.success('分享库导出成功')
  } catch (e: any) {
    const errData = e?.response?.data
    if (errData instanceof Blob) {
      try {
        const text = await errData.text()
        const json = JSON.parse(text)
        if (json?.message) {
          message.error(`导出失败: ${json.message}`)
          return
        }
      } catch { /* ignore */ }
    }
    message.error(`导出失败: ${e?.message || '未知错误'}`)
  } finally {
    exportShareDbLoading.value = false
  }
}

// [AI-2026-07-27] 基金大盘点：基于 fundConfigs（已加载的全部 YAML 配置）计算全量一览，
// 兜底链路来自代码核查（woody_api_service / market_data_service / symbol_source_map / data_fetcher）。
const showInventory = ref(false)
const invFilterCat = ref<string | null>(null)
const invQuery = ref('')

// [AI-2026-07-27] 基金大盘点：估值算法 / 数据源 区分「静态估值(step4)」与「实时估值(推演)」
// 静态估值分发逻辑来自 static_valuation.py _deduce_valuation；实时估值来自 dynamic_valuation.calculate() + fund_service NK 期货路径
// 关键事实（已查代码 + 实测确认，非猜测）：
//  - 161125/161130：静态=指数公式(.INX/.NDX)，实时=魔法公式(SPY/QQQ + Woody hedge) → Tier1/Tier2 矩阵公式兜底
//  - QDII日本：静态=指数公式(N225)，实时=NK 期货标准公式
//  - 黄金原油等多篮子：静态=实时=矩阵(篮子)标准公式（统一显示，数据源 woody API 含 hedge，无兜底）
//  - 162411：静态=魔法公式(XOP+hedge)，hedge缺失→矩阵(篮子)标准公式；实时=Tier1 魔法/Tier2 矩阵
//  - hedge = ETF净值×汇率/(基金净值×仓位)，可由公开数据自算（162411 实测误差 0.000%）；Woody 另提供锚点 ETF 权重(yaml)
//  - Woody 三层链：VPS文件 → 直接访问API(Palmmicro) → woody网站(爬虫兜底)
// [AI-2026-07-27] 判定：related_index 必须是「干净的指数符号」才算指数基金，
// 否则（ETF 符号如 XOP/GLD，或逗号串如 GLD,USO）不当作指数，避免把单ETF/多篮子基金误判为指数公式
const ETF_SYMBOLS = new Set(['XOP', 'SPY', 'QQQ', 'GLD', 'USO', 'SLV', 'NKY', 'INDA', 'XLK', 'ARKK', 'EWA', 'MGC', 'CL', 'UNG', 'GDX'])
function isIndexRi(ri: any): boolean {
  ri = String(ri ?? '')
  if (!ri || ri === 'None') return false
  if (ri.includes(',')) return false
  if (ETF_SYMBOLS.has(ri)) return false
  if (ri.startsWith('.')) return true
  if (/^\d+$/.test(ri)) return true
  return true // N225 / HSI / HSCEI 等已知指数符号
}
function vmOf(fd: any): string {
  const v = fd.valuation_method
  return (v === null || v === undefined) ? '' : String(v)
}

function invStaticAlgo(fd: any): { algo: string; src: string } {
  const vm = vmOf(fd)
  const ri = fd.related_index || ''
  const vp: any[] = fd.valuation_portfolio || []
  const cat = fd.category || ''
  const sym = vp.length ? (vp[0].symbol || '') : ''
  if (cat === 'QDII日本') return { algo: '指数公式(N225)', src: '日经225(Yahoo/新浪)' }
  if (vm === 'index' || vm === 'equity_asia' || vm === 'lof_domestic') return { algo: `指数公式(${ri || '指数'})`, src: '指数点位(新浪/东财)' }
  if (vm === 'etf') return { algo: '魔法公式(单一ETF+hedge)；hedge缺失→矩阵(篮子)标准公式', src: `Woody hedge；兜底用 ${sym} 净值(Yahoo)` }
  if (vm === 'basket') return { algo: '矩阵(篮子)标准公式', src: '各 ETF 净值(Yahoo/IB) + yaml 权重' }
  if (isIndexRi(ri) && vp.length <= 1) return { algo: `指数公式(${ri})`, src: '指数点位(新浪/东财)' }
  if (vp.length > 1) return { algo: '矩阵(篮子)标准公式', src: '各 ETF 净值(Yahoo/IB) + yaml 权重' }
  if (vp.length === 1) return { algo: '魔法公式(单一ETF+hedge)；hedge缺失→矩阵(篮子)标准公式', src: `Woody hedge；兜底用 ${sym} 净值(Yahoo)` }
  return { algo: '待确认', src: '待确认' }
}

function invDynAlgo(fd: any): { algo: string; src: string } {
  const vm = vmOf(fd)
  const ri = fd.related_index || ''
  const vp: any[] = fd.valuation_portfolio || []
  const cat = fd.category || ''
  const sym = vp.length ? (vp[0].symbol || '') : ''
  if (cat === 'QDII日本') return { algo: 'NK 期货标准公式', src: '新浪 hf_NK 实时价 + futures_daily NK 结算价 + 日元在岸价' }
  if (vm === 'index' && vp.length === 1) return { algo: 'Tier1 魔法公式(单一ETF+hedge); Tier2 矩阵(篮子)标准公式', src: `Tier1: ${sym} 实时价(IB→富途→新浪) + Woody hedge；Tier2: Yahoo 净值 + yaml 权重` }
  if (vm === 'etf' || (vm === '' && vp.length === 1)) return { algo: 'Tier1 魔法公式(单一ETF+hedge); Tier2 矩阵(篮子)标准公式', src: `Tier1: ${sym} 实时价(IB→富途→新浪) + Woody hedge；Tier2: Yahoo 净值 + yaml 权重` }
  if (vm === 'basket' || (vm === '' && vp.length > 1)) return { algo: '矩阵(篮子)标准公式', src: '各 ETF 实时价(IB→富途→新浪) + 基准价(Yahoo/IB) + yaml 权重' }
  if (isIndexRi(ri) && vm !== 'etf' && vm !== 'basket') return { algo: `指数公式(${ri})`, src: '指数点位(新浪/东财)' }
  return { algo: '待确认', src: '待确认' }
}

function invVpStr(vp: any[]): string {
  if (!vp || !vp.length) return ''
  return vp.map((v: any) => {
    const s = v.symbol || ''
    const w = v.weight != null ? v.weight : ''
    const a = v.anchor || ''
    return a ? `${s}(${w},${a})` : `${s}(${w})`
  }).join(', ')
}

// [AI-2026-07-27] invAlgoName 已弃用：估值算法现由 invStaticAlgo / invDynAlgo 按「静态/实时」分别推导，见上方。

function invHedgeStr(fd: any): string {
  const te = fd.trade_etf || ''
  const tf = fd.trade_future || ''
  const fh = fd.future_hedging || []
  const cat = fd.category || ''
  const parts: string[] = []
  if (te) parts.push(`ETF ${te}`)
  if (tf) parts.push(`期货 ${tf}`)
  else if (fh && fh.length) fh.forEach((h: any) => parts.push(`期货 ${h.symbol || ''}`))
  if (cat === 'QDII亚洲' || cat === '国内LOF') return '无法对冲'
  if (!parts.length) return '未配置'
  return parts.join(' / ')
}

// [AI-2026-07-27] 对冲方式兜底链（按分类）
function invHedgeFallback(cat: string): string {
  switch (cat) {
    case '黄金原油': return '对冲ETF实时价: IB→富途→None; 期货结算价: 新浪 hf_/nf_'
    case 'QDII欧美': return '对冲ETF实时价: IB→富途→None; 期货结算价: 新浪'
    case 'QDII日本': return '日经期货NK: 新浪 hf_NK(无兜底)'
    case 'QDII亚洲':
    case '国内LOF': return '无法对冲'
    case '白银': return '沪银Ag: 上期所/新浪(无兜底)'
    case '现金管理': return '未配置'
    default: return '待确认'
  }
}

const inventoryRows = computed(() => {
  const catOrder = ['黄金原油', 'QDII欧美', 'QDII日本', 'QDII亚洲', '国内LOF', '白银', '现金管理']
  const rows = (fundConfigs.value || []).map((fd: any) => {
    const cat = fd.category || ''
    const sa = invStaticAlgo(fd)
    const da = invDynAlgo(fd)
    const unified = cat === '黄金原油'
    const ev = invVpStr(fd.valuation_portfolio) || fd.trade_etf || fd.related_index || ''
    return {
      code: fd.code,
      name: fd.name || '',
      cat,
      unified,
      staticAlgo: unified ? '矩阵(篮子)标准公式' : sa.algo,
      staticSrc: unified ? 'woody API（含hedge）' : sa.src,
      dynAlgo: unified ? '矩阵(篮子)标准公式' : da.algo,
      dynSrc: unified ? 'woody API（含hedge）' : da.src,
      hedge: invHedgeStr(fd),
      hedgeFallback: invHedgeFallback(cat),
      evidence: ev,
    }
  })
  rows.sort((a: any, b: any) => {
    const ia = catOrder.indexOf(a.cat); const ib = catOrder.indexOf(b.cat)
    if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
    return String(a.code).localeCompare(String(b.code))
  })
  return rows
})

const invCatOptions = computed(() => {
  const set = new Set<string>()
  inventoryRows.value.forEach((r: any) => set.add(r.cat))
  return Array.from(set).map((c) => ({ label: c, value: c }))
})

const invFiltered = computed(() => {
  const c = invFilterCat.value
  const q = (invQuery.value || '').toLowerCase().trim()
  return inventoryRows.value.filter((r: any) => {
    if (c && r.cat !== c) return false
    if (!q) return true
    return (r.code + r.name + r.staticAlgo + r.dynAlgo + r.hedge + r.evidence).toLowerCase().includes(q)
  })
})

const exportInventoryCsv = () => {
  const headers = ['分类', '代码', '名称', '静态估值算法', '静态数据源', '实时估值算法', '实时数据源', '对冲方式', '对冲兜底链', '关键证据']
  const lines = [headers.join(',')]
  inventoryRows.value.forEach((r: any) => {
    const cells = [r.cat, r.code, r.name, r.staticAlgo, r.staticSrc, r.dynAlgo, r.dynSrc, r.hedge, r.hedgeFallback, r.evidence]
    lines.push(cells.map((cell: any) => `"${String(cell == null ? '' : cell).replace(/"/g, '""')}"`).join(','))
  })
  const csv = '﻿' + lines.join('\r\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const ts = new Date().toISOString().slice(0, 10)
  link.setAttribute('download', `基金大盘点_${ts}.csv`)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
  message.success('已导出 CSV')
}

onMounted(() => {
  fetchFundConfigs()
  fetchCategories()
  fetchDataStatus()
  fetchNavStatus()
  // 每 60 秒刷新数据状态
  setInterval(fetchDataStatus, 60000)
})
</script>

<style scoped>
/* [AI-2026-07-09] 基金分类下拉框高亮：蓝边+浅蓝底，占位符文字染蓝，提升可见性 */
.category-select-highlight {
  border: 1px solid #2563eb !important;
  border-radius: 6px;
  background: #eff6ff !important;
}
.category-select-highlight :deep(.n-base-selection-placeholder),
.category-select-highlight :deep(.n-base-selection__placeholder) {
  color: #2563eb !important;
  font-weight: 600;
  opacity: 1 !important;
}
.category-select-highlight :deep(.n-base-selection) {
  background: transparent !important;
}
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
.inv-controls { margin-bottom: 12px; }
.inv-table-wrap { max-height: 62vh; overflow: auto; border: 1px solid #edf2f7; border-radius: 8px; }
.inv-table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
.inv-table th, .inv-table td { border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; vertical-align: top; }
.inv-table thead th { background: #2c3e50; color: #fff; position: sticky; top: 0; z-index: 1; white-space: nowrap; }
.inv-table tbody tr:nth-child(even) { background: #fafafa; }
.inv-code { font-family: monospace; font-weight: 600; white-space: nowrap; color: #1e293b; }
.inv-tag { background: #3498db; color: #fff; padding: 2px 7px; border-radius: 3px; font-size: 12px; white-space: nowrap; }
.inv-algo { font-weight: 600; color: #1e293b; }
.inv-sub { font-size: 11px; color: #94a3b8; margin-top: 2px; line-height: 1.5; }
.inv-ev { color: #64748b; font-size: 11.5px; max-width: 260px; }
.inv-note { font-size: 11.5px; color: #64748b; line-height: 1.7; margin-top: 12px; background: #f8fafc; padding: 8px 12px; border-radius: 6px; }
</style>
