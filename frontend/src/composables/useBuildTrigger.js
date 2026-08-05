/**
 * useBuildTrigger — 题库重建触发 + 进度追踪
 *
 * 职责：公共/个人题库重建的确认、SSE 进度、状态管理
 * 不负责：数据获取（通过回调触发刷新）
 */
import { ref, computed } from 'vue'
import { getFriendlyError } from '@/services/http.js'
import * as api from '@/api/index.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { useModelGuard } from '@/composables/useModelGuard.js'

export function useBuildTrigger({ onRebuildDone } = {}) {
  const toast = useToast()
  const { confirm: showConfirm } = useConfirm()
  const { ensureModelReady } = useModelGuard()

  const isBuilding = ref(false)
  const buildProgress = ref({ step: '', current: 0, total: 0, message: '' })
  const buildStepsDef = [
    { key: 'tag', label: 'LLM 标注' },
    { key: 'cluster', label: '聚类去重' },
    { key: 'merge', label: '统一问题' },
    { key: 'save', label: '写入题库' },
  ]
  const buildStepList = computed(() => {
    const curIdx = buildStepsDef.findIndex(s => s.key === buildProgress.value.step)
    return buildStepsDef.map((s, i) => ({
      ...s,
      active: i === curIdx,
      done: curIdx >= 0 && i < curIdx,
    }))
  })

  const triggerBuildMasterBank = async () => {
    try {
      const status = await api.getAnalysisStatus()
      if (status.unanalyzed_count > 0) {
        const hasContent = status.unanalyzed.filter(u => u.has_content)
        const noContent = status.unanalyzed.filter(u => !u.has_content)
        let warnMsg = `当前有 ${status.unanalyzed_count} 条面经尚未分析：`
        if (hasContent.length > 0) {
          warnMsg += `\n\n有内容但未分析（${hasContent.length} 条）：`
          warnMsg += hasContent.slice(0, 5).map(u => `\n  · ${u.company} - ${u.round}`).join('')
          if (hasContent.length > 5) warnMsg += `\n  ...等共 ${hasContent.length} 条`
        }
        if (noContent.length > 0) { warnMsg += `\n\n无题目内容（${noContent.length} 条），将被跳过` }
        warnMsg += '\n\n未分析的面经不会被纳入题库。是否继续重建？'
        if (!await showConfirm(warnMsg, { title: '存在未分析的面经', variant: 'warning' })) return
      }
    } catch (e) { console.warn('检查分析状态失败，继续重建:', e) }

    if (!await showConfirm('将基于现有分类重新聚类（不会重新打标），确定继续？', { title: '重新聚类', variant: 'danger' })) return
    if (!await ensureModelReady({ action: '题库重建' })) return
    isBuilding.value = true
    buildProgress.value = { step: '', current: 0, total: 0, message: '提交重建任务...' }
    try {
      const res = await api.buildMasterBank()
      const jobId = res?.job_id
      if (!jobId) throw new Error('未获取到任务 ID')
      buildProgress.value = { step: '', current: 0, total: 0, message: '连接进度流...' }
      const result = await api.streamJobProgress(jobId, (event) => {
        if (event.type === 'progress') {
          buildProgress.value = { step: event.step || '', current: event.current || 0, total: event.total || 0, message: event.message || '' }
        } else if (event.type === 'error') { throw new Error(event.message) }
      })
      toast.success(result?.message || '重建完成')
      onRebuildDone?.()
    } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
    finally { isBuilding.value = false; buildProgress.value = { step: '', current: 0, total: 0, message: '' } }
  }

  const triggerBuildPersonalBank = async () => {
    if (!await showConfirm('将把你的个人题目与公共题库进行聚类合并，匹配到的题目会并入公共题库，确定继续？', { title: '重建个人题库' })) return
    if (!await ensureModelReady({ action: '个人题库重建' })) return
    isBuilding.value = true
    buildProgress.value = { step: '', current: 0, total: 0, message: '' }
    try {
      const result = await api.buildPersonalBankSSE((event) => {
        if (event.type === 'init') { buildProgress.value = { step: 'match', current: 0, total: event.total, message: event.message } }
        else if (event.type === 'progress') { buildProgress.value = { step: event.step, current: event.current, total: event.total, message: event.message } }
        else if (event.type === 'error') { throw new Error(event.message) }
      })
      toast.success(`个人题库重建完成，合并 ${result?.merged || 0} 题，保留 ${result?.kept || 0} 题`)
      onRebuildDone?.()
    } catch (e) { toast.error('重建个人题库失败：' + getFriendlyError(e)) }
    finally { isBuilding.value = false; buildProgress.value = { step: '', current: 0, total: 0, message: '' } }
  }

  return {
    isBuilding, buildProgress, buildStepList,
    triggerBuildMasterBank, triggerBuildPersonalBank,
  }
}
