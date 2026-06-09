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
  <nav
    aria-label="breadcrumb"
    data-slot="breadcrumb"
    :class="cn('', props.class)"
  >
    <slot />
  </nav>
</template>
