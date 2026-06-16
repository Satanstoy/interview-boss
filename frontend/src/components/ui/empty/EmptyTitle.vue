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
    data-slot="empty-title"
    :class="
      cn('text-lg font-medium tracking-tight cn-font-heading', props.class)
    "
  >
    <slot />
  </div>
</template>
