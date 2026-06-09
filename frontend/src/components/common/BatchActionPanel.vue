<template>
  <div class="mb-2 flex flex-wrap gap-2 items-center bg-card p-2 rounded-xl border border-border shadow-sm">
    <Button @click="$emit('toggle-select-all')" variant="ghost" size="sm" class="text-xs">
      <CheckSquare class="size-3.5" />
      全选
    </Button>
    <Button @click="$emit('invert-selection')" variant="ghost" size="sm" class="text-xs">
      <ArrowLeftRight class="size-3.5" />
      反选
    </Button>
    <div class="w-px h-5 bg-muted dark:bg-muted mx-1"></div>
    <Button
      v-for="action in actions" :key="action.key"
      variant="outline" size="sm"
      @click="executeAction(action)"
      :disabled="selectedCount === 0 || action.disabled || runningAction !== null"
      class="text-xs font-medium flex items-center gap-1.5 hover:scale-[1.02] active:scale-[0.98]"
      :class="colorClasses(action.color)"
    >
      {{ action.label }}
      <span class="bg-white/30 dark:bg-white/10 px-1.5 py-0.5 rounded text-[10px] font-bold">{{ selectedCount }}</span>
    </Button>
    <div v-if="runningAction" class="flex items-center gap-2.5">
      <div class="w-32 h-1.5 bg-muted dark:bg-muted rounded-full overflow-hidden">
        <div
          class="h-full bg-gradient-brand rounded-full transition-all duration-300"
          :style="{ width: progressPct + '%' }"
        ></div>
      </div>
      <span class="text-xs text-muted-foreground tabular-nums font-medium">{{ progress.current }}/{{ progress.total }}</span>
    </div>
    <slot />
    <div v-if="$slots.right" class="ml-auto flex items-center gap-2">
      <slot name="right" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Button } from '@/components/ui/button'
import { CheckSquare, ArrowLeftRight } from '@lucide/vue'

defineProps({
  selectedCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  actions: { type: Array, default: () => [] }
})

defineEmits(['toggle-select-all', 'invert-selection'])

const runningAction = ref(null)
const progress = ref({ current: 0, total: 0 })

const progressPct = computed(() => {
  if (!progress.value.total) return 0
  return Math.round((progress.value.current / progress.value.total) * 100)
})

const executeAction = async (action) => {
  if (runningAction.value) return
  runningAction.value = action.key
  progress.value = { current: 0, total: 0 }
  try {
    await action.handler((current, total) => {
      progress.value = { current, total }
    })
  } catch (e) {
    console.error(`Batch action ${action.key} failed:`, e)
  } finally {
    setTimeout(() => {
      runningAction.value = null
      progress.value = { current: 0, total: 0 }
    }, 1500)
  }
}

const colorClasses = (color) => {
  const map = {
    red: 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-200 dark:border-red-800 hover:bg-red-100 dark:hover:bg-red-900/50 transition-colors duration-200',
    blue: 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border border-primary-200 dark:border-primary-800 hover:bg-primary-100 dark:hover:bg-primary-900/50 transition-colors duration-200',
    green: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition-colors duration-200',
    yellow: 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800 hover:bg-amber-100 dark:hover:bg-amber-900/50 transition-colors duration-200',
  }
  return map[color] || map.blue
}
</script>
