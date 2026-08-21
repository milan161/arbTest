<template>
  <!-- 手动交易区 - 公开非涉密 -->
  <div style="display:flex;gap:12px;margin-bottom:10px;flex-wrap:wrap;">
    <!-- LOF 手动交易行 -->
    <div style="display:flex;gap:8px;align-items:center;padding:6px 10px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;flex:1;">
      <span style="font-size:16px;">🛒</span>
      <span style="color:#15803d;font-weight:bold;font-size:13px;">LOF</span>
      <span style="color:#94a3b8;font-size:12px;">@</span>
      <n-input-number
        v-model:value="lofPrice"
        :step="0.001"
        size="small"
        style="width:110px;"
        :show-button="true"
        :min="0"
      />
      <span style="color:#64748b;font-size:12px;">× {{ lofQty }}股</span>
      <n-select
        v-model:value="broker"
        size="small"
        style="width: 130px;"
        :options="[
          { label: '银河QMT', value: 'yinhe_qmt' },
          { label: '通达信(华宝)', value: 'tdx' },
          { label: '国金QMT', value: 'guojin_qmt' }
        ]"
      />
      <span style="flex:1;"></span>
      <n-button
        type="success"
        size="small"
        style="font-weight:bold;"
        :disabled="!lofPrice || !lofQty"
        @click="$emit('buy')"
      >手动买入</n-button>
      <n-button
        type="warning"
        size="small"
        style="font-weight:bold;"
        :disabled="!lofPrice || !lofQty"
        @click="$emit('sell')"
      >手动卖出</n-button>
    </div>

    <!-- ETF 手动交易行 -->
    <div
      v-if="showForeign"
      style="display:flex;gap:8px;align-items:center;padding:6px 10px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;flex:1;"
    >
      <span style="font-size:16px;">📊</span>
      <span style="color:#1d4ed8;font-weight:bold;font-size:13px;">{{ etfSymbol }}</span>
      <span style="color:#94a3b8;font-size:12px;">@</span>
      <n-input-number
        v-model:value="etfPrice"
        :step="0.01"
        size="small"
        style="width:110px;"
        :show-button="true"
        :min="0"
      />
      <span style="color:#64748b;font-size:12px;">USD × {{ etfQty }}股</span>
      <span style="flex:1;"></span>
      <n-button
        type="warning"
        size="small"
        style="font-weight:bold;"
        :disabled="!etfPrice || !etfQty"
        @click="$emit('short')"
      >手动卖出</n-button>
      <n-button
        type="success"
        size="small"
        style="font-weight:bold;"
        :disabled="!etfPrice || !etfQty"
        @click="$emit('cover')"
      >手动买入</n-button>
    </div>
  </div>
</template>

<script setup>
import { NButton, NInputNumber, NSelect } from 'naive-ui'

defineProps({
  showForeign: { type: Boolean, default: false },
  etfSymbol: { type: String, default: '' },
  lofQty: { type: Number, default: 0 },
  etfQty: { type: Number, default: 0 },
})

const lofPrice = defineModel('lofPrice', { type: Number, default: 0 })
const etfPrice = defineModel('etfPrice', { type: Number, default: 0 })
const broker = defineModel('broker', { type: String, default: 'yinhe_qmt' })

defineEmits(['buy', 'sell', 'short', 'cover'])
</script>
