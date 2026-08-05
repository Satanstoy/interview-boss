<template>
  <div class="flex h-full flex-col rounded-xl border border-border bg-card p-4 shadow-sm">
    <div class="flex items-start justify-between gap-3">
      <div>
        <h3 class="text-sm font-semibold text-card-foreground">打卡热力图</h3>
        <p class="mt-0.5 text-xs text-muted-foreground">近 90 天练习分布，每天点亮一格</p>
      </div>
      <div v-if="totalCount > 0" class="flex items-center gap-1.5 text-[10px] text-muted-foreground">
        <span>少</span>
        <span class="h-2.5 w-2.5 rounded-[3px] bg-muted/50" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-200 dark:bg-emerald-800" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-300 dark:bg-emerald-600" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-500" />
        <span class="h-2.5 w-2.5 rounded-[3px] bg-emerald-600 dark:bg-emerald-400" />
        <span>多</span>
      </div>
    </div>

    <div v-if="totalCount > 0" class="mt-3 flex-1 overflow-x-auto custom-scrollbar">
      <div class="flex flex-col gap-1">
        <div class="flex gap-1 pl-6">
          <span
            v-for="(label, wi) in monthLabels"
            :key="wi"
            class="w-[14px] text-[9px] leading-3 text-muted-foreground"
          >{{ label }}</span>
        </div>
        <div class="flex gap-1">
          <div class="flex w-5 shrink-0 flex-col justify-between text-[9px] text-muted-foreground">
            <span>一</span>
            <span>三</span>
            <span>五</span>
            <span>日</span>
          </div>
          <div class="flex gap-1">
            <div v-for="(week, wi) in weeks" :key="wi" class="flex flex-col gap-1">
              <AppTooltip
                v-for="cell in week"
                :key="cell.date"
                :text="cell.date ? `${cell.date} 练习 ${cell.count} 题${cell.avg_score ? `，平均 ${cell.avg_score} 分` : ''}` : ''"
              >
                <div class="h-2.5 w-2.5 rounded-[3px]" :class="cellClass(cell)" />
              </AppTooltip>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
      <p class="text-sm text-muted-foreground">还没有练习记录</p>
      <Button variant="outline" size="sm" @click="goPractice">去刷一题，点亮第一格</Button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
})

const router = useRouter()
const totalCount = computed(() => props.data.reduce((sum, day) => sum + (day.count || 0), 0))

function cellClass(cell) {
  if (!cell.date || cell.count === 0) return 'bg-muted/50'
  if (cell.count <= 2) return 'bg-emerald-200 dark:bg-emerald-800'
  if (cell.count <= 5) return 'bg-emerald-300 dark:bg-emerald-600'
  if (cell.count <= 9) return 'bg-emerald-500'
  return 'bg-emerald-600 dark:bg-emerald-400'
}

const weeks = computed(() => {
  const days = props.data
  if (!days.length) return []
  const today = new Date(`${days[days.length - 1].date}T00:00:00`)
  const start = new Date(today)
  start.setDate(today.getDate() - (days.length - 1))
  while (start.getDay() !== 1) start.setDate(start.getDate() - 1)
  const byDate = new Map(days.map((d) => [d.date, d]))
  const weekRows = []
  const col = start
  for (let w = 0; w < 13; w += 1) {
    const week = []
    for (let r = 0; r < 7; r += 1) {
      const date = new Date(col)
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
      const day = byDate.get(key)
      week.push({ date: day ? key : '', count: day?.count || 0, avg_score: day?.avg_score || 0 })
      col.setDate(col.getDate() + 1)
    }
    weekRows.push(week)
  }
  return weekRows
})

const monthLabels = computed(() => {
  const labels = new Array(weeks.value.length).fill('')
  weeks.value.forEach((week, wi) => {
    for (const cell of week) {
      if (!cell.date) continue
      const d = new Date(`${cell.date}T00:00:00`)
      if (d.getDate() === 1) {
        labels[wi] = `${d.getMonth() + 1}月`
        break
      }
    }
  })
  return labels
})

function goPractice() {
  router.push({ name: 'mock-interview' })
}
</script>
