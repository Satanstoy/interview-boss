<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9998] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="bg-white rounded-3xl shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col animate-slide-up overflow-hidden">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gradient-to-r from-orange-50/50 to-amber-50/30">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
                <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <div>
                <h2 class="text-lg font-bold text-gray-800">待审核题目</h2>
                <p class="text-xs text-gray-400 mt-0.5">审核用户提交到公共题库的题目</p>
              </div>
            </div>
            <button @click="$emit('close')" class="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Content -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4">
            <!-- Loading -->
            <div v-if="loading" class="flex flex-col items-center justify-center py-16 gap-3">
              <svg class="animate-spin h-6 w-6 text-primary-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="text-gray-400 text-sm">加载中...</span>
            </div>

            <!-- Empty -->
            <div v-else-if="items.length === 0" class="text-center py-16">
              <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-emerald-100 flex items-center justify-center">
                <svg class="w-8 h-8 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <p class="text-gray-500 font-medium">暂无待审核题目</p>
              <p class="text-sm text-gray-400 mt-1">所有题目均已审核完毕</p>
            </div>

            <!-- List -->
            <div v-else class="space-y-3">
              <div
                v-for="item in items"
                :key="item.id"
                class="border border-gray-100 rounded-xl p-4 hover:border-primary-200 hover:shadow-sm transition-all duration-200 animate-fade-in"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-gray-800 leading-relaxed">{{ item.question }}</p>
                    <div class="flex flex-wrap gap-1.5 mt-2.5">
                      <span v-if="item.cat1" class="badge bg-primary-50 text-primary-700 border border-primary-100">{{ item.cat1 }}</span>
                      <span v-if="item.difficulty" class="badge bg-accent-50 text-accent-700 border border-accent-100">{{ item.difficulty }}</span>
                      <span v-if="item.submitted_by_name" class="badge bg-gray-100 text-gray-600">{{ item.submitted_by_name }}</span>
                    </div>
                  </div>
                  <div class="flex gap-2 shrink-0">
                    <button
                      @click="handleApprove(item.id)"
                      :disabled="processingIds.has(item.id)"
                      class="px-3.5 py-1.5 text-xs font-semibold bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
                    >通过</button>
                    <button
                      @click="handleReject(item.id)"
                      :disabled="processingIds.has(item.id)"
                      class="px-3.5 py-1.5 text-xs font-semibold bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white rounded-xl transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
                    >拒绝</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-3.5 border-t border-gray-100 flex justify-between items-center bg-gray-50/80">
            <span class="text-sm text-gray-500">共 <span class="font-bold text-gray-700">{{ items.length }}</span> 条待审核</span>
            <button @click="loadPending" class="btn-ghost text-primary-600">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              刷新
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { fetchPendingQuestions, approveQuestion, rejectQuestion } from '../api/index.js'
import { useToast } from '../composables/useNotification.js'

const props = defineProps({ visible: Boolean })
const emit = defineEmits(['close', 'reviewed'])
const { success, error: showError } = useToast()

const loading = ref(false)
const items = ref([])
const processingIds = ref(new Set())

watch(() => props.visible, (v) => { if (v) loadPending() })

async function loadPending() {
  loading.value = true
  try {
    const data = await fetchPendingQuestions()
    items.value = data.items || []
  } catch (e) {
    showError('加载待审核题目失败: ' + (e.message || '未知错误'))
  } finally {
    loading.value = false
  }
}

async function handleApprove(id) {
  processingIds.value.add(id)
  try {
    await approveQuestion(id)
    items.value = items.value.filter(i => i.id !== id)
    success('已通过审核')
    emit('reviewed')
  } catch (e) {
    showError('审核失败: ' + (e.message || '未知错误'))
  } finally {
    processingIds.value.delete(id)
  }
}

async function handleReject(id) {
  processingIds.value.add(id)
  try {
    await rejectQuestion(id)
    items.value = items.value.filter(i => i.id !== id)
    success('已拒绝')
    emit('reviewed')
  } catch (e) {
    showError('操作失败: ' + (e.message || '未知错误'))
  } finally {
    processingIds.value.delete(id)
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
