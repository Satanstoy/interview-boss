<script setup>
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
  <div
    data-slot="empty-content"
    :class="
      cn(
        'gap-4 text-sm flex w-full max-w-sm min-w-0 flex-col items-center text-balance',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
