<script setup lang="ts">
import type { TabsTriggerProps } from "reka-ui"
import type { HTMLAttributes } from "vue"
import { reactiveOmit } from "@vueuse/core"
import { TabsTrigger, useForwardProps } from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps<TabsTriggerProps & { class?: HTMLAttributes["class"] }>()

const delegatedProps = reactiveOmit(props, "class")

const forwardedProps = useForwardProps(delegatedProps)
</script>

<template>
  <TabsTrigger
    data-slot="tabs-trigger"
    :class="cn(
      'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:outline-ring relative inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 px-4 py-2 text-xs font-semibold whitespace-nowrap transition-colors focus-visible:ring-3 focus-visible:outline-1 disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=\'size-\'])]:size-4',
      // inactive text
      'text-ink-500 dark:text-ink-400 hover:text-ink-700 dark:hover:text-ink-300',
      // active text
      'data-[state=active]:text-primary-700 dark:data-[state=active]:text-primary-400',
      // underline indicator pseudo-element
      'after:absolute after:bottom-0 after:left-2 after:right-2 after:h-0.5 after:rounded-full after:bg-primary-500 after:content-[\'\'] after:transition-transform after:duration-200',
      'after:scale-x-0 data-[state=active]:after:scale-x-100',
      'dark:after:bg-primary-400',
      props.class,
    )"
    v-bind="forwardedProps"
  >
    <slot />
  </TabsTrigger>
</template>
