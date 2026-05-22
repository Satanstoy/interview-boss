<template>
  <div class="flex items-start gap-3" :class="isUser ? 'flex-row-reverse' : ''">
    <!-- Avatar -->
    <div class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-sm font-bold"
      :class="isUser
        ? 'bg-primary-100 dark:bg-primary-900/40 text-primary-700 dark:text-primary-400'
        : 'bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-400'">
      {{ isUser ? '你' : 'AI' }}
    </div>

    <!-- Message bubble -->
    <div class="max-w-[75%] min-w-0 group">
      <div class="rounded-2xl px-4 py-3 text-sm leading-relaxed relative"
        :class="isUser
          ? 'bg-primary-600 dark:bg-primary-700 text-white rounded-tr-md'
          : 'bg-surface-100 dark:bg-surface-700 text-ink-800 dark:text-ink-100 rounded-tl-md border border-surface-200/80 dark:border-ink-600'">
        <div v-if="isUser" class="whitespace-pre-wrap">{{ message.content }}</div>
        <div v-else class="prose-chat" v-html="renderedContent"></div>
      </div>

      <!-- Message actions (AI messages only) -->
      <div v-if="!isUser && message.content" class="flex items-center gap-1 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button @click="copyContent" class="p-1 rounded-md text-ink-300 dark:text-ink-600 hover:text-ink-500 dark:hover:text-ink-400 hover:bg-surface-100 dark:hover:bg-ink-800 transition" title="复制">
          <svg v-if="!copied" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
          <svg v-else class="w-3.5 h-3.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
        </button>
      </div>

      <!-- Retrieved questions -->
      <div v-if="!isUser && message.metadata?.retrieved_questions?.length" class="mt-2">
        <button @click="showRetrieved = !showRetrieved"
          class="text-[11px] text-ink-400 dark:text-ink-500 hover:text-ink-600 dark:hover:text-ink-300 flex items-center gap-1 transition">
          <svg class="w-3 h-3 transition-transform" :class="showRetrieved ? 'rotate-90' : ''" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
          </svg>
          参考题目 ({{ message.metadata.retrieved_questions.length }})
        </button>
        <div v-if="showRetrieved" class="mt-1.5 space-y-1">
          <div v-for="q in message.metadata.retrieved_questions" :key="q.id"
            class="text-xs bg-primary-50/60 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800 rounded-lg px-3 py-2 text-ink-600 dark:text-ink-300">
            <span v-if="q.cat1" class="text-primary-600 dark:text-primary-400 font-medium">[{{ q.cat1 }}]</span>
            {{ q.question }}
          </div>
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
import { marked } from 'marked'
import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import python from 'highlight.js/lib/languages/python'
import java from 'highlight.js/lib/languages/java'
import sql from 'highlight.js/lib/languages/sql'
import bash from 'highlight.js/lib/languages/bash'
import json from 'highlight.js/lib/languages/json'
import css from 'highlight.js/lib/languages/css'
import xml from 'highlight.js/lib/languages/xml'
import typescript from 'highlight.js/lib/languages/typescript'
import DOMPurify from 'dompurify'
import 'highlight.js/styles/github-dark.css'

// Register only common languages to keep bundle small
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('js', javascript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('py', python)
hljs.registerLanguage('java', java)
hljs.registerLanguage('sql', sql)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('shell', bash)
hljs.registerLanguage('json', json)
hljs.registerLanguage('css', css)
hljs.registerLanguage('html', xml)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('ts', typescript)

const props = defineProps({
  message: { type: Object, required: true },
})

const isUser = computed(() => props.message.role === 'user')
const showRetrieved = ref(false)
const copied = ref(false)

// Configure marked with highlight.js for code syntax highlighting
marked.setOptions({
  highlight: (code, lang) => {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(code, { language: lang }).value } catch { /* ignore */ }
    }
    return hljs.highlightAuto(code).value
  },
  breaks: true,
  gfm: true,
})

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  const html = marked.parse(props.message.content)
  return DOMPurify.sanitize(html)
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
/* prose-chat styles are now in global.css */
</style>
