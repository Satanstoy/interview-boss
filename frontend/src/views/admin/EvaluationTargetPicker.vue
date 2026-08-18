<script setup>
import { computed } from 'vue'
import { EVALUATION_TARGETS } from './evaluationShared.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  capabilities: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue'])

const targets = computed(() => EVALUATION_TARGETS.map(target => {
  const capability = props.capabilities.find(item => item.target_type === target.key)
  if (!capability) return target
  return {
    ...target,
    status: capability.can_run ? 'available' : 'unavailable',
    statusLabel: capability.can_run ? '已支持' : '不可运行',
    actionLabel: capability.can_run ? target.actionLabel : '暂不可运行',
    caseCount: capability.case_count,
    reason: capability.reason || '',
  }
}))

function choose(target) {
  if (target.status !== 'available') return
  emit('update:modelValue', target.key)
}
</script>

<template>
  <section aria-label="评测对象" class="rounded-lg border border-border/70 bg-muted/20 p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold">评测对象</h3>
        <p class="mt-1 text-xs text-muted-foreground">先选择要评测的 Agent 类型；只有已接入适配器的对象可以创建运行。</p>
      </div>
      <span class="rounded-full bg-primary/10 px-2 py-1 text-xs font-medium text-primary">管理员配置</span>
    </div>

    <div class="mt-3 grid gap-2">
      <button
        v-for="target in targets"
        :key="target.key"
        type="button"
        :disabled="target.status !== 'available'"
        :aria-pressed="modelValue === target.key"
        :class="[
          'w-full rounded-lg border p-3 text-left transition-colors',
          modelValue === target.key ? 'border-primary bg-primary/5 ring-1 ring-primary/30' : 'border-border/70 bg-background',
          target.status === 'available' ? 'cursor-pointer hover:border-primary/60' : 'cursor-not-allowed opacity-70',
        ]"
        @click="choose(target)"
      >
        <div class="flex flex-wrap items-center gap-2">
          <span class="font-medium">{{ target.label }}</span>
          <span :class="['rounded-full px-2 py-0.5 text-[11px]', target.status === 'available' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-muted text-muted-foreground']">{{ target.statusLabel }}</span>
          <span class="ml-auto text-xs text-muted-foreground">{{ target.actionLabel }}</span>
        </div>
        <p class="mt-1 text-xs leading-5 text-muted-foreground">{{ target.description }}</p>
        <p v-if="target.caseCount != null" class="mt-1 text-[11px] text-muted-foreground">{{ target.caseCount }} 个 Case</p>
        <p v-if="target.reason" class="mt-1 text-[11px] text-destructive">{{ target.reason }}</p>
      </button>
    </div>
  </section>
</template>
