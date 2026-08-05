<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div>
      <h3 class="text-sm font-semibold text-card-foreground">最近刷题</h3>
      <p class="mt-0.5 text-xs text-muted-foreground">最近的答题与闪卡复习记录</p>
    </div>
    <div v-if="props.data.length" class="mt-3 flex-1 divide-y divide-border overflow-y-auto custom-scrollbar">
      <div v-for="item in props.data" :key="`${item.type}-${item.id}`" class="flex items-center gap-3 py-2.5">
        <Badge variant="secondary" class="w-11 shrink-0 justify-center">
          {{ item.type === 'answer' ? '答题' : '复习' }}
        </Badge>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm text-foreground">{{ item.question }}</p>
          <p class="mt-0.5 text-xs text-muted-foreground">
            {{ item.topic }} · {{ item.difficulty }} · {{ formatRelativeTime(item.created_at) }}
          </p>
        </div>
        <Badge v-if="item.type === 'answer'" :variant="scoreVariant(item.score)">
          {{ item.score }} 分
        </Badge>
        <Badge v-else :variant="ratingVariant(item.rating)">
          {{ ratingLabel(item.rating) }}
        </Badge>
      </div>
    </div>
    <div v-else class="flex flex-1 items-center justify-center py-10 text-sm text-muted-foreground">
      还没有刷题记录，去刷一题吧
    </div>
  </div>
</template>

<script setup>
import { Badge } from '@/components/ui/badge'
import { formatRelativeTime } from '@/utils/time.js'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const ratingLabels = { again: '忘了', hard: '困难', good: '不错', easy: '简单' }

function ratingLabel(rating) {
  return ratingLabels[rating] || rating || '复习'
}

function ratingVariant(rating) {
  if (rating === 'easy') return 'secondary'
  if (rating === 'good') return 'secondary'
  if (rating === 'hard') return 'outline'
  return 'destructive'
}

function scoreVariant(score) {
  return score >= 60 ? 'secondary' : 'destructive'
}
</script>
