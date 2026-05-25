<template>
  <div class="flex h-[calc(100vh-120px)] bg-white dark:bg-surface-800 rounded-xl border border-surface-200/80 dark:border-ink-700 overflow-hidden">
    <!-- Sidebar -->
    <div class="w-64 shrink-0 border-r border-surface-200/80 dark:border-ink-700 flex flex-col bg-surface-50/50 dark:bg-surface-900/50">
      <!-- New chat button -->
      <div class="p-3">
        <button @click="showNewChat = true"
          class="w-full flex items-center justify-center gap-2 px-3 py-2.5 text-sm font-semibold text-white bg-primary-600 dark:bg-primary-600 rounded-xl hover:bg-primary-700 dark:hover:bg-primary-700 transition">
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
          新建面试
        </button>
      </div>

      <!-- Conversation list -->
      <div class="flex-1 overflow-y-auto custom-scrollbar px-2 pb-2">
        <!-- Loading skeleton -->
        <div v-if="loadingConversations" class="p-3 space-y-2">
          <div v-for="i in 4" :key="i" class="flex items-center gap-2 px-3 py-2.5">
            <div class="flex-1 space-y-1.5">
              <div class="skeleton h-4 rounded" :style="{ width: 50 + Math.random() * 40 + '%' }"></div>
              <div class="skeleton h-2.5 w-16 rounded"></div>
            </div>
          </div>
        </div>
        <div v-else-if="conversations.length === 0" class="empty-state py-8">
          <div class="empty-state-icon">💬</div>
          <p class="empty-state-title">暂无对话</p>
          <p class="empty-state-desc">点击上方按钮开始模拟面试</p>
        </div>
        <div v-else class="space-y-0.5">
          <div v-for="conv in conversations" :key="conv.id"
            @click="selectConversation(conv.id)"
            class="group flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer transition-all text-left"
            :class="activeConversationId === conv.id
              ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400'
              : 'text-ink-600 dark:text-ink-400 hover:bg-surface-100 dark:hover:bg-ink-800'">
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate">{{ conv.title || '新对话' }}</div>
              <div class="text-[10px] mt-0.5" :class="activeConversationId === conv.id ? 'text-primary-400 dark:text-primary-500' : 'text-ink-300 dark:text-ink-600'">
                {{ conv.mode === 'jd_resume' ? 'JD定制' : '自由练习' }} · {{ formatRelativeTime(conv.updated_at) }}
              </div>
            </div>
            <!-- Delete button -->
            <button @click.stop="handleDelete(conv.id)"
              class="opacity-0 group-hover:opacity-100 p-1 rounded-lg text-ink-300 dark:text-ink-600 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition">
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Chat area -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- Empty state -->
      <div v-if="!activeConversationId" class="flex-1 flex items-center justify-center">
        <div
          v-motion
          :initial="{ opacity: 0, y: 16 }"
          :enter="{ opacity: 1, y: 0, transition: { duration: 400, easing: [0.25, 0.46, 0.45, 0.94] } }"
          class="text-center"
        >
          <div class="w-20 h-20 mx-auto mb-5 rounded-2xl bg-surface-100 dark:bg-ink-800 flex items-center justify-center">
            <svg class="w-10 h-10 text-ink-300 dark:text-ink-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/></svg>
          </div>
          <h3 class="text-base font-semibold text-ink-600 dark:text-ink-300 mb-1">开始模拟面试</h3>
          <p class="text-sm text-ink-400 dark:text-ink-500 mb-5">选择一个对话或创建新的面试会话</p>
          <button @click="showNewChat = true"
            class="btn-primary">
            新建面试
          </button>
        </div>
      </div>

      <!-- Active chat -->
      <template v-else>
        <!-- Messages area -->
        <div ref="messagesContainer" class="flex-1 overflow-y-auto custom-scrollbar px-6 py-4 space-y-4">
          <ChatMessage v-for="msg in messages" :key="msg.id" :message="msg" />

          <!-- Streaming message with step timeline -->
          <div v-if="isSending" class="flex items-start gap-3">
            <div class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm font-bold bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400">AI</div>
            <div class="max-w-[75%] min-w-0">
              <!-- Processing steps timeline -->
              <div v-if="!streamingContent && processingSteps.length > 0" class="space-y-0">
                <div v-for="(step, idx) in processingSteps" :key="step.step"
                  class="flex items-center gap-2 py-1.5 transition-all duration-300"
                  :class="idx === processingSteps.length - 1 && !step.done ? 'opacity-100' : 'opacity-60'">
                  <!-- Step icon -->
                  <div class="w-5 h-5 rounded-full flex items-center justify-center shrink-0"
                    :class="step.done ? 'bg-emerald-100 dark:bg-emerald-900/30' : 'bg-primary-100 dark:bg-primary-900/30'">
                    <svg v-if="step.done" class="w-3 h-3 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                    <div v-else class="w-2 h-2 rounded-full bg-primary-500 dark:bg-primary-400 animate-pulse"></div>
                  </div>
                  <!-- Step text -->
                  <span class="text-xs" :class="step.done ? 'text-ink-400 dark:text-ink-500' : 'text-ink-600 dark:text-ink-300 font-medium'">
                    {{ step.message }}
                  </span>
                </div>
              </div>
              <!-- Simple typing indicator (no steps yet) -->
              <div v-else-if="!streamingContent" class="flex items-center gap-1.5 px-1 py-3">
                <div class="flex gap-1">
                  <span class="w-2 h-2 bg-ink-300 dark:bg-ink-500 rounded-full animate-bounce" style="animation-delay: 0ms"></span>
                  <span class="w-2 h-2 bg-ink-300 dark:bg-ink-500 rounded-full animate-bounce" style="animation-delay: 150ms"></span>
                  <span class="w-2 h-2 bg-ink-300 dark:bg-ink-500 rounded-full animate-bounce" style="animation-delay: 300ms"></span>
                </div>
                <span class="text-xs text-ink-400 dark:text-ink-500 ml-1">正在连接...</span>
              </div>
              <!-- Streaming content -->
              <div v-else class="rounded-2xl rounded-tl-md px-4 py-3 text-sm leading-relaxed bg-surface-100 dark:bg-surface-700 text-ink-800 dark:text-ink-100 border border-surface-200/80 dark:border-ink-600">
                <div class="prose-chat" v-html="renderStreamingContent"></div>
                <span class="inline-block w-1.5 h-4 bg-ink-400 dark:bg-ink-300 animate-pulse ml-0.5 align-middle"></span>
              </div>
            </div>
          </div>
        </div>

        <!-- Input area -->
        <div class="shrink-0 border-t border-surface-200/80 dark:border-ink-700 px-6 py-4">
          <form @submit.prevent="handleSend" class="flex gap-3 items-end">
            <textarea ref="inputRef" v-model="inputText"
              :placeholder="inputPlaceholder"
              :disabled="isSending"
              @keydown="onInputKeydown"
              @input="autoResize"
              rows="1"
              class="flex-1 px-4 py-2.5 text-sm border border-surface-300 dark:border-ink-600 rounded-xl bg-white dark:bg-ink-800 text-ink-800 dark:text-ink-100 placeholder-ink-300 dark:placeholder-ink-600 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition disabled:opacity-50 resize-none overflow-hidden"
              style="min-height: 42px; max-height: 160px;"></textarea>
            <!-- Stop button (during streaming) -->
            <button v-if="isSending" type="button" @click="handleStop"
              class="px-3 py-2.5 text-sm font-medium text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl hover:bg-red-100 dark:hover:bg-red-900/30 transition shrink-0"
              title="停止生成">
              <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
            </button>
            <!-- Send button -->
            <button v-else type="submit" :disabled="!inputText.trim()"
              class="px-5 py-2.5 text-sm font-semibold text-white bg-primary-600 dark:bg-primary-600 rounded-xl hover:bg-primary-700 dark:hover:bg-primary-700 transition disabled:opacity-50 disabled:cursor-not-allowed shrink-0">
              发送
            </button>
          </form>
          <div class="text-[10px] text-ink-300 dark:text-ink-600 mt-1.5 text-center">
            Enter 发送，Shift+Enter 换行
          </div>
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
import ChatMessage from './ChatMessage.vue'
import NewChatModal from './NewChatModal.vue'
import * as chatApi from '@/services/chatApi.js'

const props = defineProps({
  jdList: { type: Array, default: () => [] },
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
const autoScrollEnabled = ref(true)
const processingSteps = ref([])

const inputPlaceholder = computed(() => {
  const conv = conversations.value.find(c => c.id === activeConversationId.value)
  if (conv?.mode === 'jd_resume') return '回答面试问题，或输入你想练习的内容...'
  return '回答面试问题，或输入你想练习的内容...'
})

const renderStreamingContent = computed(() => {
  if (!streamingContent.value) return ''
  return renderSafeMarkdown(streamingContent.value)
})

// Load conversations
async function loadConversations() {
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
        // Mark previous steps as done
        processingSteps.value.forEach(s => { s.done = true })
        processingSteps.value.push({ step: event.step, message: event.message, done: false })
        scrollToBottom()
      } else if (event.type === 'chunk') {
        streamingContent.value += event.content
        scrollToBottom()
      } else if (event.type === 'retrieved') {
        pendingRetrievedQuestions.value = event.questions || []
      }
    })

    // Streaming done - add final message
    if (streamingContent.value) {
      const metadata = {}
      if (pendingRetrievedQuestions.value?.length > 0) {
        metadata.retrieved_questions = pendingRetrievedQuestions.value
      }
      messages.value.push({
        id: Date.now() + 1,
        role: 'assistant',
        content: streamingContent.value,
        metadata,
        created_at: new Date().toISOString(),
      })
      pendingRetrievedQuestions.value = null
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
  // Smart auto-scroll listener
  watch(activeConversationId, () => {
    autoScrollEnabled.value = true
  })
})
</script>

<style scoped>
/* prose-chat styles are now in global.css */
</style>
