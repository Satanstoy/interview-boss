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
    data-slot="popover-title"
    :class="cn('font-medium cn-font-heading', props.class)"
  >
    <slot />
  </div>
</template>
