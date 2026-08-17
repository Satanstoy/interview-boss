<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, CheckCircle2 } from '@lucide/vue'
import { EVALUATION_FLOW_STEPS } from './evaluationShared.js'

const props = defineProps({
  activeKey: { type: String, default: '' },
})

const route = useRoute()
const activeStep = computed(() => props.activeKey || route.name)

function isActive(step) {
  return step.key === activeStep.value || step.keys.includes(activeStep.value)
}
</script>

<template>
  <section class="rounded-xl border border-border/70 bg-muted/20 px-4 py-3" aria-label="评测流程">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:gap-5">
      <div class="shrink-0">
        <div class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">评测流程</div>
        <p class="mt-1 text-xs text-muted-foreground">版本与发布 → Benchmark → 测评实验 → 评测结果 → 人工 A/B</p>
      </div>
      <div class="hidden h-px flex-1 bg-border/70 lg:block" />
      <div class="flex min-w-0 flex-wrap items-center gap-2" role="list" aria-label="评测中心流程位置">
        <template v-for="(step, index) in EVALUATION_FLOW_STEPS" :key="step.key">
          <ArrowRight v-if="index > 0" class="hidden size-3.5 shrink-0 text-muted-foreground/50 sm:block" />
          <div
            :class="[
              'group flex min-w-0 items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors',
              isActive(step)
                ? 'border-primary/30 bg-primary/10 text-primary'
                : 'border-transparent text-muted-foreground',
            ]"
            role="listitem"
          >
            <span
              :class="[
                'flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                isActive(step) ? 'bg-primary text-primary-foreground' : 'bg-background text-muted-foreground ring-1 ring-border/70',
              ]"
            >
              <CheckCircle2 v-if="step.key === 'results' && isActive(step)" class="size-3.5" />
              <template v-else>{{ index + 1 }}</template>
            </span>
            <span class="min-w-0">
              <span class="block truncate text-xs font-medium">{{ step.label }}</span>
              <span class="hidden text-[11px] text-muted-foreground sm:block">{{ step.description }}</span>
            </span>
          </div>
        </template>
      </div>
    </div>
  </section>
</template>
