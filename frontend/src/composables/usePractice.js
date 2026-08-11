import { generateAnswer as apiGenerateAnswer, generateRecitation as apiGenerateRecitation, streamJobProgress, evaluateAnswer, fetchPracticeHistory, updateRecord, saveUserAnswer as apiSaveUserAnswer } from '../api/index.js'
import { renderSafeMarkdown } from '../utils/markdown.js'
import { sanitizeAgainstInjection } from '../utils/validate.js'
import { useToast } from './useNotification.js'
import { useModelGuard } from './useModelGuard.js'

export const dimLabel = { completeness: '完整性', depth: '深度', accuracy: '准确性', logic: '逻辑性' }

export const leftTabs = [
  { key: 'description', label: '题目' },
  { key: 'answer', label: '参考答案' },
  { key: 'history', label: '练习记录' }
]

export function isFailedAnswer(answer) {
  return answer && answer.includes('生成失败')
}

export function renderMarkdown(text) {
  return renderSafeMarkdown(text)
}

async function resolveQueuedJob(data) {
  if (!data?.job_id) return data
  const finalEvent = await streamJobProgress(data.job_id, (event) => {
    if (event.type === 'error') throw new Error(event.message || '任务失败')
  })
  return { ...data, ...(finalEvent?.result || {}) }
}

export function scoreColor(score) {
  if (score >= 80) return 'bg-green-500 dark:bg-green-500'
  if (score >= 60) return 'bg-yellow-500 dark:bg-yellow-500'
  return 'bg-red-500 dark:bg-red-500'
}

export function scoreTextColor(score) {
  if (score >= 80) return 'text-green-700 dark:text-green-400'
  if (score >= 60) return 'text-yellow-700 dark:text-yellow-400'
  return 'text-red-700 dark:text-red-400'
}

export function resetQState(qState) {
  qState._userAnswer = ''
  qState._evaluation = null
  qState._isEvaluating = false
  qState._isLoadingAnswer = false
  qState._history = null
  qState._historyLoading = false
  qState._isEditingAnswer = false
  qState._editAnswer = ''
  qState._isSavingAnswer = false
  qState._showAnswerSources = false
  qState._recitation = ''
  qState._recitationSources = []
  qState._showRecitationSources = false
  qState._isGeneratingRecitation = false
  qState._isEditingRecitation = false
  qState._editRecitation = ''
  qState._isSavingRecitation = false
}

export async function generateAnswerForQuestion(question, qState) {
  const toast = useToast()
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: 'AI 生成答案' })) return
  qState._isLoadingAnswer = true
  try {
    const data = await resolveQueuedJob(apiGenerateAnswer(question.id, { force: true }))
    question.ai_answer = data.answer
    if (Array.isArray(data.search_sources)) question.answer_sources = data.search_sources
    toast.success('答案已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    qState._isLoadingAnswer = false
  }
}

export async function saveAnswerForQuestion(question, qState) {
  const toast = useToast()
  try {
    sanitizeAgainstInjection(qState._editAnswer, '参考答案')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  qState._isSavingAnswer = true
  try {
    await updateRecord({ table: 'question_bank', id: question.id, field: 'ai_answer', value: qState._editAnswer })
    question.ai_answer = qState._editAnswer
    qState._isEditingAnswer = false
    toast.success('答案已保存')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  } finally {
    qState._isSavingAnswer = false
  }
}

export async function generateRecitationForQuestion(question, qState) {
  const toast = useToast()
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: '生成背诵稿' })) return
  qState._isGeneratingRecitation = true
  try {
    const data = await resolveQueuedJob(await apiGenerateRecitation(question.id))
    qState._recitation = data.answer
    qState._recitationSources = data.search_sources || []
    qState._isEditingRecitation = false
    toast.success('背诵稿已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    qState._isGeneratingRecitation = false
  }
}

export async function saveRecitationForQuestion(question, qState) {
  const toast = useToast()
  try {
    sanitizeAgainstInjection(qState._editRecitation, '背诵稿')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  qState._isSavingRecitation = true
  try {
    await apiSaveUserAnswer(question.id, qState._editRecitation)
    qState._recitation = qState._editRecitation
    qState._isEditingRecitation = false
    toast.success('背诵稿已保存')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  } finally {
    qState._isSavingRecitation = false
  }
}

export async function evaluateAnswerForQuestion(question, qState) {
  const toast = useToast()
  if (!qState._userAnswer.trim()) {
    toast.warning('请先输入你的答案')
    return null
  }
  if (!question.ai_answer) {
    toast.warning('请先生成或查看 AI 参考答案')
    return null
  }
  try {
    sanitizeAgainstInjection(qState._userAnswer, '你的回答')
  } catch (e) {
    toast.warning(e.message)
    return null
  }
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: '自测评估' })) return null
  qState._isEvaluating = true
  qState._evaluation = null
  try {
    const data = await evaluateAnswer({
      question_id: question.id,
      question_text: question.question,
      user_answer: qState._userAnswer,
      reference_answer: question.ai_answer
    })
    qState._evaluation = data
    question.attempt_count = (question.attempt_count || 0) + 1
    qState._history = null
    toast.success('评估完成')
    return data
  } catch (e) {
    toast.error(`评估失败: ${e.message}`)
    return null
  } finally {
    qState._isEvaluating = false
  }
}

export async function loadHistory(questionId, qState) {
  qState._historyLoading = true
  try {
    qState._history = (await fetchPracticeHistory(questionId)).map(h => ({ ...h, _expanded: false }))
  } catch (e) {
    console.warn('加载练习记录失败', e)
    qState._history = []
    qState._historyError = true
  } finally {
    qState._historyLoading = false
  }
}
