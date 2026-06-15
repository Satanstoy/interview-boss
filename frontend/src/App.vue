<!-- frontend/src/App.vue — thin router shell -->
<script setup>
import { onMounted } from 'vue'
import { Toaster } from 'vue-sonner'

// 白屏检测标记
onMounted(() => {
  window.__VUE_APP_READY__ = true
})
</script>

<template>
  <router-view />
  <Toaster position="top-right" richColors closeButton />
</template>
