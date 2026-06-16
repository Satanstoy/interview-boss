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
    data-slot="empty-header"
    :class="cn('gap-2 flex max-w-sm flex-col items-center', props.class)"
  >
    <slot />
  </div>
</template>
