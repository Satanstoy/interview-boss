import { ref } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'

export function useMergeDialog(fetchTableData) {
  const toast = useToast()
  const { confirm: showConfirm } = useConfirm()

  const mergeDialogVisible = ref(false)
  const mergeSourceQuestionId = ref(null)
  const mergeSourceOriginalQ = ref('')
  const mergeSourceCat1 = ref('')
  const mergeSourceCat2 = ref('')
  const mergeSearchQuery = ref('')
  const mergeSearchResults = ref([])
  const mergeSearching = ref(false)

  const startMerge = ({ question, originalQuestion }) => {
    mergeSourceQuestionId.value = question.id
    mergeSourceOriginalQ.value = originalQuestion
    mergeSourceCat1.value = question.cat1 || ''
    mergeSourceCat2.value = question.cat2 || ''
    mergeSearchQuery.value = ''
    mergeSearchResults.value = []
    mergeDialogVisible.value = true
  }

  const doMergeSearch = async () => {
    mergeSearching.value = true
    try {
      const data = await api.searchMasterBank(mergeSearchQuery.value, mergeSourceQuestionId.value)
      mergeSearchResults.value = data.items || []
    } catch (e) { toast.error('搜索失败：' + getFriendlyError(e)) }
    finally { mergeSearching.value = false }
  }

  const confirmMerge = async (target) => {
    const shortQ = mergeSourceOriginalQ.value.length > 20 ? mergeSourceOriginalQ.value.slice(0, 20) + '...' : mergeSourceOriginalQ.value
    const shortT = target.question.length > 20 ? target.question.slice(0, 20) + '...' : target.question

    let targetCat1 = ''
    let targetCat2 = ''

    const srcCat = `${mergeSourceCat1.value}/${mergeSourceCat2.value}`
    const tgtCat = `${target.cat1 || '未分类'}/${target.cat2 || '未分类'}`
    if (srcCat !== tgtCat && (mergeSourceCat1.value || target.cat1)) {
      const choice = await showConfirm(
        `源类别：${srcCat}\n目标类别：${tgtCat}\n\n是否将目标聚类的类别更新为源类别？\n（取消则保留目标类别）`,
        { title: '选择类别', confirmLabel: '更新为源类别', cancelLabel: '保留目标类别' }
      )
      if (choice) {
        targetCat1 = mergeSourceCat1.value
        targetCat2 = mergeSourceCat2.value
      }
    }

    if (!await showConfirm(`确定将「${shortQ}」合并到「${shortT}」吗？`, { title: '确认合并', variant: 'danger' })) return
    try {
      await api.mergeQuestion(mergeSourceQuestionId.value, mergeSourceOriginalQ.value, target.id, targetCat1, targetCat2)
      toast.success('题目已合并到目标聚类')
      mergeDialogVisible.value = false
      fetchTableData()
    } catch (e) { toast.error('合并失败：' + getFriendlyError(e)) }
  }

  const splitAsNew = async () => {
    const shortQ = mergeSourceOriginalQ.value.length > 30 ? mergeSourceOriginalQ.value.slice(0, 30) + '...' : mergeSourceOriginalQ.value
    if (!await showConfirm(`确定要将「${shortQ}」从当前聚类中拆出为独立题目吗？`, { title: '拆分为独立题目' })) return
    try {
      await api.splitQuestion(mergeSourceQuestionId.value, mergeSourceOriginalQ.value)
      toast.success('题目已拆分为独立题目')
      mergeDialogVisible.value = false
      fetchTableData()
    } catch (e) { toast.error('拆分失败：' + getFriendlyError(e)) }
  }

  return {
    mergeDialogVisible,
    mergeSourceOriginalQ,
    mergeSearchQuery,
    mergeSearchResults,
    mergeSearching,
    startMerge,
    doMergeSearch,
    confirmMerge,
    splitAsNew,
  }
}
