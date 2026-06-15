<template>
  <div class="milestone-scroll-box">
    <div class="milestone-grid">
      <div v-for="(m, i) in items" :key="i" class="milestone-cell">
        <span class="m-time">{{ m.time }}</span>
        <span :class="['m-msg', (m.level || 'info').toLowerCase()]">{{ m.message }}</span>
      </div>
    </div>
    <div v-if="items.length === 0" class="empty-state">
      等待系统汇报...
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  items: Array<{ time: string; level: string; message: string }>
}>()
</script>

<style scoped>
.milestone-scroll-box {
  max-height: 100%;
  overflow-y: auto;
  padding: 0 8px;
}
.milestone-grid {
  display: flex;
  flex-direction: column;
}
.milestone-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 1px 0;
  font-size: 10px;
  line-height: 1.3;
  white-space: nowrap;
}
.m-time {
  color: #94a3b8;
  font-family: 'Courier New', monospace;
  min-width: 60px;
}
.m-msg.success { color: #16a34a; }
.m-msg.error { color: #dc2626; }
.m-msg.warning { color: #d97706; }
.m-msg.info { color: #2563eb; }
.empty-state {
  text-align: center;
  color: #94a3b8;
  font-size: 10px;
  padding: 8px 0;
}
</style>
