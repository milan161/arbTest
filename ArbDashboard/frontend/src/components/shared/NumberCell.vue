<template>
  <span
    :class="['num-cell', { strong, muted, compact }]"
    :style="colorStyle"
  >
    {{ displayText }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { priceColor, COLOR_MUTED } from '../../utils'

const props = withDefaults(defineProps<{
  /** 数值 */
  value?: number | null
  /** 自定义显示文本（优先） */
  text?: string
  /** 小数位数 */
  precision?: number
  /** 是否显示正号 */
  showSign?: boolean
  /** 百分比模式（末尾加 %） */
  percent?: boolean
  /** 高亮（bold） */
  strong?: boolean
  /** 灰显 */
  muted?: boolean
  /** 紧凑 */
  compact?: boolean
  /** 强制指定颜色 */
  color?: string
  /** 根据数值正负自动染色 */
  colorByValue?: boolean
  /** 空白替代符 */
  placeholder?: string
}>(), {
  value: null,
  text: '',
  precision: 2,
  showSign: false,
  percent: false,
  strong: false,
  muted: false,
  compact: false,
  color: '',
  colorByValue: false,
  placeholder: '-'
})

const displayText = computed(() => {
  if (props.text) return props.text
  if (props.value === null || props.value === undefined || props.value === 0) return props.placeholder
  let text = props.value.toFixed(props.precision)
  if (props.showSign && props.value > 0) text = '+' + text
  if (props.percent) text += '%'
  return text
})

const colorStyle = computed(() => {
  if (props.color) return { color: props.color }
  if (props.muted) return { color: COLOR_MUTED }
  if (props.colorByValue && props.value !== null && props.value !== undefined) {
    return { color: priceColor(props.value) }
  }
  return {}
})
</script>

<style scoped>
.num-cell {
  font-family: 'Courier New', Consolas, monospace;
  font-size: 12px;
}
.num-cell.strong {
  font-weight: 700;
}
.num-cell.muted {
  color: #64748b;
}
.num-cell.compact {
  letter-spacing: -0.3px;
}
</style>
