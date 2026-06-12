<template>
  <div class="mb-8 group">
    <!-- User message -->
    <div v-if="isUser" class="flex justify-end">
      <div class="max-w-[80%]">
        <div class="bg-primary/10 rounded-2xl rounded-tr-md px-4 py-3">
          <div class="prose-chat text-sm" v-html="renderedContent"></div>
        </div>
        <div class="text-[11px] text-muted-foreground mt-1 text-right">
          {{ formatTime(message.created_at) }}
        </div>
      </div>
    </div>

    <!-- Assistant message -->
    <div v-else>
      <!-- Thinking block -->
      <ThinkingBlock
        v-if="message.metadata?.thinking"
        :is-streaming="false"
        :content="message.metadata.thinking"
        :duration="message.metadata.thinking_duration || 0"
      />

      <!-- Message content -->
      <div class="prose-chat text-sm leading-relaxed">
        <div v-html="renderedContent"></div>
      </div>

      <!-- Message actions -->
      <div class="flex items-center gap-1 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
        <button 
          @click="copyContent" 
          class="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors" 
          title="复制"
        >
          <Copy v-if="!copied" :size="14" />
          <Check v-else :size="14" class="text-emerald-500" />
        </button>
        <button 
          @click="$emit('regenerate', message.id)" 
          class="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors" 
          title="重新生成"
        >
          <RotateCcw :size="14" />
        </button>
        <button 
          @click="toggleLike" 
          class="p-1.5 rounded-md transition-colors"
          :class="liked ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
          title="点赞"
        >
          <ThumbsUp :size="14" />
        </button>
        <span class="text-[11px] text-muted-foreground ml-2">{{ formatTime(message.created_at) }}</span>
      </div>

      <!-- Citations: Sources -->
      <div v-if="hasAnyReference" class="mt-4 pt-4 border-t border-border/50">
        <!-- Basis questions (new format) -->
        <div v-if="basisQuestions.length" class="mb-3">
          <button 
            @click="showRetrieved = !showRetrieved"
            class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <BookOpen :size="14" class="text-primary" />
            <span class="font-medium">依据了 {{ basisQuestions.length }} 个题目</span>
            <ChevronDown :size="14" class="transition-transform" :class="showRetrieved ? 'rotate-180' : ''" />
          </button>
          
          <Transition name="expand">
            <div v-if="showRetrieved" class="mt-2 flex flex-col gap-2">
              <div 
                v-for="q in basisQuestions" 
                :key="q.id"
                class="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50 hover:bg-muted/50 transition-colors"
              >
                <div class="size-8 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <span class="text-xs font-bold text-primary">{{ q.cat1?.[0] || 'Q' }}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-foreground">{{ q.question }}</div>
                  <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <span v-if="q.company" class="font-medium">{{ q.company }}</span>
                    <span v-if="q.round">{{ q.round }}</span>
                    <span v-if="q.cat1" class="text-primary">[{{ q.cat1 }}]</span>
                  </div>
                </div>
              </div>
            </div>
          </Transition>
        </div>

        <!-- Resume reference -->
        <div v-if="message.metadata?.resume_ref" class="flex items-center gap-2 text-xs text-muted-foreground mb-2">
          <FileText :size="14" class="text-amber-500 shrink-0" />
          <span>参考简历：</span>
          <span class="text-foreground font-medium truncate">{{ message.metadata.resume_ref }}</span>
        </div>

        <!-- JD reference -->
        <div v-if="message.metadata?.jd_ref" class="flex items-center gap-2 text-xs text-muted-foreground">
          <Briefcase :size="14" class="text-blue-500 shrink-0" />
          <span>参考 JD：</span>
          <span class="text-foreground font-medium truncate">{{ message.metadata.jd_ref }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { 
  Copy, 
  Check, 
  RotateCcw, 
  ThumbsUp, 
  ChevronDown, 
  BookOpen, 
  FileText, 
  Briefcase 
} from '@lucide/vue'
import ThinkingBlock from './ThinkingBlock.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['regenerate', 'like'])

const isUser = computed(() => props.message.role === 'user')
const showRetrieved = ref(false)
const copied = ref(false)
const liked = ref(false)

const hasAnyReference = computed(() => {
  const m = props.message.metadata
  // Only show references when should_show_references=true AND selected_basis_questions non-empty
  if (m?.should_show_references && m?.selected_basis_questions?.length) return true
  // Resume/JD refs
  return m?.resume_ref || m?.jd_ref
})

const basisQuestions = computed(() => {
  const m = props.message.metadata
  // Only use selected_basis_questions (no fallback to retrieved_questions)
  if (m?.selected_basis_questions?.length) return m.selected_basis_questions
  return []
})

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

function toggleLike() {
  liked.value = !liked.value
  emit('like', { id: props.message.id, liked: liked.value })
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts + (ts.includes('Z') || ts.includes('+') ? '' : 'Z'))
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.expand-enter-active {
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.expand-leave-active {
  transition: all 0.2s ease-out;
}
.expand-enter-from {
  opacity: 0;
  transform: translateY(-8px);
  max-height: 0;
}
.expand-leave-to {
  opacity: 0;
  transform: translateY(-4px);
  max-height: 0;
}
.expand-enter-to,
.expand-leave-from {
  max-height: 500px;
}
</style>
