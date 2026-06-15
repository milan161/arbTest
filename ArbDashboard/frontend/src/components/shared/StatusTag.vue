<template>
  <n-tag
    :type="tagType"
    size="small"
    round
    :bordered="false"
    class="status-tag"
  >
    {{ status || '未知' }}
  </n-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { statusTagType } from '../../utils'
import { NTag } from 'naive-ui'

const props = withDefaults(defineProps<{
  status?: string
}>(), {
  status: '未知'
})

const tagType = computed(() => statusTagType(props.status))
</script>

<style scoped>
.status-tag {
  font-weight: 600;
}
</style>
