<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[9998] flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
        <div class="rounded-xl border border-border bg-card shadow-lg w-full max-w-2xl mx-4 max-h-[80vh] flex flex-col animate-slide-up overflow-hidden">
          <!-- Header -->
          <div class="px-6 py-4 border-b border-border flex items-center justify-between bg-muted/40">
            <div class="flex items-center gap-3">
              <div class="size-9 rounded-xl bg-gradient-to-br from-orange-500 to-amber-500 flex items-center justify-center">
                <svg class="size-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <div>
                <h2 class="text-lg font-bold text-foreground">待审核题目</h2>
                <p class="text-xs text-muted-foreground mt-0.5">审核用户提交到公共题库的题目</p>
              </div>
            </div>
            <button @click="$emit('close')" class="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition">
              <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Content -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4">
            <!-- Loading -->
            <div v-if="loading" class="flex flex-col items-center justify-center py-16 gap-3">
              <svg class="animate-spin h-6 w-6 text-primary-500" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="text-muted-foreground text-sm">加载中...</span>
            </div>

            <!-- Empty -->
            <div v-else-if="items.length === 0" class="text-center py-16">
              <div class="size-16 mx-auto mb-4 rounded-xl bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                <svg class="size-8 text-emerald-500 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
              </div>
              <p class="text-foreground font-medium">暂无待审核题目</p>
              <p class="text-sm text-muted-foreground mt-1">所有题目均已审核完毕</p>
            </div>

            <!-- List -->
            <div v-else v-auto-animate class="flex flex-col gap-3">
              <div
                v-for="item in items"
                :key="item.id"
                class="border border-border rounded-xl p-4 hover:border-primary/30 hover:shadow-sm transition-all duration-200 animate-fade-in"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-foreground leading-relaxed">{{ item.question }}</p>
                    <div class="flex flex-wrap gap-1.5 mt-2.5">
                      <Badge v-if="item.cat1" variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-100 dark:border-primary-800/50">{{ item.cat1 }}</Badge>
                      <Badge v-if="item.difficulty" variant="outline" class="bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400 border-accent-100 dark:border-accent-800/50">{{ item.difficulty }}</Badge>
                      <Badge v-if="item.submitted_by_name" variant="outline" class="bg-muted text-muted-foreground">{{ item.submitted_by_name }}</Badge>
                    </div>
                  </div>
                  <div class="flex gap-2 shrink-0">
                    <Button
                      @click="handleApprove(item.id)"
                      :disabled="processingIds.has(item.id)"
                      size="sm"
                      class="bg-emerald-500 text-white hover:bg-emerald-600"
                    >通过</Button>
                    <Button
                      @click="handleReject(item.id)"
                      :disabled="processingIds.has(item.id)"
                      variant="destructive"
                      size="sm"
                    >拒绝</Button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="px-6 py-3.5 border-t border-border flex justify-between items-center bg-muted/40">
            <span class="text-sm text-muted-foreground">共 <span class="font-bold text-foreground">{{ items.length }}</span> 条待审核</span>
            <Button @click="loadPending" variant="ghost" size="sm" class="text-primary-600 dark:text-primary-400">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              刷新
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { fetchPendingQuestions, approveQuestion, rejectQuestion } from '@/api/index.js'
import { useToast } from '@/composables/useNotification.js'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

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
