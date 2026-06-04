<template>
  <n-config-provider>
    <n-global-style />
    <n-loading-bar-provider>
      <n-message-provider>
        <n-notification-provider>
          <n-dialog-provider>
            <router-view />
          </n-dialog-provider>
        </n-notification-provider>
      </n-message-provider>
    </n-loading-bar-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { 
  NConfigProvider, 
  NGlobalStyle, 
  NMessageProvider, 
  NNotificationProvider, 
  NDialogProvider,
  NLoadingBarProvider
} from 'naive-ui'
// Using default light theme
</script>

<style>
body {
  margin: 0;
  padding: 0;
  font-family: v-sans, v-mono, other-fallbacks, sans-serif;
  background-color: #f0f2f5;
}
</style>
