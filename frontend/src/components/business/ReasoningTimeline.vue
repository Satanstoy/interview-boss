<template>
  <div class="mb-4">
    <!-- Trigger button -->
    <button
      @click="isOpen = !isOpen"
      class="flex items-center gap-2 text-xs text-muted-foreground/70 hover:text-muted-foreground transition-colors select-none"
    >
      <!-- Spinner while streaming -->
      <Loader2 v-if="isStreaming" :size="14" class="animate-spin" />
      <!-- Lightbulb when complete -->
      <Lightbulb v-else :size="14" />

      <span>{{ displayLabel }}</span>

      <!-- Pulsing ellipsis while streaming -->
      <span v-if="isStreaming && !isOpen" class="inline-flex gap-0.5">
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
        <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
      </span>

      <!-- Chevron -->
      <ChevronDown v-else :size="14" class="transition-transform duration-200" :class="{ 'rotate-180': isOpen }" />
    </button>

    <!-- Collapsible content -->
    <Transition name="expand">
      <div v-show="isOpen" class="mt-2">
        <!-- Connected timeline -->
        <div v-if="timelineItems.length > 0" class="mb-3">
          <div
            v-for="(item, i) in timelineItems"
            :key="item.key"
            class="reasoning-timeline-item relative pl-7 pb-1 last:pb-0"
          >
            <span
              v-if="i < timelineItems.length - 1"
              class="reasoning-timeline-connector absolute top-5 bottom-[-4px] bg-border"
              aria-hidden="true"
            />
            <span
              class="reasoning-timeline-marker absolute top-1.5 flex items-center justify-center rounded-full bg-background ring-1 ring-border"
              :class="item.done ? 'text-emerald-500' : 'text-muted-foreground'"
              aria-hidden="true"
            >
              <Loader2 v-if="!item.done" :size="11" class="animate-spin" />
              <Brain v-else-if="item.type === 'skill'" :size="11" class="text-primary" />
              <Wrench v-else-if="item.type === 'tool'" :size="11" class="text-sky-500" />
              <CheckCircle2 v-else :size="11" />
            </span>
            <button
              @click="toggleTimelineItem(item)"
              class="flex items-center gap-2 w-full min-h-7 text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
            >
              <span class="text-muted-foreground flex-1">
                {{ item.title }}
                <span v-if="item.subtitle" class="text-primary ml-1">({{ item.subtitle }})</span>
              </span>
              <span v-if="item.meta" class="text-xs text-muted-foreground/50">{{ item.meta }}</span>
              <ChevronDown
                v-if="item.expandable"
                :size="12"
                class="text-muted-foreground/50 shrink-0 transition-transform duration-200"
                :class="{ 'rotate-180': isTimelineItemExpanded(item) }"
              />
            </button>

            <Transition name="expand">
              <div v-if="isTimelineItemExpanded(item) && item.type === 'step'" class="pr-2 pb-1">
                <p v-if="item.payload.reason" class="text-xs text-muted-foreground/60 leading-relaxed">
                  {{ item.payload.reason }}
                </p>
                <p v-if="item.payload.insight" class="text-xs text-amber-600/70 dark:text-amber-400/70 mt-0.5 flex items-center gap-1">
                  <Lightbulb :size="10" />
                  {{ item.payload.insight }}
                </p>
              </div>
            </Transition>
            <Transition name="expand">
              <div v-if="isTimelineItemExpanded(item) && item.type === 'skill'" class="pr-2 pb-1">
                <p class="text-xs text-muted-foreground/60 leading-relaxed">{{ item.payload.reason }}</p>
              </div>
            </Transition>
            <Transition name="expand">
              <div
                v-if="isTimelineItemExpanded(item) && item.type === 'tool'"
                class="mr-2 mb-1 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
              >
                <div v-if="item.payload.summary" class="mb-2 leading-relaxed">{{ item.payload.summary }}</div>

                <div v-if="argEntries(item.payload).length" class="mb-2">
                  <div class="text-[11px] font-medium text-foreground/70 mb-1">参数</div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="entry in argEntries(item.payload)"
                      :key="entry.key"
                      class="rounded-md bg-background/70 border border-border/50 px-2 py-0.5"
                    >
                      {{ formatArgLabel(entry.key) }}：{{ formatValue(entry.value) }}
                    </span>
                  </div>
                </div>

                <div v-if="resultPreview(item.payload).length">
                  <div class="text-[11px] font-medium text-foreground/70 mb-1">结果</div>
                  <div class="space-y-1.5">
                    <div
                      v-for="result in resultPreview(item.payload)"
                      :key="result.id || result.question || result.title"
                      class="rounded-md bg-background/70 border border-border/50 px-2 py-1.5"
                    >
                      <div class="text-foreground/90 leading-relaxed">{{ result.question || result.title || result.name || `结果 ${result.id}` }}</div>
                      <div v-if="resultMeta(result)" class="mt-0.5 text-[11px] text-muted-foreground/60">{{ resultMeta(result) }}</div>
                    </div>
                  </div>
                </div>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Public reasoning summary -->
        <div v-if="content" ref="contentRef"
          class="text-xs leading-relaxed text-muted-foreground/70 max-h-[300px] overflow-y-auto whitespace-pre-wrap break-words p-3 rounded-lg bg-muted/30 border border-border/50"
        >{{ content }}</div>

        <!-- Pulsing ellipsis at bottom while streaming -->
        <div v-if="isStreaming" class="flex justify-center mt-2">
          <span class="inline-flex gap-0.5">
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 0ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 200ms"></span>
            <span class="size-1 rounded-full bg-muted-foreground/50 animate-pulse" style="animation-delay: 400ms"></span>
          </span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { Loader2, Lightbulb, ChevronDown, CheckCircle2, Wrench, Brain } from '@lucide/vue'

const props = defineProps({
  isStreaming: { type: Boolean, default: false },
  isSending: { type: Boolean, default: false },
  content: { type: String, default: '' },
  duration: { type: Number, default: 0 },
  steps: { type: Array, default: () => [] },
  toolSteps: { type: Array, default: () => [] },
  skillSteps: { type: Array, default: () => [] },
})

const isOpen = ref(true)
const contentRef = ref(null)
const expandedTimelineItems = reactive({})

const hiddenStepNames = new Set(['loading', 'context'])
const visibleSteps = computed(() => props.steps.filter(step => !hiddenStepNames.has(step?.step)))

const stepCount = computed(() => visibleSteps.value.length)
const toolCount = computed(() => props.toolSteps.length)
const skillCount = computed(() => props.skillSteps.length)

const timelineItems = computed(() => [
  ...visibleSteps.value.map((step, index) => ({
    key: `step-${index}-${step.step || step.message || ''}`,
    type: 'step',
    title: step.message,
    subtitle: step.skill_name || '',
    meta: '',
    done: step.done !== false,
    expandable: Boolean(step.reason || step.insight),
    payload: step,
  })),
  ...props.skillSteps.map((skill, index) => ({
    key: `skill-${index}-${skill.skill_name || skill.label || ''}`,
    type: 'skill',
    title: skill.label || skill.skill_name,
    subtitle: '',
    meta: skill.status ? formatStatus(skill.status) : '',
    done: skill.status !== 'running',
    expandable: Boolean(skill.reason),
    payload: skill,
  })),
  ...props.toolSteps.map((step, index) => ({
    key: `tool-${index}-${step.tool_name || step.label || step.message || ''}`,
    type: 'tool',
    title: step.label || step.message,
    subtitle: '',
    meta: formatToolMeta(step),
    done: step.done !== false,
    expandable: hasToolDetails(step),
    payload: step,
  })),
])

const displayLabel = computed(() => {
  if (props.isStreaming || (props.isSending && props.duration > 0 && !props.content)) {
    return `面试官推理中 ${formatDuration(props.duration)}`
  }
  if (props.isSending && props.duration <= 0) return '面试官推理中'
  const parts = []
  if (props.duration > 0) parts.push(`面试官推理了 ${formatDuration(props.duration)}`)
  if (stepCount.value > 0) parts.push(`${stepCount.value} 步`)
  if (toolCount.value > 0) parts.push(`${toolCount.value} 次工具`)
  if (skillCount.value > 0) parts.push(`${skillCount.value} 个策略`)
  return parts.length > 0 ? parts.join(' · ') : '面试官推理过程'
})

function formatDuration(duration) {
  const value = Number(duration) || 0
  if (value <= 0) return '0 秒'
  return `${Number.isInteger(value) ? value : value.toFixed(1)} 秒`
}

function toggleTimelineItem(item) {
  if (!item.expandable) return
  expandedTimelineItems[item.key] = !expandedTimelineItems[item.key]
}

function isTimelineItemExpanded(item) {
  return Boolean(expandedTimelineItems[item.key])
}

function hasToolDetails(step) {
  return Boolean(step.summary || argEntries(step).length || resultPreview(step).length)
}

function formatToolMeta(step) {
  const parts = []
  if (step.elapsed_ms) parts.push(`${step.elapsed_ms}ms`)
  if (step.result_count !== undefined) parts.push(`${step.result_count} 结果`)
  return parts.join(' · ')
}

function argEntries(step) {
  if (!step?.args || typeof step.args !== 'object' || Array.isArray(step.args)) return []
  return Object.entries(step.args).filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => ({ key, value }))
}

function resultPreview(step) {
  return Array.isArray(step?.result_preview) ? step.result_preview : []
}

function formatArgLabel(key) {
  const labels = {
    keywords: '关键词',
    query: '查询',
    limit: '数量',
    category: '分类',
    skill_name: '策略',
  }
  return labels[key] || key
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join('、')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function formatStatus(status) {
  const labels = {
    loaded: '已加载',
    success: '成功',
    error: '失败',
    skipped: '跳过',
  }
  return labels[status] || status
}

function resultMeta(item) {
  const parts = [item.company, item.round, item.cat1, item.cat2].filter(Boolean)
  return parts.join(' · ')
}

watch(() => props.content, () => {
  if (contentRef.value && isOpen.value) {
    contentRef.value.scrollTop = contentRef.value.scrollHeight
  }
})

// Collapse only when the entire message is done (not just thinking done)
watch(() => props.isSending, (sending, oldSending) => {
  if (oldSending && !sending && (props.content || visibleSteps.value.length > 0 || props.toolSteps.length > 0 || props.skillSteps.length > 0)) {
    setTimeout(() => {
      isOpen.value = false
    }, 1000)
  }
})

onMounted(() => {
  if ((props.content || visibleSteps.value.length > 0 || props.toolSteps.length > 0 || props.skillSteps.length > 0) && !props.isSending) {
    isOpen.value = false
  }
})
</script>

<style scoped>
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 600px;
}

.reasoning-timeline-item {
  --timeline-marker-left: 0.25rem;
  --timeline-marker-size: 1rem;
  --timeline-line-width: 1px;
}

.reasoning-timeline-marker {
  left: var(--timeline-marker-left);
  width: var(--timeline-marker-size);
  height: var(--timeline-marker-size);
}

.reasoning-timeline-connector {
  left: calc(
    var(--timeline-marker-left) + var(--timeline-marker-size) / 2 - var(--timeline-line-width) / 2
  );
  width: var(--timeline-line-width);
}
</style>
