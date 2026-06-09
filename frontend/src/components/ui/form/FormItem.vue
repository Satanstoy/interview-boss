<script setup>
import { useId } from "reka-ui";
import { provide } from "vue";
import { cn } from "@/lib/utils";
import { FORM_ITEM_INJECTION_KEY } from "./injectionKeys";

const props = defineProps({
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});

const id = useId();
provide(FORM_ITEM_INJECTION_KEY, id);
</script>

<template>
  <div data-slot="form-item" :class="cn('grid gap-2', props.class)">
    <slot />
  </div>
</template>
