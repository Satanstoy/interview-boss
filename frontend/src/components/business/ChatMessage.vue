<template>
  <div class="mb-8 group">
    <!-- User message -->
    <div v-if="isUser" class="flex justify-end">
      <div class="max-w-[80%]">
        <div class="bg-primary/10 rounded-xl rounded-tr-md px-4 py-3">
          <div class="prose-chat text-sm" v-html="renderedContent"></div>
        </div>
        <div class="text-[11px] text-muted-foreground mt-1 text-right">
          {{ formatTime(message.created_at) }}
        </div>
      </div>
    </div>

    <!-- Assistant message -->
    <div v-else>
      <!-- Reasoning timeline (unified: steps + thinking) -->
      <ReasoningTimeline
        v-if="timelineSteps.length || timelineToolSteps.length || message.metadata?.thinking"
        :is-streaming="false"
        :content="thinkingContent"
        :duration="message.metadata?.thinking_duration || 0"
        :steps="timelineSteps"
        :tool-steps="timelineToolSteps"
      />

      <!-- Fallback: legacy insight-only messages (no steps, has insights) -->
      <InsightBlock
        v-else-if="message.metadata?.insights?.length"
        :items="message.metadata.insights"
        :is-streaming="false"
      />

      <!-- Message content -->
      <div class="prose-chat text-sm leading-relaxed">
        <div v-html="renderedContent"></div>
      </div>

      <!-- Message actions -->
      <div class="flex items-center gap-1 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
        <AppTooltip text="复制">
          <button 
            @click="copyContent" 
            class="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors" 
          >
            <Copy v-if="!copied" :size="14" />
            <Check v-else :size="14" class="text-emerald-500" />
          </button>
        </AppTooltip>
        <AppTooltip text="重新生成">
          <button 
            @click="$emit('regenerate', message.id)" 
            class="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors" 
          >
            <RotateCcw :size="14" />
          </button>
        </AppTooltip>
        <AppTooltip text="点赞">
          <button 
            @click="toggleLike" 
            class="p-1.5 rounded-md transition-colors"
            :class="liked ? 'text-primary bg-primary/10' : 'text-muted-foreground hover:text-foreground hover:bg-muted'"
          >
            <ThumbsUp :size="14" />
          </button>
        </AppTooltip>
        <span class="text-[11px] text-muted-foreground ml-2">{{ formatTime(message.created_at) }}</span>
      </div>

      <!-- Citations: Sources -->
      <div v-if="hasAnyReference" class="mt-4 pt-4 border-t border-border/50">
        <!-- Selected question -->
        <div v-if="selectedQuestion" class="mb-3">
          <div class="flex items-center gap-2 text-xs text-muted-foreground mb-2">
            <BookOpen :size="14" class="text-primary" />
            <span class="font-medium">本轮采用题</span>
            <span v-if="message.metadata?.question_source" class="text-muted-foreground">
              {{ message.metadata.question_source === 'draw' ? '抽题' : message.metadata.question_source === 'search' ? '检索' : '上下文追问' }}
            </span>
          </div>
          <div class="flex items-start gap-3 p-3 rounded-lg bg-primary/5 border border-primary/20">
            <div class="size-8 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
              <span class="text-xs font-bold text-primary">{{ selectedQuestion.cat1?.[0] || 'Q' }}</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm text-foreground">{{ selectedQuestion.question }}</div>
              <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                <span v-if="selectedQuestion.company" class="font-medium">{{ selectedQuestion.company }}</span>
                <span v-if="selectedQuestion.round">{{ selectedQuestion.round }}</span>
                <span v-if="selectedQuestion.cat1" class="text-primary">[{{ selectedQuestion.cat1 }}]</span>
              </div>
            </div>
          </div>
        </div>

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

        <!-- Retrieved candidate questions -->
        <div v-if="retrievedQuestions.length" class="mb-3">
          <button
            @click="showCandidates = !showCandidates"
            class="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <BookOpen :size="14" class="text-sky-500" />
            <span class="font-medium">检索到 {{ retrievedQuestions.length }} 个候选题</span>
            <ChevronDown :size="14" class="transition-transform" :class="showCandidates ? 'rotate-180' : ''" />
          </button>

          <Transition name="expand">
            <div v-if="showCandidates" class="mt-2 flex flex-col gap-2">
              <div
                v-for="q in retrievedQuestions"
                :key="q.id || q.question"
                class="flex items-start gap-3 p-3 rounded-lg bg-sky-500/5 border border-sky-500/20 hover:bg-sky-500/10 transition-colors"
              >
                <div class="size-8 rounded-md bg-sky-500/10 flex items-center justify-center shrink-0">
                  <span class="text-xs font-bold text-sky-600 dark:text-sky-400">{{ q.cat1?.[0] || 'Q' }}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-foreground">{{ q.question }}</div>
                  <div class="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                    <span v-if="q.company" class="font-medium">{{ q.company }}</span>
                    <span v-if="q.round">{{ q.round }}</span>
                    <span v-if="q.cat1" class="text-sky-600 dark:text-sky-400">[{{ q.cat1 }}]</span>
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
import ReasoningTimeline from './ReasoningTimeline.vue'
import InsightBlock from './InsightBlock.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['regenerate', 'like'])

const isUser = computed(() => props.message.role === 'user')
const showRetrieved = ref(false)
const showCandidates = ref(false)
const copied = ref(false)
const liked = ref(false)

const hasAnyReference = computed(() => {
  const m = props.message.metadata
  // Only show references when should_show_references=true AND selected_basis_questions non-empty
  if (m?.should_show_references && m?.selected_basis_questions?.length) return true
  if (m?.selected_question) return true
  if (m?.retrieved_questions?.length) return true
  if (m?.candidate_questions?.length) return true
  // Resume/JD refs
  return m?.resume_ref || m?.jd_ref
})

const selectedQuestion = computed(() => props.message.metadata?.selected_question || null)

const basisQuestions = computed(() => {
  const m = props.message.metadata
  // Only use selected_basis_questions (no fallback to retrieved_questions)
  if (m?.selected_basis_questions?.length) return m.selected_basis_questions
  return []
})

const retrievedQuestions = computed(() => {
  const m = props.message.metadata
  const retrieved = m?.candidate_questions || m?.retrieved_questions || []
  if (!retrieved.length) return []
  const basisIds = new Set((m?.selected_basis_questions || []).map(q => q.id))
  if (m?.selected_question?.id) basisIds.add(m.selected_question.id)
  return retrieved.filter(q => !basisIds.has(q.id))
})

const skillLabels = {
  'project-deep-dive': '项目深挖',
  'theory-qa': '八股基础',
  'algorithm-coding': '算法手撕',
  'system-design': '系统设计',
  'hr-soft-skills': '行为面',
  'interview-rhythm': '面试节奏',
  'adaptive-difficulty': '难度调整',
}

const toolLabels = {
  load_skill: '加载策略',
  search_questions: '检索题库',
  draw_questions: '抽取题目',
  select_question: '采用题目',
}

const timelineSteps = computed(() => {
  const metadata = props.message.metadata || {}
  const steps = Array.isArray(metadata.steps) ? metadata.steps : []
  return steps.map(step => {
    const skillName = step.skill_name
    const skillLabel = skillLabels[skillName] || skillName
    return {
      ...step,
      message: step.step === 'load_skill' && skillLabel
        ? `${step.message}（${skillLabel}）`
        : step.message,
    }
  })
})

const timelineToolSteps = computed(() => {
  const metadata = props.message.metadata || {}
  const toolSteps = Array.isArray(metadata.tool_steps) ? metadata.tool_steps : []
  return toolSteps.map(toolStep => {
    const label = toolLabels[toolStep.tool_name] || toolStep.tool_name || toolStep.step
    return {
      message: label,
      elapsed_ms: toolStep.elapsed_ms,
      result_count: toolStep.result_count,
      done: true,
    }
  })
})

const thinkingContent = computed(() => {
  const thinking = props.message.metadata?.thinking
  if (!thinking) return ''

  // Old format: string
  if (typeof thinking === 'string') return thinking

  // New format: array of chunks
  if (Array.isArray(thinking)) {
    return thinking
      .map(t => t.chunks?.join('') || '')
      .filter(Boolean)
      .join('\n')
  }

  return ''
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
