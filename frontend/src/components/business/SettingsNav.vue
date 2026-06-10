<script setup>
import { computed } from 'vue'
import { User, Target, Bot, Shield, Settings } from '@lucide/vue'

const props = defineProps({
  activeSection: { type: String, required: true },
  sections: { type: Array, required: true },
  isAdmin: { type: Boolean, default: false },
})

const emit = defineEmits(['update:activeSection'])

function selectSection(id) {
  emit('update:activeSection', id)
}
</script>

<template>
  <nav class="flex flex-col w-56 shrink-0 bg-sidebar border-r border-sidebar-border overflow-y-auto custom-scrollbar">
    <!-- Header -->
    <div class="px-4 pt-5 pb-3 shrink-0">
      <h2 class="text-sm font-semibold text-sidebar-foreground tracking-tight">设置</h2>
      <p class="text-xs text-sidebar-foreground/40 mt-0.5">管理你的账户和偏好</p>
    </div>

    <!-- Divider -->
    <div class="mx-4 mb-2 h-px bg-sidebar-border/50" />

    <!-- Navigation items -->
    <div class="flex-1 min-h-0 flex flex-col gap-0.5 px-2">
      <button
        v-for="item in sections"
        :key="item.id"
        @click="selectSection(item.id)"
        class="group relative flex items-center w-full rounded-lg transition-all duration-150 gap-3 px-3 py-2 text-sm"
        :class="activeSection === item.id
          ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
          : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
      >
        <component
          :is="item.icon"
          :size="18"
          class="shrink-0 transition-colors"
          :class="activeSection === item.id
            ? 'text-primary'
            : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'"
        />
        <span class="whitespace-nowrap">{{ item.label }}</span>
      </button>
    </div>

    <!-- Footer hint -->
    <div class="shrink-0 px-4 py-3 border-t border-sidebar-border/50">
      <p class="text-[11px] text-sidebar-foreground/30 leading-relaxed">
        修改后点击保存以生效
      </p>
    </div>
  </nav>
</template>
