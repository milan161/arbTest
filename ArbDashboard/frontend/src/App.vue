<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-global-style />
    <n-loading-bar-provider>
      <n-message-provider>
        <n-notification-provider>
          <n-dialog-provider>
            <router-view v-slot="{ Component }">
              <keep-alive>
                <component :is="Component" />
              </keep-alive>
            </router-view>
          </n-dialog-provider>
        </n-notification-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { ref, computed, provide, watchEffect } from 'vue'
import {
  NConfigProvider,
  NGlobalStyle,
  NMessageProvider,
  NNotificationProvider,
  NDialogProvider,
  NLoadingBarProvider
} from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'

// 获取持久化的主题色，默认蓝色
const savedColor = localStorage.getItem('theme_color') || '#3B82F6'
const primaryColor = ref(savedColor)

// 计算浅色背景（用于选中态）
const getLightColor = (hex: string) => {
    return hex + '15'; // 约 8% 透明度的浅色
}

const themeOverrides = computed<GlobalThemeOverrides>(() => ({
  common: {
    primaryColor: primaryColor.value,
    primaryColorHover: '#4f8ef7',
    primaryColorPressed: '#1d4ed8',
    primaryColorSuppl: primaryColor.value,
    bodyColor: '#f4f7fb',
    cardColor: '#ffffff',
    tableColor: '#ffffff',
    textColorBase: '#1f2937',
    borderColor: '#e5edf7'
  },
  DataTable: {
    thFontWeight: '700',
    thColor: '#eef5ff',
    thColorHover: '#e8f1ff',
    tdColor: '#ffffff',
    tdColorHover: '#f8fbff',
    tdColorStriped: '#fbfdff',
    tdColorHoverStriped: '#f8fbff',
    borderColor: '#e5edf7',
    thTextColor: '#21395c',
    tdTextColor: '#1f2937'
  },
  Card: {
    borderRadius: '8px'
  }
}))

// 动态更新 CSS 变量，确保自定义主题生效
watchEffect(() => {
    document.documentElement.style.setProperty('--primary-color', primaryColor.value);
    document.documentElement.style.setProperty('--primary-light', getLightColor(primaryColor.value));
})

provide('themeColor', primaryColor)
</script>

<style>
:root {
  /* 初始变量 */
  --primary-color: #2563eb;
  --primary-light: #eff6ff;
  --bg-color: #f4f7fb;
  --text-main: #1f2937;
  --text-muted: #64748b;
}

body {
  margin: 0;
  padding: 0;
  font-family: Inter, "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", v-sans, Arial, sans-serif;
  background-color: var(--bg-color);
  color: var(--text-main);
  font-size: 13px;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

html {
  background-color: var(--bg-color);
  color-scheme: light;
}

#app {
  background-color: var(--bg-color);
}

/* 修正后的全站标准按钮样式 */
.btn-standard {
  padding: 6px 16px;
  background-color: var(--primary-light) !important;
  color: var(--primary-color) !important;
  border: 1px solid var(--primary-color) !important;
  border-radius: 6px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
}

/* 修复：悬浮时文字必须变白，背景变深，防止看不清 */
.btn-standard:hover {
  background-color: var(--primary-color) !important;
  color: #ffffff !important; 
}

.btn-standard:active {
  filter: brightness(0.9);
}

.btn-standard:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* ========================================================
   全局覆盖 Naive UI n-button 样式以匹配 .btn-standard 风格
   ======================================================== */
.n-button:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  transition: all 0.2s !important;
  border-radius: 6px !important;
  font-weight: 600 !important;
}

/* 默认与 primary 按钮 */
.n-button.n-button--default-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text),
.n-button.n-button--primary-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  background-color: var(--primary-light) !important;
  color: var(--primary-color) !important;
  border: 1px solid var(--primary-color) !important;
}

.n-button.n-button--default-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover,
.n-button.n-button--primary-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover {
  background-color: var(--primary-color) !important;
  color: #ffffff !important;
}

.n-button.n-button--default-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover *,
.n-button.n-button--primary-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover * {
  color: #ffffff !important;
  fill: #ffffff !important;
}

/* success 状态按钮 */
.n-button.n-button--success-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  background-color: #f0fdf4 !important;
  color: #16a34a !important;
  border: 1px solid #16a34a !important;
}
.n-button.n-button--success-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover {
  background-color: #16a34a !important;
  color: #ffffff !important;
}
.n-button.n-button--success-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover * {
  color: #ffffff !important;
}

/* warning 状态按钮 */
.n-button.n-button--warning-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  background-color: #fffbeb !important;
  color: #d97706 !important;
  border: 1px solid #d97706 !important;
}
.n-button.n-button--warning-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover {
  background-color: #d97706 !important;
  color: #ffffff !important;
}
.n-button.n-button--warning-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover * {
  color: #ffffff !important;
}

/* error 状态按钮 */
.n-button.n-button--error-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  background-color: #fef2f2 !important;
  color: #dc2626 !important;
  border: 1px solid #dc2626 !important;
}
.n-button.n-button--error-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover {
  background-color: #dc2626 !important;
  color: #ffffff !important;
}
.n-button.n-button--error-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover * {
  color: #ffffff !important;
}

/* info 状态按钮 */
.n-button.n-button--info-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text) {
  background-color: #f0f9ff !important;
  color: #0284c7 !important;
  border: 1px solid #0284c7 !important;
}
.n-button.n-button--info-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover {
  background-color: #0284c7 !important;
  color: #ffffff !important;
}
.n-button.n-button--info-type:not(.n-button--quaternary):not(.n-button--circle):not(.n-button--dashed):not(.n-button--text):hover * {
  color: #ffffff !important;
}
</style>
