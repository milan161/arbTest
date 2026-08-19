<template>
  <div class="trade-workbench">
    <!-- 顶部专业摘要栏 (标题 + 基础仓位 + 可选控件) -->
    <div class="fund-summary-header shadow-soft" style="background: #fff; padding: 12px 20px; border-radius: 12px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; border-bottom: 2px solid #ffcc80;">
      <div class="header-left" style="display: flex; align-items: center; gap: 16px;">
        <n-button quaternary circle @click="handleBack"><template #icon><n-icon><ArrowLeft /></n-icon></template></n-button>
        <div class="fund-info">
          <div style="font-size:18px; font-weight:bold; color: #d35400;">
            {{ fundName }} ({{ fundCode }})
            <template v-if="isCashManagement && meta?.cashFundInfo">
              <n-tag type="success" size="small" round style="margin-left: 8px;">{{ meta.cashFundInfo.type }}</n-tag>
              <n-tag type="info" size="small" round style="margin-left: 4px;">{{ meta.cashFundInfo.riskLevel }}</n-tag>
            </template>
            <template v-else>
              - 实时估值计算器
            </template>
          </div>
        </div>
        <!-- 左侧额外控件插槽（如 LazyMode 的基金选择器） -->
        <slot name="header-left-extra" />
        <!-- [AI-2026-08-19] 基础仓位属于半涉密信息：仅在 private 模式显示 -->
        <template v-if="mode === 'private' && !isCashManagement">
          <n-tag type="warning" size="medium" round style="font-weight: bold;">
            基础仓位: {{ ((positionRatio ?? 0.95) * 100).toFixed(2) }}%
          </n-tag>
        </template>
        <template v-else-if="isCashManagement">
          <n-tag type="success" size="medium" round style="font-weight: bold;">
            日均增长: {{ meta?.avg_daily_growth ? (meta.avg_daily_growth * 10000).toFixed(1) + '万' : '-' }}
          </n-tag>
        </template>
      </div>
      <div class="header-right" v-if="!isCashManagement" style="display: flex; align-items: center; gap: 12px;">
        <n-checkbox :disabled="!hasTradeFuture" :checked="!!showFutCalib" @update:checked="(v: boolean) => emit('update:showFutCalib', v)" size="large">
          <span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: hasTradeFuture ? 1 : 0.5 }">期货校准估值</span>
        </n-checkbox>
        <n-checkbox :disabled="!hasTradeFuture" :checked="!!showPureFut" @update:checked="(v: boolean) => emit('update:showPureFut', v)" size="large">
          <span style="font-size:15px; font-weight:bold; color:#0284c7;" :style="{ opacity: hasTradeFuture ? 1 : 0.5 }">纯期货估值</span>
        </n-checkbox>
      </div>
    </div>

    <!-- 估值计算器插槽：由父组件提供 ref="vcRef" -->
    <slot name="calculator" />

    <!-- 页面主体插槽：盘口、下单区、Monitor、规则引擎等 -->
    <slot />
  </div>
</template>

<script setup lang="ts">
import { NButton, NIcon, NTag, NCheckbox } from 'naive-ui'
import { ArrowLeft } from 'lucide-vue-next'
import { useRouter } from 'vue-router'

const props = defineProps<{
  fundCode: string
  fundName: string
  mode?: 'public' | 'private'
  isCashManagement?: boolean
  positionRatio?: number
  showFutCalib?: boolean
  showPureFut?: boolean
  hasTradeFuture?: boolean
  meta?: any
}>()

const emit = defineEmits<{
  (e: 'update:showFutCalib', v: boolean): void
  (e: 'update:showPureFut', v: boolean): void
}>()

const router = useRouter()
const handleBack = () => router.back()
</script>
