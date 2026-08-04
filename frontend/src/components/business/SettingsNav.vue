<script setup>
import { PanelLeftClose } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  activeSection: { type: String, required: true },
  sections: { type: Array, required: true },
  isAdmin: { type: Boolean, default: false },
})

const emit = defineEmits(['update:activeSection', 'collapse'])

function selectSection(id) {
  emit('update:activeSection', id)
}
</script>

<template>
  <nav class="flex h-full w-full shrink-0 flex-col overflow-hidden bg-background">
    <!-- Header -->
    <div class="flex shrink-0 items-center gap-2 border-b border-border p-3">
      <div class="min-w-0 flex-1">
        <h2 class="text-sm font-semibold tracking-tight text-foreground">设置</h2>
        <p class="mt-0.5 truncate text-xs text-muted-foreground">管理你的账户和偏好</p>
      </div>
      <AppTooltip text="收起设置菜单" side="right">
        <Button variant="ghost" size="icon" class="shrink-0" aria-label="收起设置菜单" @click="emit('collapse')">
          <PanelLeftClose :size="16" />
        </Button>
      </AppTooltip>
    </div>

    <!-- Navigation items -->
    <div class="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto p-2 custom-scrollbar">
      <button
        v-for="item in sections"
        :key="item.id"
        @click="selectSection(item.id)"
        class="group relative flex w-full items-center gap-2.5 rounded-lg px-3 py-2.5 text-left transition-all duration-150"
        :class="activeSection === item.id
          ? 'bg-accent text-foreground'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'"
      >
        <component
          :is="item.icon"
          :size="18"
          class="shrink-0 transition-colors"
          :class="activeSection === item.id
            ? 'text-primary'
            : 'text-muted-foreground group-hover:text-foreground/70'"
        />
        <div class="min-w-0 flex-1">
          <div class="truncate text-sm font-medium">{{ item.label }}</div>
          <div v-if="item.description" class="mt-0.5 truncate text-[11px] text-muted-foreground">
            {{ item.description }}
          </div>
        </div>
      </button>
    </div>
  </nav>
</template>
