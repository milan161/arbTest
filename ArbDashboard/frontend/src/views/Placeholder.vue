<template>
  <div class="placeholder flex-center" style="height: 100%;">
    <n-empty size="huge" style="margin-top: 100px">
      <template #icon>
        <n-icon color="#3b82f6"><Lock /></n-icon>
      </template>
      <div style="font-size: 16px; font-weight: bold; margin-top: 10px; color: #1e293b;">
        系统防护墙 (System Guard)
      </div>
      <div style="font-size: 13px; color: #64748b; margin-top: 8px; max-width: 400px; line-height: 1.6;">
        此模块涉及真实资金路由、量化套利模型与核心参数配置。<br/>
        为保护策略隐私，当前公网演示环境已对该页面进行物理隔离。仅限本地专业私有化部署版本可用。
      </div>
    </n-empty>
  </div>
</template>

<script setup lang="ts">
import { NEmpty, NIcon } from 'naive-ui'
import { Lock } from 'lucide-vue-next'
</script>

<style scoped>
.flex-center {
  display: flex;
  justify-content: center;
  align-items: flex-start;
}
</style>
