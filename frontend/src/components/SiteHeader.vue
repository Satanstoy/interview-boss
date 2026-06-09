<script setup>
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'

const props = defineProps({
  activeTabLabel: {
    type: String,
    required: true
  },
  activeSeason: {
    type: String,
    default: null
  },
  isDark: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle-dark', 'show-settings'])
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-background/80 backdrop-blur-xl px-4 lg:px-6">
    <div class="flex min-w-0 items-center gap-3">
      <h1 class="text-sm font-semibold text-foreground">
        {{ activeTabLabel }}
      </h1>
    </div>

    <div class="flex flex-1 items-center justify-end gap-2">
      <!-- Search button -->
      <button
        type="button"
        class="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 text-sm text-muted-foreground transition-all hover:bg-muted hover:text-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <span class="hidden sm:inline">搜索</span>
        <kbd class="hidden sm:inline-flex h-5 select-none items-center gap-1 rounded border border-border bg-background px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
          <span class="text-xs">⌘</span>K
        </kbd>
      </button>

      <!-- Season badge -->
      <span
        v-if="activeSeason"
        class="hidden md:inline-flex items-center rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs font-medium text-muted-foreground"
      >
        {{ activeSeason }}
      </span>

      <Separator
        orientation="vertical"
        class="hidden sm:block h-5"
      />

      <!-- Dark mode toggle -->
      <Button
        variant="ghost"
        size="icon"
        class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        @click="emit('toggle-dark')"
        :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
      >
        <svg v-if="isDark" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
        </svg>
        <svg v-else class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
        </svg>
        <span class="sr-only">{{ isDark ? '切换到亮色模式' : '切换到暗色模式' }}</span>
      </Button>

      <!-- Settings button -->
      <Button
        variant="ghost"
        size="icon"
        class="h-9 w-9 text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
        @click="emit('show-settings')"
        title="系统配置"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span class="sr-only">系统配置</span>
      </Button>
    </div>
  </header>
</template>
