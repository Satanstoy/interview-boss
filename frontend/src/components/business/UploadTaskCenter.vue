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
import { getSSE } from '@/services/http.js'
import { fetchInterviewLocation } from '@/services/dataApi.js'
import { currentUser } from '@/composables/useAuth.js'

const router = useRouter()
const appData = inject('appData', null)
const open = ref(false)
const loading = ref(false)
const error = ref('')
const tasks = ref([])
const page = ref(1)
const total = ref(0)
const busyIds = ref(new Set())
const announcement = ref('')
const triggerButton = ref(null)
const closeButton = ref(null)

const PAGE_SIZE = 20
let pollTimer = null
let activeUserId = null

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
  retry: '重新处理',
  view_progress: '查看进度',
  view_review_status: '查看审核状态',
  view_budget: '查看额度',
  view_summary: '查看摘要',
  resubmit_source: '重新提交原文',
}

const hasPendingWork = computed(() =>
  tasks.value.some((task) => !isTerminalStatus(task.status)),
)

async function refresh({ silent = true } = {}) {
  const requestedUserId = currentUser.value?.id == null ? null : String(currentUser.value.id)
  if (!requestedUserId) {
    tasks.value = []
    total.value = 0
    return
  }
  if (!silent) loading.value = true
  try {
    const data = await loadUploadTasks({ page: page.value, pageSize: PAGE_SIZE })
    if (requestedUserId !== String(currentUser.value?.id ?? '')) return
    tasks.value = data.items || []
    total.value = data.total || 0
    error.value = ''
    const changed = tasks.value.filter((task) => isTerminalStatus(task.status))
    if (changed.length) {
      announcement.value = `任务状态更新：${changed
        .map((task) => `${task.import_id} ${statusLabel[task.status] || task.status}`)
        .join('；')}`
    }
  } catch (err) {
    // AC-010：恢复失败保留已有任务，不把失败当空列表
    error.value = err?.message || '任务列表加载失败，已保留本地状态'
  } finally {
    loading.value = false
    if (requestedUserId === String(currentUser.value?.id ?? '')) subscribePendingTasks()
  }
}

const sseControllers = new Map()

/** 非终态任务订阅快照流；网络/HTTP失败与EOF均由 getSSE退避重连（AC-010） */
function subscribePendingTasks() {
  for (const task of tasks.value) {
    if (isTerminalStatus(task.status) || sseControllers.has(task.import_id)) continue
    const controller = new AbortController()
    sseControllers.set(task.import_id, controller)
    getSSE(
      `/api/upload-imports/${encodeURIComponent(task.import_id)}/stream`,
      (event) => {
        if (!event || typeof event !== 'object') return
        if (activeUserId !== String(currentUser.value?.id ?? '')) return
        const index = tasks.value.findIndex((item) => item.import_id === event.import_id)
        if (index < 0) return
        // 乱序 revision 不回退（AC-010）
        if ((event.revision || 0) < (tasks.value[index].revision || 0)) return
        tasks.value.splice(index, 1, { ...tasks.value[index], ...event })
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
  if (open.value) closeButton.value?.focus()
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
    tasks.value = []
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

async function onAction(task, action) {
  if (action === 'open_result') {
    await openResult(task)
    return
  }
  if (action === 'configure_user_model') {
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
      if (index >= 0 && snapshot) tasks.value.splice(index, 1, { ...tasks.value[index], ...snapshot })
      announcement.value = snapshot?.created_attempt === false
        ? '已有恢复任务正在继续处理未完成步骤'
        : '恢复请求已提交，将继续未完成步骤'
      await refresh({ silent: true })
    } catch (err) {
      error.value = err?.message || '恢复失败，请稍后重试'
    } finally {
      const next = new Set(busyIds.value)
      next.delete(task.import_id)
      busyIds.value = next
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
})

onUnmounted(() => {
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

          <li v-if="!tasks.length && !loading" class="px-3 py-6 text-center text-xs text-muted-foreground">
            暂无上传任务
          </li>
        </ul>

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
