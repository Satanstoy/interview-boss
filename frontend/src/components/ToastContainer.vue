<template>
  <Teleport to="body">
    <div class="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts" :key="toast.id"
          class="pointer-events-auto w-80 rounded-lg shadow-lg border px-4 py-3 flex items-start gap-3"
          :class="typeClasses[toast.type]"
        >
          <span class="text-lg leading-none mt-0.5">{{ typeIcons[toast.type] }}</span>
          <p class="flex-1 text-sm leading-relaxed">{{ toast.message }}</p>
          <button @click="removeToast(toast.id)" class="text-current opacity-40 hover:opacity-70 transition leading-none mt-0.5">&times;</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../composables/useNotification.js'

const { toasts, removeToast } = useToast()

const typeClasses = {
  success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  error: 'bg-red-50 border-red-200 text-red-800',
  warning: 'bg-amber-50 border-amber-200 text-amber-800',
  info: 'bg-blue-50 border-blue-200 text-blue-800',
}

const typeIcons = {
  success: '✓',
  error: '✕',
  warning: '⚠',
  info: 'ℹ',
}
</script>

<style scoped>
.toast-enter-active { transition: all 0.3s ease-out; }
.toast-leave-active { transition: all 0.25s ease-in; }
.toast-enter-from { opacity: 0; transform: translateX(100%); }
.toast-leave-to { opacity: 0; transform: translateX(100%); }
.toast-move { transition: transform 0.3s ease; }
</style>
