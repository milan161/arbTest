<template>
  <div class="p-6">

    <!-- ===== 分类优先级（实时行情数据源展示已移除，顺序由系统默认固定） ===== -->
    <div style="display:grid; grid-template-columns: 1fr; gap:16px; align-items:start; margin-bottom:16px;">



      <!-- 右卡片：分类优先级 -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div class="flex items-center mb-4">
          <div class="w-2 h-6 rounded mr-3" style="background-color:#7c3aed"></div>
          <h2 class="text-xl font-bold text-gray-700">分类优先级</h2>
        </div>
        <div style="border-bottom:1px solid #e5e7eb; color:#9ca3af; font-size:12px; padding:3px 0; margin-bottom:8px;">
          点击卡片切换暂停 / 恢复（即时保存）
        </div>
        <!-- 7 个卡片：第一行 4，第二行 3 居中 -->
        <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:8px; margin-bottom:8px;">
          <div v-for="(cat, idx) in allCategories.slice(0,4)" :key="cat.name"
               @click="toggleCategory(cat.name)"
               :style="{
                 padding:'10px 4px',
                 borderRadius:'8px',
                 cursor:'pointer',
                 border: cat.paused ? '1.5px solid #e5e7eb' : '1.5px solid #7c3aed',
                 background: cat.paused ? '#f9fafb' : '#f5f3ff',
                 textAlign:'center',
                 userSelect:'none',
                 transition:'all 0.15s'
               }">
            <div style="font-size:12px; font-weight:700; color:cat.paused?'#9ca3af':'#1f2937'; margin-bottom:3px;">{{ cat.name }}</div>
            <div :style="{
              display:'inline-block',
              padding:'1px 6px',
              borderRadius:'8px',
              fontSize:'10px',
              fontWeight:'bold',
              background:cat.paused?'#f1f5f9':'#dcfce7',
              color:cat.paused?'#94a3b8':'#16a34a'
            }">{{ cat.paused ? '已暂停' : '运行中' }}</div>
          </div>
        </div>
        <div style="display:flex; gap:8px; justify-content:center;">
          <div v-for="cat in allCategories.slice(4)" :key="cat.name"
               @click="toggleCategory(cat.name)"
               :style="{
                 width:'calc(33.33% - 6px)',
                 padding:'10px 4px',
                 borderRadius:'8px',
                 cursor:'pointer',
                 border: cat.paused ? '1.5px solid #e5e7eb' : '1.5px solid #7c3aed',
                 background: cat.paused ? '#f9fafb' : '#f5f3ff',
                 textAlign:'center',
                 userSelect:'none',
                 transition:'all 0.15s'
               }">
            <div style="font-size:12px; font-weight:700; color:cat.paused?'#9ca3af':'#1f2937'; margin-bottom:3px;">{{ cat.name }}</div>
            <div :style="{
              display:'inline-block',
              padding:'1px 6px',
              borderRadius:'8px',
              fontSize:'10px',
              fontWeight:'bold',
              background:cat.paused?'#f1f5f9':'#dcfce7',
              color:cat.paused?'#94a3b8':'#16a34a'
            }">{{ cat.paused ? '已暂停' : '运行中' }}</div>
          </div>
        </div>
      </div>

    </div>

    <!-- ===== IB 核心套利标的配置（通栏） ===== -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-4">
      <div class="flex items-center mb-6">
        <div class="w-2 h-6 bg-orange-500 rounded mr-3"></div>
        <h2 class="text-xl font-bold text-gray-700">IB 核心套利标的 (Real-time Priority)</h2>
        <span class="ml-4 text-sm text-gray-400 font-normal">IB 只订阅这些标的，其余 ETF 走富途或放弃</span>
      </div>

      <!-- 当前标的列表 -->
      <div style="display: flex; flex-direction: column; gap: 12px;">
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span style="font-size: 13px; color: #64748b;">当前标的（点击标签添加/移除）：</span>
        </div>
        <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center; min-height: 36px;">
          <span v-for="(sym, idx) in ibCoreSymbols" :key="sym"
                @click="toggleIbSymbol(sym)"
                :style="{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '4px',
                  padding: '4px 10px',
                  fontSize: '13px',
                  borderRadius: '16px',
                  cursor: 'pointer',
                  backgroundColor: '#fee2e2',
                  color: '#dc2626',
                  border: '1px solid #fca5a5',
                  fontWeight: 'bold',
                  userSelect: 'none'
                }"
                :title="点击移除">
            {{ sym }}
            <span style="font-size: 10px;">✕</span>
          </span>
          <span v-if="ibCoreSymbols.length === 0" style="font-size: 13px; color: #94a3b8;">加载中...</span>
        </div>

        <!-- 富途标的可选 -->
        <div style="border-top: 1px dashed #e2e8f0; padding-top: 12px;">
          <div style="font-size: 12px; color: #64748b; margin-bottom: 6px;">
            ➕ 从下方选择添加到 IB（将富途标的提升为 IB 核心）：
          </div>
          <div style="display: flex; gap: 6px; flex-wrap: wrap;">
            <span v-for="sym in futuCandidates" :key="sym"
                  @click="addIbSymbol(sym)"
                  :style="{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '4px',
                    padding: '4px 10px',
                    fontSize: '13px',
                    borderRadius: '16px',
                    cursor: 'pointer',
                    backgroundColor: ibCoreSymbols.includes(sym) ? '#fee2e2' : '#f0fdf4',
                    color: ibCoreSymbols.includes(sym) ? '#dc2626' : '#16a34a',
                    border: ibCoreSymbols.includes(sym) ? '1px solid #fca5a5' : '1px solid #86efac',
                    textDecoration: ibCoreSymbols.includes(sym) ? 'line-through' : 'none',
                    fontWeight: ibCoreSymbols.includes(sym) ? 'bold' : 'normal',
                    userSelect: 'none',
                    opacity: ibCoreSymbols.includes(sym) ? 0.6 : 1
                  }"
                  :title="ibCoreSymbols.includes(sym) ? '已在 IB 核心中' : '点击添加到 IB'">
              {{ sym }}
              <span v-if="!ibCoreSymbols.includes(sym)" style="font-size: 10px;">+</span>
            </span>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div style="display: flex; gap: 8px; align-items: center; margin-top: 14px;">
        <button @click="saveIbCoreSymbols"
                style="padding: 6px 20px; font-size: 13px; border: none; border-radius: 6px; background: #2563eb; color: white; cursor: pointer; font-weight: bold;">
          保存
        </button>
        <button @click="loadIbCoreSymbols"
                style="padding: 6px 16px; font-size: 13px; border: 1px solid #e2e8f0; border-radius: 6px; background: white; color: #64748b; cursor: pointer;">
          刷新
        </button>
        <button @click="setDefaultIbSymbols"
                style="padding: 6px 16px; font-size: 13px; border: 1px solid #e2e8f0; border-radius: 6px; background: white; color: #64748b; cursor: pointer;">
          恢复默认
        </button>
      </div>

      <div style="font-size: 12px; color: #94a3b8; line-height: 1.6; margin-top:12px;">
        <div>📌 默认 7 只：XOP, GLD, USO, SLV, INDA, QQQ, SPY</div>
        <div>⚠️ 修改后立即生效，IB 会重新订阅</div>
        <div>ℹ️ 这些是套利必需的标的，其他 ETF（XLK、ARKK、EWA 等）走富途数据源</div>
      </div>
    </div>

    <!-- ===== 核心基金配置（合并自 Data.vue） ===== -->
    <div style="margin-top: 20px;">
      <n-card title="核心基金配置" class="shadow-soft">
      <template #header-extra>
        <n-space>
          <n-button size="tiny" type="primary" secondary @click="showInventory = true">基金大盘点</n-button>
          <n-button size="tiny" @click="handleImportClick">导入</n-button>
          <n-button size="tiny" @click="handleExportClick">导出</n-button>
        </n-space>
      </template>
      <!-- 第一步：选择/输入基金分类 -->
      <div style="margin-bottom: 12px;">
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
  </div>

  <!-- 基金配置编辑弹窗 -->
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
              <n-form-item label="数据源">
                 <n-select v-model:value="fundForm.data_source" :options="dataSourceOptions" placeholder="请选择数据源" />
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
  <n-modal v-model:show="showInventory" preset="card" title="基金大盘点（全量配置一览）" style="width: 96%; max-width: 1400px;">
    <template #header-extra>
      <n-space>
        <n-button size="small" @click="exportInventoryCsv">
          <template #icon><n-icon><FileDown /></n-icon></template>导出 CSV
        </n-button>
        <n-button size="small" quaternary @click="showInventory = false">关闭</n-button>
      </n-space>
    </template>
    <n-space vertical :size="12">
      <n-space>
        <n-select v-model:value="invFilterCat" :options="invCatOptions" placeholder="全部分类" clearable style="width: 180px;" />
        <n-input v-model:value="invQuery" placeholder="搜索 代码 / 名称 / 算法..." style="width: 260px;" />
        <n-text depth="3">共 {{ inventoryRows.length }} 只 · 当前显示 {{ invFiltered.length }}</n-text>
      </n-space>
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
                  <div class="inv-sub">实时：{{ r.dynAlgo }}</div>
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
      <n-alert type="info" :bordered="false" style="font-size: 11.5px;">
        <template #icon><n-icon :component="HelpCircle" /></template>
        估值算法区分「静态估值 / 实时估值」：静态估值（step4 批量计算）按基金跟踪方式用指数公式或篮子/魔法公式；实时估值（看板推演）按对冲标的走魔法公式（Tier1 用 Woody hedge / Tier2 矩阵公式兜底）或 NK 期货标准公式。
        hedge = ETF净值×汇率/(基金净值×仓位)，可由公开数据自算（162411 实测与 Woody 值误差 0.000%）；Woody 另提供锚点 ETF 权重（yaml 配置）。
        Woody 三层链：<strong>VPS文件 → 直接访问API(Palmmicro) → woody网站(爬虫兜底)</strong>。
        其余数据源：指数点位走新浪/东财/Yahoo；ETF 实时价走 IB→富途→新浪；A股/指数/期货走 TDX→国金/银河QMT→腾讯→新浪。标注「待确认」的请以实际配置为准。
      </n-alert>
    </n-space>
  </n-modal>
</div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue';
import {
  NCard, NGrid, NGi, NButton, NIcon, NTag, NDivider, NFormItem, NInput, useMessage, NSpace, NText,
  NList, NListItem, NEmpty, NModal, NForm, NInputNumber, NSelect, NAlert, NUpload
} from 'naive-ui';
import { h } from 'vue';
import { getFundConfigs, upsertFundConfig, deleteFundConfig, exportFundConfig, importFundConfig, getCategories } from '../api';
import { getIbCoreSymbols, postIbCoreSymbols, getPausedCategories, postPausedCategories } from '../api';
import client from '../api/client';
import { Play, FileDown, Database, Trash2, RefreshCw, CheckCircle, Clock, HelpCircle } from 'lucide-vue-next';

const message = useMessage();

// ========== IB 核心标的配置 ==========
const ibCoreSymbols = ref([]);
const ibCoreSymbolsText = ref('');

// [AI-2026-07-20] 分类优先级管理
const allCategories = ref([
  { name: '黄金原油', paused: false, priority: '第一优先级' },
  { name: 'QDII欧美', paused: false, priority: '第一优先级' },
  { name: 'QDII日本', paused: false, priority: '第二优先级' },
  { name: '白银', paused: false, priority: '第二优先级' },
  { name: 'QDII亚洲', paused: true, priority: '已暂停' },
  { name: '国内LOF', paused: true, priority: '已暂停' },
  { name: '现金管理', paused: true, priority: '已暂停' },
]);

// 富途可用标的列表（非 IB 核心美股 ETF）
const futuCandidates = ref([
  'ARKK', 'ARKG', 'ARKQ', 'BOTZ', 'FINX', 'IAU',
  'GDX', 'GDXJ', 'EWA', 'EWC', 'EWJ', 'EWZ', 'EWY',
  'EWH', 'EWI', 'EWG', 'EWU', 'FXI', 'KWEB', 'MCHI',
  'VIX', 'XLK', 'XLF', 'XLE', 'XLV', 'XLI', 'XLP',
  'XLY', 'XLU', 'XLRE', 'XLB', 'SOXX', 'SMH', 'AIQ',
  'DIA', 'IWM', 'CPER', 'DBC', 'PDBC', 'BNO', 'OIL',
]);

const loadIbCoreSymbols = async () => {
  try {
    const res = await getIbCoreSymbols()
    if (res.data.status === 'ok') {
      ibCoreSymbols.value = res.data.data
      ibCoreSymbolsText.value = res.data.data.join(', ')
    }
  } catch (e) {
    console.error('加载 IB 核心标的失败:', e)
  }
}

const saveIbCoreSymbols = async () => {
  try {
    const symbols = ibCoreSymbols.value
    if (symbols.length === 0) {
      message.warning('标的列表不能为空')
      return
    }
    const res = await postIbCoreSymbols(symbols)
    if (res.data.status === 'ok') {
      message.success(res.data.message || 'IB 核心标的已更新')
    } else {
      message.error(res.data.message || '更新失败')
    }
  } catch (e) {
    message.error('更新失败: ' + (e.message || e))
  }
}

const toggleIbSymbol = (sym) => {
  const idx = ibCoreSymbols.value.indexOf(sym)
  if (idx > -1) {
    ibCoreSymbols.value.splice(idx, 1)
  }
}

const addIbSymbol = (sym) => {
  if (!ibCoreSymbols.value.includes(sym)) {
    ibCoreSymbols.value.push(sym)
  }
}

const setDefaultIbSymbols = () => {
  ibCoreSymbols.value = ['XOP', 'GLD', 'USO', 'SLV', 'INDA', 'QQQ', 'SPY']
  message.info('已恢复默认 7 只标的')
}

// [AI-2026-07-20] 分类优先级管理
const loadPausedCategories = async () => {
  try {
    const res = await getPausedCategories()
    if (res.data.status === 'ok') {
      const paused = res.data.data || []
      allCategories.value.forEach(cat => {
        cat.paused = paused.includes(cat.name)
      })
    }
  } catch (e) {
    console.error('加载暂停分类失败:', e)
  }
}

// [AI-2026-08-22] 方向A：分类暂停即时保存（postPausedCategories 后端立即 sync）
const toggleCategory = async (name) => {
  const cat = allCategories.value.find(c => c.name === name)
  if (!cat) return
  cat.paused = !cat.paused
  try {
    const pausedList = allCategories.value.filter(c => c.paused).map(c => c.name)
    await postPausedCategories(pausedList)
    message.success(cat.paused ? `✅ 已暂停 ${name}` : `✅ 已恢复 ${name}`)
  } catch (e) {
    cat.paused = !cat.paused // 回滚
    message.error('❌ 保存失败: ' + (e.message || e))
  }
}

// ========== 核心基金配置（合并自 Data.vue） ==========
const showImportModal = ref(false);
const importFile = ref(null);
const importLoading = ref(false);
const showFundModal = ref(false);
const editMode = ref(false);

// [AI-2026-07-09] 动态读取数据库分类，填充分类下拉框
const tabOptions = ref([]);
const selectedTab = ref(null);

const fetchCategories = async () => {
  try {
    const res = await getCategories();
    if (res.data?.status === 'ok' && Array.isArray(res.data.data)) {
      tabOptions.value = res.data.data.map(c => ({ label: c, value: c }));
    }
  } catch (e) { console.error('获取分类失败', e); }
};

const fundConfigs = ref([]);
const fetchFundConfigs = async () => {
  try {
    const res = await getFundConfigs();
    fundConfigs.value = res.data.data;
  } catch (e) { message.error('获取基金列表失败'); }
};

const filteredFunds = computed(() => {
  if (!selectedTab.value) return [];
  return fundConfigs.value.filter(f => f.category === selectedTab.value);
});

// [AI-2026-08-05] 数据源下拉选项
const dataSourceOptions = [
  { label: 'Woody (QDII/跨境)', value: 'woody' },
  { label: '本地指数 (国内LOF)', value: 'localindex' },
  { label: '港股指数', value: 'hkindex' },
  { label: '现金管理 (货币/短融/政金债)', value: 'cash_mngt' },
  { label: '白银期货 (161226核心)', value: 'silver' },
  { label: '其他', value: 'other' }
];

const anchorOptions = [
  { label: '美股收盘 (US)', value: 'US' },
  { label: '欧洲时刻 (EU)', value: 'EU' },
  { label: '日本时刻 (JP)', value: 'JP' },
  { label: '香港时刻 (HK)', value: 'HK' }
];

const fundForm = reactive({
  code: '', name: '', category: '',
  trade_etf: '', trade_future: '',
  data_source: 'woody',
  holdings: { equity_ratio: 95.0 },
  valuation_portfolio: [],
  redemption_fee_rate: 0.5,
  commission_rate: 0
});

const getCategoryBadgeStyle = (cat) => {
  let textColor = '#4b5563';
  let bgColor = '#f3f4f6';
  if (cat.includes('黄金')) { textColor = '#d97706'; bgColor = '#fef3c7'; }
  else if (cat.includes('原油')) { textColor = '#475569'; bgColor = '#f1f5f9'; }
  else if (cat.includes('指数')) { textColor = '#2563eb'; bgColor = '#dbeafe'; }
  else if (cat.includes('跨境') || cat.includes('欧美') || cat.includes('亚洲') || cat.includes('纯ETF') || cat.includes('混合')) { textColor = '#dc2626'; bgColor = '#fee2e2'; }
  else if (cat.includes('白银')) { textColor = '#059669'; bgColor = '#d1fae5'; }
  return { color: textColor, backgroundColor: bgColor, padding: '3px 10px', borderRadius: '12px', fontSize: '11px', fontWeight: 'bold', display: 'inline-block', lineHeight: '1.2' };
};

const CATEGORY_TEXT_COLOR = {
  '黄金原油': '#d97706',
  'QDII欧美': '#dc2626',
  'QDII日本': '#db2777',
  'QDII亚洲': '#7c3aed',
  '国内LOF': '#2563eb',
  '白银': '#059669',
  '现金管理': '#64748b',
};
const getCategoryTextColor = (cat) => {
  const c = CATEGORY_TEXT_COLOR[cat] || '#374151';
  return { color: c, fontWeight: 'bold', fontSize: '12px' };
};

const handleImportClick = () => {
  importFile.value = null;
  showImportModal.value = true;
};
const handleFileChange = (data) => {
  importFile.value = data.file.file || null;
};
const handleExportClick = async () => {
  try {
    const res = await exportFundConfig();
    const blob = new Blob([res.data], { type: 'application/x-yaml' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const ts = new Date().toISOString().replace(/[-:]/g, '').slice(0, 15);
    link.setAttribute('download', `lof_config_${ts}.yaml`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
    message.success('配置已导出');
  } catch (e) { message.error('导出失败: ' + (e.message || '未知错误')); }
};
const handleImportConfirm = async () => {
  if (!importFile.value) return;
  importLoading.value = true;
  try {
    await importFundConfig(importFile.value);
    message.success('导入成功，配置已更新');
    showImportModal.value = false;
    importFile.value = null;
    fetchFundConfigs();
  } catch (e) {
    const errMsg = e?.response?.data?.message || e.message || '未知错误';
    message.error('导入失败: ' + errMsg);
  } finally { importLoading.value = false; }
};

const addNewFund = () => {
  if (!selectedTab.value) {
    message.warning('请先在上方「请点击选择基金分类」中选择一个分类，再新增基金');
    return;
  }
  editMode.value = false;
  Object.assign(fundForm, {
    code: '', name: '', category: selectedTab.value, trade_etf: '', trade_future: '',
    valuation_method: '',
    data_source: 'woody',
    holdings: { equity_ratio: 95.0 },
    valuation_portfolio: [{ symbol: '', weight: 100, anchor: 'US' }]
  });
  showFundModal.value = true;
};

const editFund = async (fund) => {
  editMode.value = true;
  const baseData = JSON.parse(JSON.stringify(fund));
  Object.assign(fundForm, baseData);
  if (!fundForm.holdings) fundForm.holdings = { equity_ratio: 95.0 };
  if (!fundForm.valuation_portfolio) fundForm.valuation_portfolio = [];
  if (!fundForm.data_source) fundForm.data_source = '';
  showFundModal.value = true;
};

const handleSaveFund = async () => {
  try {
    await upsertFundConfig(fundForm);
    message.success('配置已保存成功');
    showFundModal.value = false;
    fetchFundConfigs();
    fetchCategories();
  } catch (e) { message.error('保存失败'); }
};

const handleDeleteFund = async () => {
  if (!confirm(`确定要删除 ${fundForm.code} 吗？`)) return;
  try {
    const res = await deleteFundConfig(fundForm.code);
    if (res.data.status === 'ok') {
      message.success('已从配置中移除');
      showFundModal.value = false;
      fetchFundConfigs();
    }
  } catch (e) { message.error('删除失败'); }
};

// [AI-2026-07-27] 基金大盘点
const showInventory = ref(false);
const invFilterCat = ref(null);
const invQuery = ref('');

const ETF_SYMBOLS = new Set(['XOP', 'SPY', 'QQQ', 'GLD', 'USO', 'SLV', 'NKY', 'INDA', 'XLK', 'ARKK', 'EWA', 'MGC', 'CL', 'UNG', 'GDX']);
function isIndexRi(ri) {
  ri = String(ri ?? '');
  if (!ri || ri === 'None') return false;
  if (ri.includes(',')) return false;
  if (ETF_SYMBOLS.has(ri)) return false;
  if (ri.startsWith('.')) return true;
  if (/^\d+$/.test(ri)) return true;
  return true;
}
function vmOf(fd) {
  const v = fd.valuation_method;
  return (v === null || v === undefined) ? '' : String(v);
}
function invStaticAlgo(fd) {
  const vm = vmOf(fd);
  const ri = fd.related_index || '';
  const vp = fd.valuation_portfolio || [];
  const cat = fd.category || '';
  const sym = vp.length ? (vp[0].symbol || '') : '';
  if (cat === 'QDII日本') return { algo: '指数公式(N225)', src: '日经225(Yahoo/新浪)' };
  if (vm === 'index' || vm === 'equity_asia' || vm === 'lof_domestic') return { algo: `指数公式(${ri || '指数'})`, src: '指数点位(新浪/东财)' };
  if (vm === 'etf') return { algo: '魔法公式(单一ETF+hedge)；hedge缺失→矩阵(篮子)标准公式', src: `Woody hedge；兜底用 ${sym} 净值(Yahoo)` };
  if (vm === 'basket') return { algo: '矩阵(篮子)标准公式', src: '各 ETF 净值(Yahoo/IB) + yaml 权重' };
  if (isIndexRi(ri) && vp.length <= 1) return { algo: `指数公式(${ri})`, src: '指数点位(新浪/东财)' };
  if (vp.length > 1) return { algo: '矩阵(篮子)标准公式', src: '各 ETF 净值(Yahoo/IB) + yaml 权重' };
  if (vp.length === 1) return { algo: '魔法公式(单一ETF+hedge)；hedge缺失→矩阵(篮子)标准公式', src: `Woody hedge；兜底用 ${sym} 净值(Yahoo)` };
  return { algo: '待确认', src: '待确认' };
}
function invDynAlgo(fd) {
  const vm = vmOf(fd);
  const ri = fd.related_index || '';
  const vp = fd.valuation_portfolio || [];
  const cat = fd.category || '';
  const sym = vp.length ? (vp[0].symbol || '') : '';
  if (cat === 'QDII日本') return { algo: 'NK 期货标准公式', src: '新浪 hf_NK 实时价 + futures_daily NK 结算价 + 日元在岸价' };
  if (vm === 'index' && vp.length === 1) return { algo: 'Tier1 魔法公式(单一ETF+hedge); Tier2 矩阵(篮子)标准公式', src: `Tier1: ${sym} 实时价(IB→富途→新浪) + Woody hedge; Tier2: Yahoo 净值 + yaml 权重` };
  if (vm === 'etf' || (vm === '' && vp.length === 1)) return { algo: 'Tier1 魔法公式(单一ETF+hedge); Tier2 矩阵(篮子)标准公式', src: `Tier1: ${sym} 实时价(IB→富途→新浪) + Woody hedge; Tier2: Yahoo 净值 + yaml 权重` };
  if (vm === 'basket' || (vm === '' && vp.length > 1)) return { algo: '矩阵(篮子)标准公式', src: '各 ETF 实时价(IB→富途→新浪) + 基准价(Yahoo/IB) + yaml 权重' };
  if (isIndexRi(ri) && vm !== 'etf' && vm !== 'basket') return { algo: `指数公式(${ri})`, src: '指数点位(新浪/东财)' };
  return { algo: '待确认', src: '待确认' };
}
function invVpStr(vp) {
  if (!vp || !vp.length) return '';
  return vp.map((v) => {
    const s = v.symbol || '';
    const w = v.weight != null ? v.weight : '';
    const a = v.anchor || '';
    return a ? `${s}(${w},${a})` : `${s}(${w})`;
  }).join(', ');
}
function invHedgeStr(fd) {
  const te = fd.trade_etf || '';
  const tf = fd.trade_future || '';
  const fh = fd.future_hedging || [];
  const cat = fd.category || '';
  const parts = [];
  if (te) parts.push(`ETF ${te}`);
  if (tf) parts.push(`期货 ${tf}`);
  else if (fh && fh.length) fh.forEach((h) => parts.push(`期货 ${h.symbol || ''}`));
  if (cat === 'QDII亚洲' || cat === '国内LOF') return '无法对冲';
  if (!parts.length) return '未配置';
  return parts.join(' / ');
}
function invHedgeFallback(cat) {
  switch (cat) {
    case '黄金原油': return '对冲ETF实时价: IB→富途→None; 期货结算价: 新浪 hf_/nf_';
    case 'QDII欧美': return '对冲ETF实时价: IB→富途→None; 期货结算价: 新浪';
    case 'QDII日本': return '日经期货NK: 新浪 hf_NK(无兜底)';
    case 'QDII亚洲':
    case '国内LOF': return '无法对冲';
    case '白银': return '沪银Ag: 上期所/新浪(无兜底)';
    case '现金管理': return '未配置';
    default: return '待确认';
  }
}

const inventoryRows = computed(() => {
  const catOrder = ['黄金原油', 'QDII欧美', 'QDII日本', 'QDII亚洲', '国内LOF', '白银', '现金管理'];
  const rows = (fundConfigs.value || []).map((fd) => {
    const cat = fd.category || '';
    const sa = invStaticAlgo(fd);
    const da = invDynAlgo(fd);
    const unified = cat === '黄金原油';
    const ev = invVpStr(fd.valuation_portfolio) || fd.trade_etf || fd.related_index || '';
    return {
      code: fd.code, name: fd.name || '', cat, unified,
      staticAlgo: unified ? '矩阵(篮子)标准公式' : sa.algo,
      staticSrc: unified ? 'woody API（含hedge）' : sa.src,
      dynAlgo: unified ? '矩阵(篮子)标准公式' : da.algo,
      dynSrc: unified ? 'woody API（含hedge）' : da.src,
      hedge: invHedgeStr(fd), hedgeFallback: invHedgeFallback(cat), evidence: ev,
    };
  });
  rows.sort((a, b) => {
    const ia = catOrder.indexOf(a.cat); const ib = catOrder.indexOf(b.cat);
    if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    return String(a.code).localeCompare(String(b.code));
  });
  return rows;
});

const invCatOptions = computed(() => {
  const set = new Set();
  inventoryRows.value.forEach((r) => set.add(r.cat));
  return Array.from(set).map((c) => ({ label: c, value: c }));
});

const invFiltered = computed(() => {
  const c = invFilterCat.value;
  const q = (invQuery.value || '').toLowerCase().trim();
  return inventoryRows.value.filter((r) => {
    if (c && r.cat !== c) return false;
    if (!q) return true;
    return (r.code + r.name + r.staticAlgo + r.dynAlgo + r.hedge + r.evidence).toLowerCase().includes(q);
  });
});

const exportInventoryCsv = () => {
  const headers = ['分类', '代码', '名称', '静态估值算法', '静态数据源', '实时估值算法', '实时数据源', '对冲方式', '对冲兜底链', '关键证据'];
  const lines = [headers.join(',')];
  inventoryRows.value.forEach((r) => {
    const cells = [r.cat, r.code, r.name, r.staticAlgo, r.staticSrc, r.dynAlgo, r.dynSrc, r.hedge, r.hedgeFallback, r.evidence];
    lines.push(cells.map((cell) => `"${String(cell == null ? '' : cell).replace(/"/g, '""')}"`).join(','));
  });
  const csv = '﻿' + lines.join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  const ts = new Date().toISOString().slice(0, 10);
  link.setAttribute('download', `基金大盘点_${ts}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  window.URL.revokeObjectURL(url);
  message.success('已导出 CSV');
};

onMounted(() => {
  loadIbCoreSymbols();
  loadPausedCategories();
  fetchFundConfigs();
  fetchCategories();
});
</script>

<style scoped>
.header-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

/* ===== 基金大盘点表格样式 ===== */
.inv-controls { margin-bottom: 12px; }
.inv-table-wrap {
  max-height: 65vh;
  overflow: auto;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}
.inv-table {
  border-collapse: collapse;
  width: 100%;
  font-size: 12.5px;
  table-layout: fixed;
}
.inv-table th, .inv-table td {
  border: 1px solid #e5e7eb;
  padding: 8px 10px;
  text-align: left;
  vertical-align: top;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.inv-table thead th {
  background: linear-gradient(180deg, #374151 0%, #1f2937 100%);
  color: #fff;
  position: sticky;
  top: 0;
  z-index: 2;
  font-weight: 600;
  letter-spacing: 0.3px;
  white-space: nowrap;
  padding: 10px 10px;
}
.inv-table tbody tr { transition: background 0.15s; }
.inv-table tbody tr:nth-child(even) { background: #f9fafb; }
.inv-table tbody tr:hover { background: #eff6ff !important; }
.inv-code {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-weight: 600;
  white-space: nowrap;
  color: #1e293b;
  letter-spacing: 0.5px;
}
.inv-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11.5px;
  font-weight: 600;
  white-space: nowrap;
  letter-spacing: 0.2px;
}
.inv-algo { font-weight: 600; color: #1e293b; white-space: nowrap; }
.inv-sub {
  font-size: 11px;
  color: #94a3b8;
  margin-top: 3px;
  line-height: 1.5;
  white-space: nowrap;
}
.inv-ev {
  color: #475569;
  font-size: 11.5px;
  max-width: 280px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.inv-note {
  font-size: 11.5px;
  color: #64748b;
  line-height: 1.8;
  margin-top: 14px;
  background: #f8fafc;
  padding: 10px 14px;
  border-radius: 8px;
  border: 1px solid #f1f5f9;
}
</style>
