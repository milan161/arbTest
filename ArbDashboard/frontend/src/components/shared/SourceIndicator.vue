<template>
  <n-tag
    :type="isConnected ? 'success' : 'error'"
    size="small"
    round
    :bordered="false"
    style="font-weight: bold; cursor: pointer;"
    @click="$emit('click')"
  >
    <template #icon>
      <n-icon><Zap /></n-icon>
    </template>
    {{ label }}
  </n-tag>
</template>

<script setup lang="ts">
import { NTag, NIcon } from 'naive-ui'
import { Zap } from 'lucide-vue-next'

defineProps<{
  label: string
  isConnected: boolean
}>()

defineEmits<{
  click: []
}>()
</script>
