<template>
  <Teleport to="body">
    <div class="fixed top-4 right-4 z-[9999] flex flex-col gap-2.5 pointer-events-none max-w-sm">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts" :key="toast.id"
          class="pointer-events-auto w-80 rounded-xl shadow-lg border px-4 py-3.5 flex items-start gap-3 backdrop-blur-sm animate-slide-up"
          :class="typeClasses[toast.type]"
        >
          <div class="flex-shrink-0 mt-0.5" v-html="typeIcons[toast.type]"></div>
          <p class="flex-1 text-sm leading-relaxed font-medium">{{ toast.message }}</p>
          <button @click="removeToast(toast.id)" class="flex-shrink-0 text-current opacity-30 hover:opacity-60 transition leading-none mt-0.5">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../composables/useNotification.js'

const { toasts, removeToast } = useToast()

const typeClasses = {
  success: 'bg-emerald-50/90 border-emerald-200 text-emerald-800',
  error: 'bg-red-50/90 border-red-200 text-red-800',
  warning: 'bg-amber-50/90 border-amber-200 text-amber-800',
  info: 'bg-blue-50/90 border-blue-200 text-blue-800',
}

const typeIcons = {
  success: '<svg class="w-5 h-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  error: '<svg class="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
  warning: '<svg class="w-5 h-5 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
  info: '<svg class="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
}
</script>

<style scoped>
.toast-enter-active { transition: all 0.35s cubic-bezier(0.21, 1.02, 0.73, 1); }
.toast-leave-active { transition: all 0.25s cubic-bezier(0.55, 0, 1, 0.45); }
.toast-enter-from { opacity: 0; transform: translateX(80px) scale(0.95); }
.toast-leave-to { opacity: 0; transform: translateX(80px) scale(0.95); }
.toast-move { transition: transform 0.3s ease; }
</style>
