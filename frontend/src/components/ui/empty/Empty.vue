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
    data-slot="empty"
    :class="
      cn(
        'gap-4 rounded-lg border-dashed p-12 flex w-full min-w-0 flex-1 flex-col items-center justify-center text-center text-balance',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
