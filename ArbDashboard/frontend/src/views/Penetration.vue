<template>
  <div class="pen-page">
    <!-- 顶部栏 -->
    <div class="pen-header">
      <div class="pen-header-left">
        <button class="back-btn" @click="router.back()">← 返回季报持仓分析</button>
        <h1 class="pen-title">底层资产穿透分析</h1>
        <span class="pen-tag">{{ fundCode }}</span>
      </div>
      <div class="pen-periods">
        <span class="pen-periods-label">报告期:</span>
        <button
          v-for="p in periods"
          :key="p"
          class="period-btn"
          :class="{ active: currentPeriod === p }"
          @click="switchPeriod(p)"
        >{{ p }}</button>
      </div>
    </div>

    <!-- 加载 / 错误 -->
    <div v-if="loading" class="pen-state">加载中...</div>
    <div v-else-if="error" class="pen-state error">{{ error }}</div>

    <template v-else-if="rows.length > 0">
      <!-- 指标卡片 -->
      <div class="metrics-row">
        <div class="metric-card">
          <div class="metric-value metric-blue">{{ fmt(summary.total_quarter) }}%</div>
          <div class="metric-label">季报产品覆盖</div>
        </div>
        <div class="metric-card">
          <div class="metric-value metric-orange">{{ fmt(summary.total_penetrated) }}%</div>
          <div class="metric-label">已穿透至期货</div>
        </div>
        <div class="metric-card">
          <div class="metric-value metric-green">{{ fmt(wtiTotal) }}%</div>
          <div class="metric-label">WTI (CL) 敞口</div>
        </div>
        <div class="metric-card">
          <div class="metric-value metric-purple">{{ fmt(brentTotal) }}%</div>
          <div class="metric-label">Brent (B) 敞口</div>
        </div>
      </div>

      <!-- 穿透规则说明 -->
      <div class="section">
        <div class="section-title">穿透规则说明</div>
        <table>
          <thead>
            <tr>
              <th>产品类型</th>
              <th>代表基金</th>
              <th>穿透方式</th>
              <th>等效比例</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(r, i) in ruleRows" :key="i">
              <td>{{ r.type }}</td>
              <td>{{ r.funds }}</td>
              <td>{{ r.method }}</td>
              <td><span class="badge" :class="r.badgeClass">{{ r.ratio }}</span></td>
            </tr>
          </tbody>
        </table>
        <div class="explanation">
          <strong>核心逻辑：</strong>穿透公式 = <code>季报权重 ÷ 季报合计 × 等效比例 × 合约内部比例</code><br>
          TRS追踪公开指数可全额穿透（等效比例=1.0），定制OTC互换因无公开规则不计入穿透。
        </div>
      </div>

      <!-- 完整映射明细 -->
      <div class="section">
        <div class="section-title">从季报产品到期货合约的完整映射</div>
        <div style="overflow-x: auto;">
          <table class="detail-table">
            <thead>
              <tr>
                <th>季报产品</th>
                <th>季报权重</th>
                <th>归一化权重</th>
                <th>等效比例</th>
                <th>合约代码</th>
                <th>合约年月</th>
                <th>最终占比</th>
                <th>品种</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in rows" :key="i">
                <td><strong>{{ row.product }}</strong></td>
                <td>{{ fmt(row.quarter_weight) }}%</td>
                <td>{{ fmt(row.normalized_weight) }}%</td>
                <td>{{ fmt4(row.etf_ratio) }}</td>
                <td><code>{{ row.contract_code }}</code></td>
                <td :title="row.contract_name">
                  {{ row.contract_ym || '-' }}
                  <span v-if="row.month_label" class="ym-sub">（{{ row.month_label }}）</span>
                </td>
                <td><strong>{{ fmt(row.final_pct) }}%</strong></td>
                <td>
                  <span class="badge" :class="row.variety === 'WTI' ? 'badge-wti' : 'badge-brent'">
                    {{ row.variety }}
                  </span>
                </td>
              </tr>
              <tr class="summary-row">
                <td colspan="6" style="text-align: right;">WTI 小计</td>
                <td>{{ fmt(wtiTotal) }}%</td>
                <td>-</td>
              </tr>
              <tr class="summary-row">
                <td colspan="6" style="text-align: right;">Brent 小计</td>
                <td>{{ fmt(brentTotal) }}%</td>
                <td>-</td>
              </tr>
              <tr class="summary-row total-row">
                <td colspan="6" style="text-align: right;"><strong>合计</strong></td>
                <td><strong>{{ fmt(summary.total_penetrated) }}%</strong></td>
                <td>-</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 按到期月份统计（WTI / Brent + CL 对冲折算） -->
      <div class="section">
        <div class="section-title">按到期月份统计（Brent 折算同月份 CL，用于对冲）</div>
        <div style="overflow-x: auto;">
          <table class="detail-table">
            <thead>
              <tr>
                <th>到期月份</th>
                <th>CL 合约</th>
                <th>WTI 占比</th>
                <th>Brent 合约</th>
                <th>Brent 占比</th>
                <th>覆盖说明</th>
                <th>合计占比</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="m in monthStats" :key="m.ym">
                <td><strong>{{ m.ym }}</strong></td>
                <td><code>{{ m.cl }}</code></td>
                <td>{{ m.wti ? fmt(m.wti.pct) + '%' : '—' }}</td>
                <td><code v-if="m.brent">{{ m.brent.code }}</code><span v-else>—</span></td>
                <td>{{ m.brent ? fmt(m.brent.pct) + '%' : '—' }}</td>
                <td>{{ m.coverage }}</td>
                <td><strong>{{ fmt(m.total) }}%</strong></td>
              </tr>
              <tr class="summary-row total-row">
                <td><strong>小计</strong></td>
                <td></td>
                <td class="subtotal-cell">{{ fmt(wtiTotal) }}%</td>
                <td></td>
                <td class="subtotal-cell">{{ fmt(brentTotal) }}%</td>
                <td></td>
                <td class="subtotal-cell"><strong>{{ fmt(summary.total_penetrated) }}%</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 关键发现 -->
      <div class="section">
        <div class="section-title">关键发现</div>
        <ul class="findings">
          <li v-for="(f, i) in keyFindings" :key="i" v-html="f"></li>
        </ul>
      </div>
    </template>

    <div v-else class="pen-state">暂无穿透数据</div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const fundCode = ref<string>(
  (route.query.fund_code as string) || (route.query.fundCode as string) || '160723'
)
const currentPeriod = ref<string>((route.query.period as string) || '')
const periods = ref<string[]>([])

const loading = ref(false)
const error = ref('')
const rows = ref<any[]>([])
const summary = ref<any>({})

const ruleRows = [
  {
    type: 'TRS追踪公开指数',
    funds: 'CRUD / BRNT / BRNG',
    method: '按Bloomberg指数方法论等权拆分M2/M3/M4',
    ratio: '1.0',
    badgeClass: 'badge-wti'
  },
  {
    type: '直接持有期货',
    funds: 'USO / OILK',
    method: '官网披露持仓，按合约比例拆分',
    ratio: '0.44~1.0',
    badgeClass: 'badge-brent'
  },
  {
    type: '直接持有期货',
    funds: 'BNO',
    method: '单一合约持仓',
    ratio: '0.52',
    badgeClass: 'badge-brent'
  }
]

/** CME 期货月份代码 -> 数字月 */
const FUTURE_MONTH: Record<string, string> = {
  F: '01', G: '02', H: '03', J: '04', K: '05', M: '06',
  N: '07', Q: '08', U: '09', V: '10', X: '11', Z: '12'
}
/** 数字月 -> 英文缩写 */
const MONTH_ABBR: Record<string, string> = {
  '01': 'Jan', '02': 'Feb', '03': 'Mar', '04': 'Apr', '05': 'May', '06': 'Jun',
  '07': 'Jul', '08': 'Aug', '09': 'Sep', '10': 'Oct', '11': 'Nov', '12': 'Dec'
}

/**
 * 从期货合约代码解析标准合约年月（程序计算，不做硬编码）。
 * 例：CLX26(WTI) -> CL2611 / COX6(Brent) -> B2611 / CLM7 -> CL2706
 * 月份取自交易所月份代码，品种前缀由 variety 决定：WTI -> CL，Brent -> B。
 */
function parseContractYm(code: string, variety: string): { ym: string; label: string } {
  const fallback = { ym: code || '', label: '' }
  if (!code) return fallback
  const m = code.match(/^([A-Za-z]{1,2})([FGHJKMNQUVXZ])(\d{1,2})$/i)
  if (!m) return fallback
  const mm = FUTURE_MONTH[m[2].toUpperCase()]
  if (!mm) return fallback
  const yy = m[3].length === 1 ? `202${m[3]}` : `20${m[3]}`
  const prefix = variety === 'Brent' ? 'B' : 'CL'
  return {
    ym: `${prefix}${yy.slice(2)}${mm}`,
    label: `${MONTH_ABBR[mm]}${yy.slice(2)}`
  }
}

function fmt(v: any): string {
  return typeof v === 'number' ? v.toFixed(2) : (Number(v) || 0).toFixed(2)
}
function fmt4(v: any): string {
  return typeof v === 'number' ? v.toFixed(4) : (Number(v) || 0).toFixed(4)
}

const wtiTotal = computed(() =>
  rows.value.filter((r) => r.variety === 'WTI').reduce((s, r) => s + (Number(r.final_pct) || 0), 0)
)
const brentTotal = computed(() =>
  rows.value.filter((r) => r.variety === 'Brent').reduce((s, r) => s + (Number(r.final_pct) || 0), 0)
)

/** 解析合约代码的到期月份：CLV26 -> { ym:'2026-10', yy:'26', letter:'V' } */
function parseExpiry(code: string): { ym: string; yy: string; letter: string } | null {
  if (!code) return null
  const m = code.match(/^([A-Za-z]{1,2})([FGHJKMNQUVXZ])(\d{1,2})$/i)
  if (!m) return null
  const mm = FUTURE_MONTH[m[2].toUpperCase()]
  if (!mm) return null
  const yy = m[3].length === 1 ? `202${m[3]}` : `20${m[3]}`
  return { ym: `${yy}-${mm}`, yy: yy.slice(2), letter: m[2].toUpperCase() }
}

/** 统一显示代码：WTI -> CL+月码+年，Brent -> B+月码+年（COX6 -> BX26） */
function displayCode(code: string, variety: string): string {
  const e = parseExpiry(code)
  if (!e) return code
  return `${variety === 'Brent' ? 'B' : 'CL'}${e.yy}${e.letter}`
}

/** 数字月反查月份代码字母：'11' -> 'X' */
function monthLetter(mm: string): string {
  return Object.keys(FUTURE_MONTH).find((k) => FUTURE_MONTH[k] === mm) || ''
}

/**
 * 按到期月份统计（一张表同时覆盖 WTI/Brent 明细与 CL 对冲折算）：
 * Brent 敞口按同月份 CL 近似合并（Brent 不便于直接对冲时，用同月 CL 替代）。
 * 同一到期月份同一品种可能有多行（如 CRUD + USO 都持有 CLX26），必须累加。
 */
const monthStats = computed(() => {
  const map: Record<string, { ym: string; wti: any; brent: any }> = {}
  rows.value.forEach((r) => {
    const e = parseExpiry(r.contract_code || '')
    if (!e) return
    if (!map[e.ym]) map[e.ym] = { ym: e.ym, wti: null, brent: null }
    const key = r.variety === 'Brent' ? 'brent' : 'wti'
    const slot = map[e.ym][key]
    if (slot) slot.pct += Number(r.final_pct) || 0
    else map[e.ym][key] = {
      code: displayCode(r.contract_code, r.variety),
      pct: Number(r.final_pct) || 0
    }
  })
  return Object.values(map)
    .map((m) => {
      const mm = m.ym.slice(5, 7)
      const yy = m.ym.slice(2, 4)
      const parts: string[] = []
      if (m.wti) parts.push(`WTI ${Number(mm)} 月`)
      if (m.brent) parts.push(`Brent ${Number(mm)} 月`)
      return {
        ...m,
        cl: `CL${yy}${monthLetter(mm)}`,
        coverage: parts.join(' + '),
        total: (m.wti?.pct || 0) + (m.brent?.pct || 0)
      }
    })
    .sort((a, b) => a.ym.localeCompare(b.ym))
})

const keyFindings = computed(() => {
  const out: string[] = []
  const total = Number(summary.value.total_penetrated) || 0
  const list = monthStats.value
  if (list.length > 0) {
    const t = list.reduce((a, b) => (b.total > a.total ? b : a))
    out.push(
      `<strong>${t.ym} 是主战场</strong>：${t.total.toFixed(2)}%，占穿透部分的 ${total ? ((t.total / total) * 100).toFixed(1) : '0'}%`
    )
  }
  const w = wtiTotal.value
  const b = brentTotal.value
  if (w + b > 0) {
    out.push(
      `<strong>品种结构</strong>：WTI ${w.toFixed(2)}% / Brent ${b.toFixed(2)}%，WTI 占穿透部分 ${(((w / (w + b)) * 100)).toFixed(1)}%`
    )
  }
  const rest = 100 - total
  out.push(
    `<strong>剩余 ${rest.toFixed(2)}%</strong> 为不可穿透部分（OTC 互换 + 现金类资产）`
  )
  return out
})

/** 报告期从持仓接口动态获取，避免写死后访问不存在的期间 */
async function fetchPeriods() {
  try {
    const resp = await fetch(`/api/fund/${fundCode.value}/holding-periods`)
    if (!resp.ok) return
    const data = await resp.json()
    const list: any[] = (data?.data || data?.periods || [])
      .map((x: any) => x.period || x)
      .filter((x: any) => typeof x === 'string' && /Q[1-4]$/.test(x))
    periods.value = list
    const want = (route.query.period as string) || ''
    currentPeriod.value = list.includes(want) ? want : list[0] || ''
  } catch (e) {
    console.error('[Penetration] 报告期加载失败:', e)
    currentPeriod.value = currentPeriod.value || '2026Q2'
  }
}

async function fetchData() {
  if (!currentPeriod.value) return
  loading.value = true
  error.value = ''
  try {
    const resp = await fetch(`/api/penetration/${fundCode.value}/${currentPeriod.value}`)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json()
    const payload = data?.data || data

    const list = payload.penetrated || []
    rows.value = list.map((r: any) => {
      const { ym, label } = parseContractYm(r.contract_code || '', r.variety || '')
      return { ...r, contract_ym: ym || r.contract_code, month_label: label }
    })
    summary.value = payload.summary || {}
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function switchPeriod(p: string) {
  if (p === currentPeriod.value) return
  currentPeriod.value = p
  fetchData()
}

// 图表已按东哥要求移除，改为「期货合约分布（按年月聚合）」「品种敞口对比」两张程序计算的聚合表

onMounted(async () => {
  await fetchPeriods()
  await fetchData()
})
</script>

<style scoped>
.pen-page {
  padding: 16px;
  color: #1f2328;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  line-height: 1.6;
}

/* 顶部栏 */
.pen-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #d0d7de;
}
.pen-header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}
.back-btn {
  background: transparent;
  border: none;
  color: #0969da;
  font-size: 14px;
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 6px;
}
.back-btn:hover {
  background: #ddf4ff;
}
.pen-title {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
  color: #1f2328;
}
.pen-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  background: #ddf4ff;
  color: #0969da;
  border: 1px solid rgba(9, 105, 218, 0.2);
}
.pen-periods {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pen-periods-label {
  font-size: 12px;
  color: #656d76;
}
.period-btn {
  padding: 4px 12px;
  font-size: 13px;
  border: 1px solid #d0d7de;
  background: #ffffff;
  color: #1f2328;
  border-radius: 6px;
  cursor: pointer;
}
.period-btn:hover {
  background: #f6f8fa;
}
.period-btn.active {
  background: #0969da;
  border-color: #0969da;
  color: #ffffff;
  font-weight: 500;
}

.pen-state {
  text-align: center;
  padding: 60px;
  color: #656d76;
  font-size: 14px;
}
.pen-state.error {
  color: #cf222e;
}

/* 指标卡片 */
.metrics-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.metric-card {
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.metric-value {
  font-size: 30px;
  font-weight: 700;
  margin-bottom: 4px;
}
.metric-label {
  font-size: 13px;
  color: #656d76;
}
.metric-blue { color: #0969da; }
.metric-green { color: #1a7f37; }
.metric-orange { color: #9a6700; }
.metric-purple { color: #8250df; }

/* 区块 */
.section {
  background: #ffffff;
  border: 1px solid #d0d7de;
  border-radius: 8px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 20px;
  color: #1f2328;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title::before {
  content: '';
  width: 4px;
  height: 16px;
  background: #0969da;
  border-radius: 2px;
}

/* 表格 */
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
th,
td {
  padding: 10px 14px;
  text-align: left;
  border-bottom: 1px solid #eaeef2;
  white-space: nowrap;
}
th {
  background: #f6f8fa;
  color: #656d76;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.5px;
}
tbody tr:hover {
  background: #f6f8fa;
}
.detail-table td:nth-child(6),
.detail-table th:nth-child(6) {
  white-space: nowrap;
}
.summary-row {
  background: #f6f8fa;
  font-weight: 600;
}
.total-row {
  background: #ddf4ff;
}
.subtotal-cell {
  color: #0969da;
}

.ym-sub {
  color: #656d76;
  font-size: 12px;
  margin-left: 2px;
}

/* 徽标 */
.badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}
.badge-wti {
  background: rgba(9, 105, 218, 0.1);
  color: #0969da;
  border: 1px solid rgba(9, 105, 218, 0.2);
}
.badge-brent {
  background: rgba(26, 127, 55, 0.1);
  color: #1a7f37;
  border: 1px solid rgba(26, 127, 55, 0.2);
}

/* 说明块 */
.explanation {
  background: #fff8c5;
  border-left: 3px solid #9a6700;
  padding: 16px;
  margin-top: 16px;
  border-radius: 0 8px 8px 0;
  font-size: 14px;
  color: #656d76;
}
code {
  background: #f6f8fa;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Consolas', monospace;
  font-size: 13px;
  color: #9a6700;
  border: 1px solid #d0d7de;
}

.findings {
  padding-left: 20px;
  color: #656d76;
  line-height: 2;
}
.findings :deep(strong) {
  color: #1f2328;
}

@media (max-width: 900px) {
  .metrics-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
