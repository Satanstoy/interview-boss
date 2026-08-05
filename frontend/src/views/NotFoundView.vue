<script setup>
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { FileQuestion } from '@lucide/vue'

const router = useRouter()
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center px-6 text-center">
    <FileQuestion class="mb-4 size-16 text-muted-foreground/40" />
    <h1 class="text-2xl font-bold text-foreground">页面不存在</h1>
    <p class="mt-2 text-sm text-muted-foreground">你访问的页面不存在或已被移除。</p>
    <Button class="mt-6" @click="router.push('/master-bank')">返回首页</Button>
  </div>
</template>
