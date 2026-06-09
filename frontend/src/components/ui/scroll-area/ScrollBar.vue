<script setup>
import { reactiveOmit } from "@vueuse/core";
import { ScrollAreaScrollbar, ScrollAreaThumb } from "reka-ui";
import { cn } from "@/lib/utils";

const props = defineProps({
  orientation: { type: String, required: false, default: "vertical" },
  forceMount: { type: Boolean, required: false },
  asChild: { type: Boolean, required: false },
  as: { type: null, required: false },
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});

const delegatedProps = reactiveOmit(props, "class");
</script>

<template>
  <ScrollAreaScrollbar
    data-slot="scroll-area-scrollbar"
    :data-orientation="orientation"
    v-bind="delegatedProps"
    :class="
      cn(
        'data-horizontal:h-2.5 data-horizontal:flex-col data-horizontal:border-t data-horizontal:border-t-transparent data-vertical:h-full data-vertical:w-2.5 data-vertical:border-l data-vertical:border-l-transparent flex touch-none p-px transition-colors select-none',
        props.class,
      )
    "
  >
    <ScrollAreaThumb
      data-slot="scroll-area-thumb"
      class="rounded-full relative flex-1 bg-border"
    />
  </ScrollAreaScrollbar>
</template>
