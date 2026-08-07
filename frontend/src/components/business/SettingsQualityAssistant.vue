<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import {
  Bot,
  Send,
  Loader2,
  ShieldAlert,
  Check,
  X,
  RotateCcw,
  Wrench,
  ChevronDown,
  ArrowRight,
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  sendAssistantMessage,
  confirmAssistantAction,
  fetchAssistantHistory,
} from '@/services/adminAssistantApi.js'

const { success: toastSuccess, error: toastError, info: toastInfo } = useToast()
const { confirm: showConfirm } = useConfirm()

const SESSION_KEY = 'admin_assistant_session'

const sessionId = ref(localStorage.getItem(SESSION_KEY) || '')
const messages = ref([]) // {id, role: user|assistant|action, content, toolTrace[], confirmations[]}
const input = ref('')
const loading = ref(false)
const busyConfirm = ref(false)
const listRef = ref(null)

const QUICK_PROMPTS = [
  { label: '列出待审批', text: '列出当前待审批的聚合质量问题' },
  { label: '筛选高置信误合并', text: '帮我筛选置信度 ≥ 0.9 的误合并问题，逐一列出' },
  { label: '批量批准高置信', text: '批量批准所有置信度 ≥ 0.85 的误合并问题' },
  { label: '代表题不规范', text: '有哪些代表题不规范的问题？分别给出处理建议' },
]

// 目标题语义（与 SettingsQuality 卡片一致）：操作后「原题」变成什么
const targetOf = (conf) => {
  const issue = conf.issue || {}
  const action = issue.suggested_action
  if (action === 'merge') {
    return { label: '并入到 #' + issue.target_qb_id, text: issue.target_question }
  }
  if (action === 'refine_representative') {
    return { label: '新题面', text: issue.suggested_value }
  }
  if (action === 'split') {
    return { label: '新独立题', text: issue.suggested_value || issue.variant }
  }
  return { label: '目标题', text: issue.question }
}

const genSession = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return 's_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
}

const safeParse = (raw) => {
  try {
    const v = JSON.parse(raw)
    return Array.isArray(v) ? v : []
  } catch {
    return []
  }
}

let msgSeq = 0
const uid = () => `m${++msgSeq}_${Date.now().toString(36)}`

const scrollToBottom = () => {
  nextTick(() => {
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

const runTurn = async (message) => {
  loading.value = true
  try {
    const data = await sendAssistantMessage(sessionId.value, message)
    sessionId.value = data.session_id || sessionId.value
    localStorage.setItem(SESSION_KEY, sessionId.value)
    messages.value.push({
      id: uid(),
      role: 'assistant',
      content: data.reply || '',
      toolTrace: data.tool_trace || [],
      confirmations: data.confirmations || [],
    })
    scrollToBottom()
  } catch (e) {
    toastError('AI 助手请求失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

const send = () => {
  const text = input.value.trim()
  if (!text || loading.value) return
  input.value = ''
  if (!sessionId.value) sessionId.value = genSession()
  messages.value.push({ id: uid(), role: 'user', content: text })
  scrollToBottom()
  runTurn(text)
}

const onConfirm = async (msg, conf) => {
  if (busyConfirm.value) return
  busyConfirm.value = true
  try {
    const result = await confirmAssistantAction(
      sessionId.value,
      conf.confirm_id,
      conf.tool,
      conf.arguments,
    )
    msg.confirmations = msg.confirmations.filter((c) => c.confirm_id !== conf.confirm_id)
    messages.value.push({ id: uid(), role: 'action', content: result.message || '已执行' })
    toastSuccess('已执行')
    scrollToBottom()
    // 续接：让 LLM 确认并给出下一步建议
    await runTurn('')
  } catch (e) {
    toastError('执行失败：' + (e?.message || e))
  } finally {
    busyConfirm.value = false
  }
}

const onCancel = (msg, conf) => {
  msg.confirmations = msg.confirmations.filter((c) => c.confirm_id !== conf.confirm_id)
  toastInfo('已取消该操作')
}

const onClear = async () => {
  if (!await showConfirm('清空当前 AI 助手对话？', '将开始新的会话（操作日志仍保留可审计）。')) return
  messages.value = []
  sessionId.value = genSession()
  localStorage.setItem(SESSION_KEY, sessionId.value)
}

const toolSummary = (t) => {
  if (t.summary) return t.summary
  return t.status === 'ok' ? '完成' : t.status
}

onMounted(async () => {
  if (!sessionId.value) return
  try {
    const rows = await fetchAssistantHistory(sessionId.value)
    messages.value = rows.map((r) => ({
      id: r.id,
      role: r.role === 'action' ? 'action' : r.role,
      content: r.content || '',
      toolTrace: r.tool_trace ? safeParse(r.tool_trace) : [],
      confirmations: [],
    }))
    scrollToBottom()
  } catch (e) {
    toastError('加载会话历史失败：' + (e?.message || e))
  }
})
</script>

<template>
  <div class="space-y-4">
    <!-- 顶栏：说明 + 清空 -->
    <div class="flex items-center justify-between gap-2">
      <p class="text-xs text-muted-foreground">
        用自然语言筛选/批量处理聚合质量清单。写操作会先暂存为「待确认」，由你确认后执行并留痕。
      </p>
      <Button variant="ghost" size="sm" class="h-7 text-xs text-muted-foreground" @click="onClear">
        <RotateCcw :size="13" class="mr-1" />
        新对话
      </Button>
    </div>

    <!-- 消息区 -->
    <ScrollArea ref="listRef" class="h-[460px] rounded-lg border border-border bg-background">
      <div class="space-y-3 p-3">
        <div v-if="!messages.length && !loading" class="flex flex-col items-center gap-3 py-10 text-center">
          <div class="flex size-12 items-center justify-center rounded-full bg-primary/10">
            <Bot :size="24" class="text-primary" />
          </div>
          <p class="text-sm text-muted-foreground max-w-xs">
            我是聚合质量审查助手。告诉我你想怎么处理清单，或从下面快速指令开始。
          </p>
          <div class="flex flex-wrap justify-center gap-1.5 mt-1">
            <button
              v-for="p in QUICK_PROMPTS"
              :key="p.label"
              class="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground hover:border-primary/50 hover:text-primary transition-colors"
              @click="input = p.text"
            >
              {{ p.label }}
            </button>
          </div>
        </div>

        <div v-for="msg in messages" :key="msg.id" class="space-y-2">
          <!-- 用户消息：右对齐 -->
          <div v-if="msg.role === 'user'" class="flex justify-end">
            <div class="max-w-[85%] rounded-xl rounded-br-sm bg-primary px-3 py-2 text-sm text-primary-foreground">
              {{ msg.content }}
            </div>
          </div>

          <!-- action 回执：居中 -->
          <div v-else-if="msg.role === 'action'" class="flex justify-center">
            <div class="flex items-center gap-1.5 rounded-full border border-green-500/30 bg-green-500/10 px-3 py-1 text-xs text-green-600 dark:text-green-400">
              <Check :size="13" />
              {{ msg.content }}
            </div>
          </div>

          <!-- 助手消息：左对齐 + 工具轨迹 + 待确认卡片 -->
          <div v-else class="flex justify-start">
            <div class="max-w-[92%] min-w-0 rounded-xl rounded-bl-sm border border-border bg-card px-3 py-2 text-sm">
              <div class="flex items-center gap-1.5 mb-1.5 text-[11px] text-muted-foreground">
                <Bot :size="13" class="text-primary" />
                AI 助手
              </div>
              <p class="whitespace-pre-wrap leading-relaxed text-foreground">{{ msg.content }}</p>

              <!-- 工具轨迹（可折叠） -->
              <div v-if="msg.toolTrace.length" class="mt-2 border-t border-border/60 pt-1.5">
                <details class="group">
                  <summary class="flex cursor-pointer items-center gap-1 text-[11px] text-muted-foreground select-none">
                    <Wrench :size="11" />
                    工具调用（{{ msg.toolTrace.length }}）
                    <ChevronDown :size="11" class="transition-transform group-open:rotate-180" />
                  </summary>
                  <div class="mt-1.5 space-y-1">
                    <div v-for="(t, ti) in msg.toolTrace" :key="ti" class="flex items-center gap-1.5 text-[11px]">
                      <Badge variant="secondary" class="font-mono text-[10px]">{{ t.tool }}</Badge>
                      <span class="text-muted-foreground truncate">{{ toolSummary(t) }}</span>
                    </div>
                  </div>
                </details>
              </div>

              <!-- 待确认操作卡片 -->
              <div v-for="conf in msg.confirmations" :key="conf.confirm_id"
                class="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-2.5">
                <div class="flex items-center gap-1.5 mb-1.5">
                  <ShieldAlert :size="13" class="text-amber-500" />
                  <span class="text-xs font-medium text-amber-600 dark:text-amber-400">待确认操作</span>
                  <Badge class="text-[10px]">{{ conf.issue?.action_label || conf.tool }}</Badge>
                  <span v-if="conf.issue?.confidence" class="text-[10px] text-muted-foreground">
                    置信度 {{ (conf.issue.confidence * 100).toFixed(0) }}%
                  </span>
                </div>

                <!-- 前后对照：原代表题+原题目 → 目标题 -->
                <div class="grid grid-cols-[1fr_auto_1fr] items-stretch gap-2">
                  <div class="min-w-0 rounded-md border border-border bg-muted/60 px-2 py-1.5">
                    <div class="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-0.5">原代表题</div>
                    <div class="text-[11px] font-medium leading-snug">{{ conf.issue?.question }}</div>
                    <div
                      v-if="conf.issue?.variant && conf.issue?.suggested_action !== 'refine_representative'"
                      class="mt-1.5 border-t border-border/70 pt-1.5"
                    >
                      <div class="text-[10px] font-semibold text-destructive uppercase tracking-wide mb-0.5">
                        原题目（要{{ conf.issue?.suggested_action === 'split' ? '拆出' : '并入' }}）
                      </div>
                      <div class="text-[10px] text-destructive leading-snug">{{ conf.issue?.variant }}</div>
                    </div>
                  </div>
                  <div class="flex items-center justify-center text-muted-foreground">
                    <ArrowRight :size="13" />
                  </div>
                  <div class="min-w-0 rounded-md border border-primary/25 bg-primary/5 px-2 py-1.5">
                    <div class="text-[10px] font-semibold text-primary uppercase tracking-wide mb-0.5">
                      {{ targetOf(conf).label }}
                    </div>
                    <div class="text-[11px] font-medium leading-snug">
                      {{ targetOf(conf).text }}
                    </div>
                  </div>
                </div>

                <p v-if="conf.issue?.reason" class="mt-1.5 text-[10px] text-muted-foreground leading-snug">
                  {{ conf.issue.reason }}
                </p>
                <div class="mt-2 flex gap-2">
                  <Button size="sm" class="h-6 gap-1 text-[11px]" :disabled="busyConfirm" @click="onConfirm(msg, conf)">
                    <Check :size="12" />
                    确认执行
                  </Button>
                  <Button variant="outline" size="sm" class="h-6 gap-1 text-[11px] text-muted-foreground" :disabled="busyConfirm" @click="onCancel(msg, conf)">
                    <X :size="12" />
                    取消
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 思考中 -->
        <div v-if="loading" class="flex justify-start">
          <div class="flex items-center gap-2 rounded-xl rounded-bl-sm border border-border bg-card px-3 py-2">
            <Loader2 :size="14" class="animate-spin text-primary" />
            <span class="text-xs text-muted-foreground">正在分析清单…</span>
          </div>
        </div>
      </div>
    </ScrollArea>

    <!-- 输入区 -->
    <div class="flex items-end gap-2">
      <Textarea
        v-model="input"
        :rows="2"
        class="flex-1 resize-none text-sm"
        placeholder="例如：帮我列出待审批的误合并问题，或批量批准置信度 ≥ 0.85 的问题…"
        @keydown.enter.exact.prevent="send"
      />
      <Button :disabled="loading" @click="send">
        <Send :size="14" class="mr-1.5" />
        发送
      </Button>
    </div>
  </div>
</template>
