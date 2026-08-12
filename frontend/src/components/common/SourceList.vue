<template>
  <div v-if="sources.length" :data-testid="testId" class="border-t border-border/60 pt-3">
    <Button
      type="button"
      variant="ghost"
      size="sm"
      class="h-8 w-full justify-start gap-1.5 px-2 text-xs text-muted-foreground"
      :aria-expanded="open"
      @click="emit('update:open', !open)"
    >
      <svg class="size-3.5 shrink-0 transition-transform" :class="open ? 'rotate-180' : ''" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
        <path d="m6 9 6 6 6-6" />
      </svg>
      <span>{{ title }}（{{ sources.length }}）</span>
      <span class="ml-auto text-[11px] font-normal text-muted-foreground/70">点击查看原文</span>
    </Button>
    <div v-if="open" class="mt-2 grid gap-2 sm:grid-cols-2">
      <SourceCard v-for="(source, index) in sources" :key="source.url || index" :source="source" />
    </div>
  </div>
</template>

<script setup>
import { Button } from '@/components/ui/button'
import SourceCard from './SourceCard.vue'

defineProps({
  sources: { type: Array, default: () => [] },
  open: { type: Boolean, default: false },
  title: { type: String, default: '参考来源' },
  testId: { type: String, default: 'source-list' },
})

const emit = defineEmits(['update:open'])
</script>
