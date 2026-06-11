<script setup>
import { Button } from '@/components/ui/button'
import { Settings } from '@lucide/vue'

const props = defineProps({
  activeTabLabel: {
    type: String,
    required: true
  },
  activeSeason: {
    type: String,
    default: null
  },
  noBorder: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['show-settings'])
</script>

<template>
  <header
    class="flex h-11 shrink-0 items-center gap-3 bg-background/80 px-3 lg:px-5"
  >
    <div class="flex h-8 min-w-0 items-center">
      <h1 class="truncate text-[13px] font-medium leading-5 text-foreground">
        {{ activeTabLabel }}
      </h1>
    </div>

    <div class="flex h-8 flex-1 items-center justify-end gap-1.5">
      <!-- Season badge — h-8 matches settings button for visual center alignment -->
      <span
        v-if="activeSeason"
        class="hidden h-8 items-center rounded-md border border-border bg-muted/50 px-2 text-xs font-medium leading-none text-muted-foreground md:inline-flex"
      >
        {{ activeSeason }}
      </span>

      <!-- Settings button -->
      <Button
        variant="ghost"
        size="icon"
        class="inline-flex h-8 w-8 items-center justify-center text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
        @click="emit('show-settings')"
        title="设置"
      >
        <Settings class="h-4 w-4" />
        <span class="sr-only">设置</span>
      </Button>
    </div>
  </header>
</template>
