<template>
  <div class="mb-4 flex flex-wrap gap-2 items-center bg-white p-4 rounded-lg border border-gray-200 shadow-sm">
    <button @click="$emit('toggle-select-all')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
    <button @click="$emit('invert-selection')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
    <div class="w-px h-5 bg-gray-300 mx-1 self-center"></div>
    <button
      v-for="action in actions" :key="action.key"
      @click="executeAction(action)"
      :disabled="selectedCount === 0 || action.disabled || runningAction !== null"
      :class="colorClasses(action.color)"
    >
      {{ action.label }} ({{ selectedCount }})
    </button>
    <div v-if="runningAction" class="flex items-center gap-2 ml-auto">
      <div class="w-32 h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          class="h-full bg-blue-500 rounded-full transition-all duration-300"
          :style="{ width: progressPct + '%' }"
        ></div>
      </div>
      <span class="text-sm text-gray-600 tabular-nums">{{ progress.current }}/{{ progress.total }}</span>
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
    red: 'bg-red-100 text-red-700 hover:bg-red-200',
    blue: 'bg-blue-100 text-blue-700 hover:bg-blue-200',
    green: 'bg-green-100 text-green-700 hover:bg-green-200',
    yellow: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200',
  }
  return (map[color] || map.blue) + ' text-sm px-3 py-1.5 rounded transition font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1'
}
</script>
