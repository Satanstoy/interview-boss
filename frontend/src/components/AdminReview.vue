<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9998] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
            <div>
              <h2 class="text-lg font-bold text-gray-800">待审核题目</h2>
              <p class="text-sm text-gray-500 mt-0.5">审核用户提交到公共题库的题目</p>
            </div>
            <button @click="$emit('close')" class="p-1 rounded-lg hover:bg-gray-100 transition">
              <svg class="w-5 h-5 text-gray-400" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
              </svg>
            </button>
          </div>

          <!-- Content -->
          <div class="flex-1 overflow-y-auto px-6 py-4">
            <!-- Loading -->
            <div v-if="loading" class="flex items-center justify-center py-12">
              <svg class="animate-spin h-6 w-6 text-blue-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="ml-2 text-gray-500">加载中...</span>
            </div>

            <!-- Empty -->
            <div v-else-if="items.length === 0" class="text-center py-12">
              <svg class="w-12 h-12 text-gray-300 mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
              </svg>
              <p class="text-gray-500">暂无待审核题目</p>
            </div>

            <!-- List -->
            <div v-else class="space-y-3">
              <div
                v-for="item in items"
                :key="item.id"
                class="border border-gray-200 rounded-xl p-4 hover:border-blue-200 transition"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-gray-800 line-clamp-2">{{ item.question }}</p>
                    <div class="flex flex-wrap gap-2 mt-2">
                      <span v-if="item.cat1" class="px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded-md">{{ item.cat1 }}</span>
                      <span v-if="item.difficulty" class="px-2 py-0.5 text-xs bg-purple-50 text-purple-700 rounded-md">{{ item.difficulty }}</span>
                      <span v-if="item.submitted_by_name" class="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-md">{{ item.submitted_by_name }}</span>
                    </div>
                  </div>
                  <div class="flex gap-1.5 shrink-0">
                    <button
                      @click="handleApprove(item.id)"
                      :disabled="processingIds.has(item.id)"
                      class="px-3 py-1.5 text-xs font-medium bg-green-500 hover:bg-green-600 disabled:opacity-50 text-white rounded-lg transition"
                    >通过</button>
                    <button
                      @click="handleReject(item.id)"
                      :disabled="processingIds.has(item.id)"
                      class="px-3 py-1.5 text-xs font-medium bg-red-500 hover:bg-red-600 disabled:opacity-50 text-white rounded-lg transition"
                    >拒绝</button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-3 border-t border-gray-100 flex justify-between items-center">
            <span class="text-sm text-gray-500">共 {{ items.length }} 条待审核</span>
            <button @click="loadPending" class="text-sm text-blue-600 hover:text-blue-800 font-medium">刷新</button>
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
