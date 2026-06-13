<template>
  <div class="flex h-full bg-background">
    <!-- Conversation list sidebar (always visible) -->
    <div 
      class="sidebar-container border-r border-border flex flex-col shrink-0 overflow-hidden"
      :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      :style="{ width: sidebarCollapsed ? '0px' : '288px' }"
    >
      <div class="p-4 border-b border-border flex items-center gap-2 sidebar-content">
        <Button @click="showNewChat = true" class="flex-1" size="sm">
          <Plus :size="16" />
          新建面试
        </Button>
        <Button variant="ghost" size="icon" @click="sidebarCollapsed = true" class="shrink-0">
          <PanelLeftClose :size="16" />
        </Button>
      </div>
      <div class="flex-1 overflow-y-auto custom-scrollbar p-2 sidebar-content">
        <div v-if="conversations.length === 0" class="p-4 text-center text-sm text-muted-foreground">
          暂无对话
        </div>
        <div v-else class="flex flex-col gap-0.5">
          <div v-for="conv in conversations" :key="conv.id"
            @click="selectConversation(conv.id)"
            class="group flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-150 text-left"
            :class="activeConversationId === conv.id ? 'bg-accent' : 'hover:bg-accent/50'">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate text-foreground">{{ conv.title || '新对话' }}</div>
              <div class="text-[11px] mt-0.5 truncate text-muted-foreground">
                {{ conv.mode === 'jd_resume' ? 'JD定制' : '自由练习' }} · {{ formatRelativeTime(conv.updated_at) }}
              </div>
            </div>
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <Button 
                  variant="ghost" 
                  size="icon-xs" 
                  class="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                  @click.stop
                >
                  <MoreHorizontal :size="14" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" class="w-40">
                <DropdownMenuItem @click.stop="handlePin(conv.id)">
                  <Pin :size="14" class="mr-2" />
                  <span>置顶</span>
                </DropdownMenuItem>
                <DropdownMenuItem @click.stop="handleRename(conv.id, conv.title)">
                  <Pencil :size="14" class="mr-2" />
                  <span>重命名</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem @click.stop="handleDelete(conv.id)" class="text-destructive focus:text-destructive">
                  <Trash2 :size="14" class="mr-2" />
                  <span>删除</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
      </div>
    </div>

    <!-- Sidebar collapsed: show expand button -->
    <div v-if="sidebarCollapsed" class="flex flex-col items-center py-3 px-2 gap-1 shrink-0 border-r border-border sidebar-expand-buttons">
      <Button variant="ghost" size="icon" @click="sidebarCollapsed = false" class="shrink-0">
        <PanelLeft :size="16" />
      </Button>
      <Button variant="ghost" size="icon" @click="showNewChat = true" class="shrink-0">
        <Plus :size="16" />
      </Button>
    </div>

    <!-- Main content area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Empty state -->
      <div v-if="!activeConversationId" class="flex-1 flex items-center justify-center">
        <div
          v-motion
          :initial="{ opacity: 0, y: 16 }"
          :enter="{ opacity: 1, y: 0, transition: { duration: 400, easing: [0.25, 0.46, 0.45, 0.94] } }"
          class="flex flex-col items-center max-w-2xl mx-auto px-6"
        >
          <div class="size-20 mx-auto mb-6 rounded-2xl bg-primary/10 flex items-center justify-center">
            <MessageSquare :size="40" class="text-primary" />
          </div>
          <h2 class="text-3xl font-bold text-foreground mb-3 text-center">开始模拟面试</h2>
          <p class="text-muted-foreground mb-8 text-center text-lg">选择左侧对话或创建新的面试会话</p>
          
          <!-- Prompt suggestions -->
          <div class="grid grid-cols-2 gap-4 w-full max-w-lg">
            <button
              v-for="suggestion in promptSuggestions"
              :key="suggestion.text"
              @click="startWithSuggestion(suggestion.text)"
              class="flex items-start gap-3 p-4 rounded-xl border border-border bg-card hover:bg-accent/50 hover:border-primary/30 transition-all text-left group"
            >
              <div class="size-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition-colors">
                <component :is="suggestion.icon" :size="20" class="text-primary" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">{{ suggestion.title }}</div>
                <div class="text-xs text-muted-foreground mt-1">{{ suggestion.description }}</div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <!-- Active chat -->
      <template v-else>
      <!-- Chat header -->
      <div class="flex items-center justify-between px-6 py-1.5 shrink-0">
        <div class="min-w-0 flex-1">
          <form v-if="isRenamingHeader" @submit.prevent="saveHeaderRename" class="flex items-center gap-1.5">
            <input
              ref="headerTitleInput"
              v-model="headerTitleDraft"
              class="h-7 min-w-0 max-w-[420px] rounded-md border border-input bg-background px-2.5 text-sm font-medium text-foreground outline-none focus:ring-1 focus:ring-ring"
              @keydown.esc.prevent="cancelHeaderRename"
              @blur="saveHeaderRename"
            />
            <Button type="submit" variant="ghost" size="icon-xs" title="保存标题">
              <Check :size="14" />
            </Button>
            <Button type="button" variant="ghost" size="icon-xs" title="取消" @mousedown.prevent @click="cancelHeaderRename">
              <X :size="14" />
            </Button>
          </form>
          <button
            v-else
            type="button"
            @click="startHeaderRename"
            class="group flex max-w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-muted/70 transition-colors"
            title="重命名对话"
          >
            <span class="truncate text-sm font-semibold text-foreground">{{ activeConversationTitle }}</span>
            <Pencil :size="13" class="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
          </button>
        </div>
        <span class="shrink-0 bg-muted/60 rounded-full px-2 py-0.5 text-[11px] text-muted-foreground">{{ activeConversationMode }}</span>
      </div>

      <!-- Messages area -->
      <div ref="messagesContainer" @scroll="onMessagesScroll" class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        <div class="max-w-3xl mx-auto px-6 pt-8 pb-8">
          <!-- Grouped messages -->
          <template v-for="(group, groupIndex) in groupedMessages" :key="groupIndex">
            <!-- Time separator -->
            <div v-if="group.showTime" class="flex items-center justify-center my-8">
              <div class="px-3 py-1 rounded-full bg-muted text-xs text-muted-foreground">
                {{ group.timeLabel }}
              </div>
            </div>

            <!-- Messages in group -->
            <ChatMessage 
              v-for="msg in group.messages" 
              :key="msg.id" 
              :message="msg"
              @regenerate="handleRegenerate"
              @like="handleLike"
            />
          </template>

          <!-- Streaming message -->
          <div v-if="isSending" class="mb-6">
            <!-- Thinking block -->
            <ThinkingBlock
              v-if="isThinking || thinkingContent"
              :is-streaming="isThinking"
              :content="thinkingContent"
              :duration="thinkingDuration"
            />

            <!-- Processing steps -->
            <div v-else-if="!streamingContent && processingSteps.length > 0" class="mb-4">
              <div class="flex items-center gap-2 text-xs text-muted-foreground mb-3">
                <Loader2 :size="14" class="animate-spin" />
                <span>{{ waitingText }}</span>
              </div>
              <div class="flex flex-wrap gap-2">
                <TransitionGroup name="step">
                  <div v-for="step in processingSteps" :key="step.step"
                    class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs transition-all duration-300"
                    :class="step.done 
                      ? 'bg-primary/10 text-primary' 
                      : 'bg-muted text-muted-foreground animate-pulse'">
                    <CheckCircle2 v-if="step.done" :size="12" />
                    <Loader2 v-else :size="12" class="animate-spin" />
                    <span>{{ step.message }}</span>
                  </div>
                </TransitionGroup>
              </div>
            </div>

            <!-- Simple thinking indicator -->
            <div v-else-if="!streamingContent" class="flex items-center gap-2 text-xs text-muted-foreground mb-4">
              <Loader2 :size="14" class="animate-spin" />
              <span>思考中...</span>
            </div>

            <!-- Retrieved questions while streaming -->
            <div v-if="pendingRetrievedQuestions?.length" class="mb-4 rounded-xl border border-sky-500/20 bg-sky-500/5 p-3">
              <div class="text-xs font-medium text-sky-700 dark:text-sky-300 mb-2">
                已检索到 {{ pendingRetrievedQuestions.length }} 个候选题
              </div>
              <div class="space-y-2">
                <div
                  v-for="q in pendingRetrievedQuestions"
                  :key="q.id || q.question"
                  class="rounded-lg bg-background/70 border border-border/50 px-3 py-2"
                >
                  <div class="text-sm text-foreground">{{ q.question }}</div>
                  <div class="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                    <span v-if="q.company">{{ q.company }}</span>
                    <span v-if="q.round">{{ q.round }}</span>
                    <span v-if="q.cat1" class="text-sky-600 dark:text-sky-400">[{{ q.cat1 }}]</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Insight cards during streaming -->
            <div v-if="pendingInsights.length > 0 && !isThinking && !thinkingContent" class="mb-2">
              <div
                v-for="(item, i) in pendingInsights"
                :key="i"
                class="flex items-start gap-2 px-3 py-1.5 text-xs text-muted-foreground
                       bg-amber-500/5 rounded-lg mb-1"
              >
                <span class="text-amber-500/70">&#x1F4A1;</span>
                <span>{{ item.text }}</span>
              </div>
            </div>

            <!-- Streaming content -->
            <div v-if="streamingContent" class="prose-chat">
              <div v-html="renderStreamingContent"></div>
              <span class="inline-block w-1.5 h-4 bg-primary animate-pulse ml-0.5 align-middle rounded-sm"></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Input area -->
      <div class="shrink-0">
        <div class="max-w-3xl mx-auto px-6 pb-4">
          <form @submit.prevent="handleSend">
            <div class="chat-input-area flex flex-col gap-2 p-2 bg-muted rounded-2xl">
              <!-- Textarea -->
              <textarea
                ref="inputRef"
                v-model="inputText"
                :placeholder="inputPlaceholder"
                :disabled="isSending"
                @keydown="onInputKeydown"
                @input="autoResize"
                rows="1"
                class="w-full px-3 py-2 text-sm resize-none overflow-hidden"
                style="min-height: 32px; max-height: 120px;"
              ></textarea>

              <!-- Action buttons -->
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-1">
                  <!-- Attachment button -->
                  <button
                    type="button"
                    class="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-background transition-colors"
                    title="上传文件"
                  >
                    <Paperclip :size="16" />
                  </button>
                  <!-- Model selector -->
                  <ModelSelector
                    :current-model="selectedModel"
                    @select="handleModelSelect"
                  />
                </div>
                <!-- Send button -->
                <Button
                  v-if="isSending"
                  type="button"
                  @click="handleStop"
                  variant="destructive"
                  size="icon"
                  class="rounded-lg size-8 shrink-0"
                >
                  <Square :size="14" />
                </Button>
                <Button
                  v-else
                  type="submit"
                  :disabled="!inputText.trim()"
                  size="icon"
                  class="rounded-lg size-8 shrink-0"
                >
                  <ArrowUp :size="16" />
                </Button>
              </div>
            </div>
            <div class="mt-2 flex items-center justify-between px-1">
              <span class="text-[11px] text-muted-foreground">按 Enter 发送，Shift+Enter 换行</span>
              <span class="text-[11px] text-muted-foreground">基于题库和 JD 上下文追问</span>
            </div>
          </form>
        </div>
      </div>
    </template>
    </div>

    <!-- New Chat Modal -->
    <NewChatModal
      :visible="showNewChat"
      :jd-list="jdList"
      :initial-message="pendingInitialMessage"
      @close="showNewChat = false; pendingInitialMessage = ''"
      @create="handleCreateConversation"
    />
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onActivated, watch } from 'vue'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { cancelAllRequests } from '@/services/http.js'
import { Button } from '@/components/ui/button'
import { 
  Plus, 
  MessageSquare, 
  Paperclip, 
  Square, 
  ArrowUp,
  ArrowLeft,
  BookOpen,
  Code,
  Briefcase,
  Brain,
  CheckCircle2,
  Check,
  X,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  MoreHorizontal,
  Pin,
  Pencil,
  Trash2
} from '@lucide/vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import ChatMessage from './ChatMessage.vue'
import ThinkingBlock from './ThinkingBlock.vue'
import NewChatModal from './NewChatModal.vue'
import ModelSelector from './ModelSelector.vue'
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
const messagesContainer = ref(null)
const inputRef = ref(null)
const pendingRetrievedQuestions = ref(null)
const pendingResumeRef = ref(null)
const pendingJdRef = ref(null)
const pendingInitialMessage = ref('')
const pendingBasisType = ref(null)
const pendingBasisQuestionIds = ref([])
const pendingBasisConfidence = ref(0)
const pendingInsights = ref([])
const pendingShouldShowReferences = ref(false)
const pendingSelectedBasisQuestions = ref([])
const autoScrollEnabled = ref(true)
const processingSteps = ref([])
const selectedModel = ref('')
const sidebarCollapsed = ref(false)
const isRenamingHeader = ref(false)
const headerTitleDraft = ref('')
const headerTitleInput = ref(null)

// Thinking state
const isThinking = ref(false)
const thinkingContent = ref('')
const thinkingDuration = ref(0)

const STORAGE_KEY_ACTIVE_ID = 'chatview_active_conversation_id'

// Prompt suggestions
const promptSuggestions = [
  { 
    icon: BookOpen, 
    title: '项目介绍', 
    description: '如何介绍一个复杂业务项目？' 
  },
  { 
    icon: Code, 
    title: '算法练习', 
    description: '帮我复习 React Hooks 相关题目' 
  },
  { 
    icon: Briefcase, 
    title: 'JD 分析', 
    description: '分析这个 JD 的考察重点' 
  },
  { 
    icon: Brain, 
    title: '行为面试', 
    description: '用 STAR 法则回答软技能问题' 
  },
]

const inputPlaceholder = computed(() => {
  return '回答面试问题，或输入你想练习的内容...'
})

const activeConversation = computed(() =>
  conversations.value.find(c => c.id === activeConversationId.value)
)

const activeConversationTitle = computed(() =>
  activeConversation.value?.title || '模拟面试会话'
)

const activeConversationMode = computed(() =>
  activeConversation.value?.mode === 'jd_resume' ? 'JD 定制面试' : '自由练习'
)

const renderStreamingContent = computed(() => {
  if (!streamingContent.value) return ''
  const cleaned = streamingContent.value
    .replace(/\[BASIS\][\s\S]*?\[\/BASIS\]/g, '')
    .replace(/\[BASIS\]\{[^}]*\}/g, '')
    .trim()
  return renderSafeMarkdown(cleaned || streamingContent.value)
})

const waitingText = computed(() => {
  if (processingSteps.value.length === 0) return '正在连接...'
  const lastStep = processingSteps.value[processingSteps.value.length - 1]
  if (!lastStep) return '正在思考...'
  const stepTextMap = {
    'retrieve': '检索相关题目...',
    'evaluate': '评估答案...',
    'generate': '生成回答...',
    'generating': '正在组织面试官回复...',
    'search': '搜索知识库...',
    'analyze': '分析问题...',
    'think': '深度思考...',
    'load_skill': '正在加载面试策略...',
    'search_questions': '正在检索相关面试题...',
    'draw_questions': '正在从题库抽题...',
    'project-deep-dive': '正在切换到项目深挖...',
    'algorithm-coding': '正在切换到算法面试...',
    'interview-rhythm': '正在调整面试节奏...',
    'theory-qa': '正在准备理论追问...',
    'hr-soft-skills': '正在准备软技能追问...',
    'adaptive-difficulty': '正在调整题目难度...',
  }
  return stepTextMap[lastStep.step] || lastStep.message || '思考中...'
})

// Message grouping by time
const groupedMessages = computed(() => {
  if (!messages.value.length) return []
  
  const groups = []
  let currentGroup = null
  let lastTime = null
  
  for (const msg of messages.value) {
    const msgTime = new Date(msg.created_at + (msg.created_at.includes('Z') || msg.created_at.includes('+') ? '' : 'Z'))
    const timeDiff = lastTime ? (msgTime - lastTime) / 1000 / 60 : Infinity
    
    if (!currentGroup || timeDiff > 30) {
      currentGroup = {
        showTime: true,
        timeLabel: formatGroupTime(msgTime),
        messages: []
      }
      groups.push(currentGroup)
    }
    
    currentGroup.messages.push(msg)
    lastTime = msgTime
  }
  
  return groups
})

function formatGroupTime(date) {
  const now = new Date()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)
  
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  if (hours < 24) return `${hours} 小时前`
  if (days < 7) return `${days} 天前`
  return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric' })
}

// Load conversations
async function loadConversations() {
  if (props.preview) {
    conversations.value = [
      { id: 'preview-1', title: '前端一面模拟', mode: 'jd_resume', updated_at: new Date().toISOString() },
      { id: 'preview-2', title: '项目深挖', mode: 'free', updated_at: new Date(Date.now() - 1200000).toISOString() },
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
    await scrollToBottom(true)
    return
  }
  try {
    const res = await chatApi.getConversations()
    conversations.value = res.data || []

    // Preserve active selection: only clear if conversation no longer exists
    if (activeConversationId.value) {
      const stillExists = conversations.value.some(c => c.id === activeConversationId.value)
      if (!stillExists) {
        activeConversationId.value = null
        messages.value = []
      }
    }
  } catch (e) {
    console.error('加载对话列表失败:', e)
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
    pendingInitialMessage.value = ''
    await loadConversations()
    if (res.data?.id) {
      await selectConversation(res.data.id)
      if (data.initial_message) {
        inputText.value = data.initial_message
        await nextTick()
        await handleSend()
      }
    }
  } catch (e) {
    console.error('创建对话失败:', e)
  }
}

// Start with suggestion
async function startWithSuggestion(text) {
  pendingInitialMessage.value = text
  showNewChat.value = true
}

// Send message
async function handleSend() {
  const text = inputText.value.trim()
  if (!text || isSending.value || !activeConversationId.value) return

  inputText.value = ''
  resetInputHeight()
  isSending.value = true
  streamingContent.value = ''
  pendingRetrievedQuestions.value = null
  pendingBasisType.value = null
  pendingBasisQuestionIds.value = []
  pendingBasisConfidence.value = 0
  pendingShouldShowReferences.value = false
  pendingSelectedBasisQuestions.value = []
  pendingInsights.value = []
  processingSteps.value = []
  autoScrollEnabled.value = true

  isThinking.value = false
  thinkingContent.value = ''
  thinkingDuration.value = 0

  const userMsg = { id: Date.now(), role: 'user', content: text, created_at: new Date().toISOString() }
  messages.value.push(userMsg)
  await scrollToBottom()

  try {
    await chatApi.sendMessage(
      activeConversationId.value,
      text,
      (event) => {
        if (event.type === 'step') {
          processingSteps.value.forEach(s => { s.done = true })
          processingSteps.value.push({ step: event.step, message: event.message, done: false })
          scrollToBottom()
        } else if (event.type === 'thinking_start') {
          isThinking.value = true
          thinkingContent.value = ''
          thinkingDuration.value = 0
        } else if (event.type === 'thinking') {
          thinkingContent.value += event.content
          scrollToBottom()
        } else if (event.type === 'thinking_done') {
          isThinking.value = false
          thinkingDuration.value = event.duration || 0
        } else if (event.type === 'chunk') {
          // Strip [BASIS] blocks from streaming content to prevent leakage
          const rawContent = event.content
          const cleanedContent = rawContent
            .replace(/\[BASIS\][\s\S]*?\[\/BASIS\]/g, '')
            .replace(/\[BASIS\]\{[^}]*$/g, '')  // Partial [BASIS]{ at end of chunk
            .replace(/^\{[^}]*\}?\[\/BASIS\]/g, '')  // Partial }[/BASIS] at start
          streamingContent.value += cleanedContent
          scrollToBottom()
        } else if (event.type === 'retrieved') {
          pendingRetrievedQuestions.value = event.questions || []
        } else if (event.type === 'resume_ref') {
          pendingResumeRef.value = event.name || null
        } else if (event.type === 'jd_ref') {
          pendingJdRef.value = event.title || null
        } else if (event.type === 'basis') {
          pendingBasisType.value = event.basis_type || 'none'
          pendingBasisQuestionIds.value = event.basis_question_ids || []
          pendingBasisConfidence.value = event.basis_confidence || 0
          pendingShouldShowReferences.value = event.should_show_references || false
          pendingSelectedBasisQuestions.value = event.selected_basis_questions || []
          if (event.resume_ref) pendingResumeRef.value = event.resume_ref
          if (event.jd_ref) pendingJdRef.value = event.jd_ref
        } else if (event.type === 'insight') {
          pendingInsights.value.push({ text: event.text })
        }
      },
      selectedModel.value || null
    )

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
      if (thinkingContent.value) {
        metadata.thinking = thinkingContent.value
        metadata.thinking_duration = thinkingDuration.value
      }
      if (pendingInsights.value.length > 0) {
        metadata.insights = [...pendingInsights.value]
      }
      if (pendingBasisType.value && pendingBasisType.value !== 'none') {
        metadata.basis_type = pendingBasisType.value
        metadata.basis_question_ids = pendingBasisQuestionIds.value
        metadata.basis_confidence = pendingBasisConfidence.value
        metadata.should_show_references = pendingShouldShowReferences.value
        if (pendingSelectedBasisQuestions.value?.length > 0) {
          metadata.selected_basis_questions = pendingSelectedBasisQuestions.value
        }
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
      pendingInsights.value = []
      pendingBasisType.value = null
      pendingBasisQuestionIds.value = []
      pendingBasisConfidence.value = 0
      pendingShouldShowReferences.value = false
      pendingSelectedBasisQuestions.value = []
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
    isThinking.value = false
    thinkingContent.value = ''
    thinkingDuration.value = 0
    await scrollToBottom()
  }
}

// Regenerate message
async function handleRegenerate(messageId) {
  const msgIndex = messages.value.findIndex(m => m.id === messageId)
  if (msgIndex === -1) return
  
  let userMessageIndex = -1
  for (let i = msgIndex - 1; i >= 0; i--) {
    if (messages.value[i].role === 'user') {
      userMessageIndex = i
      break
    }
  }
  
  if (userMessageIndex === -1) return
  
  const userMessage = messages.value[userMessageIndex]
  messages.value = messages.value.slice(0, userMessageIndex)
  
  inputText.value = userMessage.content
  await handleSend()
}

function handleLike({ id, liked }) {
  console.log('Like message:', id, liked)
}

function handleModelSelect(modelId) {
  selectedModel.value = modelId
}

async function handlePin(id) {
  try {
    await chatApi.pinConversation(id)
    await loadConversations()
  } catch (e) {
    console.error('置顶对话失败:', e)
  }
}

async function handleRename(id, currentTitle) {
  const newTitle = prompt('请输入新标题', currentTitle || '新对话')
  if (!newTitle || newTitle === currentTitle) return
  try {
    if (props.preview) {
      const conv = conversations.value.find(c => c.id === id)
      if (conv) conv.title = newTitle
      return
    }
    await chatApi.updateTitle(id, newTitle)
    await loadConversations()
  } catch (e) {
    console.error('重命名对话失败:', e)
  }
}

async function startHeaderRename() {
  headerTitleDraft.value = activeConversationTitle.value
  isRenamingHeader.value = true
  await nextTick()
  headerTitleInput.value?.focus()
  headerTitleInput.value?.select()
}

function cancelHeaderRename() {
  isRenamingHeader.value = false
  headerTitleDraft.value = ''
}

async function saveHeaderRename() {
  if (!isRenamingHeader.value || !activeConversationId.value) return
  const newTitle = headerTitleDraft.value.trim()
  const currentTitle = activeConversationTitle.value
  if (!newTitle || newTitle === currentTitle) {
    cancelHeaderRename()
    return
  }
  try {
    if (props.preview) {
      const conv = conversations.value.find(c => c.id === activeConversationId.value)
      if (conv) conv.title = newTitle
    } else {
      await chatApi.updateTitle(activeConversationId.value, newTitle)
      await loadConversations()
    }
  } catch (e) {
    console.error('重命名对话失败:', e)
  } finally {
    cancelHeaderRename()
  }
}

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

function autoResize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
}

function resetInputHeight() {
  nextTick(() => {
    if (inputRef.value) inputRef.value.style.height = '32px'
  })
}

function onInputKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function onMessagesScroll() {
  const el = messagesContainer.value
  if (!el) return
  const threshold = 100
  autoScrollEnabled.value = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
}

async function scrollToBottom(force = false) {
  await nextTick()
  if (messagesContainer.value && (force || autoScrollEnabled.value)) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

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

// Restore active conversation from localStorage
const savedId = localStorage.getItem(STORAGE_KEY_ACTIVE_ID)
if (savedId) {
  activeConversationId.value = savedId
}

// Load conversations on mount
onMounted(async () => {
  await loadConversations()

  // If we have a saved ID and it exists in the list, load its messages
  if (activeConversationId.value) {
    const exists = conversations.value.some(c => c.id === activeConversationId.value)
    if (exists) {
      try {
        const res = await chatApi.getMessages(activeConversationId.value)
        messages.value = res.data || []
        await scrollToBottom(true)
      } catch (e) {
        console.error('加载消息失败:', e)
      }
    } else {
      activeConversationId.value = null
    }
  }

  watch(activeConversationId, (id) => {
    autoScrollEnabled.value = true
    if (id) {
      localStorage.setItem(STORAGE_KEY_ACTIVE_ID, id)
    } else {
      localStorage.removeItem(STORAGE_KEY_ACTIVE_ID)
    }
  })
})

// Refresh conversations when returning to this tab (KeepAlive)
onActivated(async () => {
  await loadConversations()
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

/* Sidebar animation */
.sidebar-container {
  transition: width 380ms cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-content {
  transition: opacity 200ms ease-out;
}

.sidebar-collapsed .sidebar-content {
  opacity: 0;
  pointer-events: none;
}

.sidebar-expand-buttons {
  animation: sidebarExpandButtons 280ms cubic-bezier(0, 0, 0.2, 1) 100ms both;
}

@keyframes sidebarExpandButtons {
  from { opacity: 0; transform: translateX(-4px); }
  to   { opacity: 1; transform: translateX(0); }
}

/* Shimmer animation */
.animate-shimmer {
  background: linear-gradient(90deg, transparent 0%, color-mix(in oklab, var(--primary) 40%, transparent) 50%, transparent 100%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Chat input textarea — strip all browser defaults, blend with container */
.chat-input-area textarea {
  background-color: transparent !important;
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
  -webkit-appearance: none !important;
  appearance: none !important;
  font-family: inherit;
  color: var(--foreground);
}
.chat-input-area textarea:focus,
.chat-input-area textarea:focus-visible {
  outline: none !important;
  box-shadow: none !important;
}
.chat-input-area textarea:disabled {
  opacity: 0.5;
}
.chat-input-area textarea::placeholder {
  color: var(--muted-foreground);
}
</style>
