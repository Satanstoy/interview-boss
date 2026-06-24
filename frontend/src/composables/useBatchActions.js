import { computed } from 'vue'
import * as api from '@/api/index.js'
import { getFriendlyError } from '@/services/http.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'

export function useBatchActions({ currentUser, jdSelection, interviewSelection, masterSelection, fetchTableData, fetchAnalytics }) {
  const toast = useToast()
  const { confirm: showConfirm } = useConfirm()

  const jdBatchActions = computed(() => {
    if (!currentUser.value?.is_admin) return []
    return [
    {
      key: 'batch-delete',
      label: '批量删除',
      color: 'red',
      handler: async (onProgress) => {
        const ids = [...jdSelection.selectedIds.value]
        if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`, { title: '确认删除', variant: 'danger' })) return
        onProgress(0, ids.length)
        try {
          const result = await api.batchDeleteData('jd', ids)
          onProgress(result.deleted, ids.length)
          toast.success(`已成功删除 ${result.deleted} 条记录！`)
          jdSelection.clearSelection()
          fetchTableData()
          fetchAnalytics()
        } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      }
    }
    ]
  })

  const interviewBatchActions = computed(() => {
    if (!currentUser.value?.is_admin) return []
    return [
    {
      key: 'batch-reprocess',
      label: '批量重新分析',
      color: 'blue',
      handler: async (onProgress) => {
        const ids = [...interviewSelection.selectedIds.value]
        if (!await showConfirm(`确定要重新分析选中的 ${ids.length} 条面经？`)) return
        onProgress(0, ids.length)
        let ok = 0
        const failed = []
        for (let i = 0; i < ids.length; i++) {
          try {
            await api.reprocessInterviewSSE(ids[i], (evt) => {
              if (evt.type === 'error') throw new Error(evt.message)
            })
            ok++
          } catch (e) {
            try {
              await api.reprocessInterviewSSE(ids[i], (evt) => {
                if (evt.type === 'error') throw new Error(evt.message)
              })
              ok++
            } catch (e2) {
              failed.push({ id: ids[i], error: getFriendlyError(e2) })
            }
          }
          onProgress(i + 1, ids.length)
        }
        if (failed.length === 0) {
          toast.success(`全部 ${ok} 条面经分析完成！`)
        } else {
          toast.error(`完成 ${ok}/${ids.length} 条，${failed.length} 条失败（已重试一次）`)
          console.warn('批量分析失败详情:', failed)
          const failList = failed.map(f => `ID ${f.id}: ${f.error}`).join('\n')
          await showConfirm(`${failed.length} 条面经分析失败（已重试一次）：\n\n${failList}\n\n请检查这些问题后重试。`, { title: '分析失败详情', variant: 'danger' })
        }
        interviewSelection.clearSelection()
        fetchTableData()
        fetchAnalytics()
      }
    },
    {
      key: 'batch-delete',
      label: '批量删除',
      color: 'red',
      handler: async (onProgress) => {
        const ids = [...interviewSelection.selectedIds.value]
        if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`, { title: '确认删除', variant: 'danger' })) return
        onProgress(0, ids.length)
        try {
          const result = await api.batchDeleteData('interview', ids)
          onProgress(result.deleted, ids.length)
          toast.success(`已成功删除 ${result.deleted} 条记录！`)
          interviewSelection.clearSelection()
          fetchTableData()
          fetchAnalytics()
        } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      }
    }
    ]
  })

  const masterBatchActions = computed(() => [
    {
      key: 'batch-generate',
      label: '批量生成答案',
      color: 'blue',
      handler: async (onProgress) => {
        const ids = [...masterSelection.selectedIds.value]
        if (!await showConfirm(`确定要为选中的 ${ids.length} 道题目生成答案？`)) return
        try {
          const result = await api.batchGenerateAnswers(ids, (event) => {
            if (event.type === 'init') {
              if (event.total === 0) {
                toast.info(`所有 ${event.skipped} 道题目已有答案，无需生成`)
              } else {
                onProgress(0, event.total)
              }
            } else if (event.type === 'progress') {
              onProgress(event.current, event.total)
            }
          })
          if (result) {
            const parts = []
            if (result.generated) parts.push(`成功 ${result.generated} 题`)
            if (result.failed) parts.push(`失败 ${result.failed} 题`)
            if (result.skipped) parts.push(`跳过 ${result.skipped} 题`)
            toast.success(parts.length ? `生成完成：${parts.join('，')}` : '生成完成')
          }
          fetchTableData()
        } catch (e) { toast.error('批量生成答案失败：' + getFriendlyError(e)) }
      }
    },
    {
      key: 'batch-delete',
      label: '批量删除',
      color: 'red',
      handler: async (onProgress) => {
        const ids = [...masterSelection.selectedIds.value]
        if (!await showConfirm(`确定要删除选中的 ${ids.length} 道题目？`, { title: '确认删除', variant: 'danger' })) return
        onProgress(0, ids.length)
        try {
          const result = await api.batchDeleteMasterBank(ids)
          onProgress(result.deleted, ids.length)
          toast.success(`已成功删除 ${result.deleted} 道题目！`)
          masterSelection.clearSelection()
          fetchTableData()
        } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      }
    }
  ])

  return { jdBatchActions, interviewBatchActions, masterBatchActions }
}
