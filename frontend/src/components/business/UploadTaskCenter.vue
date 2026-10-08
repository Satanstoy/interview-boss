<script setup>
/**
 * 上传任务中心（AC-010 / AC-027）
 *
 * - 常驻任务列表：成功/失败/待审核/待配置都留在这里，不能 5 秒后消失；
 * - 只显示服务端 allowed_actions（没有暂停能力就不出现暂停按钮）；
 * - 结果入口：按 location 接口定位页码与高亮，不打断当前浏览；
 * - 状态更新 aria-live=polite，键盘可操作；375px/1440px 均可查看。
 */
import { computed, inject, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  isTerminalStatus,
  loadUploadTasks,
  retryUploadTask,
} from '@/composables/useSubmitJobs.js'
import { get, getSSE } from '@/services/http.js'
import {
  fetchInterviewLocation,
  fetchPersonalAnalysisFailures,
  refreshPersonalAnalysisFailures,
  retryPersonalAnalysisFailure,
} from '@/services/dataApi.js'
import { currentUser } from '@/composables/useAuth.js'

const router = useRouter()
const appData = inject('appData', null)
const open = ref(false)
const loading = ref(false)
const error = ref('')
const tasks = ref([])
const personalAnalysisFailures = ref([])
const page = ref(1)
const personalAnalysisFailurePage = ref(1)
const personalAnalysisFailureLoadingMore = ref(false)
const personalAnalysisFailureRefreshing = ref(false)
const total = ref(0)
const uploadTaskTotal = ref(0)
const personalAnalysisFailureTotal = ref(0)
const busyIds = ref(new Set())
const announcement = ref('')
const triggerButton = ref(null)
const closeButton = ref(null)
const activeDetail = ref(null)
const detailTask = computed(() => tasks.value.find(task => task.import_id === activeDetail.value?.importId))
const reviewLabel = { pending: '待审核', pending_review: '待审核', approved_for_processing: '审核通过，处理中', published: '已发布', partially_published: '部分已发布', rejected: '已拒绝', withdrawn: '已撤回', changes_requested: '需要修改' }

const PAGE_SIZE = 20
const PERSONAL_FAILURE_PAGE_SIZE = 20
const PERSONAL_FAILURE_REFRESH_BATCH_SIZE = 5000
let pollTimer = null
let activeUserId = null
const taskSnapshots = new Map()
let refreshSequence = 0
let personalFailureLoadMoreSequence = 0

async function refreshPersonalFailureRange(loadedCount) {
  const items = []
  let total = 0
  let cursor = null
  while (items.length < loadedCount) {
    const requestLimit = Math.min(
      PERSONAL_FAILURE_REFRESH_BATCH_SIZE,
      loadedCount - items.length,
    )
    const result = await refreshPersonalAnalysisFailures(requestLimit, cursor)
    total = result.total || 0
    items.push(...(result.items || []))
    cursor = result.next_cursor || null
    if (!cursor || !result.items?.length) break
  }
  return { items, total, page: 1, page_size: loadedCount }
}

function rememberSnapshot(snapshot) {
  const previous = taskSnapshots.get(snapshot.import_id)
  if (previous && Number(snapshot.revision || 0) <= Number(previous.revision || 0)) return previous
  taskSnapshots.set(snapshot.import_id, snapshot)
  return snapshot
}

const statusLabel = {
  queued: '排队中',
  running: '处理中',
  waiting_review: '待审核',
  needs_action: '需要配置',
  partial_failed: '部分失败',
  failed: '失败',
  completed: '已完成',
}

const statusClass = {
  running: 'bg-sky-500/10 text-sky-600',
  queued: 'bg-muted text-muted-foreground',
  waiting_review: 'bg-amber-500/10 text-amber-600',
  needs_action: 'bg-orange-500/10 text-orange-600',
  partial_failed: 'bg-destructive/10 text-destructive',
  failed: 'bg-destructive/10 text-destructive',
  completed: 'bg-emerald-500/10 text-emerald-600',
}

const actionLabel = {
  open_result: '查看结果',
  retry_failed_steps: '重试失败步骤',
  retry_after_configuration: '配置后继续',
  configure_user_model: '去配置模型',
  configure_system_model: '配置系统模型',
  check_permission: '检查模型权限',
  retry: '重新处理',
  view_progress: '查看进度',
  view_review_status: '查看审核状态',
  view_budget: '查看额度',
  view_summary: '查看摘要',
  resubmit_source: '重新提交原文',
}

const hasPendingWork = computed(() =>
  tasks.value.some((task) => !isTerminalStatus(task.status)) || personalAnalysisFailures.value.length > 0,
)

async function refresh({ silent = true } = {}) {
  const requestedRefreshSequence = ++refreshSequence
  personalFailureLoadMoreSequence += 1
  personalAnalysisFailureLoadingMore.value = false
  personalAnalysisFailureRefreshing.value = true
  const requestedUserId = currentUser.value?.id == null ? null : String(currentUser.value.id)
  if (!requestedUserId) {
    activeDetail.value = null
    tasks.value = []
    personalAnalysisFailures.value = []
    personalAnalysisFailurePage.value = 1
    personalFailureLoadMoreSequence += 1
    personalAnalysisFailureLoadingMore.value = false
    personalAnalysisFailureRefreshing.value = false
    uploadTaskTotal.value = 0
    personalAnalysisFailureTotal.value = 0
    total.value = 0
    return
  }
  if (!silent) loading.value = true
  try {
    const requestedPersonalPage = personalAnalysisFailurePage.value
    const loadedCount = Math.max(
      PERSONAL_FAILURE_PAGE_SIZE,
      requestedPersonalPage * PERSONAL_FAILURE_PAGE_SIZE,
    )
    const [dataResult, queueRangeResult] = await Promise.allSettled([
      loadUploadTasks({ page: page.value, pageSize: PAGE_SIZE }),
      refreshPersonalFailureRange(loadedCount),
    ])
    if (
      requestedUserId !== String(currentUser.value?.id ?? '')
      || requestedRefreshSequence !== refreshSequence
    ) return
    const errors = []
    if (dataResult.status === 'fulfilled') {
      const data = dataResult.value
      tasks.value = (data.items || []).map(rememberSnapshot)
      uploadTaskTotal.value = data.total || 0
      const changed = tasks.value.filter((task) => isTerminalStatus(task.status))
      if (changed.length) {
        announcement.value = `任务状态更新：${changed
          .map((task) => `${task.import_id} ${statusLabel[task.status] || task.status}`)
          .join('；')}`
      }
    } else {
      errors.push(dataResult.reason?.message || '上传任务列表加载失败')
    }
    if (queueRangeResult.status === 'fulfilled') {
      if (requestedPersonalPage >= personalAnalysisFailurePage.value) {
        const queueFailures = queueRangeResult.value.items || []
        personalAnalysisFailures.value = queueFailures
        personalAnalysisFailureTotal.value = queueRangeResult.value.total || 0
        personalAnalysisFailurePage.value = Math.max(
          1,
          Math.ceil(queueFailures.length / PERSONAL_FAILURE_PAGE_SIZE),
        )
      }
    } else {
      errors.push(queueRangeResult.reason?.message || '个人失败任务列表加载失败')
      personalAnalysisFailurePage.value = Math.max(
        1,
        Math.ceil(personalAnalysisFailures.value.length / PERSONAL_FAILURE_PAGE_SIZE),
      )
    }
    total.value = uploadTaskTotal.value + personalAnalysisFailureTotal.value
    error.value = errors.length
      ? `${errors.join('；')}，已保留已加载任务`
      : ''
  } catch (err) {
    // AC-010：恢复失败保留已有任务，不把失败当空列表
    error.value = err?.message || '任务列表加载失败，已保留本地状态'
    if (requestedRefreshSequence === refreshSequence) {
      personalAnalysisFailurePage.value = Math.max(
        1,
        Math.ceil(personalAnalysisFailures.value.length / PERSONAL_FAILURE_PAGE_SIZE),
      )
    }
  } finally {
    if (requestedRefreshSequence === refreshSequence) {
      loading.value = false
      personalAnalysisFailureLoadingMore.value = false
      personalAnalysisFailureRefreshing.value = false
      if (requestedUserId === String(currentUser.value?.id ?? '')) subscribePendingTasks()
    }
  }
}

const sseControllers = new Map()

/** 非终态任务订阅快照流；网络/HTTP失败与EOF均由 getSSE退避重连（AC-010） */
function subscribePendingTasks() {
  for (const task of tasks.value) {
    if (isTerminalStatus(task.status) || sseControllers.has(task.import_id)) continue
    const requestedUserId = activeUserId
    const controller = new AbortController()
    sseControllers.set(task.import_id, controller)
    getSSE(
      `/api/upload-imports/${encodeURIComponent(task.import_id)}/stream`,
      (event) => {
        if (!event || typeof event !== 'object') return
        if (controller.signal.aborted || requestedUserId !== activeUserId || activeUserId !== String(currentUser.value?.id ?? '')) return
        const index = tasks.value.findIndex((item) => item.import_id === event.import_id)
        if (index < 0) return
        // 乱序 revision 不回退（AC-010）
        if ((event.revision || 0) <= (tasks.value[index].revision || 0)) return
        tasks.value.splice(index, 1, rememberSnapshot(event))
        if (isTerminalStatus(event.status)) {
          announcement.value = `任务状态更新：${event.import_id} ${statusLabel[event.status] || event.status}`
        }
      },
      {
        signal: controller.signal,
        isTerminal: (status) => isTerminalStatus(status),
        maxReconnects: 3,
        onReconnect: () => {
          announcement.value = '连接中断，后台任务继续，正在重新连接'
        },
      },
    ).catch(() => {
      if (activeUserId === String(currentUser.value?.id ?? '')) {
        error.value = '连接中断，后台任务继续；稍后将自动重连'
      }
    }).finally(() => {
      if (sseControllers.get(task.import_id) === controller) {
        sseControllers.delete(task.import_id)
      }
    })
  }
}

function stopTaskStreams() {
  for (const controller of sseControllers.values()) {
    try { controller.abort() } catch { /* ignored */ }
  }
  sseControllers.clear()
}

async function toggleTaskCenter() {
  open.value = !open.value
  await nextTick()
  if (open.value) {
    closeButton.value?.focus()
    await refresh({ silent: true })
  }
  else triggerButton.value?.focus()
}

async function closeTaskCenter() {
  open.value = false
  await nextTick()
  triggerButton.value?.focus()
}

watch(
  () => currentUser.value?.id == null ? null : String(currentUser.value.id),
  (nextUserId) => {
    stopTaskStreams()
    activeUserId = nextUserId
    taskSnapshots.clear()
    activeDetail.value = null
    tasks.value = []
    personalAnalysisFailures.value = []
    personalAnalysisFailurePage.value = 1
    personalFailureLoadMoreSequence += 1
    personalAnalysisFailureLoadingMore.value = false
    personalAnalysisFailureRefreshing.value = false
    uploadTaskTotal.value = 0
    personalAnalysisFailureTotal.value = 0
    total.value = 0
    page.value = 1
    error.value = ''
    announcement.value = ''
    if (nextUserId) refresh({ silent: true })
  },
  { immediate: true, flush: 'sync' },
)

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer)
  // 等待审核/人工操作：每 15 秒 GET 一次（SSE 关闭后仍可发现状态变化）
  pollTimer = setTimeout(async () => {
    await refresh({ silent: true })
    schedulePoll()
  }, 15_000)
}

async function changeUploadPage(nextPage) {
  if (loading.value || nextPage < 1 || nextPage > Math.ceil(uploadTaskTotal.value / PAGE_SIZE)) return
  page.value = nextPage
  activeDetail.value = null
  stopTaskStreams()
  await refresh({ silent: false })
}

function refreshOnFocus() {
  if (currentUser.value?.id && document.visibilityState === 'visible') refresh({ silent: true })
}

async function onAction(task, action) {
  if (['view_summary', 'view_progress', 'view_review_status', 'view_budget'].includes(action)) {
    const detail = { importId: task.import_id, action, budget: null, requestId: Symbol() }
    activeDetail.value = detail
    if (action === 'view_budget') {
      const userId = currentUser.value?.id
      try {
        const budget = await get(`/api/upload-imports/${encodeURIComponent(task.import_id)}/budget`, { noCache: true })
        if (currentUser.value?.id === userId && activeDetail.value?.requestId === detail.requestId) activeDetail.value = { ...detail, budget }
      } catch (err) {
        if (currentUser.value?.id === userId) error.value = err?.message || '用量加载失败'
      }
    }
    return
  }
  if (action === 'open_result') {
    await openResult(task)
    return
  }
  if (action === 'configure_user_model') {
    router.push({ name: 'settings' })
    return
  }
  if (action === 'check_permission') {
    router.push({ name: 'settings' })
    return
  }
  if (action === 'configure_system_model') {
    router.push({
      name: 'settings',
      query: { section: 'admin', adminTab: 'model' },
    })
    return
  }
  if (action === 'resubmit_source') {
    router.push('/import')
    return
  }
  if (action === 'retry' || action === 'retry_failed_steps' || action === 'retry_after_configuration') {
    busyIds.value = new Set([...busyIds.value, task.import_id])
    try {
      const snapshot = await retryUploadTask(task.import_id)
      const index = tasks.value.findIndex((item) => item.import_id === task.import_id)
      if (index >= 0 && snapshot) tasks.value.splice(index, 1, rememberSnapshot(snapshot))
      await refresh({ silent: true })
      announcement.value = snapshot?.created_attempt === false
        ? '已有恢复任务正在继续处理未完成步骤'
        : '恢复请求已提交，将继续未完成步骤'
    } catch (err) {
      error.value = err?.message || '恢复失败，请稍后重试'
    } finally {
      const next = new Set(busyIds.value)
      next.delete(task.import_id)
      busyIds.value = next
    }
  }
}

async function retryPersonalFailure(task) {
  const busyId = `analysis-queue:${task.queue_id}`
  busyIds.value = new Set([...busyIds.value, busyId])
  try {
    const result = await retryPersonalAnalysisFailure(task.queue_id)
    personalAnalysisFailures.value = personalAnalysisFailures.value.filter(
      (item) => item.queue_id !== task.queue_id,
    )
    await refresh({ silent: true })
    announcement.value = result?.created === false
      ? '该题目已在重新处理中'
      : '失败题目已重新排队处理'
  } catch (err) {
    error.value = err?.message || '重试失败，请稍后重试'
  } finally {
    const next = new Set(busyIds.value)
    next.delete(busyId)
    busyIds.value = next
  }
}

async function loadMorePersonalFailures() {
  if (personalAnalysisFailureLoadingMore.value) return
  if (personalAnalysisFailures.value.length >= personalAnalysisFailureTotal.value) return

  const nextPage = personalAnalysisFailurePage.value + 1
  const requestedUserId = currentUser.value?.id == null ? null : String(currentUser.value.id)
  const requestedRefreshSequence = refreshSequence
  const requestedLoadMoreSequence = ++personalFailureLoadMoreSequence
  personalAnalysisFailureLoadingMore.value = true
  personalAnalysisFailurePage.value = nextPage
  try {
    const result = await fetchPersonalAnalysisFailures({
      page: nextPage,
      page_size: PERSONAL_FAILURE_PAGE_SIZE,
    })
    if (
      requestedUserId !== String(currentUser.value?.id ?? '')
      || requestedRefreshSequence !== refreshSequence
      || requestedLoadMoreSequence !== personalFailureLoadMoreSequence
      || personalAnalysisFailurePage.value !== nextPage
    ) return
    const existing = new Map(personalAnalysisFailures.value.map((item) => [item.queue_id, item]))
    for (const item of result.items || []) existing.set(item.queue_id, item)
    personalAnalysisFailures.value = [...existing.values()]
    personalAnalysisFailureTotal.value = result.total || 0
  } catch (err) {
    if (
      requestedUserId === String(currentUser.value?.id ?? '')
      && requestedRefreshSequence === refreshSequence
      && requestedLoadMoreSequence === personalFailureLoadMoreSequence
      && personalAnalysisFailurePage.value === nextPage
    ) {
      personalAnalysisFailurePage.value = nextPage - 1
      error.value = err?.message || '更多个人失败任务加载失败'
    }
  } finally {
    if (
      requestedUserId === String(currentUser.value?.id ?? '')
      && requestedRefreshSequence === refreshSequence
      && requestedLoadMoreSequence === personalFailureLoadMoreSequence
    ) {
      personalAnalysisFailureLoadingMore.value = false
    }
  }
}

async function openResult(task) {
  // 已发布分享优先定位 public projection；旧/private 快照继续读 result.interview_id。
  const resultTarget = task.result_target
  const interviewId = resultTarget?.entity_type === 'interview'
    ? resultTarget.entity_id
    : task.result?.interview_id
  if (!interviewId) return
  try {
    const pageSize = Number(appData?.interviewPageSize?.value || PAGE_SIZE)
    const sort = appData?.interviewSortOrder?.value === 'asc'
      ? 'created_at_asc'
      : 'created_at_desc'
    const locationParams = {
      sort,
      page_size: pageSize,
      scope: 'all',
    }
    const positionId = task.position_id ?? task.result?.position_id
    if (positionId != null && positionId !== '') locationParams.position_id = positionId
    const location = await fetchInterviewLocation(interviewId, locationParams)
    // 只在用户主动“查看结果”时切换筛选与页码
    if (appData?.filterSeason) appData.filterSeason.value = ''
    router.push({
      name: 'interview',
      query: {
        page: location.page,
        page_size: location.page_size || pageSize,
        position: location.position_id || undefined,
        position_name: location.position_name || undefined,
        highlight: interviewId,
      },
    })
    open.value = false
  } catch {
    error.value = '面经已删除或无权访问'
  }
}

onMounted(() => {
  schedulePoll()
  window.addEventListener('focus', refreshOnFocus)
  window.addEventListener('upload-task-accepted', refreshOnFocus)
  document.addEventListener('visibilitychange', refreshOnFocus)
})

onUnmounted(() => {
  window.removeEventListener('focus', refreshOnFocus)
  window.removeEventListener('upload-task-accepted', refreshOnFocus)
  document.removeEventListener('visibilitychange', refreshOnFocus)
  if (pollTimer) clearTimeout(pollTimer)
  stopTaskStreams()
})
</script>

<template>
  <div class="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col items-end gap-2">
    <transition
      enter-active-class="transition duration-200"
      enter-from-class="translate-y-2 opacity-0"
      leave-active-class="transition duration-150"
      leave-to-class="translate-y-2 opacity-0"
    >
      <section
        v-if="open"
        class="pointer-events-auto w-[min(92vw,26rem)] rounded-xl border bg-background shadow-lg"
        aria-label="上传任务中心"
      >
        <header class="flex items-center justify-between border-b px-4 py-3">
          <h2 class="text-sm font-semibold">上传任务</h2>
          <button
            ref="closeButton"
            type="button"
            class="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-muted"
            aria-label="关闭任务中心"
            @click="closeTaskCenter"
          >
            关闭
          </button>
        </header>

        <p class="sr-only" aria-live="polite">{{ announcement }}</p>

        <div v-if="error" class="px-4 py-2 text-xs text-destructive">{{ error }}</div>

        <ul class="max-h-[60vh] overflow-y-auto px-2 py-2">
          <li
            v-for="task in tasks"
            :key="task.import_id"
            class="rounded-lg border border-border/60 p-3"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-xs text-muted-foreground">
                {{ task.position_name || '未指定岗位' }} · {{ task.import_id }}
              </span>
              <span
                role="status"
                aria-live="polite"
                class="rounded-full px-2 py-0.5 text-[11px]"
                :class="statusClass[task.status] || 'bg-muted text-muted-foreground'"
              >
                {{ statusLabel[task.status] || task.status }}
              </span>
            </div>

            <p v-if="task.stage" class="mt-1 text-xs text-muted-foreground">
              当前阶段：{{ task.stage }}
            </p>
            <div v-if="task.progress" class="mt-2 space-y-1">
              <p v-if="task.progress.total != null" class="text-xs text-muted-foreground">
                {{ task.progress.completed || 0 }}/{{ task.progress.total }} 题已处理
              </p>
              <p v-else class="text-xs text-muted-foreground">正在识别题目数量</p>
              <div
                v-if="task.progress.total != null && task.progress.total > 0"
                class="h-1.5 overflow-hidden rounded-full bg-muted"
                role="progressbar"
                :aria-label="`题目处理进度 ${task.progress.completed || 0}/${task.progress.total}`"
                :aria-valuemin="0"
                :aria-valuemax="task.progress.total"
                :aria-valuenow="Math.min(task.progress.completed || 0, task.progress.total)"
              >
                <div
                  class="h-full rounded-full bg-primary transition-[width]"
                  :style="{ width: `${Math.min(100, Math.round((task.progress.completed || 0) * 100 / task.progress.total))}%` }"
                />
              </div>
              <p v-if="task.counts" class="text-xs text-muted-foreground">
                答案成功 {{ task.counts.answered || 0 }} · 失败 {{ task.counts.failed || 0 }}
              </p>
            </div>
            <p v-if="task.error" class="mt-1 text-xs text-destructive">
              {{ task.error.message || task.error.code }}
            </p>
            <p
              v-if="task.recovery_available === false && task.recovery_message"
              class="mt-1 text-xs text-amber-700 dark:text-amber-400"
              role="status"
            >
              {{ task.recovery_message }}
            </p>

            <div class="mt-2 flex flex-wrap gap-2">
              <template v-for="action in task.allowed_actions || []" :key="action">
                <p
                  v-if="action === 'wait_for_global_model'"
                  class="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground"
                  role="status"
                >
                  等待管理员配置公共模型
                </p>
                <button
                  v-else
                  type="button"
                  class="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                  :disabled="busyIds.has(task.import_id)"
                  @click="onAction(task, action)"
                >
                  {{ actionLabel[action] || action }}
                </button>
              </template>
            </div>
          </li>

          <li
            v-for="task in personalAnalysisFailures"
            :key="`analysis-queue-${task.queue_id}`"
            class="rounded-lg border border-border/60 p-3"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="truncate text-xs text-muted-foreground">
                {{ task.company || '个人题库' }} · {{ task.job_position || '未指定岗位' }} · 私人队列
              </span>
              <span
                role="status"
                class="rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] text-destructive"
              >
                失败
              </span>
            </div>
            <p class="mt-1 text-sm">{{ task.question }}</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <button
                v-for="action in task.allowed_actions || []"
                :key="action"
                type="button"
                class="rounded-md border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
                :disabled="busyIds.has(`analysis-queue:${task.queue_id}`)"
                @click="action === 'retry' && retryPersonalFailure(task)"
              >
                {{ action === 'retry' ? '重试' : action }}
              </button>
            </div>
          </li>

          <li v-if="personalAnalysisFailures.length < personalAnalysisFailureTotal" class="text-center">
            <button
              type="button"
              class="rounded-md px-3 py-2 text-xs text-muted-foreground hover:bg-muted disabled:opacity-50"
              :disabled="personalAnalysisFailureLoadingMore || personalAnalysisFailureRefreshing"
              @click="loadMorePersonalFailures"
            >
              {{ personalAnalysisFailureLoadingMore ? '加载中…' : personalAnalysisFailureRefreshing ? '刷新中…' : `加载更多个人失败项（${personalAnalysisFailures.length}/${personalAnalysisFailureTotal}）` }}
            </button>
          </li>

          <li v-if="!tasks.length && !personalAnalysisFailures.length && !loading" class="px-3 py-6 text-center text-xs text-muted-foreground">
            暂无上传任务
          </li>
        </ul>

        <section v-if="activeDetail && detailTask" role="region" :aria-label="actionLabel[activeDetail.action]" class="border-t px-4 py-3 text-xs space-y-1">
          <div class="flex justify-between"><strong>{{ actionLabel[activeDetail.action] }}</strong><button type="button" aria-label="关闭任务详情" @click="activeDetail = null">关闭详情</button></div>
          <template v-if="activeDetail.action === 'view_summary'">
            <p>已识别题目 {{ detailTask.counts?.extracted ?? '待确认' }} · 保留 {{ detailTask.counts?.retained ?? '待确认' }} · 排除 {{ detailTask.counts?.excluded ?? '待确认' }}</p>
            <p>答案成功 {{ detailTask.counts?.answered ?? 0 }} · 失败 {{ detailTask.counts?.failed ?? 0 }}</p>
          </template>
          <template v-else-if="activeDetail.action === 'view_progress'">
            <p>处理进度：{{ statusLabel[detailTask.status] || detailTask.status }}</p>
            <p>当前阶段：{{ detailTask.stage || '等待下一阶段' }} · {{ detailTask.progress?.completed ?? 0 }}/{{ detailTask.progress?.total ?? '待确认' }}</p>
          </template>
          <p v-else-if="activeDetail.action === 'view_review_status'">审核状态：{{ reviewLabel[detailTask.review_status] || '尚未提交审核' }}</p>
          <template v-else-if="activeDetail.action === 'view_budget'">
            <p>累计用量：{{ activeDetail.budget?.total_tokens ?? '加载中' }} tokens</p>
            <p v-if="activeDetail.budget">模型调用 {{ activeDetail.budget.calls }} 次；用量未确认 {{ activeDetail.budget.unknown_calls }} 次。额度限制请查看模型服务账户。</p>
          </template>
        </section>
        <nav v-if="uploadTaskTotal > PAGE_SIZE" aria-label="上传任务分页" class="flex items-center justify-between border-t px-4 py-2 text-xs">
          <button type="button" aria-label="上一页上传任务" :disabled="page <= 1 || loading" @click="changeUploadPage(page - 1)">上一页</button>
          <span>第 {{ page }} / {{ Math.ceil(uploadTaskTotal / PAGE_SIZE) }} 页</span>
          <button type="button" aria-label="下一页上传任务" :disabled="page * PAGE_SIZE >= uploadTaskTotal || loading" @click="changeUploadPage(page + 1)">下一页</button>
        </nav>
        <footer class="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
          <span>共 {{ total }} 条</span>
          <button type="button" class="rounded-md px-2 py-1 hover:bg-muted" @click="refresh({ silent: false })">
            刷新
          </button>
        </footer>
      </section>
    </transition>

    <button
      ref="triggerButton"
      type="button"
      class="pointer-events-auto flex items-center gap-2 rounded-full border bg-background px-4 py-2 text-sm shadow-md hover:bg-muted"
      :aria-expanded="open"
      aria-label="上传任务中心"
      @click="toggleTaskCenter"
    >
      上传任务
      <span
        v-if="hasPendingWork"
        class="inline-block h-2 w-2 rounded-full bg-sky-500"
        aria-hidden="true"
      />
    </button>
  </div>
</template>
