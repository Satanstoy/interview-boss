<script setup>
import { MoreHorizontalIcon } from "@lucide/vue";

import { cn } from "@/lib/utils";

const props = defineProps({
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});
</script>

<template>
  <span
    data-slot="breadcrumb-ellipsis"
    role="presentation"
    aria-hidden="true"
    :class="
      cn('size-5 [&>svg]:size-4 flex items-center justify-center', props.class)
    "
  >
    <slot>
      <MoreHorizontalIcon />
    </slot>
    <span class="sr-only">More</span>
  </span>
</template>
