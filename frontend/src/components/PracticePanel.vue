<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible && question" class="fixed inset-0 z-[100] flex items-center justify-center p-4 sm:p-6">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="emit('close')"></div>

        <!-- Modal -->
        <div class="relative bg-white dark:bg-surface-800 rounded-2xl shadow-2xl w-full max-w-6xl h-[90vh] flex flex-col overflow-hidden animate-slide-up">
          <!-- Top bar -->
          <div class="flex items-center justify-between px-5 py-3 border-b border-gray-200 dark:border-gray-600 shrink-0 bg-gray-50 dark:bg-surface-900">
            <div class="flex items-center gap-3 min-w-0">
              <h2 class="text-sm font-bold text-gray-800 dark:text-gray-100 truncate max-w-md">{{ question.question }}</h2>
              <span class="badge bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border border-primary-100 dark:border-primary-800 text-[10px] shrink-0">{{ question.cat1 || '未分类' }}</span>
              <span class="badge text-[10px] shrink-0"
                :class="String(question.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-800' : String(question.difficulty).includes('L2') ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border border-amber-100 dark:border-amber-800' : 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-800'">
                {{ question.difficulty || '-' }}
              </span>
            </div>
            <button @click="emit('close')" class="p-1.5 rounded-lg text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition shrink-0">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Main content: left + right panels -->
          <div class="flex-1 flex flex-col lg:flex-row overflow-hidden">
            <!-- LEFT PANEL -->
            <div class="w-full lg:w-1/2 flex flex-col border-r border-gray-200 dark:border-gray-600">
              <!-- Tabs -->
              <div class="flex border-b border-gray-200 dark:border-gray-600 shrink-0 bg-white dark:bg-surface-800">
                <button v-for="tab in leftTabs" :key="tab.key"
                  @click="leftTab = tab.key"
                  class="px-4 py-2.5 text-xs font-semibold transition-colors relative"
                  :class="leftTab === tab.key ? 'text-primary-700 dark:text-primary-400' : 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'">
                  {{ tab.label }}
                  <span v-if="tab.key === 'answer' && !question.ai_answer" class="ml-1 inline-block w-1.5 h-1.5 rounded-full bg-red-400 dark:bg-red-400"></span>
                  <span v-if="tab.key === 'history' && question.attempt_count" class="ml-1 text-[10px] text-gray-400 dark:text-gray-500">({{ question.attempt_count }})</span>
                  <div v-if="leftTab === tab.key" class="absolute bottom-0 left-2 right-2 h-0.5 bg-primary-500 dark:bg-primary-500 rounded-full"></div>
                </button>
              </div>

              <!-- Tab content -->
              <div class="flex-1 overflow-y-auto custom-scrollbar">
                <!-- Description tab -->
                <div v-if="leftTab === 'description'" class="p-5 space-y-4">
                  <div class="flex gap-1.5 flex-wrap">
                    <span v-for="tag in (question.tags ? question.tags.split(',') : [])" :key="tag" class="badge bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 border border-gray-200/80 dark:border-gray-700 text-[10px]">{{ tag }}</span>
                  </div>
                  <div class="text-sm text-gray-800 dark:text-gray-100 leading-relaxed font-medium">{{ question.question }}</div>

                  <!-- Sources -->
                  <div v-if="question.sources && question.sources.length > 0" class="bg-primary-50/40 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800 rounded-xl p-4">
                    <h4 class="text-xs font-bold text-primary-800 dark:text-primary-400 mb-2 flex items-center gap-1.5">
                      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                      出处追溯 ({{ question.sources.length }} 次出现)
                    </h4>
                    <div class="flex flex-wrap gap-1.5 text-[11px]">
                      <span v-for="(src, idx) in question.sources" :key="idx" class="bg-white dark:bg-gray-800 border border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400 px-2 py-1 rounded-lg inline-flex items-center">
                        {{ src.company === '未提供' ? '未知' : src.company }}
                        <span class="text-primary-300 dark:text-primary-600 mx-1">|</span>
                        {{ src.round === '未提供' ? '未知轮次' : src.round }}
                        <a v-if="src.url && src.url !== '未提供链接'" :href="src.url" target="_blank" rel="noopener noreferrer" class="ml-1.5 text-primary-500 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-bold">[原文]</a>
                      </span>
                    </div>
                  </div>
                </div>

                <!-- Answer/Solution tab -->
                <div v-else-if="leftTab === 'answer'" class="p-5">
                  <div v-if="qState._isEditingAnswer" class="flex flex-col gap-3">
                    <textarea v-model="qState._editAnswer" rows="12" class="w-full border border-primary-200 dark:border-primary-800 rounded-xl p-3 text-sm bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 font-mono resize-y"></textarea>
                    <div class="flex gap-2 justify-end">
                      <button @click="qState._isEditingAnswer = false" class="px-4 py-1.5 text-xs text-gray-600 dark:text-gray-400 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition">取消</button>
                      <button @click="handleSaveAnswer" :disabled="qState._isSavingAnswer" class="px-4 py-1.5 text-xs text-white bg-primary-600 dark:bg-primary-600 rounded-lg hover:bg-primary-700 dark:hover:bg-primary-700 transition disabled:opacity-50">
                        {{ qState._isSavingAnswer ? '保存中...' : '保存' }}
                      </button>
                    </div>
                  </div>

                  <div v-else-if="question.ai_answer && !isFailedAnswer(question.ai_answer)">
                    <div class="flex items-center justify-between mb-3">
                      <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">AI 参考答案</span>
                      <div class="flex gap-1.5">
                        <button @click="qState._isEditingAnswer = true; qState._editAnswer = question.ai_answer" class="text-[10px] text-primary-600 dark:text-primary-400 hover:text-primary-800 dark:hover:text-primary-300 bg-primary-50 dark:bg-primary-900/30 hover:bg-primary-100 dark:hover:bg-primary-900/50 px-2 py-0.5 rounded border border-primary-200 dark:border-primary-800 transition">编辑</button>
                        <button @click="handleGenerate" :disabled="qState._isLoadingAnswer" class="text-[10px] text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-300 bg-gray-50 dark:bg-gray-800 hover:bg-gray-100 dark:hover:bg-gray-700 px-2 py-0.5 rounded border border-gray-200 dark:border-gray-600 transition disabled:opacity-30">重新生成</button>
                      </div>
                    </div>
                    <div class="text-sm text-gray-700 dark:text-gray-300 leading-relaxed answer-content" v-html="renderMarkdown(question.ai_answer)"></div>
                  </div>

                  <div v-else-if="qState._isLoadingAnswer" class="flex flex-col items-center justify-center py-12 text-primary-600 dark:text-primary-400 gap-3">
                    <svg class="animate-spin h-7 w-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                    <span class="text-sm">正在生成参考答案...</span>
                  </div>

                  <div v-else class="text-center py-12">
                    <p v-if="isFailedAnswer(question.ai_answer)" class="text-red-500 dark:text-red-400 mb-3 text-sm">上次生成失败，请重试</p>
                    <p v-else class="text-gray-400 dark:text-gray-500 mb-4 text-sm">暂无参考答案</p>
                    <button @click="handleGenerate" class="btn-primary px-5 py-2 text-sm">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                      AI 生成答案
                    </button>
                  </div>
                </div>

                <!-- History tab -->
                <div v-else-if="leftTab === 'history'" class="p-5">
                  <div v-if="qState._historyLoading" class="text-center py-8 text-xs text-gray-400 dark:text-gray-500">加载中...</div>
                  <div v-else-if="qState._history && qState._history.length > 0" class="space-y-2">
                    <div v-for="(h, hIdx) in qState._history" :key="h.id" class="border border-gray-200 dark:border-gray-600 rounded-xl overflow-hidden">
                      <div class="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 transition" @click="h._expanded = !h._expanded">
                        <span class="text-[10px] text-gray-400 dark:text-gray-500 w-6 text-right shrink-0">#{{ qState._history.length - hIdx }}</span>
                        <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                        <span class="text-[10px] text-gray-400 dark:text-gray-500 ml-auto">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                        <div class="w-16 shrink-0">
                          <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                            <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                          </div>
                        </div>
                        <svg class="w-3 h-3 text-gray-400 dark:text-gray-500 transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                      </div>
                      <div v-if="h._expanded" class="px-3 pb-3 space-y-2 border-t border-gray-100 dark:border-gray-700 pt-2">
                        <div>
                          <p class="text-[10px] font-semibold text-gray-500 dark:text-gray-400 mb-1">我的回答</p>
                          <p class="text-xs text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800 rounded-lg p-2 whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                        </div>
                        <div v-if="h.evaluation_result">
                          <div class="flex items-center gap-2 flex-wrap mb-1">
                            <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-[10px] text-gray-500 dark:text-gray-400">
                              {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                            </span>
                          </div>
                          <p v-if="h.evaluation_result.suggestions" class="text-[10px] text-gray-500 dark:text-gray-400">
                            <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 150) }}{{ h.evaluation_result.suggestions?.length > 150 ? '...' : '' }}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div v-else class="text-center py-12 text-gray-400 dark:text-gray-500 text-sm">
                    <svg class="w-10 h-10 mx-auto mb-2 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                    暂无练习记录
                  </div>
                </div>
              </div>
            </div>

            <!-- RIGHT PANEL -->
            <div class="w-full lg:w-1/2 flex flex-col">
              <!-- Answer input area -->
              <div class="flex-1 flex flex-col overflow-hidden">
                <div class="px-5 pt-4 pb-2 shrink-0">
                  <h3 class="text-xs font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wider flex items-center gap-1.5">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                    我的回答
                  </h3>
                </div>
                <div class="flex-1 px-5 pb-3 overflow-hidden">
                  <textarea
                    v-model="qState._userAnswer"
                    class="w-full h-full border border-gray-200 dark:border-gray-600 rounded-xl p-3.5 text-sm leading-relaxed focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 resize-none transition-all duration-200 bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800"
                    placeholder="在此输入你的回答，完成后点击下方「提交评估」..."
                  ></textarea>
                </div>
                <div class="px-5 pb-3 flex gap-2 items-center shrink-0">
                  <button
                    @click="handleEvaluate"
                    :disabled="qState._isEvaluating || !qState._userAnswer.trim()"
                    class="flex items-center gap-2 bg-gradient-to-r from-primary-600 to-indigo-600 dark:from-primary-600 dark:to-indigo-600 text-white font-medium px-5 py-2.5 rounded-xl hover:from-primary-700 hover:to-indigo-700 dark:hover:from-primary-700 dark:hover:to-indigo-700 transition-all duration-200 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <svg v-if="qState._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                    {{ qState._isEvaluating ? '评估中...' : '提交评估' }}
                  </button>
                  <button v-if="qState._userAnswer" @click="qState._userAnswer = ''; qState._evaluation = null"
                    class="text-sm text-gray-500 dark:text-gray-400 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition">清空</button>
                  <span v-if="question.attempt_count" class="text-[10px] text-gray-400 dark:text-gray-500 ml-auto">已练习 {{ question.attempt_count }} 次</span>
                </div>
              </div>

              <!-- Evaluation result -->
              <div v-if="qState._evaluation" class="border-t border-gray-200 dark:border-gray-600 bg-gradient-to-b from-primary-50/30 to-white dark:from-primary-900/20 dark:to-surface-800 overflow-y-auto custom-scrollbar" style="max-height: 55%;">
                <div class="p-5 space-y-4">
                  <!-- Overall score -->
                  <div class="flex items-center gap-4">
                    <span class="text-4xl font-extrabold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span>
                    <div class="flex-1">
                      <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-3 overflow-hidden">
                        <div class="h-full rounded-full transition-all duration-700" :class="scoreColor(qState._evaluation.overall_score)" :style="{ width: qState._evaluation.overall_score + '%' }"></div>
                      </div>
                      <p class="text-[10px] text-gray-400 dark:text-gray-500 mt-1">加权总分（准确性 35%、完整性 30%、深度 20%、逻辑性 15%）</p>
                    </div>
                  </div>

                  <!-- Dimension scores -->
                  <div class="grid grid-cols-2 gap-2.5">
                    <div v-for="(val, key) in qState._evaluation.dimensions" :key="key" class="bg-white dark:bg-gray-800 rounded-xl p-2.5 border border-gray-100 dark:border-gray-700">
                      <div class="flex items-center justify-between mb-1">
                        <span class="text-[10px] font-semibold text-gray-600 dark:text-gray-400">{{ dimLabel[key] || key }}</span>
                        <span class="text-sm font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                      </div>
                      <div class="bg-gray-100 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden mb-1">
                        <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                      </div>
                      <p v-if="val.comment" class="text-[10px] text-gray-400 dark:text-gray-500 leading-snug">{{ val.comment }}</p>
                    </div>
                  </div>

                  <!-- Strengths & Weaknesses -->
                  <div class="grid grid-cols-2 gap-3">
                    <div v-if="qState._evaluation.strengths?.length" class="bg-white dark:bg-gray-800 rounded-xl p-2.5 border border-green-100 dark:border-green-800">
                      <p class="text-[10px] font-semibold text-green-700 dark:text-green-400 mb-1.5">亮点</p>
                      <ul class="space-y-0.5">
                        <li v-for="s in qState._evaluation.strengths" :key="s" class="text-[11px] text-gray-600 dark:text-gray-400 flex gap-1">
                          <span class="text-green-500 dark:text-green-400 shrink-0">+</span>{{ s }}
                        </li>
                      </ul>
                    </div>
                    <div v-if="qState._evaluation.weaknesses?.length" class="bg-white dark:bg-gray-800 rounded-xl p-2.5 border border-red-100 dark:border-red-800">
                      <p class="text-[10px] font-semibold text-red-700 dark:text-red-400 mb-1.5">不足</p>
                      <ul class="space-y-0.5">
                        <li v-for="w in qState._evaluation.weaknesses" :key="w" class="text-[11px] text-gray-600 dark:text-gray-400 flex gap-1">
                          <span class="text-red-500 dark:text-red-400 shrink-0">-</span>{{ w }}
                        </li>
                      </ul>
                    </div>
                  </div>

                  <!-- Suggestions -->
                  <div v-if="qState._evaluation.suggestions" class="bg-white dark:bg-gray-800 rounded-xl p-3 border border-gray-100 dark:border-gray-700">
                    <p class="text-[10px] font-semibold text-gray-700 dark:text-gray-300 mb-1">改进建议</p>
                    <div class="text-xs text-gray-600 dark:text-gray-400 leading-relaxed answer-content" v-html="renderMarkdown(qState._evaluation.suggestions)"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown.js'
import { generateAnswer as apiGenerateAnswer, evaluateAnswer, fetchPracticeHistory, updateRecord } from '../api/index.js'
import { sanitizeAgainstInjection } from '../utils/validate.js'
import { useToast } from '../composables/useNotification.js'

const toast = useToast()

const props = defineProps({
  visible: { type: Boolean, default: false },
  question: { type: Object, default: null }
})

const emit = defineEmits(['close', 'answer-evaluated'])

const dimLabel = { completeness: '完整性', depth: '深度', accuracy: '准确性', logic: '逻辑性' }

const leftTabs = [
  { key: 'description', label: '题目' },
  { key: 'answer', label: '参考答案' },
  { key: 'history', label: '练习记录' }
]

const leftTab = ref('description')

const qState = reactive({
  _userAnswer: '',
  _evaluation: null,
  _isEvaluating: false,
  _isLoadingAnswer: false,
  _history: null,
  _historyLoading: false,
  _isEditingAnswer: false,
  _editAnswer: '',
  _isSavingAnswer: false
})

watch(() => props.question, (q) => {
  if (q) {
    leftTab.value = 'description'
    qState._userAnswer = ''
    qState._evaluation = null
    qState._isEvaluating = false
    qState._isLoadingAnswer = false
    qState._history = null
    qState._historyLoading = false
    qState._isEditingAnswer = false
    qState._editAnswer = ''
    qState._isSavingAnswer = false
  }
})

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')
const renderMarkdown = (text) => renderSafeMarkdown(text)

const scoreColor = (score) => {
  if (score >= 80) return 'bg-green-500 dark:bg-green-500'
  if (score >= 60) return 'bg-yellow-500 dark:bg-yellow-500'
  return 'bg-red-500 dark:bg-red-500'
}

const scoreTextColor = (score) => {
  if (score >= 80) return 'text-green-700 dark:text-green-400'
  if (score >= 60) return 'text-yellow-700 dark:text-yellow-400'
  return 'text-red-700 dark:text-red-400'
}

const handleGenerate = async () => {
  const q = props.question
  qState._isLoadingAnswer = true
  try {
    const data = await apiGenerateAnswer(q.id)
    q.ai_answer = data.answer
    toast.success('答案已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    qState._isLoadingAnswer = false
  }
}

const handleSaveAnswer = async () => {
  const q = props.question
  try {
    sanitizeAgainstInjection(qState._editAnswer, '参考答案')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  qState._isSavingAnswer = true
  try {
    await updateRecord({ table: 'question_bank', id: q.id, field: 'ai_answer', value: qState._editAnswer })
    q.ai_answer = qState._editAnswer
    qState._isEditingAnswer = false
    toast.success('答案已保存')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  } finally {
    qState._isSavingAnswer = false
  }
}

const handleEvaluate = async () => {
  const q = props.question
  if (!qState._userAnswer.trim()) {
    toast.warning('请先输入你的答案')
    return
  }
  if (!q.ai_answer) {
    toast.warning('请先生成或查看 AI 参考答案')
    return
  }
  try {
    sanitizeAgainstInjection(qState._userAnswer, '你的回答')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  qState._isEvaluating = true
  qState._evaluation = null
  try {
    const data = await evaluateAnswer({
      question_id: q.id,
      question_text: q.question,
      user_answer: qState._userAnswer,
      reference_answer: q.ai_answer
    })
    qState._evaluation = data
    q.attempt_count = (q.attempt_count || 0) + 1
    qState._history = null
    // Auto-switch to history tab after evaluation
    leftTab.value = 'answer'
    toast.success('评估完成')
    emit('answer-evaluated', { questionId: q.id, score: data.overall_score })
  } catch (e) {
    toast.error(`评估失败: ${e.message}`)
  } finally {
    qState._isEvaluating = false
  }
}

// Load history when switching to history tab
watch(leftTab, async (tab) => {
  if (tab === 'history' && !qState._history && props.question) {
    qState._historyLoading = true
    try {
      qState._history = (await fetchPracticeHistory(props.question.id)).map(h => ({ ...h, _expanded: false }))
    } catch (e) {
      console.error('加载练习记录失败', e)
      qState._history = []
    } finally {
      qState._historyLoading = false
    }
  }
})
</script>
