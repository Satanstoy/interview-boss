<script setup>
import { reactiveOmit } from "@vueuse/core";
import { PaginationList } from "reka-ui";
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
  <PaginationList
    v-slot="slotProps"
    data-slot="pagination-content"
    v-bind="delegatedProps"
    :class="cn('gap-1 flex items-center', props.class)"
  >
    <slot v-bind="slotProps" />
  </PaginationList>
</template>
