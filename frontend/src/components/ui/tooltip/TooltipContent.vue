<script setup lang="ts">
import type { TooltipContentEmits, TooltipContentProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TooltipArrow, TooltipContent, TooltipPortal, useForwardPropsEmits } from "reka-ui"
import { cn } from "@/lib/utils"

defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<TooltipContentProps & { class?: HTMLAttributes["class"] }>(), {
  sideOffset: 8,
  collisionPadding: 12,
})

const emits = defineEmits<TooltipContentEmits>()

const delegatedProps = reactiveOmit(props, "class")
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <TooltipPortal>
    <TooltipContent
      data-slot="tooltip-content"
      data-material="glass"
      v-bind="{ ...forwarded, ...$attrs }"
      :class="cn('bg-popover text-popover-foreground border border-border/80 shadow-xl shadow-black/10 dark:shadow-black/30 backdrop-blur-sm animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-1.5 data-[side=left]:slide-in-from-right-1.5 data-[side=right]:slide-in-from-left-1.5 data-[side=top]:slide-in-from-bottom-1.5 z-50 w-fit max-w-64 rounded-lg px-2.5 py-1.5 text-xs leading-relaxed text-balance duration-150 ease-out will-change-transform', props.class)"
    >
      <slot />

      <TooltipArrow data-material="glass-arrow" class="size-2.5" />
    </TooltipContent>
  </TooltipPortal>
</template>
