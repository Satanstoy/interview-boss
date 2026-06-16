<script setup>
import { cn } from "@/lib/utils";
import { buttonVariants } from '@/components/ui/button';

const props = defineProps({
  href: { type: String, required: false },
  size: { type: null, required: false, default: "icon" },
  isActive: { type: Boolean, required: false, default: false },
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});
</script>

<template>
  <a
    :href="href"
    data-slot="pagination-link"
    :data-active="isActive ? '' : undefined"
    :aria-current="isActive ? 'page' : undefined"
    :class="
      cn(
        buttonVariants({
          variant: isActive ? 'outline' : 'ghost',
          size,
        }),
        '',
        props.class,
      )
    "
  >
    <slot />
  </a>
</template>
