<template>
  <div class="relative min-h-[calc(100vh-56px)] overflow-hidden">
    <div class="absolute inset-0 overflow-hidden pointer-events-none">
      <div class="absolute -top-40 -right-40 w-[500px] h-[500px] bg-primary-200/20 dark:bg-primary-900/15 rounded-full blur-[100px] animate-pulse-slow"></div>
      <div class="absolute -bottom-40 -left-40 w-[500px] h-[500px] bg-accent-200/20 dark:bg-accent-900/15 rounded-full blur-[100px] animate-pulse-slow" style="animation-delay: 1.5s"></div>
      <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] bg-primary-100/10 rounded-full blur-[80px] animate-float"></div>
    </div>

    <div class="relative flex flex-col lg:flex-row min-h-[calc(100vh-56px)]">
      <!-- Left: brand showcase -->
      <div class="flex-1 flex flex-col justify-center px-8 lg:px-16 py-12 lg:py-0">
        <div
          v-motion
          :initial="{ opacity: 0, y: 24 }"
          :enter="{ opacity: 1, y: 0, transition: { duration: 500, easing: [0.25, 0.46, 0.45, 0.94] } }"
          class="max-w-md mx-auto lg:mx-0"
        >
          <div class="w-20 h-20 mb-8 rounded-2xl bg-gradient-brand flex items-center justify-center shadow-warm transform hover:scale-105 transition-transform duration-300">
            <svg class="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
            </svg>
          </div>

          <h2 class="font-serif text-3xl lg:text-[2.5rem] text-ink-900 dark:text-ink-100 mb-3 leading-tight">
            欢迎使用 InterviewBoss
          </h2>
          <p class="text-ink-400 dark:text-ink-400 mb-10 leading-relaxed text-lg font-light">
            AI 驱动的面试准备平台
          </p>

          <div class="grid grid-cols-3 gap-4">
            <div v-for="(feature, idx) in loginFeatures" :key="feature.label"
              v-motion
              :initial="{ opacity: 0, y: 20, scale: 0.95 }"
              :enter="{
                opacity: 1, y: 0, scale: 1,
                transition: { duration: 400, delay: 200 + idx * 100, easing: [0.25, 0.46, 0.45, 0.94] }
              }"
              class="flex flex-col items-center gap-2.5 p-4 rounded-2xl bg-white/70 dark:bg-surface-800/70 backdrop-blur-sm border border-surface-200/80 dark:border-ink-700/50 shadow-card hover:shadow-card-hover transition-all duration-300 hover:-translate-y-0.5 cursor-default">
              <div class="w-10 h-10 rounded-xl flex items-center justify-center" :class="feature.iconBg">
                <span class="text-lg">{{ feature.icon }}</span>
              </div>
              <span class="text-xs font-semibold text-ink-600 dark:text-ink-400">{{ feature.label }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: login form -->
      <div class="flex items-center justify-center px-8 lg:px-16 py-12 lg:py-0 lg:w-[440px] xl:w-[480px]">
        <div
          v-motion
          :initial="{ opacity: 0, x: 24 }"
          :enter="{ opacity: 1, x: 0, transition: { duration: 500, delay: 150, easing: [0.25, 0.46, 0.45, 0.94] } }"
          class="w-full max-w-sm"
        >
          <LoginModal embedded @login-success="$emit('login-success', $event)" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import LoginModal from '@/components/business/LoginModal.vue'

defineProps({
  loginFeatures: {
    type: Array,
    default: () => [
      { icon: '📚', label: '智能题库', iconBg: 'bg-primary-100 dark:bg-primary-900/30' },
      { icon: '🤖', label: 'AI 刷题', iconBg: 'bg-sage-100 dark:bg-sage-700/30' },
      { icon: '🎯', label: '模拟面试', iconBg: 'bg-accent-100 dark:bg-accent-700/30' },
    ]
  }
})

defineEmits(['login-success'])
</script>
