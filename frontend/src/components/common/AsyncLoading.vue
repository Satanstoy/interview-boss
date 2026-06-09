<template>
  <div class="flex items-center justify-center min-h-[200px]">
    <div class="flex flex-col items-center gap-3">
      <Loader2 class="animate-spin w-8 h-8 text-primary" />
      <p class="text-sm text-muted-foreground">加载中...</p>
    </div>
  </div>
</template>

<script setup>
import { Loader2 } from '@lucide/vue'
</script>
