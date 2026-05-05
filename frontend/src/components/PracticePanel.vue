<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible && question" class="fixed inset-0 z-[100] flex items-start justify-center pt-[5vh] px-4">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="emit('close')"></div>

        <!-- Modal -->
        <div class="relative bg-white rounded-3xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-slide-up">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0 bg-gradient-to-r from-blue-50/50 to-indigo-50/30">
            <div class="flex items-center gap-3 min-w-0">
              <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shrink-0">
                <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
              </div>
              <div class="min-w-0">
                <h2 class="text-base font-bold text-gray-800 truncate">{{ question.question }}</h2>
                <div class="flex gap-1.5 mt-1 flex-wrap">
                  <span class="badge bg-blue-50 text-blue-700 border border-blue-100 text-[10px]">{{ question.cat1 || '未分类' }}</span>
                  <span v-for="tag in (question.tags ? question.tags.split(',').slice(0, 3) : [])" :key="tag" class="badge bg-gray-100 text-gray-500 border border-gray-200/80 text-[10px]">{{ tag }}</span>
                  <span class="badge text-[10px]"
                    :class="String(question.difficulty).includes('L3') ? 'bg-red-50 text-red-600 border border-red-100' : String(question.difficulty).includes('L2') ? 'bg-amber-50 text-amber-600 border border-amber-100' : 'bg-emerald-50 text-emerald-600 border border-emerald-100'">
                    {{ question.difficulty || '-' }}
                  </span>
                  <span v-if="question.attempt_count" class="badge bg-gray-50 text-gray-500 border border-gray-200 text-[10px]">已练 {{ question.attempt_count }} 次</span>
                </div>
              </div>
            </div>
            <button @click="emit('close')" class="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition shrink-0">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto custom-scrollbar">
            <div class="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-gray-100">
              <!-- Left: Reference Answer -->
              <div class="p-5 space-y-3">
                <h3 class="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                  AI 参考答案
                </h3>
                <div v-if="qState._isEditingAnswer">
                  <textarea v-model="qState._editAnswer" rows="12"
                    class="w-full border border-blue-300 rounded-xl p-3 text-sm leading-relaxed focus:ring-blue-500 focus:border-blue-500 resize-y font-mono bg-gray-50"></textarea>
                  <div class="flex gap-2 justify-end mt-2">
                    <button @click="qState._isEditingAnswer = false" class="px-3 py-1.5 text-xs text-gray-600 border border-gray-300 rounded-lg hover:bg-gray-100 transition">取消</button>
                    <button @click="handleSaveAnswer" :disabled="qState._isSavingAnswer" class="px-3 py-1.5 text-xs text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition disabled:opacity-50">
                      {{ qState._isSavingAnswer ? '保存中...' : '保存' }}
                    </button>
                  </div>
                </div>
                <div v-else-if="question.ai_answer" class="relative">
                  <button @click="qState._isEditingAnswer = true; qState._editAnswer = question.ai_answer"
                    class="absolute top-0 right-0 text-[10px] text-blue-600 hover:text-blue-800 bg-blue-50 hover:bg-blue-100 px-2 py-0.5 rounded border border-blue-200">编辑</button>
                  <div class="text-sm text-gray-700 leading-relaxed answer-content" v-html="renderMarkdown(question.ai_answer)"></div>
                </div>
                <div v-else class="text-center py-8">
                  <p class="text-gray-400 mb-3 text-sm">暂无参考答案</p>
                  <button @click="handleGenerate" :disabled="qState._isLoadingAnswer"
                    class="bg-blue-100 text-blue-700 font-bold px-5 py-2 rounded-lg hover:bg-blue-200 transition text-sm disabled:opacity-50">
                    {{ qState._isLoadingAnswer ? '生成中...' : 'AI 生成答案' }}
                  </button>
                </div>
              </div>

              <!-- Right: User Answer -->
              <div class="p-5 space-y-3">
                <h3 class="text-xs font-bold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                  我的回答
                </h3>
                <textarea
                  v-model="qState._userAnswer"
                  rows="10"
                  placeholder="在此输入你的回答，完成后点击「提交评估」获取 AI 评分..."
                  class="w-full border border-gray-200 rounded-xl p-3.5 text-sm leading-relaxed focus:ring-2 focus:ring-blue-200 focus:border-blue-400 resize-y transition-all duration-200 bg-gray-50 focus:bg-white"
                ></textarea>
                <div class="flex gap-2 items-center">
                  <button
                    @click="handleEvaluate"
                    :disabled="qState._isEvaluating || !qState._userAnswer.trim()"
                    class="flex items-center gap-2 bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-medium px-5 py-2.5 rounded-xl hover:from-blue-700 hover:to-indigo-700 transition-all duration-200 text-sm disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <svg v-if="qState._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    {{ qState._isEvaluating ? '评估中...' : '提交评估' }}
                  </button>
                  <button v-if="qState._userAnswer" @click="qState._userAnswer = ''; qState._evaluation = null"
                    class="text-sm text-gray-500 px-3 py-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition">清空</button>
                </div>
              </div>
            </div>

            <!-- Evaluation Result -->
            <div v-if="qState._evaluation" class="px-6 py-5 border-t border-blue-100 bg-gradient-to-br from-blue-50/50 to-indigo-50/30">
              <h4 class="text-sm font-bold text-gray-700 mb-4">评估结果</h4>

              <!-- Overall score -->
              <div class="flex items-center gap-4 mb-5">
                <span class="text-4xl font-extrabold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span>
                <div class="flex-1">
                  <div class="bg-gray-200 rounded-full h-3.5 overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-700" :class="scoreColor(qState._evaluation.overall_score)" :style="{ width: qState._evaluation.overall_score + '%' }"></div>
                  </div>
                  <p class="text-xs text-gray-400 mt-1">加权总分（准确性 35%、完整性 30%、深度 20%、逻辑性 15%）</p>
                </div>
              </div>

              <!-- Dimension scores -->
              <div class="grid grid-cols-2 gap-3 mb-5">
                <div v-for="(val, key) in qState._evaluation.dimensions" :key="key" class="bg-white rounded-xl p-3 border border-gray-100">
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-xs font-semibold text-gray-600">{{ dimLabel[key] || key }}</span>
                    <span class="text-sm font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                  </div>
                  <div class="bg-gray-100 rounded-full h-2 overflow-hidden mb-1.5">
                    <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                  </div>
                  <p v-if="val.comment" class="text-xs text-gray-400 leading-snug">{{ val.comment }}</p>
                </div>
              </div>

              <!-- Strengths & Weaknesses -->
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                <div v-if="qState._evaluation.strengths?.length" class="bg-white rounded-xl p-3 border border-green-100">
                  <p class="text-xs font-semibold text-green-700 mb-2">亮点</p>
                  <ul class="space-y-1">
                    <li v-for="s in qState._evaluation.strengths" :key="s" class="text-xs text-gray-600 flex gap-1.5">
                      <span class="text-green-500 shrink-0">+</span>{{ s }}
                    </li>
                  </ul>
                </div>
                <div v-if="qState._evaluation.weaknesses?.length" class="bg-white rounded-xl p-3 border border-red-100">
                  <p class="text-xs font-semibold text-red-700 mb-2">不足</p>
                  <ul class="space-y-1">
                    <li v-for="w in qState._evaluation.weaknesses" :key="w" class="text-xs text-gray-600 flex gap-1.5">
                      <span class="text-red-500 shrink-0">-</span>{{ w }}
                    </li>
                  </ul>
                </div>
              </div>

              <!-- Suggestions -->
              <div v-if="qState._evaluation.suggestions" class="bg-white rounded-xl p-3 border border-gray-100">
                <p class="text-xs font-semibold text-gray-700 mb-1.5">改进建议</p>
                <div class="text-sm text-gray-600 leading-relaxed answer-content" v-html="renderMarkdown(qState._evaluation.suggestions)"></div>
              </div>
            </div>

            <!-- Practice History -->
            <div v-if="question.attempt_count > 0" class="border-t border-gray-100">
              <button @click="toggleHistory"
                class="w-full py-3 text-xs font-medium text-gray-500 hover:bg-gray-50 transition flex items-center justify-center gap-2">
                <svg class="w-3.5 h-3.5 transition-transform" :class="{ 'rotate-90': qState._showHistory }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                {{ qState._showHistory ? '收起练习记录' : `查看练习记录 (${question.attempt_count}次)` }}
              </button>
              <div v-if="qState._showHistory" class="px-6 py-4 bg-gray-50 border-t border-gray-100 space-y-2 max-h-64 overflow-y-auto">
                <div v-if="qState._historyLoading" class="text-center py-3 text-xs text-gray-400">加载中...</div>
                <div v-else-if="qState._history && qState._history.length > 0">
                  <div v-for="(h, hIdx) in qState._history" :key="h.id" class="border-b border-gray-100 last:border-b-0">
                    <div class="flex items-center gap-3 py-2 cursor-pointer hover:bg-gray-100/50 px-1 rounded" @click="h._expanded = !h._expanded">
                      <span class="text-xs text-gray-400 w-5 text-right shrink-0">#{{ qState._history.length - hIdx }}</span>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2 mb-1">
                          <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                          <span class="text-xs text-gray-300">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                        </div>
                        <p v-if="!h._expanded" class="text-xs text-gray-500 truncate">{{ h.user_answer?.slice(0, 80) }}{{ h.user_answer?.length > 80 ? '...' : '' }}</p>
                      </div>
                      <div class="w-16 shrink-0">
                        <div class="bg-gray-200 rounded-full h-1.5 overflow-hidden">
                          <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                        </div>
                      </div>
                      <svg class="w-3.5 h-3.5 text-gray-400 transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                    </div>
                    <div v-if="h._expanded" class="pl-6 pr-2 pb-3 space-y-2">
                      <div>
                        <p class="text-xs font-semibold text-gray-500 mb-1">我的回答</p>
                        <p class="text-xs text-gray-600 bg-white rounded p-2 border border-gray-100 whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                      </div>
                      <div v-if="h.evaluation_result">
                        <div class="flex items-center gap-3 mb-1 flex-wrap">
                          <span class="text-xs font-semibold text-gray-500">维度评分：</span>
                          <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-xs text-gray-500">
                            {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                          </span>
                        </div>
                        <div v-if="h.evaluation_result.suggestions" class="text-xs text-gray-500">
                          <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 200) }}{{ h.evaluation_result.suggestions?.length > 200 ? '...' : '' }}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-else class="text-center py-3 text-xs text-gray-400">暂无练习记录</div>
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

// Per-question reactive state, reset when question changes
const qState = reactive({
  _userAnswer: '',
  _evaluation: null,
  _isEvaluating: false,
  _isLoadingAnswer: false,
  _showHistory: false,
  _history: null,
  _historyLoading: false,
  _isEditingAnswer: false,
  _editAnswer: '',
  _isSavingAnswer: false
})

// Reset state when question changes
watch(() => props.question, (q) => {
  if (q) {
    qState._userAnswer = ''
    qState._evaluation = null
    qState._isEvaluating = false
    qState._isLoadingAnswer = false
    qState._showHistory = false
    qState._history = null
    qState._historyLoading = false
    qState._isEditingAnswer = false
    qState._editAnswer = ''
    qState._isSavingAnswer = false
  }
})

const renderMarkdown = (text) => renderSafeMarkdown(text)

const scoreColor = (score) => {
  if (score >= 80) return 'bg-green-500'
  if (score >= 60) return 'bg-yellow-500'
  return 'bg-red-500'
}

const scoreTextColor = (score) => {
  if (score >= 80) return 'text-green-700'
  if (score >= 60) return 'text-yellow-700'
  return 'text-red-700'
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
    toast.success('评估完成')
    emit('answer-evaluated', { questionId: q.id, score: data.overall_score })
  } catch (e) {
    toast.error(`评估失败: ${e.message}`)
  } finally {
    qState._isEvaluating = false
  }
}

const toggleHistory = async () => {
  qState._showHistory = !qState._showHistory
  if (qState._showHistory && !qState._history) {
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
}
</script>
