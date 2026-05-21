<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="confirmState.show" class="fixed inset-0 z-[10000] flex items-center justify-center" @keydown.esc="handleCancel" @keydown.enter="handleConfirm" tabindex="-1" ref="dialogEl">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="handleCancel"></div>
        <div class="relative bg-white dark:bg-surface-800 rounded-2xl shadow-2xl w-[420px] max-w-[90vw] p-6 z-10 animate-slide-up" role="alertdialog" aria-modal="true">
          <div class="flex items-start gap-4 mb-5">
            <div class="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center" :class="iconBgClass">
              <!-- Danger icon -->
              <svg v-if="variant === 'danger'" class="w-5 h-5" :class="iconTextClass" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <!-- Info icon -->
              <svg v-else-if="variant === 'info'" class="w-5 h-5" :class="iconTextClass" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <!-- Warning icon (default) -->
              <svg v-else class="w-5 h-5" :class="iconTextClass" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
              </svg>
            </div>
            <div>
              <h3 class="text-lg font-bold text-gray-900 dark:text-ink-100">{{ confirmState.title }}</h3>
              <p class="text-sm text-ink-500 dark:text-ink-400 leading-relaxed mt-1 whitespace-pre-line">{{ confirmState.message }}</p>
            </div>
          </div>
          <div class="flex justify-end gap-3">
            <button
              @click="handleCancel"
              class="btn-secondary px-5"
            >{{ confirmState.cancelLabel || '取消' }}</button>
            <button
              @click="handleConfirm"
              class="px-5 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98] text-white"
              :class="confirmBtnClass"
            >{{ confirmState.confirmLabel || '确定' }}</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick, computed } from 'vue'
import { useConfirm } from '@/composables/useNotification.js'

const { confirmState, handleConfirm, handleCancel } = useConfirm()
const dialogEl = ref(null)

const variant = computed(() => confirmState.value.variant || 'warning')

const iconBgClass = computed(() => ({
  danger: 'bg-red-100 dark:bg-red-900/30',
  warning: 'bg-amber-100 dark:bg-amber-900/30',
  info: 'bg-blue-100 dark:bg-blue-900/30',
}[variant.value]))

const iconTextClass = computed(() => ({
  danger: 'text-red-600 dark:text-red-400',
  warning: 'text-amber-600 dark:text-amber-400',
  info: 'text-blue-600 dark:text-blue-400',
}[variant.value]))

const confirmBtnClass = computed(() => ({
  danger: 'bg-red-600 hover:bg-red-700 shadow-sm',
  warning: 'bg-gradient-brand shadow-glow',
  info: 'bg-blue-600 hover:bg-blue-700 shadow-sm',
}[variant.value]))

watch(() => confirmState.value.show, (show) => {
  if (show) nextTick(() => dialogEl.value?.focus())
})
</script>

<style scoped>
.fade-enter-active { transition: opacity 0.2s ease; }
.fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
