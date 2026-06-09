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
  <ol
    data-slot="breadcrumb-list"
    :class="
      cn(
        'text-muted-foreground gap-1.5 text-sm sm:gap-2.5 flex flex-wrap items-center wrap-break-word',
        props.class,
      )
    "
  >
    <slot />
  </ol>
</template>
