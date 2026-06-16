<script setup>
import { MoreHorizontalIcon } from "@lucide/vue";

import { reactiveOmit } from "@vueuse/core";
import { PaginationEllipsis } from "reka-ui";
import { cn } from "@/lib/utils";

const props = defineProps({
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
  <PaginationEllipsis
    data-slot="pagination-ellipsis"
    v-bind="delegatedProps"
    :class="
      cn(
        'size-9 [&_svg:not([class*=size-])]:size-4 flex items-center justify-center',
        props.class,
      )
    "
  >
    <slot>
      <MoreHorizontalIcon />
      <span class="sr-only">More pages</span>
    </slot>
  </PaginationEllipsis>
</template>
