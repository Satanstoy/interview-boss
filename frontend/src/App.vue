<!-- frontend/src/App.vue — thin router shell with auth initialization -->
<script setup>
import { onMounted } from 'vue'
import { Toaster } from 'vue-sonner'
import { useAuth } from '@/composables/useAuth.js'
import { markAuthReady } from '@/router/index.js'

const { initAuth } = useAuth()

onMounted(async () => {
  // 初始化认证（检查 refresh token cookie 自动登录）
  // 必须在 App 层执行，因为路由守卫依赖 currentUser 状态
  await initAuth()
  markAuthReady()
  // 通知白屏检测器：Vue 应用已完成初始化
  window.__VUE_APP_READY__ = true
})
</script>

<template>
  <router-view />
  <Toaster position="top-right" richColors closeButton />
</template>
