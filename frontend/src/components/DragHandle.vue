<script setup lang="ts">
import { IconGripVertical } from "@tabler/icons-vue"
import { useSortableContext } from "dnd-kit-vue"
import { Button } from '@/components/ui/button'
import AppTooltip from '@/components/common/AppTooltip.vue'

const { handleRef, sortable } = useSortableContext()
</script>

<template>
  <AppTooltip text="拖动调整顺序">
    <Button
      :ref="handleRef"
      variant="ghost"
      size="icon"
      aria-label="拖动调整顺序"
      class="text-muted-foreground size-7 hover:bg-transparent"
    >
      <IconGripVertical class="text-muted-foreground size-3" />
      <span class="sr-only">Drag to reorder</span>
    </Button>
  </AppTooltip>
</template>
