<template>
  <div class="p-6">
    <div class="header-section">
      <div style="display: flex; align-items: center; gap: 16px;">
        <h1 class="text-2xl font-bold text-gray-800">数据源配置中心</h1>
      </div>
      <button
        @click="saveAll"
        class="btn-standard"
        style="padding: 8px 24px; font-size: 14px;"
      >
        保存并应用配置
      </button>
    </div>

    <!-- 实时行情配置 - 强制横向网格 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-8">
      <div class="flex items-center mb-6">
        <div class="w-2 h-6 bg-blue-500 rounded mr-3" style="background-color: var(--primary-color)"></div>
        <h2 class="text-xl font-bold text-gray-700">实时行情 (Real-time Market)</h2>
        <span class="ml-4 text-sm text-gray-400 font-normal">点击箭头调整优先级</span>
      </div>

      <!-- 网格容器：强制 4 列 -->
      <div class="grid-container">
        <div
          v-for="(source, index) in realtimeSources"
          :key="source.source_name"
          class="source-card"
          :class="{ 'active': source.is_active }"
        >
          <!-- 优先级角标 -->
          <div class="priority-badge" style="color: var(--primary-color)">{{ index + 1 }}</div>

          <div class="card-header">
            <div class="title">{{ source.displayName }}</div>
            <div class="desc">{{ source.config.desc || '暂无描述' }}</div>
          </div>

          <!-- 状态显示 -->
          <div class="status-box">
            <div class="dot" :class="{ 'on': source.is_active }" :style="source.is_active ? { backgroundColor: 'var(--primary-color)', boxShadow: '0 0 8px var(--primary-color)' } : {}"></div>
            <span class="status-text" :style="source.is_active ? { color: 'var(--primary-color)' } : {}">{{ source.is_active ? '已启用' : '已停用' }}</span>
          </div>

          <!-- 底部操作区 -->
          <div class="card-footer">
            <div class="actions">
              <button @click="toggleActive(source)" class="btn-standard" style="padding: 4px 10px; font-size: 11px;">
                {{ source.is_active ? '停用' : '启用' }}
              </button>
              <button @click="testConnection(source)" class="btn-test">测试</button>
            </div>

            <div class="arrows">
              <button @click="move(index, -1)" :disabled="index === 0" class="btn-arrow" style="color: var(--primary-color)">◀</button>
              <button @click="move(index, 1)" :disabled="index === realtimeSources.length - 1" class="btn-arrow" style="color: var(--primary-color)">▶</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 历史数据配置 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div class="flex items-center mb-6">
        <div class="w-2 h-6 bg-blue-400 rounded mr-3" style="background-color: var(--primary-color); opacity: 0.8;"></div>
        <h2 class="text-xl font-bold text-gray-700">历史数据 (Historical Data)</h2>
      </div>

      <div class="grid-container-hist">
          <div
            v-for="source in historicalSources"
            :key="source.source_name"
            class="hist-card"
          >
              <div class="hist-title">{{ source.displayName }}</div>
              <div class="hist-desc">{{ source.config.desc }}</div>
              <div class="hist-select-box">
                <span class="label">状态</span>
                <select v-model="source.is_active" class="select-status">
                    <option :value="1">🔵 启用</option>
                    <option :value="0">⚪ 停用</option>
                </select>
              </div>
          </div>
      </div>
    </div>
    
    <!-- IB 核心套利标的配置 -->
    <div class="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-8">
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
        
        <!-- 操作按钮 -->
        <div style="display: flex; gap: 8px; align-items: center;">
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
        
        <div style="font-size: 12px; color: #94a3b8; line-height: 1.6;">
          <div>📌 默认 7 只：XOP, GLD, USO, SLV, INDA, QQQ, SPY</div>
          <div>⚠️ 修改后立即生效，IB 会重新订阅</div>
          <div>ℹ️ 这些是套利必需的标的，其他 ETF（XLK、ARKK、EWA 等）走富途数据源</div>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { getDataSources, updateDataSource, updateDataSourcesPriority } from '../api';
import { getIbCoreSymbols, postIbCoreSymbols } from '../api';
import { useMessage, NInput, NButton, NTag, NSpace } from 'naive-ui';

const message = useMessage();
const ibCoreSymbols = ref([]);
const ibCoreSymbolsText = ref('');

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
const historicalSources = ref([]);

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

        const resNav = await getDataSources('historical_nav');
        const resPrice = await getDataSources('historical_price');
        historicalSources.value = [
            ...resNav.data.data.map(s => ({ ...s, displayName: `基金净值源: ${sourceNames[s.source_name] || s.source_name}` })),
            ...resPrice.data.data.map(s => ({ ...s, displayName: `价格行情源: ${sourceNames[s.source_name] || s.source_name}` }))
        ];


    } catch (e) {
        console.error('获取配置失败', e);
    }
};

const move = (index, direction) => {
    const target = index + direction;
    if (target < 0 || target >= realtimeSources.value.length) return;
    const temp = realtimeSources.value[index];
    realtimeSources.value[index] = realtimeSources.value[target];
    realtimeSources.value[target] = temp;
};

const toggleActive = (source) => {
    source.is_active = source.is_active ? 0 : 1;
};

const testConnection = async (source) => {
    alert(`正在对 ${source.displayName} 进行连接诊断...`);
};

const saveAll = async () => {
    try {
        const priorities = realtimeSources.value.map((s, idx) => ({
            source_name: s.source_name,
            priority: idx + 1
        }));
        await updateDataSourcesPriority('realtime_market', priorities);

        for (const s of [...realtimeSources.value, ...historicalSources.value]) {
            await updateDataSource({
                module: s.module,
                source_name: s.source_name,
                is_active: s.is_active
            });
        }



        alert('✅ 配置已保存成功！');
        fetchConfigs();
    } catch (e) {
        alert('❌ 保存失败: ' + e.message);
    }
};

onMounted(() => { fetchConfigs(); loadIbCoreSymbols() });
</script>

<style scoped>
.header-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
}

.grid-container {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
@media (max-width: 1200px) {
  .grid-container { grid-template-columns: repeat(2, 1fr); }
}

.source-card {
  position: relative;
  padding: 20px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #f9fafb;
  transition: all 0.3s;
  display: flex;
  flex-direction: column;
}
.source-card.active {
  border-color: var(--primary-color);
  background: var(--primary-light);
}
.priority-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: white;
  border: 1px solid #d1d5db;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: bold;
}
.card-header .title {
  font-weight: 700;
  color: #1f2937;
  margin-bottom: 4px;
}
.card-header .desc {
  font-size: 12px;
  color: #9ca3af;
  height: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-box {
  margin: 16px 0;
  display: flex;
  align-items: center;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #d1d5db;
  margin-right: 8px;
}
.status-text {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.card-footer {
  margin-top: auto;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.btn-test {
  padding: 4px 8px;
  font-size: 11px;
  background: #f3f4f6;
  border: none;
  border-radius: 6px;
  margin-left: 8px;
  cursor: pointer;
}
.btn-arrow {
  padding: 2px 6px;
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 14px;
}
.btn-arrow:disabled { color: #d1d5db !important; }

/* 历史数据网格 */
.grid-container-hist {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
.hist-card {
  padding: 16px;
  border: 1px solid #f3f4f6;
  border-radius: 12px;
  background: #f9fafb;
}
.hist-title { font-weight: 700; font-size: 14px; }
.hist-desc { font-size: 12px; color: #9ca3af; margin: 4px 0 12px; height: 32px; overflow: hidden; }
.hist-select-box { display: flex; align-items: center; }
.hist-select-box .label { font-size: 12px; color: #6b7280; margin-right: 8px; }
.select-status {
  flex-grow: 1;
  padding: 4px;
  border-radius: 6px;
  border: 1px solid #e5e7eb;
  font-size: 12px;
}
</style>
