<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="confirmState.show" class="fixed inset-0 z-[10000] flex items-center justify-center" @keydown.esc="handleCancel" @keydown.enter="handleConfirm" tabindex="-1" ref="dialogEl">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="handleCancel"></div>
        <div class="relative bg-white rounded-2xl shadow-2xl w-[420px] max-w-[90vw] p-6 z-10 animate-slide-up" role="alertdialog" aria-modal="true">
          <div class="flex items-start gap-4 mb-5">
            <div class="flex-shrink-0 w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center">
              <svg class="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/>
              </svg>
            </div>
            <div>
              <h3 class="text-lg font-bold text-gray-900">{{ confirmState.title }}</h3>
              <p class="text-sm text-gray-500 leading-relaxed mt-1">{{ confirmState.message }}</p>
            </div>
          </div>
          <div class="flex justify-end gap-3">
            <button
              @click="handleCancel"
              class="btn-secondary px-5"
            >取消</button>
            <button
              @click="handleConfirm"
              class="btn-primary px-5"
            >确定</button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { useConfirm } from '../composables/useNotification.js'

const { confirmState, handleConfirm, handleCancel } = useConfirm()
const dialogEl = ref(null)

watch(() => confirmState.value.show, (show) => {
  if (show) nextTick(() => dialogEl.value?.focus())
})
</script>

<style scoped>
.fade-enter-active { transition: opacity 0.2s ease; }
.fade-leave-active { transition: opacity 0.15s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
