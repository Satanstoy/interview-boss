<template>
  <div class="flex h-[calc(100vh-132px)] bg-background rounded-xl border border-border overflow-hidden shadow-card">
    <!-- Sidebar -->
    <div class="w-72 shrink-0 border-r border-border flex flex-col bg-sidebar">
      <!-- Header -->
      <div class="border-b border-border p-4">
        <div class="mb-3">
          <h2 class="text-sm font-semibold text-sidebar-foreground">模拟面试</h2>
          <p class="mt-0.5 text-xs text-muted-foreground">AI Interview Copilot</p>
        </div>
        <Button @click="showNewChat = true" class="w-full" size="sm">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
          新建面试
        </Button>
      </div>

      <!-- Conversation list -->
      <div class="flex-1 overflow-y-auto custom-scrollbar px-2 py-2">
        <!-- Loading skeleton -->
        <div v-if="loadingConversations" class="p-2 space-y-1">
          <div v-for="i in 4" :key="i" class="flex items-center gap-2 px-3 py-2.5 rounded-lg">
            <div class="flex-1 space-y-1.5">
              <Skeleton class="h-4 rounded" :style="{ width: 50 + Math.random() * 40 + '%' }" />
              <Skeleton class="h-2.5 w-16 rounded" />
            </div>
          </div>
        </div>
        <div v-else-if="conversations.length === 0" class="p-4">
          <AppEmpty title="暂无对话" description="点击上方按钮开始模拟面试" icon="💬">
            <template #icon>
              <span class="text-2xl">💬</span>
            </template>
          </AppEmpty>
        </div>
        <div v-else class="space-y-0.5">
          <div v-for="conv in conversations" :key="conv.id"
            @click="selectConversation(conv.id)"
            class="group flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-150 text-left"
            :class="activeConversationId === conv.id
              ? 'bg-sidebar-accent text-sidebar-accent-foreground'
              : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50'">
            <div class="size-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-semibold transition-colors"
              :class="activeConversationId === conv.id
                ? 'bg-primary/10 text-primary'
                : 'bg-muted text-muted-foreground'">
              {{ conv.mode === 'jd_resume' ? 'JD' : 'AI' }}
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate">{{ conv.title || '新对话' }}</div>
              <div class="text-[11px] mt-0.5 truncate"
                :class="activeConversationId === conv.id ? 'text-muted-foreground' : 'text-muted-foreground/60'">
                {{ conv.mode === 'jd_resume' ? 'JD定制' : '自由练习' }} · {{ formatRelativeTime(conv.updated_at) }}
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon-xs"
              @click.stop="handleDelete(conv.id)"
              class="opacity-0 group-hover:opacity-100 text-muted-foreground/40 hover:text-destructive hover:bg-destructive/10"
            >
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- Chat area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Empty state -->
      <div v-if="!activeConversationId" class="flex-1 flex items-center justify-center bg-muted/30">
        <div
          v-motion
          :initial="{ opacity: 0, y: 16 }"
          :enter="{ opacity: 1, y: 0, transition: { duration: 400, easing: [0.25, 0.46, 0.45, 0.94] } }"
        >
          <AppEmpty title="开始模拟面试" description="选择一个对话或创建新的面试会话">
            <template #icon>
              <div class="size-16 mx-auto mb-5 rounded-2xl bg-card border border-border flex items-center justify-center shadow-sm">
                <svg class="size-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
              </div>
            </template>
            <Button @click="showNewChat = true" class="mt-2">
              新建面试
            </Button>
          </AppEmpty>
        </div>
      </div>

      <!-- Active chat -->
      <template v-else>
        <!-- Chat header -->
        <div class="flex h-14 items-center justify-between border-b border-border bg-card px-5 shrink-0">
          <div class="min-w-0">
            <h2 class="truncate text-sm font-semibold text-foreground">{{ activeConversationTitle }}</h2>
            <p class="text-xs text-muted-foreground">{{ activeConversationMode }} · 基于题库和 JD 上下文追问</p>
          </div>
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
              <span class="size-1.5 rounded-full bg-primary animate-pulse"></span>
              AI 在线
            </span>
            <Button variant="outline" size="sm">
              复盘
            </Button>
          </div>
        </div>

        <!-- Messages area -->
        <div ref="messagesContainer" class="flex-1 overflow-y-auto custom-scrollbar bg-muted/20 px-6 py-5 space-y-5">
          <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />

          <!-- Streaming message with step timeline -->
          <div v-if="isSending" class="flex items-start gap-3">
            <div class="size-8 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold bg-card border border-border text-foreground shadow-sm">AI</div>
            <div class="max-w-[75%] min-w-0">
              <!-- Processing steps timeline -->
              <div v-if="!streamingContent && processingSteps.length > 0" class="rounded-xl border border-border bg-card p-3 shadow-sm">
                <div class="mb-2 flex items-center justify-between">
                  <p class="text-xs font-semibold text-foreground">AI Thinking</p>
                  <span class="text-[11px] text-muted-foreground">RAG + Eval</span>
                </div>
                <TransitionGroup name="step">
                  <div v-for="(step, idx) in processingSteps" :key="step.step"
                    class="flex items-center gap-2.5 py-1.5 px-2 rounded-md transition-all duration-300"
                    :class="idx === processingSteps.length - 1 && !step.done ? 'bg-muted/50' : 'opacity-60'">
                    <div class="size-6 rounded-full flex items-center justify-center shrink-0 transition-all duration-300"
                      :class="step.done ? 'bg-emerald-100 dark:bg-emerald-900/30' : 'bg-primary/10'">
                      <svg v-if="step.done" class="size-3.5 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                      <div v-else class="size-2.5 rounded-full bg-primary animate-pulse"></div>
                    </div>
                    <span class="text-xs" :class="step.done ? 'text-muted-foreground line-through' : 'text-foreground font-medium'">
                      {{ step.message }}
                    </span>
                    <div v-if="!step.done" class="flex-1 h-1 bg-muted rounded-full overflow-hidden">
                      <div class="h-full bg-primary rounded-full animate-shimmer" style="width: 40%"></div>
                    </div>
                  </div>
                </TransitionGroup>
              </div>
              <!-- Simple typing indicator -->
              <div v-else-if="!streamingContent" class="flex items-center gap-2.5 px-4 py-3 bg-card rounded-xl border border-border shadow-sm">
                <div class="flex gap-1">
                  <span class="size-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0ms"></span>
                  <span class="size-2 bg-primary rounded-full animate-bounce" style="animation-delay: 150ms"></span>
                  <span class="size-2 bg-primary rounded-full animate-bounce" style="animation-delay: 300ms"></span>
                </div>
                <span class="text-xs text-muted-foreground ml-1">{{ waitingText }}</span>
              </div>
              <!-- Streaming content -->
              <div class="rounded-xl rounded-tl-md px-4 py-3 text-sm leading-relaxed bg-card text-foreground border border-border shadow-sm">
                <div class="prose-chat streaming-content" v-html="renderStreamingContent"></div>
                <span class="inline-block w-1.5 h-4 bg-primary animate-pulse ml-0.5 align-middle rounded-sm"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- Input area -->
        <div class="shrink-0 border-t border-border bg-card px-5 py-4">
          <form @submit.prevent="handleSend" class="rounded-xl border border-border bg-background p-2 shadow-inner-glow focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all">
            <textarea ref="inputRef" v-model="inputText"
              :placeholder="inputPlaceholder"
              :disabled="isSending"
              @keydown="onInputKeydown"
              @input="autoResize"
              rows="1"
              class="w-full px-3 py-2 text-sm bg-transparent text-foreground placeholder:text-muted-foreground focus:outline-none disabled:opacity-50 resize-none overflow-hidden"
              style="min-height: 56px; max-height: 160px;"></textarea>
            <div class="mt-2 flex items-center justify-between border-t border-border/50 pt-2">
              <span class="px-2 text-[11px] text-muted-foreground">Context: JD / 面经 / 高频题库</span>
              <div class="flex items-center gap-2">
                <Button v-if="isSending" type="button" @click="handleStop" variant="destructive" size="sm">
                  停止
                </Button>
                <Button v-else type="submit" :disabled="!inputText.trim()" size="sm">
                  发送
                </Button>
              </div>
            </div>
          </form>
        </div>
      </template>
    </div>

    <!-- New Chat Modal -->
    <NewChatModal
      :visible="showNewChat"
      :jd-list="jdList"
      @close="showNewChat = false"
      @create="handleCreateConversation"
    />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onUnmounted, watch } from 'vue'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { cancelAllRequests } from '@/services/http.js'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import ChatMessage from './ChatMessage.vue'
import NewChatModal from './NewChatModal.vue'
import AppEmpty from '@/components/common/AppEmpty.vue'
import * as chatApi from '@/services/chatApi.js'

const props = defineProps({
  jdList: { type: Array, default: () => [] },
  preview: { type: Boolean, default: false },
})

// State
const conversations = ref([])
const activeConversationId = ref(null)
const messages = ref([])
const inputText = ref('')
const isSending = ref(false)
const streamingContent = ref('')
const showNewChat = ref(false)
const loadingConversations = ref(false)
const messagesContainer = ref(null)
const inputRef = ref(null)
const pendingRetrievedQuestions = ref(null)
const pendingResumeRef = ref(null)
const pendingJdRef = ref(null)
const autoScrollEnabled = ref(true)
const processingSteps = ref([])

const inputPlaceholder = computed(() => {
  const conv = conversations.value.find(c => c.id === activeConversationId.value)
  if (conv?.mode === 'jd_resume') return '回答面试问题，或输入你想练习的内容...'
  return '回答面试问题，或输入你想练习的内容...'
})

const activeConversation = computed(() =>
  conversations.value.find(c => c.id === activeConversationId.value)
)

const activeConversationTitle = computed(() =>
  activeConversation.value?.title || '模拟面试会话'
)

const activeConversationMode = computed(() =>
  activeConversation.value?.mode === 'jd_resume' ? 'JD 定制' : '自由练习'
)

const renderStreamingContent = computed(() => {
  if (!streamingContent.value) return ''
  return renderSafeMarkdown(streamingContent.value)
})

// Contextual waiting text based on processing steps
const waitingText = computed(() => {
  if (processingSteps.value.length === 0) return '正在连接...'
  const lastStep = processingSteps.value[processingSteps.value.length - 1]
  if (!lastStep) return '正在思考...'
  const stepTextMap = {
    'retrieve': '正在检索相关题目...',
    'evaluate': '正在评估你的答案...',
    'generate': '正在生成回答...',
    'search': '正在搜索知识库...',
    'analyze': '正在分析问题...',
    'think': '正在深度思考...',
  }
  return stepTextMap[lastStep.step] || lastStep.message || '正在思考...'
})

// Load conversations
async function loadConversations() {
  if (props.preview) {
    conversations.value = [
      { id: 'preview-1', title: '前端一面模拟', mode: 'jd_resume', updated_at: new Date().toISOString() },
      { id: 'preview-2', title: '项目深挖', mode: 'free', updated_at: new Date(Date.now() - 1200000).toISOString() },
      { id: 'preview-3', title: '工程化复盘', mode: 'free', updated_at: new Date(Date.now() - 7200000).toISOString() },
    ]
    activeConversationId.value = 'preview-1'
    messages.value = [
      {
        id: 'm1',
        role: 'assistant',
        content: '先用 2 分钟介绍最近负责的项目，以及你承担的核心职责。',
        created_at: new Date(Date.now() - 180000).toISOString(),
        metadata: {
          retrieved_questions: [
            { id: 1, cat1: '项目复盘', question: '如何介绍一个复杂业务项目？', company: '腾讯', round: '一面' },
            { id: 2, cat1: '工程化', question: '如何设计稳定的导入解析链路？', company: '美团', round: '二面' },
          ],
        },
      },
      {
        id: 'm2',
        role: 'user',
        content: '我最近负责 InterviewBoss 的题库导入解析和练习链路，重点解决面经内容结构化、高频题归类以及模拟问答体验。',
        created_at: new Date(Date.now() - 120000).toISOString(),
      },
      {
        id: 'm3',
        role: 'assistant',
        content: '你提到了"导入解析"。如果遇到一份格式很乱的面经，你会如何设计容错、回滚和质量评估？',
        created_at: new Date(Date.now() - 60000).toISOString(),
        metadata: { jd_ref: '高级前端工程师 JD', resume_ref: '项目经历：AI 面试准备平台' },
      },
    ]
    processingSteps.value = [
      { step: 'retrieve', message: '检索相关题目', done: true },
      { step: 'evaluate', message: '评估回答结构', done: true },
      { step: 'generate', message: '生成追问方向', done: false },
    ]
    await scrollToBottom(true)
    return
  }
  loadingConversations.value = true
  try {
    const res = await chatApi.getConversations()
    conversations.value = res.data || []
  } catch (e) {
    console.error('加载对话列表失败:', e)
  } finally {
    loadingConversations.value = false
  }
}

// Select conversation
async function selectConversation(id) {
  activeConversationId.value = id
  messages.value = []
  try {
    const res = await chatApi.getMessages(id)
    messages.value = res.data || []
    await scrollToBottom()
  } catch (e) {
    console.error('加载消息失败:', e)
  }
}

// Create conversation
async function handleCreateConversation(data) {
  try {
    const res = await chatApi.createConversation(data)
    showNewChat.value = false
    await loadConversations()
    if (res.data?.id) {
      await selectConversation(res.data.id)
    }
  } catch (e) {
    console.error('创建对话失败:', e)
  }
}

// Send message
async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isSending.value || !activeConversationId.value) return

  inputText.value = ''
  isSending.value = true
  streamingContent.value = ''
  pendingRetrievedQuestions.value = null
  processingSteps.value = []
  autoScrollEnabled.value = true

  // Add user message to UI immediately
  const userMsg = { id: Date.now(), role: 'user', content: text, created_at: new Date().toISOString() }
  messages.value.push(userMsg)
  await scrollToBottom()

  try {
    await chatApi.sendMessage(activeConversationId.value, text, (event) => {
      if (event.type === 'step') {
        processingSteps.value.forEach(s => { s.done = true })
        processingSteps.value.push({ step: event.step, message: event.message, done: false })
        scrollToBottom()
      } else if (event.type === 'chunk') {
        streamingContent.value += event.content
        scrollToBottom()
      } else if (event.type === 'retrieved') {
        pendingRetrievedQuestions.value = event.questions || []
      } else if (event.type === 'resume_ref') {
        pendingResumeRef.value = event.name || null
      } else if (event.type === 'jd_ref') {
        pendingJdRef.value = event.title || null
      }
    })

    // Streaming done - add final message
    if (streamingContent.value) {
      const metadata = {}
      if (pendingRetrievedQuestions.value?.length > 0) {
        metadata.retrieved_questions = pendingRetrievedQuestions.value
      }
      if (pendingResumeRef.value) {
        metadata.resume_ref = pendingResumeRef.value
      }
      if (pendingJdRef.value) {
        metadata.jd_ref = pendingJdRef.value
      }
      messages.value.push({
        id: Date.now() + 1,
        role: 'assistant',
        content: streamingContent.value,
        metadata,
        created_at: new Date().toISOString(),
      })
      pendingRetrievedQuestions.value = null
      pendingResumeRef.value = null
      pendingJdRef.value = null
    }
  } catch (e) {
    console.error('发送消息失败:', e)
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      content: '抱歉，发送消息时出现错误，请稍后重试。',
      created_at: new Date().toISOString(),
    })
  } finally {
    streamingContent.value = ''
    isSending.value = false
    await scrollToBottom()
  }
}

// Delete conversation
async function handleDelete(id) {
  if (!confirm('确定要删除这个对话吗？')) return
  try {
    await chatApi.deleteConversation(id)
    if (activeConversationId.value === id) {
      activeConversationId.value = null
      messages.value = []
    }
    await loadConversations()
  } catch (e) {
    console.error('删除对话失败:', e)
  }
}

// Stop generation (cancel SSE stream)
function handleStop() {
  cancelAllRequests()
  if (streamingContent.value) {
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      content: streamingContent.value + '\n\n*[已停止生成]*',
      metadata: {},
      created_at: new Date().toISOString(),
    })
  }
  streamingContent.value = ''
  isSending.value = false
}

// Auto-resize textarea
function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

// Keyboard handling: Enter to send, Shift+Enter for newline
function onInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

// Smart auto-scroll: detect user scroll position
function onMessagesScroll() {
  const el = messagesContainer.value
  if (!el) return
  const threshold = 100
  autoScrollEnabled.value = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
}

// Scroll to bottom (respects smart auto-scroll)
async function scrollToBottom(force = false) {
  await nextTick()
  if (messagesContainer.value && (force || autoScrollEnabled.value)) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// Format relative time
function formatRelativeTime(ts) {
  if (!ts) return ''
  const d = new Date(ts + (ts.includes('Z') || ts.includes('+') ? '' : 'Z'))
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return d.toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

// Init
onMounted(() => {
  loadConversations()
  watch(activeConversationId, () => {
    autoScrollEnabled.value = true
  })
})
</script>

<style scoped>
/* Step transition animations */
.step-enter-active {
  transition: all 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.step-leave-active {
  transition: all 0.2s ease-out;
}
.step-enter-from {
  opacity: 0;
  transform: translateY(-8px) scale(0.95);
}
.step-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.95);
}

/* Streaming content fade-in */
.streaming-content {
  animation: contentFadeIn 0.3s ease-out;
}
@keyframes contentFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Shimmer animation for step progress */
.animate-shimmer {
  background: linear-gradient(90deg, transparent 0%, rgb(var(--c-primary-400) / 0.6) 50%, transparent 100%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
</style>
