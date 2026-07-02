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
        <!-- Steps timeline -->
        <div v-if="steps.length > 0" class="space-y-1 mb-3">
          <div
            v-for="(step, i) in steps"
            :key="i"
            class="group/step"
          >
            <!-- Step row -->
            <button
              @click="toggleStep(i)"
              class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
            >
              <CheckCircle2 v-if="step.done !== false" :size="12" class="text-emerald-500 shrink-0" />
              <Loader2 v-else :size="12" class="animate-spin text-muted-foreground shrink-0" />
              <span class="text-muted-foreground flex-1">
                {{ step.message }}
                <span v-if="step.skill_name" class="text-primary ml-1">({{ step.skill_name }})</span>
              </span>
              <ChevronDown
                v-if="step.reason || step.insight"
                :size="12"
                class="text-muted-foreground/50 shrink-0 transition-transform duration-200"
                :class="{ 'rotate-180': expandedSteps[i] }"
              />
            </button>

            <!-- Step detail (reason + insight) -->
            <Transition name="expand">
              <div v-if="expandedSteps[i] && (step.reason || step.insight)" class="pl-7 pr-2 pb-1">
                <p v-if="step.reason" class="text-xs text-muted-foreground/60 leading-relaxed">
                  {{ step.reason }}
                </p>
                <p v-if="step.insight" class="text-xs text-amber-600/70 dark:text-amber-400/70 mt-0.5 flex items-center gap-1">
                  <Lightbulb :size="10" />
                  {{ step.insight }}
                </p>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Skill trace -->
        <div v-if="skillSteps.length > 0" class="space-y-1 mb-3">
          <div v-for="(skill, i) in skillSteps" :key="skill.skill_name || i">
            <button
              @click="toggleSkillStep(i)"
              class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
            >
              <Brain :size="12" class="text-primary shrink-0" />
              <span class="text-muted-foreground flex-1">{{ skill.label || skill.skill_name }}</span>
              <span v-if="skill.status" class="text-[11px] text-muted-foreground/50">{{ formatStatus(skill.status) }}</span>
              <ChevronDown
                v-if="skill.reason"
                :size="12"
                class="text-muted-foreground/50 shrink-0 transition-transform duration-200"
                :class="{ 'rotate-180': expandedSkillSteps[i] }"
              />
            </button>
            <Transition name="expand">
              <div v-if="expandedSkillSteps[i] && skill.reason" class="pl-7 pr-2 pb-1">
                <p class="text-xs text-muted-foreground/60 leading-relaxed">{{ skill.reason }}</p>
              </div>
            </Transition>
          </div>
        </div>

        <!-- Tool steps -->
        <div v-if="toolSteps.length > 0" class="space-y-1 mb-3">
          <div v-for="(step, i) in toolSteps" :key="i" class="group/step">
            <button
              @click="toggleToolStep(i)"
              class="flex items-center gap-2 w-full text-left px-2 py-1 rounded-md text-xs hover:bg-muted/50 transition-colors"
            >
              <Wrench v-if="step.done !== false" :size="12" class="text-sky-500 shrink-0" />
              <Loader2 v-else :size="12" class="animate-spin text-muted-foreground shrink-0" />
              <span class="text-muted-foreground flex-1">{{ step.label || step.message }}</span>
              <span v-if="step.elapsed_ms" class="text-xs text-muted-foreground/50">{{ step.elapsed_ms }}ms</span>
              <span v-if="step.result_count !== undefined" class="text-xs text-muted-foreground/50">{{ step.result_count }} 结果</span>
              <ChevronDown
                v-if="hasToolDetails(step)"
                :size="12"
                class="text-muted-foreground/50 shrink-0 transition-transform duration-200"
                :class="{ 'rotate-180': expandedToolSteps[i] }"
              />
            </button>
            <Transition name="expand">
              <div
                v-if="expandedToolSteps[i] && hasToolDetails(step)"
                class="ml-7 mr-2 mb-1 rounded-md border border-border/60 bg-muted/20 px-3 py-2 text-xs text-muted-foreground"
              >
                <div v-if="step.summary" class="mb-2 leading-relaxed">{{ step.summary }}</div>

                <div v-if="argEntries(step).length" class="mb-2">
                  <div class="text-[11px] font-medium text-foreground/70 mb-1">参数</div>
                  <div class="flex flex-wrap gap-1.5">
                    <span
                      v-for="entry in argEntries(step)"
                      :key="entry.key"
                      class="rounded-md bg-background/70 border border-border/50 px-2 py-0.5"
                    >
                      {{ formatArgLabel(entry.key) }}：{{ formatValue(entry.value) }}
                    </span>
                  </div>
                </div>

                <div v-if="resultPreview(step).length">
                  <div class="text-[11px] font-medium text-foreground/70 mb-1">结果</div>
                  <div class="space-y-1.5">
                    <div
                      v-for="item in resultPreview(step)"
                      :key="item.id || item.question || item.title"
                      class="rounded-md bg-background/70 border border-border/50 px-2 py-1.5"
                    >
                      <div class="text-foreground/90 leading-relaxed">{{ item.question || item.title || item.name || `结果 ${item.id}` }}</div>
                      <div v-if="resultMeta(item)" class="mt-0.5 text-[11px] text-muted-foreground/60">{{ resultMeta(item) }}</div>
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
const expandedSteps = reactive({})
const expandedToolSteps = reactive({})
const expandedSkillSteps = reactive({})

const stepCount = computed(() => props.steps.length)
const toolCount = computed(() => props.toolSteps.length)
const skillCount = computed(() => props.skillSteps.length)

const displayLabel = computed(() => {
  if (props.isStreaming || (props.isSending && props.duration > 0 && !props.content)) {
    return `思考中 ${formatDuration(props.duration)}`
  }
  if (props.isSending && props.duration <= 0) return '思考中'
  const parts = []
  if (props.duration > 0) parts.push(`思考了 ${formatDuration(props.duration)}`)
  if (stepCount.value > 0) parts.push(`${stepCount.value} 步`)
  if (toolCount.value > 0) parts.push(`${toolCount.value} 次工具`)
  if (skillCount.value > 0) parts.push(`${skillCount.value} 个策略`)
  return parts.length > 0 ? parts.join(' · ') : '思考过程'
})

function formatDuration(duration) {
  const value = Number(duration) || 0
  if (value <= 0) return '0 秒'
  return `${Number.isInteger(value) ? value : value.toFixed(1)} 秒`
}

function toggleStep(index) {
  expandedSteps[index] = !expandedSteps[index]
}

function toggleToolStep(index) {
  expandedToolSteps[index] = !expandedToolSteps[index]
}

function toggleSkillStep(index) {
  expandedSkillSteps[index] = !expandedSkillSteps[index]
}

function hasToolDetails(step) {
  return Boolean(step.summary || argEntries(step).length || resultPreview(step).length)
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
  if (oldSending && !sending && (props.content || props.steps.length > 0 || props.toolSteps.length > 0 || props.skillSteps.length > 0)) {
    setTimeout(() => {
      isOpen.value = false
    }, 1000)
  }
})

onMounted(() => {
  if ((props.content || props.steps.length > 0 || props.toolSteps.length > 0 || props.skillSteps.length > 0) && !props.isSending) {
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
</style>
