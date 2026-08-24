<template>
  <section
    class="turn-run-card mb-5 rounded-xl border border-border/70 bg-card/70 shadow-sm"
    data-testid="turn-run-card"
  >
    <button
      type="button"
      class="flex w-full items-center gap-2 px-3 py-2.5 text-left text-xs"
      data-testid="turn-run-toggle"
      @click="outerOpen = !outerOpen"
    >
      <Loader2 v-if="isLive" :size="14" class="animate-spin text-primary" />
      <CheckCircle2 v-else-if="run.status === 'completed'" :size="14" class="text-emerald-500" />
      <CircleAlert v-else :size="14" class="text-amber-500" />
      <span class="font-medium text-foreground">本轮运行</span>
      <span class="text-muted-foreground">{{ statusLabel }}</span>
      <span class="ml-auto text-muted-foreground/70">{{ durationLabel }}</span>
      <ChevronDown :size="14" class="text-muted-foreground transition-transform" :class="outerOpen ? 'rotate-180' : ''" />
    </button>

    <Transition name="expand">
      <div v-show="outerOpen" class="border-t border-border/60 px-3 pb-3 pt-2">
        <div v-if="visibleActions.length" class="space-y-1.5">
          <template v-for="(action, index) in visibleActions" :key="action.id">
            <article
              class="rounded-lg border border-border/50 bg-background/50"
              :data-testid="`turn-run-action-${index}`"
            >
            <button
              type="button"
              class="flex w-full items-center gap-2 px-2.5 py-2 text-left text-xs"
              @click="toggleAction(action)"
            >
              <CheckCircle2 v-if="isActionDone(action)" :size="13" class="text-emerald-500" />
              <Loader2 v-else :size="13" class="animate-spin text-muted-foreground" />
              <span class="flex-1 text-foreground">{{ action.label || action.phase || '运行步骤' }}</span>
              <span class="text-muted-foreground/70">{{ action.status }}</span>
              <ChevronDown :size="12" class="text-muted-foreground transition-transform" :class="isActionOpen(action) ? 'rotate-180' : ''" />
            </button>

            <div v-show="isActionOpen(action)" class="space-y-2 border-t border-border/40 px-2.5 pb-2.5 pt-2">
              <div v-if="action.reasoning" class="rounded-md border border-border/50 bg-muted/25">
                <button type="button" class="flex w-full items-center justify-between px-2 py-1.5 text-[11px] text-muted-foreground" @click="toggleReasoning(action)">
                  <span>模型推理 / CoT</span>
                  <ChevronDown :size="12" :class="action.reasoningOpen ? 'rotate-180' : ''" />
                </button>
                <pre v-if="action.reasoningOpen" class="max-h-56 overflow-y-auto whitespace-pre-wrap break-words border-t border-border/40 px-2 py-2 text-[11px] leading-relaxed text-muted-foreground/80">{{ action.reasoning }}</pre>
              </div>
              <div v-if="action.evidence?.length" class="text-[11px] text-muted-foreground">
                <div class="mb-1 font-medium text-foreground/80">Evidence</div>
                <pre class="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded-md bg-muted/20 p-2">{{ formatEvidence(action.evidence) }}</pre>
              </div>
              <div v-if="action.output" class="rounded-md bg-primary/5 px-2 py-1.5 text-xs text-foreground/80">
                {{ action.output }}
              </div>
            </div>
            </article>
            <template v-if="index < visibleActions.length - 1">
              <span class="reasoning-timeline-connector" aria-hidden="true"></span>
              <span class="reasoning-timeline-marker" aria-hidden="true"></span>
            </template>
          </template>
        </div>

        <div v-if="run.assistant" class="mt-2 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2 text-sm leading-relaxed text-foreground">
          <div class="mb-1 text-[11px] text-muted-foreground">{{ run.assistantStatus === 'completed' ? '正式回复' : '生成中 / 待校验' }}</div>
          <div class="whitespace-pre-wrap">{{ run.assistant }}</div>
        </div>
      </div>
    </Transition>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { CheckCircle2, CircleAlert, ChevronDown, Loader2 } from '@lucide/vue'

const props = defineProps({
  run: { type: Object, required: true },
  isLive: { type: Boolean, default: false },
})

const outerOpen = ref(Boolean(props.isLive))
const actionOpen = reactive({})
const now = ref(Date.now())
let durationTimer = null

onMounted(() => {
  if (props.isLive) durationTimer = window.setInterval(() => { now.value = Date.now() }, 250)
})
onBeforeUnmount(() => {
  if (durationTimer) window.clearInterval(durationTimer)
})

const visibleActions = computed(() => (props.run.actions || []).filter(action => action.visible !== false))

const statusLabel = computed(() => {
  if (props.isLive) return `面试官推理中 ${liveSeconds.value} 秒`
  if (props.run.status === 'completed') return `面试官推理了 ${durationLabel.value.replace(/秒$/, ' 秒')}`
  if (props.run.status === 'cancelled') return '已停止'
  return '未完成'
})

const durationLabel = computed(() => {
  const ms = props.isLive
    ? Math.max(Number(props.run.durationMs || 0), runElapsedMs.value)
    : Number(props.run.durationMs || 0)
  if (!ms && props.isLive) return '0秒'
  const seconds = Math.max(0, Math.round(ms / 100) / 10)
  const minutes = Math.floor(seconds / 60)
  const remain = Math.round((seconds % 60) * 10) / 10
  return minutes ? `${minutes}分${remain}秒` : `${remain}秒`
})

const runElapsedMs = computed(() => {
  if (!props.run.startedAt) return 0
  const end = props.isLive ? now.value : new Date(props.run.finishedAt || props.run.startedAt).getTime()
  return Math.max(0, end - new Date(props.run.startedAt).getTime())
})

const liveSeconds = computed(() => Math.max(0, Math.floor(runElapsedMs.value / 1000)))

function isActionOpen(action) {
  if (Object.prototype.hasOwnProperty.call(actionOpen, action.id)) return actionOpen[action.id]
  return action.open !== false
}

function toggleAction(action) {
  actionOpen[action.id] = !isActionOpen(action)
}

function toggleReasoning(action) {
  action.reasoningOpen = !action.reasoningOpen
}

function isActionDone(action) {
  return ['completed', 'succeeded'].includes(action.status)
}

function formatEvidence(value) {
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}
</script>

<style scoped>
.turn-run-card pre {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}
</style>
