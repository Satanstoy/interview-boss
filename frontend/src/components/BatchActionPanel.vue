<template>
  <div class="mb-4 flex flex-wrap gap-2 items-center bg-white/80 backdrop-blur-sm p-3 rounded-xl border border-gray-100 shadow-card">
    <button @click="$emit('toggle-select-all')" class="btn-ghost text-xs">
      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
      全选
    </button>
    <button @click="$emit('invert-selection')" class="btn-ghost text-xs">
      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
      反选
    </button>
    <div class="w-px h-5 bg-gray-200 mx-1"></div>
    <button
      v-for="action in actions" :key="action.key"
      @click="executeAction(action)"
      :disabled="selectedCount === 0 || action.disabled || runningAction !== null"
      class="text-xs px-3 py-1.5 rounded-lg font-medium transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5 hover:scale-[1.02] active:scale-[0.98]"
      :class="colorClasses(action.color)"
    >
      {{ action.label }}
      <span class="bg-white/30 px-1.5 py-0.5 rounded text-[10px] font-bold">{{ selectedCount }}</span>
    </button>
    <div v-if="runningAction" class="flex items-center gap-2.5 ml-auto">
      <div class="w-32 h-1.5 bg-gray-200 rounded-full overflow-hidden">
        <div
          class="h-full bg-gradient-brand rounded-full transition-all duration-300"
          :style="{ width: progressPct + '%' }"
        ></div>
      </div>
      <span class="text-xs text-gray-500 tabular-nums font-medium">{{ progress.current }}/{{ progress.total }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

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
    red: 'bg-red-50 text-red-700 border border-red-200 hover:bg-red-100',
    blue: 'bg-primary-50 text-primary-700 border border-primary-200 hover:bg-primary-100',
    green: 'bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100',
    yellow: 'bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100',
  }
  return map[color] || map.blue
}
</script>
