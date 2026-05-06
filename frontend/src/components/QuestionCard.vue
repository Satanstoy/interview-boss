<template>
  <div
    class="card-smooth overflow-hidden"
    :class="[
      isSelected(question.id) ? 'border-primary-400 dark:border-primary-500 ring-2 ring-primary-100 dark:ring-primary-900/50' : '',
    ]"
  >
    <!-- Card header -->
    <div class="p-5 flex gap-4 items-start cursor-pointer hover:bg-slate-50/50 dark:hover:bg-surface-700/50 transition-colors duration-200" @click="$emit('toggle-answer', question)">
      <div class="flex items-center h-full pt-1" @click.stop>
        <input type="checkbox" :checked="isSelected(question.id)" @change="$emit('toggle-item', question.id)"
          class="w-[18px] h-[18px] text-primary-600 rounded-md border-gray-300 dark:border-gray-600 focus:ring-primary-500 cursor-pointer transition bg-white dark:bg-surface-900">
      </div>
      <div class="flex flex-col items-center justify-center bg-gradient-to-b from-red-50 to-red-100/50 dark:from-red-900/30 dark:to-red-900/10 text-red-600 dark:text-red-400 font-bold rounded-xl p-3 min-w-[56px] border border-red-100 dark:border-red-800/50">
        <span class="text-[10px] font-medium text-red-400 dark:text-red-500 mb-0.5 uppercase tracking-wider">频率</span>
        <span class="text-xl leading-none">{{ question.frequency }}</span>
      </div>

      <div class="flex-1 min-w-0">
        <div class="flex gap-1.5 mb-2.5 items-center flex-wrap">
          <!-- 所属个人/公共标识（mixed 模式下显示） -->
          <span v-if="showOwnership" class="badge text-[10px]"
            :class="question.is_personal
              ? 'bg-violet-50 dark:bg-violet-900/30 text-violet-600 dark:text-violet-400 border border-violet-200 dark:border-violet-800/50'
              : 'bg-teal-50 dark:bg-teal-900/30 text-teal-600 dark:text-teal-400 border border-teal-200 dark:border-teal-800/50'">
            {{ question.is_personal ? '个人' : '公共' }}
          </span>
          <!-- 岗位标签 -->
          <span v-if="question.job_position" class="badge text-[10px] bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800/50">
            {{ formatPosition(question.job_position) }}
          </span>
          <span class="badge bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border border-primary-100 dark:border-primary-800/50">{{ question.cat1 || '未分类' }}</span>
          <span v-for="tag in parsedTags" :key="tag" class="badge bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200/80 dark:border-gray-700/50">
            {{ tag }}
          </span>
          <span class="badge ml-auto"
            :class="difficultyClass">
            {{ question.difficulty || '-' }}
          </span>
          <button @click.stop="$emit('toggle-star', question)" class="ml-1 transition-all duration-200 hover:scale-125 star-btn" :title="question.is_starred ? '取消收藏' : '收藏'">
            <svg class="w-5 h-5 transition-colors" :class="question.is_starred ? 'text-amber-400' : 'text-gray-300 dark:text-gray-600 hover:text-amber-300 dark:hover:text-amber-500'" :fill="question.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
            </svg>
          </button>
          <!-- Practice status badge -->
          <span v-if="practiceInfo" class="badge text-[10px] font-bold"
            :class="practiceInfo.best_score >= 80 ? 'bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 border border-green-200 dark:border-green-800/50' : practiceInfo.best_score >= 60 ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 border border-yellow-200 dark:border-yellow-800/50' : 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800/50'">
            {{ practiceInfo.best_score }}分
          </span>
          <span v-else class="badge text-[10px] bg-blue-50 dark:bg-blue-900/30 text-blue-500 dark:text-blue-400 border border-blue-100 dark:border-blue-800/50">New</span>
          <!-- Practice button -->
          <button @click.stop="$emit('practice', question)"
            class="text-xs bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 px-2.5 py-1 rounded-lg border border-blue-200 dark:border-blue-800/50 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-all duration-200 flex items-center gap-1 font-medium">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
            做题
          </button>
          <button @click.stop="$emit('retag', question)" :disabled="question._isRetagging"
            class="text-xs bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 px-2.5 py-1 rounded-lg border border-amber-200 dark:border-amber-800/50 hover:bg-amber-100 dark:hover:bg-amber-900/50 transition-all duration-200 disabled:opacity-50 flex items-center gap-1">
            <svg v-if="question._isRetagging" class="animate-spin w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            {{ question._isRetagging ? '分类中...' : '重新分类' }}
          </button>
        </div>
        <h3 class="text-base font-bold text-gray-800 dark:text-gray-100 leading-snug">{{ question.question }}</h3>
      </div>

      <div class="text-gray-300 dark:text-gray-600 mt-1 flex-shrink-0">
        <svg class="w-5 h-5 transform transition-transform duration-200" :class="question._showAnswer ? 'rotate-180 text-primary-400 dark:text-primary-500' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
      </div>
    </div>

    <!-- Answer section: v-if instead of v-show for performance -->
    <div v-if="question._showAnswer" class="border-t border-gray-100 dark:border-gray-700 bg-gradient-to-b from-gray-50/80 to-white dark:from-surface-700/80 dark:to-surface-800 relative group answer-section">

      <!-- Answer (primary content — shown first) -->
      <div class="p-6 pb-0">
        <!-- Edit answer mode -->
        <div v-if="question._isEditingAnswer" class="flex flex-col gap-3">
          <label class="font-bold text-gray-700 dark:text-gray-300 text-sm">编辑答案</label>
          <textarea v-model="question._editAnswer" rows="8" class="w-full max-w-3xl border border-primary-200 dark:border-primary-700/50 rounded-xl p-4 text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 font-mono bg-white dark:bg-surface-900 text-gray-800 dark:text-gray-200 transition-all duration-200"></textarea>
          <div class="flex gap-2 justify-end mt-2">
            <button @click="question._isEditingAnswer = false" class="btn-secondary px-5">取消</button>
            <button @click="$emit('save-field', { tableName: 'question_bank', recordId: question.id, dbColumn: 'ai_answer', newValue: question._editAnswer, rowObj: question, editStateKey: '_isEditingAnswer', frontendKey: 'ai_answer' })" class="btn-primary px-5">保存</button>
          </div>
        </div>

        <!-- View answer mode -->
        <div v-else>
          <div v-if="question.ai_answer && !isFailedAnswer(question.ai_answer)" class="relative">
            <div class="absolute top-0 right-0 flex gap-1.5 z-10">
              <button @click="question._isEditingAnswer = true; question._editAnswer = question.ai_answer" class="bg-white dark:bg-surface-700 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-surface-600 text-gray-600 dark:text-gray-300 px-3 py-1.5 rounded-lg text-xs transition-all duration-200 opacity-0 group-hover:opacity-100 hover:opacity-100 shadow-sm">
                编辑
              </button>
              <button @click.stop="$emit('generate-answer', question)" :disabled="question._isLoadingAnswer" class="bg-white dark:bg-surface-700 border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-surface-600 text-gray-600 dark:text-gray-300 px-3 py-1.5 rounded-lg text-xs transition-all duration-200 opacity-0 group-hover:opacity-100 hover:opacity-100 shadow-sm disabled:opacity-30 disabled:cursor-not-allowed">
                重新生成
              </button>
            </div>
            <div class="text-gray-700 dark:text-gray-300 text-sm leading-relaxed max-w-none answer-content" v-html="cachedMarkdown"></div>
          </div>

          <div v-else-if="question._isLoadingAnswer" class="flex flex-col items-center justify-center py-8 text-primary-600 dark:text-primary-400 gap-3">
            <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span class="font-medium text-sm">AI 正在生成答案，请稍候...</span>
          </div>

          <div v-else class="text-center py-6">
            <p v-if="isFailedAnswer(question.ai_answer)" class="text-red-500 dark:text-red-400 mb-3 text-sm flex items-center justify-center gap-1.5">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              上次生成失败，请重试。
            </p>
            <p v-else class="text-gray-400 dark:text-gray-500 mb-4 text-sm">该题目暂无答案</p>
            <div class="flex gap-2 justify-center flex-wrap">
              <button @click.stop="$emit('generate-answer', question)" class="btn-primary px-6 py-2.5">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                AI 生成答案
              </button>
              <button @click="question._isEditingAnswer = true; question._editAnswer = ''" class="btn-secondary px-6 py-2.5">
                手动编写
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Sources & original questions (secondary — collapsible) -->
      <div v-if="hasSources" class="border-t border-gray-100 dark:border-gray-700 mt-5">
        <button @click.stop="showSources = !showSources"
          class="w-full px-6 py-3 flex items-center gap-2 text-xs font-medium text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-50 dark:hover:bg-surface-700/50 transition-colors">
          <svg class="w-3.5 h-3.5 transform transition-transform duration-200" :class="showSources ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <svg class="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
          <span>来源详情</span>
          <span class="badge bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200/80 dark:border-gray-700/50 text-[10px] ml-0.5">{{ sourceCount }}条</span>
        </button>

        <div v-if="showSources" class="px-6 pb-5 space-y-2.5">
          <!-- Multi-question cluster (has original_questions) -->
          <template v-if="question.original_questions && question.original_questions.length > 0">
            <div v-for="(oq, idx) in question.original_questions" :key="idx"
              class="bg-gray-50 dark:bg-surface-700 border border-gray-200 dark:border-gray-600 rounded-xl p-3 flex items-start gap-3">
              <span class="text-gray-400 dark:text-gray-500 font-mono text-xs shrink-0 mt-0.5">{{ idx + 1 }}.</span>
              <div class="flex-1 min-w-0">
                <div class="text-sm text-gray-700 dark:text-gray-300 mb-1.5">{{ oq }}</div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <span v-for="(src, sIdx) in getOrigSources(oq)" :key="sIdx"
                    class="text-[11px] bg-primary-50 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800/40 text-primary-600 dark:text-primary-400 px-2 py-0.5 rounded-md inline-flex items-center">
                    <svg class="w-3 h-3 mr-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                    {{ src.company === '未提供' ? '未知' : src.company }}
                    <span class="text-primary-300 dark:text-primary-600 mx-0.5">|</span>
                    {{ src.round === '未提供' ? '未知' : src.round }}
                    <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" class="ml-1 text-primary-500 hover:text-primary-700 dark:hover:text-primary-300 font-bold" title="查看原文">[原文]</a>
                  </span>
                  <button @click.stop="$emit('split-question', { question, originalQuestion: oq })"
                    class="text-[11px] bg-orange-50 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 px-2 py-0.5 rounded-md border border-orange-200 dark:border-orange-800/50 hover:bg-orange-100 dark:hover:bg-orange-900/50 transition-all">
                    独立
                  </button>
                  <button @click.stop="$emit('start-merge', { question, originalQuestion: oq })"
                    class="text-[11px] bg-purple-50 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400 px-2 py-0.5 rounded-md border border-purple-200 dark:border-purple-800/50 hover:bg-purple-100 dark:hover:bg-purple-900/50 transition-all">
                    合并到
                  </button>
                </div>
              </div>
            </div>
          </template>

          <!-- Single-question sources (no original_questions) -->
          <div v-else-if="question.sources && question.sources.length > 0" class="flex flex-wrap items-center gap-1.5">
            <span v-for="(src, idx) in question.sources" :key="idx"
              class="text-xs bg-primary-50 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800/40 text-primary-600 dark:text-primary-400 px-2 py-1 rounded-md inline-flex items-center">
              <svg class="w-3.5 h-3.5 mr-1 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
              {{ src.company === '未提供' ? '未知' : src.company }}
              <span class="text-primary-300 dark:text-primary-600 mx-1">|</span>
              {{ src.round === '未提供' ? '未知轮次' : src.round }}
              <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" class="ml-1.5 text-primary-500 hover:text-primary-700 dark:hover:text-primary-300 font-bold" title="查看原文">[原文]</a>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown.js'

const showSources = ref(false)

const DIFFICULTY_CLASSES = {
  L3: 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-800/50',
  L2: 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-100 dark:border-amber-800/50',
  default: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-800/50',
}

const props = defineProps({
  question: { type: Object, required: true },
  isSelected: { type: Function, required: true },
  practiceInfo: { type: Object, default: null },
  bankMode: { type: String, default: 'public' },
})

defineEmits(['toggle-answer', 'toggle-star', 'retag', 'generate-answer', 'save-field', 'toggle-item', 'practice', 'split-question', 'start-merge'])

const parsedTags = computed(() => {
  const tags = props.question.tags
  return tags ? tags.split(',') : []
})

const difficultyClass = computed(() => {
  const d = String(props.question.difficulty || '')
  if (d.includes('L3')) return DIFFICULTY_CLASSES.L3
  if (d.includes('L2')) return DIFFICULTY_CLASSES.L2
  return DIFFICULTY_CLASSES.default
})

const cachedMarkdown = computed(() => {
  return renderSafeMarkdown(props.question.ai_answer || '')
})

const hasSources = computed(() => {
  const q = props.question
  return (q.original_questions && q.original_questions.length > 0) || (q.sources && q.sources.length > 0)
})

const sourceCount = computed(() => {
  const q = props.question
  if (q.original_questions && q.original_questions.length > 0) return q.original_questions.length
  if (q.sources && q.sources.length > 0) return q.sources.length
  return 0
})

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')

const showOwnership = computed(() => props.bankMode === 'mixed')

const formatPosition = (pos) => {
  if (!pos) return ''
  // 取第一段作为简称，如 "agent开发/大模型应用开发" → "Agent开发"
  const first = pos.split('/')[0].trim()
  return first.charAt(0).toUpperCase() + first.slice(1)
}

const getOrigSources = (questionText) => {
  const oqs = props.question.original_question_sources
  if (!oqs || !Array.isArray(oqs)) return []
  const found = oqs.find(item => item.question === questionText)
  return found ? (found.sources || []) : []
}
</script>

<style scoped>
.star-btn:active svg { animation: star-pop 0.3s ease-out; }
@keyframes star-pop {
  0% { transform: scale(1); }
  50% { transform: scale(1.4); }
  100% { transform: scale(1); }
}
</style>
