<template>
  <div class="silver-ratio-page">
    <n-card :bordered="false" class="shadow-soft" size="small">
      <template #header>
        <div style="display: flex; align-items: center; gap: 12px;">
          <n-icon size="20" color="#d97706"><TrendingUp /></n-icon>
          <span style="font-size: 16px; font-weight: bold; color: #d97706;">白银比价监控 (161226)</span>
          <n-tag :type="silverRatioData.length > 0 ? 'success' : 'warning'" size="small" round>
            {{ silverRatioData.length }} 条数据
          </n-tag>
        </div>
      </template>

      <p style="font-size: 12px; color: #64748b; margin: 0 0 12px 0;">
        比价公式: (AG_settle / (USDCNY × 32.15)) / SI_close &nbsp;|&nbsp; 32.15 = 金衡盎司/千克转换系数
      </p>

      <div v-if="silverRatioLoading" style="text-align: center; padding: 40px; color: #999;">
        <n-spin size="small" />
        <span style="margin-left: 8px;">加载中...</span>
      </div>

      <div v-else style="overflow-x: auto; max-height: 600px; overflow-y: auto;">
        <n-empty v-if="silverRatioData.length === 0" description="暂无比价数据" />
        <table v-else style="width: 100%; border-collapse: collapse; font-size: 12px; font-family: monospace;">
          <thead>
            <tr style="background: #f8fafc; border-bottom: 2px solid #e2e8f0; position: sticky; top: 0;">
              <th style="padding: 6px 8px; text-align: left;">日期</th>
              <th style="padding: 6px 8px; text-align: right;">AG收盘(¥/kg)</th>
              <th style="padding: 6px 8px; text-align: right;">AG结算(¥/kg)</th>
              <th style="padding: 6px 8px; text-align: right;">成交量(手)</th>
              <th style="padding: 6px 8px; text-align: right;">SI($/oz)</th>
              <th style="padding: 6px 8px; text-align: right;">USDCNY</th>
              <th style="padding: 6px 8px; text-align: right; color: #d97706; font-weight: bold;">比价</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, idx) in silverRatioData" :key="idx"
                :style="{ background: row.ratio ? '#fffbeb' : '#f9fafb', borderBottom: '1px solid #f1f5f9' }">
              <td style="padding: 4px 8px;">{{ row.date ? row.date.substring(5) : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right;">{{ row.ag_close != null ? row.ag_close.toFixed(2) : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right;">{{ row.ag_settle != null ? row.ag_settle.toFixed(2) : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right;">{{ row.ag_volume != null ? row.ag_volume.toLocaleString() : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right;">{{ row.si_close != null ? row.si_close.toFixed(2) : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right;">{{ row.usd_cny != null ? row.usd_cny.toFixed(4) : '-' }}</td>
              <td style="padding: 4px 8px; text-align: right; font-weight: bold; color: #d97706;">
                {{ row.ratio != null ? row.ratio.toFixed(4) : '-' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NTag, NIcon, NEmpty, NSpin } from 'naive-ui'
import { TrendingUp } from 'lucide-vue-next'
import { getSilverRatio } from '../api'

const silverRatioData = ref<any[]>([])
const silverRatioLoading = ref(false)

const fetchSilverRatio = async () => {
  silverRatioLoading.value = true
  try {
    const res = await getSilverRatio()
    if (res.data.status === 'ok') {
      silverRatioData.value = res.data.data || []
    }
  } catch (e) {
    silverRatioData.value = []
  } finally {
    silverRatioLoading.value = false
  }
}

onMounted(() => {
  fetchSilverRatio()
})
</script>

<style scoped>
.silver-ratio-page { padding: 12px; }
.shadow-soft { box-shadow: 0 4px 20px rgba(0, 0, 0, 0.04); border-radius: 12px; }
</style>
