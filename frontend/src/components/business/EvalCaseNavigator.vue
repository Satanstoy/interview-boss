<script setup>
import { computed, ref } from 'vue'
import { Search } from '@lucide/vue'
import { casePrioritySort, checkStatusLabel } from '@/views/admin/evaluationShared.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
  activeId: { type: Number, default: null },
  sortMode: { type: String, default: 'priority' },
})

const emit = defineEmits(['select'])
const filter = ref('all')
const search = ref('')

const filteredItems = computed(() => {
  let list = props.sortMode === 'priority' ? casePrioritySort(props.items) : [...props.items]
  if (filter.value === 'failed') list = list.filter(i => i.status === 'failed' || (i.status === 'completed' && i.hard_gate_status === 'failed'))
  if (filter.value === 'running') list = list.filter(i => i.status === 'running' || i.status === 'queued')
  if (search.value.trim()) {
    const q = search.value.trim().toLowerCase()
    list = list.filter(i => i.case_key.toLowerCase().includes(q))
  }
  return list
})

function gateMeta(item) {
  if (item.status === 'failed' || item.hard_gate_status === 'failed') return { label: checkStatusLabel('failed'), cls: 'bg-destructive/10 text-destructive' }
  if (item.hard_gate_status === 'passed') return { label: checkStatusLabel('passed'), cls: 'bg-emerald-500/10 text-emerald-600' }
  return { label: checkStatusLabel(item.hard_gate_status || 'pending'), cls: 'bg-muted text-muted-foreground' }
}

function selectItem(item) {
  emit('select', item.id)
}

function scoreDisplay(item) {
  return item.score == null ? '—' : Number(item.score).toFixed(3)
}

function itemDotClass(item) {
  if (item.status === 'failed') return 'bg-destructive'
  if (item.status === 'completed' && item.hard_gate_status === 'failed') return 'bg-amber-500'
  if (item.status === 'completed') return 'bg-emerald-500'
  if (item.status === 'running') return 'bg-primary animate-pulse'
  return 'bg-muted-foreground/50'
}
</script>

<template>
  <nav aria-label="Case 导航" class="flex h-full flex-col">
    <div class="flex items-center justify-between border-b border-border/60 px-3 py-2">
      <span class="text-xs font-semibold text-muted-foreground">Cases</span>
      <span class="text-[11px] text-muted-foreground">{{ items.length }} 个</span>
    </div>
    <!-- 搜索 -->
    <div class="border-b border-border/60 px-3 py-2">
      <label class="flex items-center gap-1.5 rounded-md border border-input bg-background px-2">
        <Search class="size-3.5 text-muted-foreground" />
        <input v-model="search" type="text" placeholder="搜索 Case..." class="h-7 w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground" />
      </label>
    </div>
    <!-- 筛选 -->
    <div class="flex gap-1 border-b border-border/60 px-3 py-2">
      <button v-for="f in [{ key: 'all', label: '全部' }, { key: 'failed', label: '失败' }, { key: 'running', label: '进行中' }]" :key="f.key" type="button" :class="['rounded-md px-2 py-1 text-[11px] transition-colors', filter === f.key ? 'bg-primary/10 text-primary font-medium' : 'text-muted-foreground hover:text-foreground']" @click="filter = f.key">{{ f.label }}</button>
    </div>
    <div class="flex-1 overflow-y-auto custom-scrollbar">
      <button
        v-for="item in filteredItems"
        :key="item.id"
        type="button"
        :aria-current="activeId === item.id ? 'true' : undefined"
        :class="[
          'eval-case-item flex w-full items-center gap-2 px-3 py-2 text-left text-xs transition-colors border-b border-border/30',
          activeId === item.id ? 'bg-primary/10 text-primary border-l-2 border-l-primary' : 'hover:bg-muted/40 text-foreground border-l-2 border-l-transparent',
        ]"
        @click="selectItem(item)"
      >
        <span :class="['size-1.5 shrink-0 rounded-full', itemDotClass(item)]" />
        <span class="min-w-0 flex-1 truncate">
          <span class="font-medium">{{ item.case_key }}</span>
          <span class="ml-1 text-[10px] text-muted-foreground">#{{ item.replication_index }}</span>
        </span>
        <span :class="['shrink-0 rounded px-1 py-0.5 text-[10px]', gateMeta(item).cls]">{{ gateMeta(item).label }}</span>
        <span class="w-8 shrink-0 text-right font-mono text-[11px] text-muted-foreground">{{ scoreDisplay(item) }}</span>
      </button>
      <div v-if="!filteredItems.length" class="px-3 py-8 text-center text-xs text-muted-foreground">无匹配 Case</div>
    </div>
  </nav>
</template>