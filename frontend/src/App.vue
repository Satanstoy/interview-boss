<!-- frontend/src/App.vue — thin router shell with auth initialization -->
<script setup>
import { onMounted } from 'vue'
import { Toaster } from 'vue-sonner'
import { useAuth } from '@/composables/useAuth.js'
import { markAuthReady } from '@/router/index.js'

const { initAuth } = useAuth()

onMounted(async () => {
  // 初始化认证（检查 refresh token cookie 自动登录）
  // 成功后设置 currentUser + authCompleted，路由守卫放行
  await initAuth()
  markAuthReady()
  // 通知白屏检测器
  window.__VUE_APP_READY__ = true
})
</script>

<template>
  <router-view />
  <Toaster position="top-right" richColors closeButton />
</template>
