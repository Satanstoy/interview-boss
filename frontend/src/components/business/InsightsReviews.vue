<script setup>
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, MessageSquareText } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const props = defineProps({ snapshot: { type: Object, required: true } })
const router = useRouter()
const route = useRoute()

function startInterview() {
  router.push({ name: 'chat', query: { ...route.query } })
}
</script>

<template>
  <section class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-5 md:px-6 md:py-7">
    <header>
      <p class="text-sm text-muted-foreground">目标岗位：{{ props.snapshot.target_position.name }}</p>
      <h1 class="text-2xl font-semibold tracking-tight text-foreground">面试复盘</h1>
      <p class="mt-1 max-w-2xl text-sm text-muted-foreground">回看最近的模拟面试场次，把下一次训练接起来。</p>
    </header>

    <Card v-if="props.snapshot.reviews.items.length">
      <CardHeader>
        <CardTitle>最近面试</CardTitle>
        <p class="text-sm text-muted-foreground">共 {{ props.snapshot.reviews.total }} 场。</p>
      </CardHeader>
      <CardContent class="grid gap-3 md:grid-cols-2">
        <div v-for="review in props.snapshot.reviews.items" :key="review.id" class="rounded-xl border border-border p-4">
          <div class="flex items-start justify-between gap-3">
            <h2 class="font-medium text-foreground">{{ review.title }}</h2>
            <span class="text-xs text-muted-foreground">{{ review.mode }}</span>
          </div>
          <p class="mt-2 text-sm text-muted-foreground">{{ review.job_position }} · {{ review.message_count }} 条消息</p>
          <Button variant="link" class="mt-2 h-auto px-0" @click="startInterview">继续模拟面试 <ArrowRight class="h-4 w-4" /></Button>
        </div>
      </CardContent>
    </Card>

    <Card v-else>
      <CardContent class="flex flex-col items-center justify-center px-6 py-16 text-center">
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground"><MessageSquareText class="h-6 w-6" /></div>
        <h2 class="mt-4 text-lg font-medium text-foreground">还没有模拟面试记录</h2>
        <p class="mt-2 max-w-md text-sm text-muted-foreground">完成一次模拟面试后，这里会按场次整理回顾入口；没有结构化评分时不会臆测你的薄弱项。</p>
        <Button class="mt-5" @click="startInterview">开始一次模拟面试 <ArrowRight class="h-4 w-4" /></Button>
      </CardContent>
    </Card>
  </section>
</template>
