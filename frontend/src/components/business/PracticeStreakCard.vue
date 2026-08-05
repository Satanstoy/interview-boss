<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-center gap-2">
      <Flame class="h-5 w-5 text-orange-500" />
      <h3 class="text-sm font-semibold text-card-foreground">连续打卡</h3>
    </div>
    <div class="mt-4 flex items-baseline gap-1">
      <span class="text-4xl font-bold tracking-tight text-foreground">{{ streak.current }}</span>
      <span class="text-sm text-muted-foreground">天</span>
    </div>
    <p class="mt-1 text-xs text-muted-foreground">历史最长 {{ streak.longest }} 天</p>
    <p v-if="todayCount === 0 && streak.current > 0" class="mt-3 text-xs font-medium text-amber-600 dark:text-amber-400">
      今天还没打卡，再刷一题连击 +1
    </p>
    <p v-else-if="todayCount === 0" class="mt-3 text-xs text-muted-foreground">
      从今天开始，连续 7 天养成面试准备习惯
    </p>
    <p v-else class="mt-3 text-xs font-medium text-emerald-600 dark:text-emerald-400">
      今日已打卡 {{ todayCount }} 题，保持住
    </p>
    <div class="mt-auto pt-4">
      <Button variant="outline" size="sm" class="w-full" @click="goPractice">
        {{ todayCount === 0 ? '去刷一题' : '继续刷题' }}
      </Button>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { Flame } from '@lucide/vue'
import { Button } from '@/components/ui/button'

defineProps({
  streak: { type: Object, default: () => ({ current: 0, longest: 0 }) },
  todayCount: { type: Number, default: 0 },
})

const router = useRouter()

function goPractice() {
  router.push({ name: 'mock-interview' })
}
</script>
