<template>
  <div style="display: flex; justify-content: center; align-items: center; height: 100%; flex-direction: column; background: #f8fafc; border-radius: 8px;">
    <n-icon size="80" color="#94a3b8"><Construction /></n-icon>
    <h2 style="color: #475569; margin-top: 20px; font-size: 22px; letter-spacing: 1px;">功能开发中</h2>
    <p style="color: #94a3b8; margin-top: 10px;">该分类基金的交易模式与黄金原油不同，实盘功能正在开发</p>
    <n-button type="primary" ghost style="margin-top: 24px;" @click="$router.back()">返回</n-button>
  </div>
</template>

<script setup>
import { Construction } from 'lucide-vue-next'
import { NIcon, NButton } from 'naive-ui'
</script>
