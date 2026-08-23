<template>
  <div class="p-6">

    <!-- ===== 顶部一行：左 实时行情 | 右 分类优先级 ===== -->
    <div style="display:grid; grid-template-columns: 1fr 1.3fr; gap:16px; align-items:start; margin-bottom:16px;">

      <!-- 左卡片：实时行情 -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div class="flex items-center mb-4">
          <div class="w-2 h-6 bg-blue-500 rounded mr-3" style="background-color: var(--primary-color)"></div>
          <h2 class="text-xl font-bold text-gray-700">实时行情</h2>
        </div>

        <table style="width:100%; border-collapse:collapse; font-size:13px;">
          <thead>
            <tr style="border-bottom:1px solid #e5e7eb; color:#6b7280; font-weight:500;">
              <th style="text-align:left; padding-left:12px;">数据源</th>
              <th style="width:44px; text-align:center;">优先级</th>
              <th style="width:80px; text-align:center;">状态</th>
              <th style="width:50px; text-align:center;">排序</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(source, index) in realtimeSources" :key="source.source_name"
                style="border-bottom:1px solid #f3f4f6; transition: background 0.15s;"
                :style="{ background: source.is_active ? '#eff6ff' : 'transparent' }">
              <!-- 数据源名称（左对齐，第一列） -->
              <td style="text-align:left; padding:6px 12px;">
                <div style="font-weight:600; color:#1f2937; font-size:13px;">{{ source.displayName }}</div>
                <div style="font-size:11px; color:#9ca3af; margin-top:1px;">{{ source.config?.desc || '' }}</div>
              </td>
              <!-- 优先级圆标 -->
              <td style="text-align:center; padding:6px 0;">
                <span style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; border-radius:50%; background:white; border:1px solid #d1d5db; font-size:11px; font-weight:bold; color:var(--primary-color);">{{ index + 1 }}</span>
              </td>
              <!-- 状态开关（点击切换） -->
              <td style="text-align:center; padding:6px 0;">
                <div style="display:inline-flex; align-items:center; gap:5px; cursor:pointer;" @click="toggleActive(source)">
                  <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#d1d5db; transition:all 0.2s;" :class="{ 'on': source.is_active }" :style="source.is_active ? { background:'var(--primary-color)', boxShadow:'0 0 6px var(--primary-color)' } : {}"></span>
                  <span :style="{ color: source.is_active ? 'var(--primary-color)' : '#9ca3af', fontSize:'11px', fontWeight:600 }">{{ source.is_active ? '启用' : '停用' }}</span>
                </div>
              </td>
              <!-- 上下箭头 -->
              <td style="text-align:center; padding:6px 0;">
                <n-space :size="2" vertical style="gap:2px;">
                  <button @click="move(index, -1)" :disabled="index === 0" class="btn-arrow" style="padding:1px 4px; font-size:10px;">▲</button>
                  <button @click="move(index, 1)" :disabled="index === realtimeSources.length - 1" class="btn-arrow" style="padding:1px 4px; font-size:10px;">▼</button>
                </n-space>
              </td>
            </tr>
          </tbody>
        </table>
        <div style="font-size:11px; color:#9ca3af; margin-top:6px;">点击状态切换启用/停用 · 箭头调整优先级 · 改动即时自动保存</div>
      </div>

      <!-- 右卡片：分类优先级 -->
      <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div class="flex items-center mb-4">
          <div class="w-2 h-6 rounded mr-3" style="background-color:#7c3aed"></div>
          <h2 class="text-xl font-bold text-gray-700">分类优先级</h2>
        </div>
        <!-- 对齐条：与左侧实时行情表头等高，使下方分类首行（黄金原油）与「通达信极速」行对齐 -->
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

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { getDataSources, updateDataSource, updateDataSourcesPriority } from '../api';
import { getIbCoreSymbols, postIbCoreSymbols, getPausedCategories, postPausedCategories } from '../api';
import { useMessage, NSpace } from 'naive-ui';

const message = useMessage();
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

const realtimeSources = ref([]);

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


const sourceNames = {
    'guojin': '国金证券 QMT',
    'galaxy': '银河证券 QMT',
    'tdx': '通达信极速',
    'sina': '新浪财经 API',
    'eastmoney': '东方财富数据'
};

const fetchConfigs = async () => {
    try {
        const resRealtime = await getDataSources('realtime_market');
        realtimeSources.value = resRealtime.data.data.map(s => ({
            ...s,
            displayName: sourceNames[s.source_name] || s.source_name
        }));
    } catch (e) {
        console.error('获取配置失败', e);
    }
};

// [AI-2026-08-22] 方向A：排序即时保存（触发引擎重启使新顺序生效）
const move = async (index, direction) => {
    const target = index + direction;
    if (target < 0 || target >= realtimeSources.value.length) return;
    const temp = realtimeSources.value[index];
    realtimeSources.value[index] = realtimeSources.value[target];
    realtimeSources.value[target] = temp;
    try {
        const priorities = realtimeSources.value.map((s, idx) => ({
            source_name: s.source_name,
            priority: idx + 1
        }));
        await updateDataSourcesPriority('realtime_market', priorities);
        message.success('✅ 优先级已更新');
    } catch (e) {
        message.error('❌ 保存失败: ' + (e.message || e));
    }
};

// [AI-2026-08-22] 方向A：开关即时保存。updateDataSource 仅持久化，
// 需再调 updateDataSourcesPriority 触发引擎重启，is_active 才会真正生效
const toggleActive = async (source) => {
    source.is_active = source.is_active ? 0 : 1;
    try {
        await updateDataSource({
            module: source.module,
            source_name: source.source_name,
            is_active: source.is_active
        });
        const priorities = realtimeSources.value.map((s, idx) => ({
            source_name: s.source_name,
            priority: idx + 1
        }));
        await updateDataSourcesPriority('realtime_market', priorities);
        message.success(source.is_active ? '✅ 已启用' : '✅ 已停用');
    } catch (e) {
        source.is_active = source.is_active ? 0 : 1; // 回滚
        message.error('❌ 保存失败: ' + (e.message || e));
    }
};

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

onMounted(() => { fetchConfigs(); loadIbCoreSymbols(); loadPausedCategories() });
</script>

<style scoped>
.header-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.btn-arrow { padding: 2px 6px; background: transparent; border: none; cursor: pointer; font-size: 12px; }
.btn-arrow:disabled { color: #d1d5db !important; }
</style>
