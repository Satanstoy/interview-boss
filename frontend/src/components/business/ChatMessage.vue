<template>
  <div class="flex items-start gap-3" :class="isUser ? 'flex-row-reverse' : ''">
    <!-- Avatar -->
    <div class="size-8 rounded-full flex items-center justify-center shrink-0 text-xs font-semibold border"
      :class="isUser
        ? 'bg-primary text-primary-foreground border-primary'
        : 'bg-white dark:bg-ink-800 text-ink-700 dark:text-ink-200 border-surface-200 dark:border-ink-700'">
      {{ isUser ? '你' : 'AI' }}
    </div>

    <!-- Message bubble -->
    <div class="max-w-[75%] min-w-0 group">
      <!-- Thinking block (for saved messages with thinking metadata) -->
      <ThinkingBlock
        v-if="!isUser && message.metadata?.thinking"
        :is-streaming="false"
        :content="message.metadata.thinking"
        :duration="message.metadata.thinking_duration || 0"
      />

      <div class="rounded-xl px-4 py-3 text-sm leading-relaxed relative shadow-sm"
        :class="isUser
          ? 'bg-primary text-primary-foreground rounded-tr-md'
          : 'bg-white dark:bg-surface-900 text-ink-800 dark:text-ink-100 rounded-tl-md border border-surface-200 dark:border-ink-800'">
        <div v-if="isUser" class="prose-chat" v-html="renderedContent"></div>
        <div v-else class="prose-chat" v-html="renderedContent"></div>
      </div>

      <!-- Message actions (AI messages only) -->
      <div v-if="!isUser && message.content" class="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button @click="copyContent" class="p-1 rounded-md text-ink-300 dark:text-ink-600 hover:text-ink-500 dark:hover:text-ink-400 hover:bg-surface-100 dark:hover:bg-ink-800 transition" title="复制">
          <svg v-if="!copied" class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
          <svg v-else class="size-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
        </button>
      </div>

      <!-- Retrieved questions -->
      <div v-if="!isUser && message.metadata?.retrieved_questions?.length" class="mt-2">
        <button @click="showRetrieved = !showRetrieved"
          class="text-[11px] text-ink-400 dark:text-ink-500 hover:text-ink-600 dark:hover:text-ink-300 flex items-center gap-1.5 transition group/sources">
          <svg class="size-3 transition-transform" :class="showRetrieved ? 'rotate-90' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
          </svg>
          <svg class="size-3 text-primary-400 dark:text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/></svg>
          <span class="group-hover/sources:text-ink-600 dark:group-hover/sources:text-ink-300">参考题目 ({{ message.metadata.retrieved_questions.length }})</span>
        </button>
        <Transition name="expand">
          <div v-if="showRetrieved" class="mt-1.5 flex flex-col gap-1.5">
            <div v-for="q in message.metadata.retrieved_questions" :key="q.id"
              class="text-xs bg-white dark:bg-surface-900 border border-surface-200 dark:border-ink-800 rounded-lg px-3 py-2 text-ink-600 dark:text-ink-300 hover:bg-surface-50 dark:hover:bg-ink-800/50 transition-colors">
              <div class="flex items-start gap-2">
                <span v-if="q.cat1" class="text-primary-600 dark:text-primary-400 font-medium shrink-0">[{{ q.cat1 }}]</span>
                <span class="flex-1">{{ q.question }}</span>
              </div>
              <div v-if="q.source || q.company" class="mt-1 flex items-center gap-1.5 text-[10px] text-ink-400 dark:text-ink-500">
                <svg class="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                <span>{{ q.company || '未知来源' }}{{ q.round ? ' · ' + q.round : '' }}</span>
              </div>
            </div>
          </div>
        </Transition>
      </div>

      <!-- Resume reference -->
      <div v-if="!isUser && message.metadata?.resume_ref" class="mt-2">
        <div class="flex items-center gap-1.5 text-[11px] text-ink-400 dark:text-ink-500 bg-amber-50/60 dark:bg-amber-900/15 border border-amber-100 dark:border-amber-800/30 rounded-lg px-3 py-1.5">
          <svg class="size-3 text-amber-500 dark:text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
          <span class="font-medium text-amber-600 dark:text-amber-400">参考简历：</span>
          <span>{{ message.metadata.resume_ref }}</span>
        </div>
      </div>

      <!-- JD reference -->
      <div v-if="!isUser && message.metadata?.jd_ref" class="mt-2">
        <div class="flex items-center gap-1.5 text-[11px] text-ink-400 dark:text-ink-500 bg-blue-50/60 dark:bg-blue-900/15 border border-blue-100 dark:border-blue-800/30 rounded-lg px-3 py-1.5">
          <svg class="size-3 text-blue-500 dark:text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
          <span class="font-medium text-blue-600 dark:text-blue-400">参考 JD：</span>
          <span>{{ message.metadata.jd_ref }}</span>
        </div>
      </div>

      <!-- Timestamp -->
      <div class="text-[10px] text-ink-300 dark:text-ink-600 mt-1" :class="isUser ? 'text-right' : ''">
        {{ formatTime(message.created_at) }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import ThinkingBlock from './ThinkingBlock.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const isUser = computed(() => props.message.role === 'user')
const showRetrieved = ref(false)
const copied = ref(false)

const renderedContent = computed(() => {
  return renderSafeMarkdown(props.message.content)
})

async function copyContent() {
  try {
    await navigator.clipboard.writeText(props.message.content || '')
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch { /* ignore */ }
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts + (ts.includes('Z') || ts.includes('+') ? '' : 'Z'))
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
/* Expand transition for retrieved questions */
.expand-enter-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.expand-leave-active {
  transition: all 0.2s ease-out;
}
.expand-enter-from {
  opacity: 0;
  transform: translateY(-8px) scaleY(0.95);
  max-height: 0;
}
.expand-leave-to {
  opacity: 0;
  transform: translateY(-4px) scaleY(0.98);
  max-height: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 500px;
}
</style>
