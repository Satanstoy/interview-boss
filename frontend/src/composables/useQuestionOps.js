import { ref, computed } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { useModelGuard } from '@/composables/useModelGuard.js'
import { runWithSearchFallback } from '@/composables/useSearchFallback.js'

export function useQuestionOps(masterBank, currentUser, fetchTableData, fetchAnalytics) {
  const toast = useToast()
  const { confirm: showConfirm } = useConfirm()
  const { ensureModelReady } = useModelGuard()

  const resolveQueuedJob = async (data) => {
    if (!data?.job_id) return data
    const finalEvent = await api.streamJobProgress(data.job_id, (event) => {
      if (event.type === 'error') throw new Error(event.message || '任务失败')
    })
    return { ...data, ...(finalEvent?.result || {}) }
  }

  const reprocessingIds = ref({})
  const reprocessProgress = ref({})
  const deletingIds = ref(new Set())

  const activeReprocessing = computed(() => {
    const active = {}
    for (const [id, isProcessing] of Object.entries(reprocessingIds.value)) {
      if (isProcessing && reprocessProgress.value[id]) {
        active[id] = reprocessProgress.value[id]
      }
    }
    return active
  })

  const deleteDataRow = async (type, recordId) => {
    if (!await showConfirm('确定要删除该记录？', { title: '确认删除', variant: 'danger' })) return
    if (deletingIds.value.has(recordId)) return
    deletingIds.value = new Set(deletingIds.value).add(recordId)
    let refreshStarted = false
    try {
      // The backend mutation is atomic and idempotent.  Retrying a timed-out
      // DELETE only makes the following refreshes race and look like a hang.
      await api.deleteRecord(type, recordId, { noRetry: true, timeout: 30_000 })
      toast.success('删除成功')
      // Refresh in the background so a slow analytics/master-bank request
      // cannot block the delete interaction after the mutation committed.
      refreshStarted = true
      void Promise.allSettled([
        Promise.resolve().then(() => fetchTableData()),
        Promise.resolve().then(() => fetchAnalytics()),
      ]).finally(() => {
        const next = new Set(deletingIds.value)
        next.delete(recordId)
        deletingIds.value = next
      })
    } catch (err) {
      toast.error('删除失败：' + getFriendlyError(err))
    } finally {
      if (!refreshStarted) {
        const next = new Set(deletingIds.value)
        next.delete(recordId)
        deletingIds.value = next
      }
    }
  }

  const reprocessInterview = async (id) => {
    if (!await showConfirm('确定要重新解析该面经？')) return
    reprocessingIds.value[id] = true
    reprocessProgress.value[id] = { step: '', message: '准备中...' }
    try {
      await api.reprocessInterviewSSE(id, (evt) => {
        if (evt.type === 'progress' || evt.type === 'done') {
          reprocessProgress.value[id] = { step: evt.step, message: evt.message || '' }
        }
        if (evt.type === 'error') throw new Error(evt.message)
      })
      toast.success('重新解析完成')
      fetchTableData()
      fetchAnalytics()
    } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
    finally {
      reprocessingIds.value[id] = false
      reprocessProgress.value[id] = null
    }
  }

  const retagQuestion = async (question) => {
    const origTexts = new Set()
    if (question.original_questions) {
      question.original_questions.forEach(oq => {
        const text = typeof oq === 'string' ? oq : (oq.question || '')
        if (text) origTexts.add(text)
      })
    }
    const siblings = origTexts.size > 0
      ? masterBank.value.filter(q => q.id !== question.id && q.original_questions?.some(oq => {
          const text = typeof oq === 'string' ? oq : (oq.question || '')
          return origTexts.has(text)
        }))
      : []

    const totalCount = 1 + siblings.length
    const msg = siblings.length > 0
      ? `确定要重新分类该题目及其 ${siblings.length} 个聚类关联题？共 ${totalCount} 题。`
      : '确定要重新分类该题目？'
    if (!await showConfirm(msg)) return

    question._isRetagging = true
    siblings.forEach(s => { s._isRetagging = true })
    try {
      const data = await api.retagQuestion(question.id)
      const newCat1 = data.data.cat1
      const newCat2 = data.data.cat2
      const newTags = data.data.tags
      const newDiff = data.data.difficulty

      question.cat1 = newCat1
      question.cat2 = newCat2
      question.tags = newTags
      question.difficulty = newDiff

      if (siblings.length > 0) {
        await Promise.all(siblings.map(async (s) => {
          try {
            await api.retagQuestion(s.id)
            s.cat1 = newCat1
            s.cat2 = newCat2
            s.tags = newTags
            s.difficulty = newDiff
          } catch (e) { /* sibling fail non-fatal */ }
        }))
      }

      toast.success(siblings.length > 0 ? `已更新 ${totalCount} 个聚类关联题` : '分类成功')
      fetchAnalytics()
    } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
    finally {
      question._isRetagging = false
      siblings.forEach(s => { s._isRetagging = false })
    }
  }

  const saveField = async (tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey) => {
    try {
      await api.updateRecord({ table_name: tableName, record_id: recordId, update_data: { [dbColumn]: newValue } })
      rowObj[frontendKey] = newValue
      rowObj[editStateKey] = false
      toast.success('保存成功')
    } catch (err) { toast.error('保存失败：' + getFriendlyError(err)) }
  }

  const saveFieldFromEvent = ({ tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey }) => {
    saveField(tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey)
  }

  const toggleStar = async (question) => {
    try {
      const data = await api.toggleStar(question.id)
      question.is_starred = data.is_starred
    } catch (e) { toast.error('操作失败：' + getFriendlyError(e)) }
  }

  const generateAnswer = async (question) => {
    if (!await ensureModelReady({ action: 'AI 生成答案' })) return
    question._isLoadingAnswer = true
    try {
      const data = await runWithSearchFallback(
        (allowNoSearch) => resolveQueuedJob(api.generateAnswer(question.id, { force: true, allowNoSearch })),
        showConfirm,
      )
      if (!data) return
      if (currentUser.value?.is_admin) {
        question.ai_answer = data.answer
      } else {
        question.user_answer = data.answer
      }
      if (Array.isArray(data.search_sources)) question.answer_sources = data.search_sources
      toast.success('答案生成成功')
    } catch (e) { toast.error('生成失败：' + getFriendlyError(e)) }
    finally { question._isLoadingAnswer = false }
  }

  const saveUserAnswer = async ({ question, answer }) => {
    try {
      await api.saveUserAnswer(question.id, answer)
      question.user_answer = answer
      question._isEditingAnswer = false
      toast.success('保存成功')
    } catch (e) { toast.error('保存失败：' + getFriendlyError(e)) }
  }

  const deleteQuestion = async (question) => {
    const shortQ = question.question.length > 30 ? question.question.slice(0, 30) + '...' : question.question
    if (!await showConfirm(`确定要删除题目「${shortQ}」吗？此操作不可撤销。`, { title: '确认删除', variant: 'danger' })) return
    try {
      await api.deleteMasterQuestion(question.id)
      toast.success('题目已删除')
      fetchTableData()
      fetchAnalytics()
    } catch (e) { toast.error('删除失败：' + getFriendlyError(e)) }
  }

  const deleteOriginalQuestion = async ({ question, originalQuestion }) => {
    const shortQ = originalQuestion.length > 30 ? originalQuestion.slice(0, 30) + '...' : originalQuestion
    if (!await showConfirm(`确定要从聚类中删除「${shortQ}」吗？此操作不可撤销。`, { title: '删除聚类题目', variant: 'danger' })) return
    try {
      await api.deleteOriginalQuestion(question.id, originalQuestion)
      toast.success('已从聚类中删除')
      fetchTableData()
      fetchAnalytics()
    } catch (e) { toast.error('删除失败：' + getFriendlyError(e)) }
  }

  const editQuestion = async ({ question, newValue }) => {
    try {
      const data = await api.updateQuestion(question.id, { question: newValue })
      question.question = data.data.question
      question._isEditingQuestion = false
      question._editQuestion = ''
      toast.success('题目已更新')
    } catch (e) { toast.error('编辑失败：' + getFriendlyError(e)) }
  }

  const onUpdateAnswer = ({ id, ai_answer, user_answer, answer_sources }) => {
    const q = masterBank.value.find(item => item.id === id)
    if (q) {
      if (ai_answer !== undefined) q.ai_answer = ai_answer
      if (user_answer !== undefined) q.user_answer = user_answer
      if (answer_sources !== undefined) q.answer_sources = answer_sources
    }
  }

  const splitQuestion = async ({ question, originalQuestion }) => {
    const shortQ = originalQuestion.length > 30 ? originalQuestion.slice(0, 30) + '...' : originalQuestion
    if (!await showConfirm(`确定要将「${shortQ}」从当前聚类中拆出为独立题目吗？`, { title: '拆分为独立题目' })) return
    try {
      await api.splitQuestion(question.id, originalQuestion)
      toast.success('题目已拆分为独立题目')
      fetchTableData()
    } catch (e) { toast.error('拆分失败：' + getFriendlyError(e)) }
  }

  return {
    reprocessingIds,
    reprocessProgress,
    deletingIds,
    activeReprocessing,
    deleteDataRow,
    reprocessInterview,
    retagQuestion,
    saveField,
    saveFieldFromEvent,
    toggleStar,
    generateAnswer,
    saveUserAnswer,
    deleteQuestion,
    deleteOriginalQuestion,
    editQuestion,
    onUpdateAnswer,
    splitQuestion,
  }
}
