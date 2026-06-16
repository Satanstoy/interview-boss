<script setup>
import { ChevronLeftIcon } from "@lucide/vue";

import { reactiveOmit } from "@vueuse/core";
import { PaginationPrev, useForwardProps } from "reka-ui";
import { cn } from "@/lib/utils";
import { buttonVariants } from '@/components/ui/button';

const props = defineProps({
  asChild: { type: Boolean, required: false },
  as: { type: null, required: false },
  size: { type: null, required: false, default: "default" },
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});

const delegatedProps = reactiveOmit(props, "class", "size");
const forwarded = useForwardProps(delegatedProps);
</script>

<template>
  <PaginationPrev
    data-slot="pagination-previous"
    :class="
      cn(buttonVariants({ variant: 'ghost', size }), 'pl-2!', props.class)
    "
    v-bind="forwarded"
  >
    <slot>
      <ChevronLeftIcon data-icon="inline-start" class="cn-rtl-flip" />
      <span class="hidden sm:block">Previous</span>
    </slot>
  </PaginationPrev>
</template>
