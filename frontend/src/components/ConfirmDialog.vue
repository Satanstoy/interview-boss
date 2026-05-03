<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="confirmState.show" class="fixed inset-0 z-[10000] flex items-center justify-center" @keydown.esc="handleCancel" @keydown.enter="handleConfirm" tabindex="-1" ref="dialogEl">
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="handleCancel"></div>
        <div class="relative bg-white rounded-2xl shadow-2xl w-[420px] max-w-[90vw] p-6 z-10" role="alertdialog" aria-modal="true">
          <h3 class="text-lg font-bold text-gray-900 mb-2">{{ confirmState.title }}</h3>
          <p class="text-sm text-gray-600 leading-relaxed mb-6">{{ confirmState.message }}</p>
          <div class="flex justify-end gap-3">
            <button
              @click="handleCancel"
              class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-gray-400"
            >取消</button>
            <button
              @click="handleConfirm"
              class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition shadow-sm focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-blue-500"
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
