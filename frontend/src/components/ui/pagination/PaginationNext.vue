<script setup>
import { ChevronRightIcon } from "@lucide/vue";

import { reactiveOmit } from "@vueuse/core";
import { PaginationNext, useForwardProps } from "reka-ui";
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
  <PaginationNext
    data-slot="pagination-next"
    :class="
      cn(buttonVariants({ variant: 'ghost', size }), 'pr-2!', props.class)
    "
    v-bind="forwarded"
  >
    <slot>
      <span class="hidden sm:block">Next</span>
      <ChevronRightIcon data-icon="inline-end" class="cn-rtl-flip" />
    </slot>
  </PaginationNext>
</template>
