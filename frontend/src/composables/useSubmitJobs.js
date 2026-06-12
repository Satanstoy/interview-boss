/**
 * 全局上传任务管理 Composable
 *
 * 职责：
 * - 管理所有活跃的 submit import 任务
 * - 通过 SSE 订阅每个任务的进度
 * - localStorage 持久化活跃 job ids
 * - 页面加载时恢复未完成任务
 * - 任务完成/失败时触发回调
 */
import { ref, readonly } from 'vue'
import { createSubmitJob, fetchActiveSubmitJobs } from '@/services/dataApi.js'
import { getSSE } from '@/services/http.js'

const STORAGE_KEY = 'interviewboss-submit-jobs'

// ── 全局状态（跨组件共享） ──
const activeJobs = ref([])
const _sseControllers = new Map()  // jobId → AbortController
let _onJobDone = null

/**
 * 注册任务完成回调（由 App.vue 设置）
 */
export function setOnJobDone(fn) {
  _onJobDone = fn
}

/**
 * 从 localStorage 读取持久化的 job ids
 */
function _loadStoredJobIds() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch { return [] }
}

/**
 * 将活跃 job ids 写入 localStorage
 */
function _persistJobIds() {
  const ids = activeJobs.value.map(j => j.id)
  if (ids.length > 0) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids))
  } else {
    localStorage.removeItem(STORAGE_KEY)
  }
}

/**
 * 查找或创建 job 对象
 */
function _ensureJob(jobId) {
  let job = activeJobs.value.find(j => j.id === jobId)
  if (!job) {
    job = {
      id: jobId,
      status: 'pending',
      current: 0,
      total: 7,
      percent: 0,
      phase: 'queued',
      message: '等待中...',
      result: null,
      error: null,
      startedAt: Date.now(),
      updatedAt: Date.now(),
    }
    activeJobs.value.push(job)
  }
  return job
}

/**
 * 更新 job 状态
 */
function _updateJob(jobId, updates) {
  const idx = activeJobs.value.findIndex(j => j.id === jobId)
  if (idx === -1) return
  const job = activeJobs.value[idx]
  Object.assign(job, updates, { updatedAt: Date.now() })
  // 计算百分比
  if (job.total > 0) {
    job.percent = Math.round((job.current / job.total) * 100)
  }
  // 触发响应式更新
  activeJobs.value = [...activeJobs.value]
}

/**
 * 移除 job
 */
function _removeJob(jobId) {
  // 取消 SSE 连接
  const ctrl = _sseControllers.get(jobId)
  if (ctrl) {
    try { ctrl.abort() } catch {}
    _sseControllers.delete(jobId)
  }
  activeJobs.value = activeJobs.value.filter(j => j.id !== jobId)
  _persistJobIds()
}

/**
 * 为一个 job 订阅 SSE 进度
 */
function _subscribeJobSSE(jobId) {
  // 避免重复订阅
  if (_sseControllers.has(jobId)) return

  const job = _ensureJob(jobId)
  const url = `/api/jobs/${jobId}/stream`

  // 创建 AbortController 并传给 getSSE，支持 removeJob() 取消
  const controller = new AbortController()
  _sseControllers.set(jobId, controller)

  getSSE(url, (event) => {
    const currentJob = activeJobs.value.find(j => j.id === jobId)
    if (!currentJob) return

    if (event.type === 'progress') {
      _updateJob(jobId, {
        status: event.status || 'running',
        current: event.current || 0,
        total: event.total || 7,
        message: event.message || '',
      })
    } else if (event.type === 'done') {
      _updateJob(jobId, {
        status: 'completed',
        current: currentJob.total,
        percent: 100,
        message: '处理完成',
        result: event.result || event.message || null,
      })
      _sseControllers.delete(jobId)
      // completed 后立即从 localStorage 移除，UI 保留 5 秒
      _persistJobIds()
      // 触发完成回调
      if (_onJobDone) {
        try { _onJobDone(jobId, event.result || event.message) } catch {}
      }
      // 5 秒后自动移除 UI
      setTimeout(() => _removeJob(jobId), 5000)
    } else if (event.type === 'error') {
      _updateJob(jobId, {
        status: 'failed',
        message: event.message || '处理失败',
        error: event.message || '未知错误',
      })
      _sseControllers.delete(jobId)
      // failed 也不持久化到 localStorage
      _persistJobIds()
    }
  }, { signal: controller.signal }).catch((err) => {
    // 被主动 abort 的不处理
    if (err.name === 'AbortError') return
    // SSE 断开不代表任务失败 — 前端允许重连
    console.warn(`[useSubmitJobs] SSE 断开 job=${jobId}:`, err.message)
    _sseControllers.delete(jobId)
    // 如果任务还在 pending/running，3 秒后尝试重连
    const currentJob = activeJobs.value.find(j => j.id === jobId)
    if (currentJob && (currentJob.status === 'running' || currentJob.status === 'pending')) {
      setTimeout(() => _subscribeJobSSE(jobId), 3000)
    }
  })
}

/**
 * 启动新的上传任务
 * @param {FormData} formData - 上传表单
 * @returns {Promise<{job_id: number}>}
 */
export async function startSubmitJob(formData) {
  const result = await createSubmitJob(formData)
  const jobId = result.job_id
  const job = _ensureJob(jobId)
  job.status = 'pending'
  job.message = '任务已创建，等待处理...'
  _persistJobIds()
  _subscribeJobSSE(jobId)
  return result
}

/**
 * 手动关联一个已存在的 job（用于页面恢复时）
 */
export function attachJob(jobId) {
  _ensureJob(jobId)
  _persistJobIds()
  _subscribeJobSSE(jobId)
}

/**
 * 恢复未完成的 jobs（页面加载时调用）
 * 1. 从 localStorage 读取 job ids
 * 2. 调服务端查询活跃任务
 * 3. 合并去重
 * 4. 对每个未完成任务重新订阅 SSE
 */
export async function restoreActiveJobs() {
  const storedIds = _loadStoredJobIds()

  let serverJobs = []
  try {
    serverJobs = await fetchActiveSubmitJobs()
  } catch (err) {
    console.warn('[useSubmitJobs] 获取活跃任务失败:', err.message)
  }

  // 服务端只返回 pending/running 的 jobs
  const serverJobIds = new Set(serverJobs.map(j => j.id))

  // 本地存储但服务端已完成/失败的 id → 清理掉
  const staleIds = storedIds.filter(id => !serverJobIds.has(id))
  if (staleIds.length > 0) {
    console.log(`[useSubmitJobs] 清理 ${staleIds.length} 个已完成/已消失的任务`)
  }

  // 合并：服务端任务 + 本地存储中仍活跃的任务
  const allJobIds = new Set()
  for (const sj of serverJobs) {
    allJobIds.add(sj.id)
    const job = _ensureJob(sj.id)
    job.status = sj.status
    job.current = sj.progress_current || 0
    job.total = sj.progress_total || 7
    job.message = sj.progress_message || ''
    if (job.total > 0) {
      job.percent = Math.round((job.current / job.total) * 100)
    }
  }
  for (const id of storedIds) {
    if (serverJobIds.has(id)) {
      allJobIds.add(id)
    }
    // stale ids 不加入 allJobIds，自然被清除
  }

  // 清理本地 activeJobs 中不在 allJobIds 的条目
  activeJobs.value = activeJobs.value.filter(j => allJobIds.has(j.id))
  _persistJobIds()

  // 为所有活跃任务订阅 SSE
  for (const jobId of allJobIds) {
    const job = activeJobs.value.find(j => j.id === jobId)
    if (job && job.status !== 'completed' && job.status !== 'failed') {
      _subscribeJobSSE(jobId)
    }
  }
}

/**
 * 手动关闭/移除一个 job
 */
export function removeJob(jobId) {
  _removeJob(jobId)
}

/**
 * Composable 入口
 */
export function useSubmitJobs() {
  return {
    activeJobs: readonly(activeJobs),
    startSubmitJob,
    attachJob,
    restoreActiveJobs,
    removeJob,
    setOnJobDone,
  }
}
