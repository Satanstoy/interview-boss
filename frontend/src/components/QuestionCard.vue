<template>
  <div
    class="card-smooth overflow-hidden"
    :class="[
      isSelected(question.id) ? 'border-primary-400 dark:border-primary-500 ring-2 ring-primary-100 dark:ring-primary-900/50' : '',
    ]"
  >
    <!-- Card header -->
    <div class="p-4 flex gap-3 items-start cursor-pointer hover:bg-surface-50/60 dark:hover:bg-surface-700/40 transition-colors duration-200" @click="$emit('toggle-answer', question)">
      <div class="flex items-center self-stretch" @click.stop>
        <input type="checkbox" :checked="isSelected(question.id)" @change="$emit('toggle-item', question.id)"
          class="w-4 h-4 text-primary-600 rounded-md border-surface-300 dark:border-ink-600 focus:ring-primary-500 cursor-pointer transition bg-white dark:!bg-ink-800">
      </div>

      <div class="flex-1 min-w-0">
        <!-- Question text (primary — most prominent) -->
        <div class="flex items-start gap-2 group mb-2">
          <h3 class="text-[15px] font-bold text-ink-900 dark:text-ink-100 leading-snug flex-1">{{ question.question }}</h3>
          <button v-if="canEdit" @click.stop="startEditQuestion"
            class="opacity-0 group-hover:opacity-100 p-1 -m-1 rounded transition-all duration-200 hover:bg-surface-100 dark:hover:bg-surface-700 text-ink-400 hover:text-primary-600 dark:hover:text-primary-400 shrink-0"
            title="编辑题目">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
          </button>
        </div>

        <!-- Metadata row (secondary — smaller, lighter) -->
        <div class="flex gap-1.5 items-center flex-wrap">
          <!-- Frequency: prominent badge -->
          <span class="inline-flex flex-col items-center justify-center bg-gradient-to-b from-red-50 to-red-100/50 dark:from-red-900/30 dark:to-red-900/10 text-red-600 dark:text-red-400 font-bold rounded-lg px-2 py-1 min-w-[36px] border border-red-100 dark:border-red-800/50">
            <span class="text-label text-red-400 dark:text-red-500 mb-0.5">频率</span>
            <span class="text-base leading-none">{{ question.frequency }}</span>
          </span>

          <!-- Category tag: primary color, single badge -->
          <span class="badge bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">
            {{ question.cat1 || '未分类' }}
          </span>

          <!-- Tags: neutral, max 3 shown -->
          <span v-for="tag in parsedTags.slice(0, 3)" :key="tag" class="badge bg-surface-100 dark:bg-ink-800/80 text-ink-500 dark:text-ink-400 text-label">
            {{ tag }}
          </span>
          <span v-if="parsedTags.length > 3" class="text-caption text-ink-400 dark:text-ink-500">+{{ parsedTags.length - 3 }}</span>

          <!-- Ownership badge (mixed mode only) -->
          <span v-if="showOwnership" class="badge text-label"
            :class="question.is_personal
              ? 'bg-violet-50 dark:bg-violet-900/25 text-violet-600 dark:text-violet-400'
              : 'bg-teal-50 dark:bg-teal-900/25 text-teal-600 dark:text-teal-400'">
            {{ question.is_personal ? '个人' : '公共' }}
          </span>

          <!-- Position badge -->
          <span v-if="question.job_position" class="badge text-label bg-surface-100 dark:bg-ink-800/80 text-ink-500 dark:text-ink-400">
            {{ formatPosition(question.job_position) }}
          </span>

          <!-- Difficulty: semantic color (the only strong color on the row) -->
          <span class="badge ml-auto" :class="difficultyClass">
            {{ question.difficulty || '-' }}
          </span>

          <!-- Practice status: compact -->
          <span v-if="practiceInfo" class="badge text-label"
            :class="practiceInfo.best_score >= 80 ? 'bg-emerald-50 dark:bg-emerald-900/25 text-emerald-600 dark:text-emerald-400' : practiceInfo.best_score >= 60 ? 'bg-amber-50 dark:bg-amber-900/25 text-amber-600 dark:text-amber-400' : 'bg-red-50 dark:bg-red-900/25 text-red-500 dark:text-red-400'">
            {{ practiceInfo.best_score }}
          </span>
          <span v-else class="badge text-label bg-surface-100 dark:bg-ink-800/80 text-ink-400 dark:text-ink-500">New</span>
        </div>

        <!-- Actions row: hover-reveal for secondary actions -->
        <div class="flex gap-1.5 mt-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
          <button @click.stop="$emit('practice', question)"
            class="text-label px-2 py-1 rounded-lg bg-primary-50 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 hover:bg-primary-100 dark:hover:bg-primary-900/40 transition-all duration-200 flex items-center gap-1">
            <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
            做题
          </button>
          <button v-if="isAdmin" @click.stop="$emit('retag', question)" :disabled="question._isRetagging"
            class="text-label px-2 py-1 rounded-lg bg-surface-100 dark:bg-ink-800/80 text-ink-500 dark:text-ink-400 hover:bg-surface-200 dark:hover:bg-ink-700 transition-all duration-200 disabled:opacity-50 flex items-center gap-1">
            <svg v-if="question._isRetagging" class="animate-spin w-3 h-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            {{ question._isRetagging ? '分类中...' : '重新分类' }}
          </button>
          <button v-if="canDelete" @click.stop="$emit('delete', question)" class="text-label px-2 py-1 rounded-lg text-ink-400 dark:text-ink-500 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-all duration-200" title="删除">
            <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Star (always visible, tertiary action) -->
      <button @click.stop="$emit('toggle-star', question)" class="p-1 transition-all duration-200 hover:scale-110 star-btn shrink-0" :title="question.is_starred ? '取消收藏' : '收藏'">
        <svg class="w-4.5 h-4.5 transition-colors" :class="question.is_starred ? 'text-amber-400' : 'text-ink-200 dark:text-ink-700 hover:text-amber-300 dark:hover:text-amber-500'" :fill="question.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
        </svg>
      </button>

      <!-- Expand chevron -->
      <div class="text-ink-300 dark:text-ink-600 mt-0.5 shrink-0">
        <svg class="w-4 h-4 transform transition-transform duration-200" :class="question._showAnswer ? 'rotate-180 text-primary-400 dark:text-primary-500' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
      </div>
    </div>

    <!-- Answer section: v-if instead of v-show for performance -->
    <div v-if="question._showAnswer" class="border-t border-surface-100 dark:border-ink-700 bg-gradient-to-b from-gray-50/80 to-white dark:from-surface-800 dark:to-surface-800 relative group answer-section">

      <!-- Answer (primary content — shown first) -->
      <div class="p-6 pb-0">
        <!-- Edit answer mode -->
        <div v-if="question._isEditingAnswer" class="flex flex-col gap-3">
          <label class="font-bold text-ink-700 dark:text-ink-300 text-sm">编辑答案</label>
          <textarea v-model="question._editAnswer" rows="8" class="w-full max-w-3xl border border-primary-200 dark:border-primary-700/50 rounded-xl p-4 text-sm focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 font-mono bg-white dark:bg-surface-900 text-ink-800 dark:text-ink-200 transition-all duration-200"></textarea>
          <div class="flex gap-2 justify-end mt-2">
            <button @click="question._isEditingAnswer = false" class="btn-secondary px-5">取消</button>
            <button @click="isAdmin ? $emit('save-field', { tableName: 'question_bank', recordId: question.id, dbColumn: 'ai_answer', newValue: question._editAnswer, rowObj: question, editStateKey: '_isEditingAnswer', frontendKey: 'ai_answer' }) : $emit('save-user-answer', { question, answer: question._editAnswer })" class="btn-primary px-5">保存</button>
          </div>
        </div>

        <!-- View answer mode -->
        <div v-else>
          <div v-if="displayAnswer && !isFailedAnswer(displayAnswer)" class="relative group/answer">
            <div class="absolute top-0 right-0 flex gap-1 z-10">
              <button @click="question._isEditingAnswer = true; question._editAnswer = displayAnswer" class="bg-white/80 dark:bg-surface-700/60 text-caption text-ink-500 dark:text-ink-400 px-2.5 py-1 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-600 transition-all duration-200 opacity-0 group-hover/answer:opacity-100">
                编辑
              </button>
              <button @click.stop="$emit('generate-answer', question)" :disabled="question._isLoadingAnswer" class="bg-white/80 dark:bg-surface-700/60 text-caption text-ink-500 dark:text-ink-400 px-2.5 py-1 rounded-lg hover:bg-surface-100 dark:hover:bg-surface-600 transition-all duration-200 opacity-0 group-hover/answer:opacity-100 disabled:opacity-30 disabled:cursor-not-allowed">
                重新生成
              </button>
            </div>
            <div v-if="(fullUserAnswer ?? question.user_answer) && question.has_reference_answer" class="mb-2 flex items-center gap-1.5">
              <span class="text-label text-primary-500 dark:text-primary-400 bg-primary-50/60 dark:bg-primary-900/20 px-2 py-0.5 rounded">个人答案</span>
            </div>
            <div class="text-ink-700 dark:text-ink-100 text-sm leading-relaxed max-w-none answer-content" v-html="cachedMarkdown"></div>
          </div>

          <div v-else-if="isLoadingDetail" class="flex flex-col items-center justify-center py-8 text-primary-600 dark:text-primary-400 gap-3">
            <svg class="animate-spin h-6 w-6" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span class="font-medium text-sm">加载答案中...</span>
          </div>

          <div v-else-if="question._isLoadingAnswer" class="flex flex-col items-center justify-center py-8 text-primary-600 dark:text-primary-400 gap-3">
            <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span class="font-medium text-sm">AI 正在生成答案，请稍候...</span>
          </div>

          <div v-else class="text-center py-6">
            <p v-if="isFailedAnswer(displayAnswer)" class="text-red-500 dark:text-red-400 mb-3 text-sm flex items-center justify-center gap-1.5">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              上次生成失败，请重试。
            </p>
            <p v-else class="text-ink-400 dark:text-ink-500 mb-4 text-sm">该题目暂无答案</p>
            <div class="flex gap-2 justify-center flex-wrap">
              <button v-if="question.has_reference_answer && !(fullUserAnswer ?? question.user_answer)" @click.stop="$emit('use-reference-answer', question)" class="btn-secondary px-5 py-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                使用参考答案
              </button>
              <button @click.stop="$emit('generate-answer', question)" class="btn-primary px-5 py-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                AI 生成答案
              </button>
              <button @click="question._isEditingAnswer = true; question._editAnswer = ''" class="btn-ghost px-5 py-2">
                手动编写
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Sources & original questions (secondary — collapsible) -->
      <div v-if="hasSources" class="border-t border-surface-100 dark:border-ink-700 mt-5">
        <button @click.stop="showSources = !showSources"
          class="w-full px-6 py-3 flex items-center gap-2 text-caption font-medium text-ink-400 dark:text-ink-500 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-50/60 dark:hover:bg-surface-700/30 transition-colors">
          <svg class="w-3 h-3 transform transition-transform duration-200" :class="showSources ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <span>来源详情</span>
          <span class="text-label text-ink-400 dark:text-ink-500 ml-0.5">{{ sourceCount }}条</span>
        </button>

        <div v-if="showSources" class="px-6 pb-5 space-y-2">
          <div v-for="(src, idx) in dedupedSources" :key="src.url || idx"
            class="bg-surface-50/80 dark:bg-surface-700/30 rounded-xl p-3 flex items-start gap-3">
            <span class="text-caption text-ink-400 dark:text-ink-500 font-mono shrink-0 mt-0.5">{{ idx + 1 }}.</span>
            <div class="flex-1 min-w-0">
              <div v-if="src._origQuestion" class="text-xs text-ink-400 dark:text-ink-500 mb-1 whitespace-pre-line">{{ src._origQuestion }}</div>
              <div class="flex flex-wrap items-center gap-1.5">
                <span @click="$emit('navigate-to-interview', src)"
                  class="text-caption bg-primary-50/60 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 px-2 py-0.5 rounded-md inline-flex items-center cursor-pointer hover:bg-primary-100 dark:hover:bg-primary-900/30 transition-colors">
                  <svg class="w-3 h-3 mr-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                  {{ src.company === '未提供' ? '未知' : src.company }}
                  <span class="text-primary-300 dark:text-primary-600 mx-0.5">|</span>
                  {{ src.round === '未提供' ? '未知' : src.round }}
                  <a v-if="src.url && src.url !== '未提供链接'" @click.stop :href="safeUrl(src.url)" target="_blank" rel="noopener noreferrer" class="ml-1 text-primary-500 hover:text-primary-700 dark:hover:text-primary-300 font-bold" title="查看原文">[原文]</a>
                </span>
                <button v-if="isAdmin && dedupedSources.length > 1" @click.stop="$emit('split-question', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-ink-400 dark:text-ink-500 hover:text-orange-500 dark:hover:text-orange-400 px-1.5 py-0.5 rounded transition-colors">
                  独立
                </button>
                <button v-if="isAdmin" @click.stop="$emit('start-merge', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-ink-400 dark:text-ink-500 hover:text-violet-500 dark:hover:text-violet-400 px-1.5 py-0.5 rounded transition-colors">
                  合并到
                </button>
                <button v-if="canDelete" @click.stop="$emit('delete-original-question', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-ink-400 dark:text-ink-500 hover:text-red-500 dark:hover:text-red-400 px-1.5 py-0.5 rounded transition-colors">
                  删除
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown.js'
import { safeUrl } from '../utils/validate.js'
import { get } from '../utils/http.js'

const showSources = ref(false)

// Lazy-loaded full answer detail (for compact mode)
const fullAnswer = ref(null)
const fullUserAnswer = ref(null)
const isLoadingDetail = ref(false)

async function loadFullAnswer() {
  if (fullAnswer.value !== null) return
  if (props.question.ai_answer) {
    fullAnswer.value = props.question.ai_answer
    fullUserAnswer.value = props.question.user_answer
    return
  }
  if (!props.question.has_reference_answer && !props.question.id) return
  isLoadingDetail.value = true
  try {
    const detail = await get(`/api/master-bank/${props.question.id}/detail`)
    fullAnswer.value = detail.ai_answer || ''
    fullUserAnswer.value = detail.user_answer || ''
    // Emit to parent so it updates the question object too
    emit('update-answer', { id: props.question.id, ai_answer: detail.ai_answer, user_answer: detail.user_answer })
  } catch (e) {
    console.error('Failed to load answer detail:', e)
    fullAnswer.value = ''
  } finally {
    isLoadingDetail.value = false
  }
}

// Trigger detail load when answer section is shown
watch(() => props.question._showAnswer, (show) => {
  if (show) loadFullAnswer()
}, { immediate: true })

const DIFFICULTY_CLASSES = {
  L3: 'bg-red-50 dark:bg-red-900/25 text-red-600 dark:text-red-400',
  L2: 'bg-amber-50 dark:bg-amber-900/25 text-amber-600 dark:text-amber-400',
  default: 'bg-emerald-50 dark:bg-emerald-900/25 text-emerald-600 dark:text-emerald-400',
}

const props = defineProps({
  question: { type: Object, required: true },
  isSelected: { type: Function, required: true },
  practiceInfo: { type: Object, default: null },
  bankMode: { type: String, default: 'public' },
  isAdmin: { type: Boolean, default: false },
  currentUserId: { type: [Number, String], default: null },
})

const emit = defineEmits(['toggle-answer', 'toggle-star', 'retag', 'generate-answer', 'use-reference-answer', 'save-user-answer', 'save-field', 'toggle-item', 'practice', 'split-question', 'start-merge', 'navigate-to-interview', 'delete', 'edit-question', 'delete-original-question', 'update-answer'])

const parsedTags = computed(() => {
  const tags = props.question.tags
  return tags ? tags.split(',') : []
})

const canDelete = computed(() => {
  if (props.isAdmin) return true
  if (props.question.owner_id != null && String(props.question.owner_id) === String(props.currentUserId)) return true
  return false
})

const canEdit = computed(() => {
  if (props.isAdmin) return true
  if (props.question.owner_id != null && String(props.question.owner_id) === String(props.currentUserId)) return true
  return false
})

const startEditQuestion = () => {
  props.question._isEditingQuestion = true
  props.question._editQuestion = props.question.question
}

const cancelEditQuestion = () => {
  props.question._isEditingQuestion = false
  props.question._editQuestion = ''
}

const saveEditQuestion = () => {
  const newValue = (props.question._editQuestion || '').trim()
  if (!newValue) return
  emit('edit-question', { question: props.question, newValue })
}

const difficultyClass = computed(() => {
  const d = String(props.question.difficulty || '')
  if (d.includes('L3')) return DIFFICULTY_CLASSES.L3
  if (d.includes('L2')) return DIFFICULTY_CLASSES.L2
  return DIFFICULTY_CLASSES.default
})

const displayAnswer = computed(() => {
  // 优先显示个人答案，其次显示全局答案
  const userAns = fullUserAnswer.value ?? props.question.user_answer
  const aiAns = fullAnswer.value ?? props.question.ai_answer
  return userAns || aiAns || ''
})

const cachedMarkdown = computed(() => {
  return renderSafeMarkdown(displayAnswer.value)
})

const hasSources = computed(() => {
  const q = props.question
  return (q.original_questions && q.original_questions.length > 0) || (q.sources && q.sources.length > 0)
})

const sourceCount = computed(() => {
  const q = props.question
  if (q.sources && q.sources.length > 0) return q.sources.length
  return 0
})

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')

const showOwnership = computed(() => props.bankMode === 'mixed')

const formatPosition = (pos) => {
  if (!pos) return ''
  const first = pos.split('/')[0].trim()
  return first.charAt(0).toUpperCase() + first.slice(1)
}

// 按 URL 去重的来源列表，仅在展开时计算以节省性能
const dedupedSources = computed(() => {
  if (!showSources.value) return []
  const q = props.question
  const sources = q.sources || []
  if (!q.original_question_sources || !q.original_question_sources.length) return sources
  // 建立 url -> 原始问题文本 的映射（支持同一 URL 多个题目）
  const urlToOq = {}
  for (const item of q.original_question_sources) {
    for (const s of (item.sources || [])) {
      if (s.url) {
        if (!urlToOq[s.url]) urlToOq[s.url] = item.question
        else if (!urlToOq[s.url].includes(item.question)) urlToOq[s.url] += '\n' + item.question
      }
    }
  }
  return sources.map(s => ({ ...s, _origQuestion: urlToOq[s.url] || '' }))
})
</script>

<style scoped>
.star-btn:active svg { animation: star-pop 0.3s ease-out; }
@keyframes star-pop {
  0% { transform: scale(1); }
  50% { transform: scale(1.4); }
  100% { transform: scale(1); }
}

/* 暗黑模式：答案区域高对比度 */
.dark :deep(.answer-content) {
  color: #f5f5f4;
}
.dark :deep(.answer-content p),
.dark :deep(.answer-content li),
.dark :deep(.answer-content span) {
  color: #f5f5f4;
}
.dark :deep(.answer-content h1),
.dark :deep(.answer-content h2),
.dark :deep(.answer-content h3),
.dark :deep(.answer-content h4) {
  color: #fafaf9;
}
.dark :deep(.answer-content code) {
  background-color: #302b28;
  color: #f5f5f4;
  padding: 0.125rem 0.375rem;
  border-radius: 0.25rem;
}
.dark :deep(.answer-content pre) {
  background-color: #1c1917;
  color: #f5f5f4;
  border: 1px solid #44403c;
  border-radius: 0.5rem;
  padding: 1rem;
}
.dark :deep(.answer-content pre code) {
  background-color: transparent;
  padding: 0;
}
.dark :deep(.answer-content a) {
  color: #fdba74;
}
.dark :deep(.answer-content strong) {
  color: #fafaf9;
}
.dark :deep(.answer-content blockquote) {
  border-left-color: #78716c;
  color: #d6d3d1;
}
</style>
