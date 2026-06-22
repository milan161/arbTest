<template>
  <div style="display: flex; justify-content: center; align-items: center; height: 100%; flex-direction: column; background-color: #1e1e1e; border-radius: 8px;">
    <n-icon size="80" color="#f5a623"><LockIcon /></n-icon>
    <h2 style="color: #fff; margin-top: 20px; font-size: 24px; letter-spacing: 2px;">这是东哥的自留地 ——<br/><span style="font-size: 18px; color: #f5a623; margin-top: 10px; display: block;">微观做市</span></h2>
    <p style="color: #888; margin-top: 10px;">核心做市策略未对外开源，敬请谅解！</p>
  </div>
</template>

<script setup>
import { Lock as LockIcon } from 'lucide-vue-next'
import { NIcon } from 'naive-ui'
</script>
