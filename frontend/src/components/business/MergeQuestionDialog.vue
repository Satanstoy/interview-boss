<template>
  <Teleport to="body">
    <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="$emit('close')">
      <div class="rounded-xl border border-border bg-card shadow-lg w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div class="p-5 border-b border-border">
          <h3 class="text-lg font-bold text-foreground">移动题目到目标聚类</h3>
          <p class="text-sm text-muted-foreground mt-1">选择要移动到的目标题目，或独立为新聚类</p>
          <p class="text-xs text-muted-foreground mt-2 bg-muted/50 rounded-lg p-2 truncate">
            <span class="font-medium">当前题目：</span>{{ sourceQuestion }}
          </p>
        </div>
        <div class="p-4 border-b border-border">
          <button @click="$emit('split')" class="w-full text-left p-3 rounded-xl border-2 border-dashed border-primary-300 dark:border-primary-700 hover:bg-primary-50 dark:hover:bg-primary-900/20 hover:border-primary-400 dark:hover:border-primary-600 transition-all duration-200">
            <div class="flex items-center gap-2">
              <svg class="size-4 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/></svg>
              <span class="text-sm font-medium text-primary-700 dark:text-primary-400">成为新的独立聚类</span>
            </div>
            <p class="text-xs text-muted-foreground mt-1 ml-6">从当前聚类中拆出，作为独立题目</p>
          </button>
        </div>
        <div class="p-5 border-b border-border">
          <div class="flex gap-2">
            <input :value="searchQuery" @input="$emit('update:searchQuery', $event.target.value)" @keyup.enter="$emit('search')"
              class="flex-1 px-3 py-2 border border-input rounded-md text-sm bg-background text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:border-ring"
              placeholder="搜索目标题目..." />
            <Button @click="$emit('search')" :disabled="searching"
              variant="default" size="sm" class="px-4 py-2 text-sm disabled:opacity-50">
              {{ searching ? '搜索中...' : '搜索' }}
            </Button>
          </div>
        </div>
        <div class="flex-1 overflow-y-auto p-5 custom-scrollbar">
          <div v-if="results.length === 0" class="text-center py-8 text-muted-foreground text-sm">
            {{ searching ? '搜索中...' : '输入关键词搜索目标题目' }}
          </div>
          <div v-else class="flex flex-col gap-2">
            <button v-for="item in results" :key="item.id"
              @click="$emit('confirm', item)"
              class="w-full text-left p-3 rounded-xl border border-border hover:bg-muted/60 hover:border-primary/30 transition-all duration-200">
              <div class="text-sm font-medium text-foreground line-clamp-2">{{ item.question }}</div>
              <div class="text-xs text-muted-foreground mt-1">频率: {{ item.frequency }} | {{ item.cat1 || '未分类' }} / {{ item.cat2 || '未分类' }}</div>
            </button>
          </div>
        </div>
        <div class="p-4 border-t border-border flex justify-end">
          <Button @click="$emit('close')" variant="outline" size="sm" class="px-4 py-2 text-sm">取消</Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { Button } from '@/components/ui/button'

defineProps({
  visible: { type: Boolean, default: false },
  sourceQuestion: { type: String, default: '' },
  searchQuery: { type: String, default: '' },
  results: { type: Array, default: () => [] },
  searching: { type: Boolean, default: false },
})
defineEmits(['close', 'search', 'confirm', 'split', 'update:searchQuery'])
</script>
