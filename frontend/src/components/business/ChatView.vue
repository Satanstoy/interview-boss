<template>
  <div class="relative flex h-full overflow-hidden bg-background">
    <div
      v-if="!sidebarCollapsed"
      class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden"
      @click="sidebarCollapsed = true"
    />

    <!-- Conversation list sidebar -->
    <div
      class="sidebar-container z-30 border-r border-border bg-background flex flex-col shrink-0 overflow-hidden md:z-auto"
      :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      :style="{ width: sidebarCollapsed ? '0px' : '16rem' }"
    >
      <div class="flex shrink-0 items-center gap-2 p-2 sidebar-content">
        <Button @click="showNewChat = true" class="flex-1" size="sm">
          <Plus :size="16" />
          新建面试
        </Button>
        <AppTooltip text="收起面试会话列表" side="right">
          <Button variant="ghost" size="icon" class="size-7 shrink-0 text-muted-foreground" aria-label="收起面试会话列表" @click="sidebarCollapsed = true">
            <PanelLeftClose :size="14" />
          </Button>
        </AppTooltip>
      </div>
      <div class="flex-1 overflow-y-auto custom-scrollbar px-2 pb-2 sidebar-content">
        <div v-if="conversations.length === 0" class="p-4 text-center text-sm text-muted-foreground">
          暂无对话
        </div>
        <div v-else class="flex flex-col gap-0.5">
          <div v-for="conv in conversations" :key="conv.id"
            @click="selectConversation(conv.id)"
            class="group relative flex w-full items-center gap-2 rounded-md p-2 text-left text-sm cursor-pointer transition-colors"
            :class="activeConversationId === conv.id
              ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
              : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'">
            <div class="flex-1 min-w-0">
              <div class="truncate">{{ conv.title || '新对话' }}</div>
              <div class="text-[11px] mt-0.5 truncate text-muted-foreground">
                {{ conv.mode === 'jd_resume' ? 'JD定制' : '自由练习' }} · {{ formatRelativeTime(conv.updated_at) }}
              </div>
            </div>
            <DropdownMenu>
              <AppTooltip text="更多操作">
                <DropdownMenuTrigger as-child>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    class="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    aria-label="更多操作"
                    @click.stop
                  >
                    <MoreHorizontal :size="14" />
                  </Button>
                </DropdownMenuTrigger>
              </AppTooltip>
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
    <div v-if="sidebarCollapsed" class="hidden flex-col items-center py-2 px-2 gap-1 shrink-0 sidebar-expand-buttons md:flex">
      <AppTooltip text="展开面试会话列表" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="展开面试会话列表" @click="sidebarCollapsed = false">
          <PanelLeft :size="14" />
        </Button>
      </AppTooltip>
      <AppTooltip text="新建面试" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="新建面试" @click="showNewChat = true">
          <Plus :size="14" />
        </Button>
      </AppTooltip>
    </div>

    <!-- Main content area -->
    <div class="flex-1 flex flex-col min-w-0">
      <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2 md:hidden">
        <Button
          variant="outline"
          size="sm"
          class="h-8 shrink-0 gap-1.5 rounded-lg text-xs"
          aria-label="切换面试会话"
          @click="sidebarCollapsed = false"
        >
          <PanelLeft :size="14" />
          <span>切换面试会话</span>
        </Button>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {{ activeConversationId ? activeConversationTitle : '模拟面试' }}
        </span>
      </div>

      <!-- Empty state -->
      <div v-if="!activeConversationId || activeConversationId === 'pending'" class="flex-1 flex flex-col">
        <!-- 有待创建对话时，显示简洁界面 -->
        <template v-if="pendingNewConversation">
          <div class="flex-1 flex items-center justify-center">
            <div class="text-center text-muted-foreground">
              <MessageSquare :size="48" class="mx-auto mb-4 text-primary/30" />
              <p class="text-sm">输入你的回答开始面试</p>
            </div>
          </div>
        </template>
        
        <!-- 没有待创建对话时，显示原始空状态 -->
        <template v-else>
        <div
          v-motion
          :initial="{ opacity: 0, y: 16 }"
          :enter="{ opacity: 1, y: 0, transition: { duration: 400, easing: [0.25, 0.46, 0.45, 0.94] } }"
          class="flex flex-col items-center max-w-2xl mx-auto px-6"
        >
          <div class="size-20 mx-auto mb-6 rounded-xl bg-primary/10 flex items-center justify-center">
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
        </template>
      </div>

      <!-- Active chat -->
      <template v-else>
      <!-- Chat header -->
      <div class="hidden items-center justify-between px-6 py-1.5 shrink-0 md:flex">
        <div class="min-w-0 flex-1">
          <form v-if="isRenamingHeader" @submit.prevent="saveHeaderRename" class="flex items-center gap-1.5">
            <input
              ref="headerTitleInput"
              v-model="headerTitleDraft"
              class="h-7 min-w-0 max-w-[420px] rounded-md border border-input bg-background px-2.5 text-sm font-medium text-foreground outline-none focus:ring-1 focus:ring-ring"
              @keydown.esc.prevent="cancelHeaderRename"
              @blur="saveHeaderRename"
            />
            <AppTooltip text="保存标题">
              <Button type="submit" variant="ghost" size="icon-xs">
                <Check :size="14" />
              </Button>
            </AppTooltip>
            <AppTooltip text="取消">
              <Button type="button" variant="ghost" size="icon-xs" @mousedown.prevent @click="cancelHeaderRename">
                <X :size="14" />
              </Button>
            </AppTooltip>
          </form>
          <AppTooltip v-else text="重命名对话">
            <button
              type="button"
              @click="startHeaderRename"
              class="group flex max-w-full items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-muted/70 transition-colors"
            >
              <span class="truncate text-sm font-semibold text-foreground">{{ activeConversationTitle }}</span>
              <Pencil :size="13" class="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
            </button>
          </AppTooltip>
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
            <ReasoningTimeline
              v-if="isSending || isThinking || thinkingContent || processingSteps.length > 0"
              :is-streaming="isThinking"
              :is-sending="isSending"
              :content="thinkingContent"
              :duration="displayThinkingDuration"
              :steps="processingSteps"
              :tool-steps="pendingToolSteps"
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
            <div class="chat-input-area flex flex-col gap-2 p-2 bg-muted rounded-xl">
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
                  <AppTooltip text="上传文件">
                    <button
                      type="button"
                      class="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-background transition-colors"
                    >
                      <Paperclip :size="16" />
                    </button>
                  </AppTooltip>
                  <!-- Model selector -->
                  <ModelSelector
                    :current-model="selectedModel"
                    @select="handleModelSelect"
                  />
                </div>
                <!-- Send button -->
                <AppTooltip v-if="isSending" text="停止生成">
                  <Button
                    type="button"
                    aria-label="停止生成"
                    @click="handleStop"
                    variant="destructive"
                    size="icon"
                    class="rounded-lg size-8 shrink-0"
                  >
                    <Square :size="14" />
                  </Button>
                </AppTooltip>
                <AppTooltip v-else text="发送消息">
                  <Button
                    type="submit"
                    aria-label="发送消息"
                    :disabled="!inputText.trim()"
                    size="icon"
                    class="rounded-lg size-8 shrink-0"
                  >
                    <ArrowUp :size="16" />
                  </Button>
                </AppTooltip>
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
      :interview-list="interviewList"
      :initial-message="pendingInitialMessage"
      @close="showNewChat = false; pendingInitialMessage = ''"
      @create="handleCreateConversation"
    />

    <!-- Rename Dialog -->
    <Dialog :open="showRenameDialog" @update:open="handleRenameCancel">
      <DialogContent class="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{{ renameDialogTitle }}</DialogTitle>
        </DialogHeader>
        <div class="py-4">
          <Input
            v-model="renameDialogValue"
            placeholder="请输入新标题"
            @keyup.enter="handleRenameConfirm"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="handleRenameCancel">取消</Button>
          <Button @click="handleRenameConfirm">确定</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onActivated, watch } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
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
import ReasoningTimeline from './ReasoningTimeline.vue'
import NewChatModal from './NewChatModal.vue'
import ModelSelector from './ModelSelector.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'
import * as chatApi from '@/services/chatApi.js'
import { fetchMyLLMConfig } from '@/services/profileApi.js'

const props = defineProps({
  jdList: { type: Array, default: () => [] },
  interviewList: { type: Array, default: () => [] },
  preview: { type: Boolean, default: false },
  modelValue: { type: String, default: null },
})

const emit = defineEmits(['update:modelValue'])
const { success: toastSuccess, error: toastError } = useToast()
const { confirm: showConfirm } = useConfirm()

// State
const conversations = ref([])
const activeConversationId = ref(null)
const messages = ref([])
const inputText = ref('')
const isSending = ref(false)
const streamingContent = ref('')
const showNewChat = ref(false)
const creatingConversation = ref(false)
const messagesContainer = ref(null)
const inputRef = ref(null)
const pendingRetrievedQuestions = ref(null)
const pendingCandidateQuestions = ref(null)
const pendingSelectedQuestion = ref(null)
const pendingQuestionSource = ref(null)
const pendingQuestionSourceReason = ref(null)
const pendingResumeRef = ref(null)
const pendingJdRef = ref(null)
const pendingInitialMessage = ref('')
const pendingBasisType = ref(null)
const pendingBasisQuestionIds = ref([])
const pendingBasisConfidence = ref(0)
const pendingInsights = ref([])
const pendingToolSteps = ref([])
const pendingShouldShowReferences = ref(false)
const pendingSelectedBasisQuestions = ref([])
const autoScrollEnabled = ref(true)
const processingSteps = ref([])
const selectedModel = ref('')
const isMobileViewport = () => window.matchMedia('(max-width: 767px)').matches
const sidebarCollapsed = ref(isMobileViewport())
const isRenamingHeader = ref(false)
const headerTitleDraft = ref('')
const headerTitleInput = ref(null)
const pendingNewConversation = ref(null)
const openingMessageText = ref('')

// Rename dialog state
const showRenameDialog = ref(false)
const renameDialogTitle = ref('')
const renameDialogValue = ref('')
const renameDialogCallback = ref(null)

// Thinking state
const isThinking = ref(false)
const thinkingContent = ref('')
const thinkingDuration = ref(0)
const liveThinkingSeconds = ref(0)
let thinkingTimer = null
let activeRequestContext = null

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
  if (pendingNewConversation.value) {
    return openingMessageText.value || '回答面试问题，或输入你想练习的内容...'
  }
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

const displayThinkingDuration = computed(() => {
  return thinkingDuration.value || liveThinkingSeconds.value
})

function startThinkingTimer() {
  stopThinkingTimer()
  liveThinkingSeconds.value = 0
  const startedAt = Date.now()
  thinkingTimer = window.setInterval(() => {
    liveThinkingSeconds.value = Math.max(1, Math.round((Date.now() - startedAt) / 1000))
  }, 250)
}

function stopThinkingTimer() {
  if (thinkingTimer) {
    window.clearInterval(thinkingTimer)
    thinkingTimer = null
  }
}

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

async function loadDefaultModel() {
  if (props.preview) {
    selectedModel.value = 'gpt-4o'
    return
  }
  if (selectedModel.value) return
  try {
    const res = await fetchMyLLMConfig()
    const model = String(res?.settings?.llm_model || '').trim()
    if (model && !selectedModel.value) selectedModel.value = model
  } catch (e) {
    console.warn('加载默认模型失败:', e)
  }
}

// Select conversation
async function selectConversation(id) {
  if (activeRequestContext && activeRequestContext.conversationId !== id) {
    await cancelActiveRequest('conversation_switch', false)
  }
  activeConversationId.value = id
  messages.value = []
  if (isMobileViewport()) sidebarCollapsed.value = true
  try {
    const res = await chatApi.getMessages(id)
    messages.value = res.data || []
    await scrollToBottom()
  } catch (e) {
    console.error('加载消息失败:', e)
  }
}

async function reloadMessages(conversationId) {
  try {
    const res = await chatApi.getMessages(conversationId)
    if (activeConversationId.value === conversationId) {
      messages.value = res.data || []
      await scrollToBottom(true)
    }
  } catch (e) {
    console.error('刷新消息失败:', e)
  }
}

// Create conversation
async function handleCreateConversation(data) {
  if (creatingConversation.value) return
  creatingConversation.value = true
  try {
    if (props.preview) {
      // In preview mode, simulate conversation creation without calling real API
      const newConv = {
        id: `preview-${Date.now()}`,
        title: data.title || (data.mode === 'free_practice' ? '新对话' : 'JD定制面试'),
        mode: data.mode || 'free_practice',
        updated_at: new Date().toISOString(),
      }
      conversations.value.unshift(newConv)
      activeConversationId.value = newConv.id
      messages.value = []
      showNewChat.value = false
      pendingInitialMessage.value = ''
      return
    }

    // 延迟创建：保存配置到前端状态，不调用API
    pendingNewConversation.value = {
      mode: data.mode || 'free_practice',
      title: data.title || null,
      jd_id: data.jd_id || null,
      resume_text: data.resume_text || null,
      difficulty: data.difficulty || 'mid',
      experience_id: data.experience_id || null,
      initial_message: data.initial_message || null,
    }

    // 生成开场白用于placeholder
    openingMessageText.value = data.mode === 'jd_resume'
      ? '请先简单做一下自我介绍吧。'
      : '请先简单做一下自我介绍吧。'

    // 设置临时active状态，显示空聊天界面
    activeConversationId.value = 'pending'
    messages.value = []
    showNewChat.value = false
    pendingInitialMessage.value = ''
  } catch (e) {
    console.error('准备对话失败:', e)
  } finally {
    creatingConversation.value = false
  }
}

// Start with suggestion
async function startWithSuggestion(text) {
  pendingInitialMessage.value = text
  showNewChat.value = true
}

// Send message
async function handleSend({ regenerateMessageId = null } = {}) {
  let text = inputText.value.trim()
  if (regenerateMessageId) {
    const targetIndex = messages.value.findIndex(m => m.id === regenerateMessageId)
    for (let i = targetIndex - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        text = String(messages.value[i].content || '').trim()
        break
      }
    }
  }
  if (!text || isSending.value) return

  // 如果有待创建的对话，先创建对话
  if (pendingNewConversation.value && activeConversationId.value === 'pending') {
    try {
      const createData = {
        ...pendingNewConversation.value,
        first_message: text,
      }
      const res = await chatApi.createConversation(createData)
      if (res.data?.id) {
        // 创建成功，更新状态
        pendingNewConversation.value = null
        openingMessageText.value = ''
        activeConversationId.value = res.data.id
        
        // 刷新对话列表
        await loadConversations()
        
        // 添加用户消息到显示
        messages.value.push({
          id: Date.now(),
          role: 'user',
          content: text,
          created_at: new Date().toISOString(),
        })
        inputText.value = ''
        resetInputHeight()
      }
    } catch (e) {
      console.error('创建对话失败:', e)
      return
    }
  }

  if (!activeConversationId.value || activeConversationId.value === 'pending') return

  // In preview mode, simulate a response without calling real API
  if (props.preview) {
    const userMsg = { id: Date.now(), role: 'user', content: text, created_at: new Date().toISOString() }
    messages.value.push(userMsg)
    inputText.value = ''
    resetInputHeight()
    await scrollToBottom()

    // Simulate a mock response after a short delay
    isSending.value = true
    await new Promise(resolve => setTimeout(resolve, 800))
    const mockResponse = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '这是一个预览模式的模拟回复。在实际使用中，AI 面试官会根据你的回答进行针对性提问。',
      created_at: new Date().toISOString(),
      metadata: {},
    }
    messages.value.push(mockResponse)
    isSending.value = false
    await scrollToBottom()
    return
  }

  const conversationId = activeConversationId.value
  const clientRequestId = globalThis.crypto?.randomUUID
    ? globalThis.crypto.randomUUID()
    : `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
  const context = {
    conversationId,
    clientRequestId,
    turnId: null,
    controller: null,
    stopped: false,
    serverCancelled: false,
  }
  activeRequestContext = context

  inputText.value = ''
  resetInputHeight()
  isSending.value = true
  streamingContent.value = ''
  pendingRetrievedQuestions.value = null
  pendingCandidateQuestions.value = null
  pendingSelectedQuestion.value = null
  pendingQuestionSource.value = null
  pendingQuestionSourceReason.value = null
  pendingBasisType.value = null
  pendingBasisQuestionIds.value = []
  pendingBasisConfidence.value = 0
  pendingShouldShowReferences.value = false
  pendingSelectedBasisQuestions.value = []
  pendingInsights.value = []
  pendingToolSteps.value = []
  processingSteps.value = []
  autoScrollEnabled.value = true

  isThinking.value = false
  thinkingContent.value = ''
  thinkingDuration.value = 0
  liveThinkingSeconds.value = 0
  startThinkingTimer()

  if (!regenerateMessageId) {
    const userMsg = { id: Date.now(), role: 'user', content: text, created_at: new Date().toISOString() }
    messages.value.push(userMsg)
  }
  await scrollToBottom()

  try {
    const finalEvent = await chatApi.sendMessage(
      conversationId,
      text,
      (event) => {
        if (activeRequestContext !== context || activeConversationId.value !== conversationId) return
        if (context.stopped && event.type !== 'cancelled') return

        if (event.type === 'turn_started') {
          context.turnId = event.turn_id || null
          return
        } else if (event.type === 'cancelled') {
          context.serverCancelled = true
          context.stopped = true
          return
        }

        if (event.type === 'step') {
          processingSteps.value.forEach(s => { s.done = true })
          processingSteps.value.push({
            step: event.step,
            message: event.message,
            done: false,
            reason: event.reason || '',
            insight: event.insight || '',
            skill_name: event.skill_name || '',
          })
          scrollToBottom()
        } else if (event.type === 'tool_step') {
          if (event.data) {
            pendingToolSteps.value.push(event.data)
          }
        } else if (event.type === 'thinking_start') {
          isThinking.value = true
          thinkingContent.value = ''
          thinkingDuration.value = 0
          liveThinkingSeconds.value = 0
          startThinkingTimer()
        } else if (event.type === 'thinking') {
          thinkingContent.value += event.content
          scrollToBottom()
        } else if (event.type === 'thinking_done') {
          isThinking.value = false
          thinkingDuration.value = event.duration || 0
          if (thinkingDuration.value > 0) {
            liveThinkingSeconds.value = thinkingDuration.value
          }
          stopThinkingTimer()
        } else if (event.type === 'chunk') {
          // Strip [BASIS] blocks from streaming content to prevent leakage
          const rawContent = event.content
          const cleanedContent = rawContent
            .replace(/\[BASIS\][\s\S]*?\[\/BASIS\]/g, '')
            .replace(/\[BASIS\]\{[^}]*$/g, '')  // Partial [BASIS]{ at end of chunk
            .replace(/^\{[^}]*\}?\[\/BASIS\]/g, '')  // Partial }[/BASIS] at start
          if (event.replace) {
            streamingContent.value = cleanedContent
          } else {
            streamingContent.value += cleanedContent
          }
          scrollToBottom()
        } else if (event.type === 'retrieved') {
          pendingRetrievedQuestions.value = event.questions || []
        } else if (event.type === 'candidates') {
          pendingCandidateQuestions.value = event.questions || []
        } else if (event.type === 'selected_question') {
          pendingSelectedQuestion.value = event.question || null
          pendingQuestionSource.value = event.source || null
          pendingQuestionSourceReason.value = event.reason || null
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
      selectedModel.value || null,
      {
        clientRequestId,
        regenerateMessageId,
        onController: (controller) => {
          if (activeRequestContext === context) context.controller = controller
        },
      }
    )

    if (context.serverCancelled) {
      await reloadMessages(conversationId)
    }

    if (streamingContent.value) {
      const serverMetadata = finalEvent?.metadata && typeof finalEvent.metadata === 'object'
        ? finalEvent.metadata
        : {}
      const metadata = { ...serverMetadata }

      // 从 done 事件中提取 reasoning 相关字段（后端下发）
      for (const key of ['reasoning_trace', 'tool_calls_trace', 'skill_trace', 'steps', 'tool_steps', 'thinking', 'thinking_duration', 'insights']) {
        if (finalEvent?.[key] && !metadata[key]) {
          metadata[key] = finalEvent[key]
        }
      }

      if (pendingRetrievedQuestions.value?.length > 0) {
        metadata.retrieved_questions ||= pendingRetrievedQuestions.value
      }
      if (pendingCandidateQuestions.value?.length > 0) {
        metadata.candidate_questions ||= pendingCandidateQuestions.value
        if (!metadata.retrieved_questions) {
          metadata.retrieved_questions = pendingCandidateQuestions.value
        }
      }
      if (pendingSelectedQuestion.value) {
        metadata.selected_question ||= pendingSelectedQuestion.value
        metadata.question_source ||= pendingQuestionSource.value
        metadata.question_source_reason ||= pendingQuestionSourceReason.value
      }
      if (pendingResumeRef.value) {
        metadata.resume_ref ||= pendingResumeRef.value
      }
      if (pendingJdRef.value) {
        metadata.jd_ref ||= pendingJdRef.value
      }
      // Persist processing steps, merging insights into their preceding step
      if (processingSteps.value.length > 0 && !metadata.steps) {
        const stepsCopy = processingSteps.value.map(s => ({
          step: s.step,
          message: s.message,
          reason: s.reason || '',
          insight: '',
          skill_name: s.skill_name || '',
        }))
        // Merge pending insights into the last tool step (by timing order)
        for (const insight of pendingInsights.value) {
          for (let j = stepsCopy.length - 1; j >= 0; j--) {
            if (['load_skill', 'search_questions', 'draw_questions'].includes(stepsCopy[j].step)) {
              stepsCopy[j].insight = insight.text
              break
            }
          }
        }
        metadata.steps = stepsCopy
      }
      if (pendingToolSteps.value.length > 0 && !metadata.tool_steps && !metadata.tool_calls_trace) {
        metadata.tool_steps = [...pendingToolSteps.value]
      }
      if (thinkingContent.value && !metadata.thinking) {
        metadata.thinking = thinkingContent.value
        metadata.thinking_duration ||= thinkingDuration.value
      }
      if (pendingInsights.value.length > 0) {
        metadata.insights ||= [...pendingInsights.value]
      }
      if (pendingBasisType.value && pendingBasisType.value !== 'none') {
        metadata.basis_type ||= pendingBasisType.value
        metadata.basis_question_ids ||= pendingBasisQuestionIds.value
        metadata.basis_confidence ||= pendingBasisConfidence.value
        metadata.should_show_references ||= pendingShouldShowReferences.value
        if (pendingSelectedBasisQuestions.value?.length > 0) {
          metadata.selected_basis_questions ||= pendingSelectedBasisQuestions.value
        }
      }
      if (regenerateMessageId) {
        await reloadMessages(conversationId)
      } else {
        messages.value.push({
          id: Date.now() + 1,
          role: 'assistant',
          content: streamingContent.value,
          metadata,
          created_at: new Date().toISOString(),
        })
      }
      pendingRetrievedQuestions.value = null
      pendingCandidateQuestions.value = null
      pendingSelectedQuestion.value = null
      pendingQuestionSource.value = null
      pendingQuestionSourceReason.value = null
      pendingResumeRef.value = null
      pendingJdRef.value = null
      pendingInsights.value = []
      pendingToolSteps.value = []
      pendingBasisType.value = null
      pendingBasisQuestionIds.value = []
      pendingBasisConfidence.value = 0
      pendingShouldShowReferences.value = false
      pendingSelectedBasisQuestions.value = []
    }
    if (regenerateMessageId && !streamingContent.value) {
      await reloadMessages(conversationId)
    }
  } catch (e) {
    const code = e?.code || e?.data?.detail?.code || e?.message
    const controlMessages = {
      TURN_IN_PROGRESS: '当前回合仍在生成，请等待完成或先点击停止。',
      TURN_IDEMPOTENCY_CONFLICT: '这条消息已经提交，请勿重复发送。',
      TURN_REQUEST_ALREADY_EXISTS: '这条消息已经提交，请勿重复发送。',
      TURN_NOT_ACTIVE: '当前回合已停止，请重新发送。',
      TURN_NOT_FOUND: '当前回合已失效，请重新发送。',
    }

    if (context.stopped || e?.name === 'AbortError') return
    if (controlMessages[code]) {
      toastError(controlMessages[code])
      return
    }

    console.error('发送消息失败:', e)
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      content: '抱歉，发送消息时出现错误，请稍后重试。',
      created_at: new Date().toISOString(),
    })
  } finally {
    if (activeRequestContext !== context) return
    activeRequestContext = null
    isSending.value = false
    resetTransientStreamState()
    await scrollToBottom()
  }
}

// Regenerate message
async function handleRegenerate(messageId) {
  if (!messages.value.some(message => message.id === messageId)) return
  await handleSend({ regenerateMessageId: messageId })
}

function resetTransientStreamState() {
  streamingContent.value = ''
  isThinking.value = false
  stopThinkingTimer()
  thinkingContent.value = ''
  thinkingDuration.value = 0
  liveThinkingSeconds.value = 0
  pendingRetrievedQuestions.value = null
  pendingCandidateQuestions.value = null
  pendingSelectedQuestion.value = null
  pendingQuestionSource.value = null
  pendingQuestionSourceReason.value = null
  pendingResumeRef.value = null
  pendingJdRef.value = null
  pendingInsights.value = []
  pendingToolSteps.value = []
  pendingBasisType.value = null
  pendingBasisQuestionIds.value = []
  pendingBasisConfidence.value = 0
  pendingShouldShowReferences.value = false
  pendingSelectedBasisQuestions.value = []
  processingSteps.value = []
}

async function cancelActiveRequest(reason = 'client_stop', reload = true) {
  const context = activeRequestContext
  if (!context) return

  context.stopped = true
  try {
    if (context.turnId) {
      await chatApi.cancelTurn(context.conversationId, context.turnId, reason)
    }
  } catch (e) {
    // Disconnecting the SSE still triggers the backend finally block, so a
    // failed cancel request must not prevent the local stream from stopping.
    console.warn('取消当前回合失败，继续中断流:', e)
  } finally {
    context.controller?.abort()
  }

  if (activeRequestContext === context) {
    activeRequestContext = null
    isSending.value = false
    resetTransientStreamState()
  }

  if (reload && activeConversationId.value === context.conversationId) {
    await reloadMessages(context.conversationId)
  }
}

function handleLike({ id, liked }) {
  console.log('Like message:', id, liked)
}

function handleModelSelect(modelId) {
  selectedModel.value = modelId
}

async function handlePin(id) {
  try {
    if (props.preview) {
      // In preview mode, toggle pin locally without calling real API
      const conv = conversations.value.find(c => c.id === id)
      if (conv) conv.pinned = !conv.pinned
      return
    }
    await chatApi.pinConversation(id)
    await loadConversations()
  } catch (e) {
    console.error('置顶对话失败:', e)
  }
}

async function handleRename(id, currentTitle) {
  renameDialogTitle.value = '重命名对话'
  renameDialogValue.value = currentTitle || '新对话'
  showRenameDialog.value = true

  const newTitle = await new Promise((resolve) => {
    renameDialogCallback.value = resolve
  })

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

function handleRenameConfirm() {
  showRenameDialog.value = false
  renameDialogCallback.value?.(renameDialogValue.value)
  renameDialogCallback.value = null
}

function handleRenameCancel() {
  showRenameDialog.value = false
  renameDialogCallback.value?.(null)
  renameDialogCallback.value = null
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
  if (!await showConfirm('确定要删除这个对话吗？')) return
  try {
    if (props.preview) {
      // In preview mode, remove from local list without calling real API
      conversations.value = conversations.value.filter(c => c.id !== id)
      if (activeConversationId.value === id) {
        activeConversationId.value = null
        messages.value = []
      }
      toastSuccess('对话已删除')
      return
    }
    await chatApi.deleteConversation(id)
    if (activeConversationId.value === id) {
      activeConversationId.value = null
      messages.value = []
    }
    await loadConversations()
    toastSuccess('对话已删除')
  } catch (e) {
    console.error('删除对话失败:', e)
    toastError(`删除失败: ${e.message}`)
  }
}

async function handleStop() {
  await cancelActiveRequest('client_stop', true)
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

// Restore active conversation from localStorage (only if no modelValue from URL)
const savedId = localStorage.getItem(STORAGE_KEY_ACTIVE_ID)
if (!props.modelValue && savedId) {
  activeConversationId.value = savedId
}

// Load conversations on mount
onMounted(async () => {
  await loadDefaultModel()
  await loadConversations()

  // Determine which conversation to load: modelValue (URL) takes precedence
  const targetId = props.modelValue || activeConversationId.value
  if (targetId) {
    const exists = conversations.value.some(c => c.id === targetId)
    if (exists) {
      activeConversationId.value = targetId
      try {
        const res = await chatApi.getMessages(targetId)
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
      emit('update:modelValue', id)
    } else {
      localStorage.removeItem(STORAGE_KEY_ACTIVE_ID)
      emit('update:modelValue', null)
    }
  })
})

// Sync external modelValue changes (from URL route param)
// Skip on mount — onMounted already handles initial load
let _mounted = false
onMounted(() => { _mounted = true })
watch(() => props.modelValue, async (newId) => {
  if (!_mounted) return
  if (newId && newId !== activeConversationId.value) {
    await selectConversation(newId)
  }
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

@media (max-width: 767px) {
  .sidebar-container {
    position: absolute;
    inset: 0 auto 0 0;
    width: min(82vw, 256px) !important;
    max-width: calc(100vw - 24px);
    box-shadow: 18px 0 40px rgba(0, 0, 0, 0.12);
    transform: translateX(0);
    transition: transform 220ms ease-out;
  }

  .sidebar-container.sidebar-collapsed {
    transform: translateX(-100%);
    pointer-events: none;
  }
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
