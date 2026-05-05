<template>
  <div class="space-y-4">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="items.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <div v-if="items.length > 0" class="flex gap-2 mb-2">
      <button @click="$emit('expand-all')" class="btn-ghost text-xs border border-gray-200 rounded-lg">全部展开</button>
      <button @click="$emit('collapse-all')" class="btn-ghost text-xs border border-gray-200 rounded-lg">全部收起</button>
    </div>

    <div v-if="items.length === 0" class="text-center py-16 rounded-2xl border-2 border-dashed border-gray-200 bg-gray-50/50">
      <svg class="w-14 h-14 text-gray-300 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
      </svg>
      <p class="text-gray-500 font-medium mb-1">暂无符合条件的题目</p>
      <p class="text-sm text-gray-400">点击左侧「全部」查看所有题目，或录入更多面经自动扩充。</p>
    </div>

    <div v-for="(q, idx) in items" :key="q.id"
      class="card-smooth overflow-hidden animate-fade-in"
      :class="[
        isSelected(q.id) ? 'border-primary-400 ring-2 ring-primary-100' : '',
      ]"
      :style="{ animationDelay: Math.min(idx * 40, 400) + 'ms' }"
    >
      <!-- Card header -->
      <div class="p-5 flex gap-4 items-start cursor-pointer hover:bg-slate-50/50 transition-colors duration-200" @click="q._showAnswer = !q._showAnswer">
        <div class="flex items-center h-full pt-1" @click.stop>
          <input type="checkbox" :checked="isSelected(q.id)" @change="$emit('toggle-item', q.id)"
            class="w-[18px] h-[18px] text-primary-600 rounded-md border-gray-300 focus:ring-primary-500 cursor-pointer transition">
        </div>
        <div class="flex flex-col items-center justify-center bg-gradient-to-b from-red-50 to-red-100/50 text-red-600 font-bold rounded-xl p-3 min-w-[56px] border border-red-100">
          <span class="text-[10px] font-medium text-red-400 mb-0.5 uppercase tracking-wider">频率</span>
          <span class="text-xl leading-none">{{ q.frequency }}</span>
        </div>

        <div class="flex-1 min-w-0">
          <div class="flex gap-1.5 mb-2.5 items-center flex-wrap">
            <span class="badge bg-primary-50 text-primary-700 border border-primary-100">{{ q.cat1 || '未分类' }}</span>
            <span v-for="tag in (q.tags ? q.tags.split(',') : [])" :key="tag" class="badge bg-gray-100 text-gray-500 border border-gray-200/80">
              {{ tag }}
            </span>
            <span class="badge ml-auto"
              :class="String(q.difficulty).includes('L3') ? 'bg-red-50 text-red-600 border border-red-100' : String(q.difficulty).includes('L2') ? 'bg-amber-50 text-amber-600 border border-amber-100' : 'bg-emerald-50 text-emerald-600 border border-emerald-100'">
              {{ q.difficulty || '-' }}
            </span>
            <button @click.stop="$emit('toggle-star', q)" class="ml-1 transition-all duration-200 hover:scale-125" :title="q.is_starred ? '取消收藏' : '收藏'">
              <svg class="w-5 h-5 transition-colors" :class="q.is_starred ? 'text-amber-400' : 'text-gray-300 hover:text-amber-300'" :fill="q.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
              </svg>
            </button>
            <button @click.stop="$emit('retag', q)" :disabled="q._isRetagging"
              class="text-xs bg-amber-50 text-amber-700 px-2.5 py-1 rounded-lg border border-amber-200 hover:bg-amber-100 transition-all duration-200 disabled:opacity-50 flex items-center gap-1">
              <svg v-if="q._isRetagging" class="animate-spin w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              {{ q._isRetagging ? '分类中...' : '重新分类' }}
            </button>
          </div>
          <h3 class="text-base font-bold text-gray-800 leading-snug">{{ q.question }}</h3>
        </div>

        <div class="text-gray-300 mt-1 flex-shrink-0">
          <svg class="w-5 h-5 transform transition-transform duration-200" :class="q._showAnswer ? 'rotate-180 text-primary-400' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
        </div>
      </div>

      <!-- Expandable answer section -->
      <Transition name="expand">
        <div v-if="q._showAnswer" class="border-t border-gray-100 bg-gradient-to-b from-gray-50/80 to-white p-6 relative group">
          <!-- Source tracing -->
          <div v-if="q.sources && q.sources.length > 0" class="mb-5 bg-primary-50/40 border border-primary-100 rounded-xl p-4">
            <h4 class="text-sm font-bold text-primary-800 mb-2.5 flex items-center gap-1.5">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
              出处追溯 ({{ q.sources.length }} 次出现)
            </h4>
            <div class="flex flex-wrap gap-2 text-xs">
              <span v-for="(src, idx) in q.sources" :key="idx" class="bg-white border border-primary-200 text-primary-700 px-2.5 py-1.5 rounded-lg inline-flex items-center shadow-sm">
                {{ src.company === '未提供' ? '未知' : src.company }}
                <span class="text-primary-300 mx-1.5">|</span>
                {{ src.round === '未提供' ? '未知轮次' : src.round }}
                <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" class="ml-2 text-primary-500 hover:text-primary-700 font-bold transition-colors" title="查看原文">
                  [原文]
                </a>
              </span>
            </div>
          </div>

          <!-- Edit answer mode -->
          <div v-if="q._isEditingAnswer" class="flex flex-col gap-3">
            <label class="font-bold text-gray-700 text-sm">编辑答案</label>
            <textarea v-model="q._editAnswer" rows="8" class="w-full max-w-3xl border border-primary-200 rounded-xl p-4 text-sm focus:ring-2 focus:ring-primary-200 focus:border-primary-400 font-mono bg-white transition-all duration-200"></textarea>
            <div class="flex gap-2 justify-end mt-2">
              <button @click="q._isEditingAnswer = false" class="btn-secondary px-5">取消</button>
              <button @click="$emit('save-field', { tableName: 'question_bank', recordId: q.id, dbColumn: 'ai_answer', newValue: q._editAnswer, rowObj: q, editStateKey: '_isEditingAnswer', frontendKey: 'ai_answer' })" class="btn-primary px-5">保存</button>
            </div>
          </div>

          <!-- View answer mode -->
          <div v-else>
            <div v-if="q.ai_answer && !isFailedAnswer(q.ai_answer)" class="relative">
              <div class="absolute top-0 right-0 flex gap-1.5 z-10">
                <button @click="q._isEditingAnswer = true; q._editAnswer = q.ai_answer" class="bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 px-3 py-1.5 rounded-lg text-xs transition-all duration-200 opacity-0 group-hover:opacity-100 hover:opacity-100 shadow-sm">
                  编辑
                </button>
                <button @click.stop="$emit('generate-answer', q)" :disabled="q._isLoadingAnswer" class="bg-white border border-gray-200 hover:bg-gray-50 text-gray-600 px-3 py-1.5 rounded-lg text-xs transition-all duration-200 opacity-0 group-hover:opacity-100 hover:opacity-100 shadow-sm disabled:opacity-30 disabled:cursor-not-allowed">
                  重新生成
                </button>
              </div>
              <div class="text-gray-700 text-sm leading-relaxed max-w-none answer-content pt-6" v-html="renderMarkdown(q.ai_answer)"></div>
            </div>

            <div v-else-if="q._isLoadingAnswer" class="flex flex-col items-center justify-center py-8 text-primary-600 gap-3">
              <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="font-medium text-sm">AI 正在生成答案，请稍候...</span>
            </div>

            <div v-else class="text-center py-6">
              <p v-if="isFailedAnswer(q.ai_answer)" class="text-red-500 mb-3 text-sm flex items-center justify-center gap-1.5">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                上次生成失败，请重试。
              </p>
              <p v-else class="text-gray-400 mb-4 text-sm">该题目暂无答案</p>
              <div class="flex gap-2 justify-center flex-wrap">
                <button @click.stop="$emit('generate-answer', q)" class="btn-primary px-6 py-2.5">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                  AI 生成答案
                </button>
                <button @click="q._isEditingAnswer = true; q._editAnswer = ''" class="btn-secondary px-6 py-2.5">
                  手动编写
                </button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { marked } from 'marked'
import BatchActionPanel from './BatchActionPanel.vue'

defineProps({
  items: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] }
})

defineEmits(['toggle-select-all', 'invert-selection', 'toggle-star', 'retag', 'generate-answer', 'save-field', 'toggle-item', 'expand-all', 'collapse-all'])

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')
const renderMarkdown = (text) => text ? marked.parse(text) : ''
</script>

<style scoped>
.expand-enter-active { transition: all 0.3s ease-out; }
.expand-leave-active { transition: all 0.2s ease-in; }
.expand-enter-from { opacity: 0; max-height: 0; }
.expand-leave-to { opacity: 0; max-height: 0; }
</style>
