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
  <li
    data-slot="breadcrumb-item"
    :class="cn('gap-1.5 inline-flex items-center', props.class)"
  >
    <slot />
  </li>
</template>
