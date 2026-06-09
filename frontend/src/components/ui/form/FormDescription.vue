<script setup>
import { cn } from "@/lib/utils";
import { useFormField } from "./useFormField";

const props = defineProps({
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});

const { formDescriptionId } = useFormField();
</script>

<template>
  <p
    :id="formDescriptionId"
    data-slot="form-description"
    :class="cn('text-muted-foreground text-sm', props.class)"
  >
    <slot />
  </p>
</template>
