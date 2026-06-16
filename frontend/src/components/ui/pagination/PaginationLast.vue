<script setup>
import { ChevronsRightIcon } from "@lucide/vue";

import { reactiveOmit } from "@vueuse/core";
import { PaginationLast, useForwardProps } from "reka-ui";
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
  <PaginationLast
    data-slot="pagination-last"
    :class="cn(buttonVariants({ variant: 'ghost', size }), '', props.class)"
    v-bind="forwarded"
  >
    <slot>
      <span class="hidden sm:block">Last</span>
      <ChevronsRightIcon data-icon="inline-end" />
    </slot>
  </PaginationLast>
</template>
