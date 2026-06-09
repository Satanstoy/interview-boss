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
    data-slot="popover-header"
    :class="cn('flex flex-col gap-1 text-sm', props.class)"
  >
    <slot />
  </div>
</template>
