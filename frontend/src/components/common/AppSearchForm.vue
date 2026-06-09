<template>
  <div class="flex flex-col sm:flex-row gap-3">
    <div class="relative flex-1">
      <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
      <Input
        :model-value="modelValue"
        type="text"
        :placeholder="placeholder"
        class="pl-9 pr-9"
        @update:model-value="$emit('update:modelValue', $event)"
        @keydown.enter="$emit('search')"
      />
      <button
        v-if="modelValue"
        type="button"
        class="absolute inset-y-0 right-0 pr-3 flex items-center text-muted-foreground hover:text-foreground transition-colors"
        @click="$emit('update:modelValue', ''); $emit('reset')"
      >
        <X class="h-4 w-4" />
      </button>
    </div>

    <div v-if="$slots.filters" class="flex items-center gap-2 flex-wrap">
      <slot name="filters" />
    </div>

    <div v-if="showButtons" class="flex items-center gap-2 shrink-0">
      <Button variant="outline" size="sm" @click="$emit('reset')">
        <RotateCcw class="size-3.5" />
        重置
      </Button>
      <Button size="sm" @click="$emit('search')">
        <Search class="size-4" />
        搜索
      </Button>
    </div>
  </div>
</template>

<script setup>
import { Search, X, RotateCcw } from '@lucide/vue'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '搜索...' },
  showButtons: { type: Boolean, default: true },
})

defineEmits(['update:modelValue', 'search', 'reset'])
</script>
