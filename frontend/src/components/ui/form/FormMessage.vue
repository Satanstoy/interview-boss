<script setup>
import { ErrorMessage } from "vee-validate";
import { toValue } from "vue";
import { cn } from "@/lib/utils";
import { useFormField } from "./useFormField";

const props = defineProps({
  class: {
    type: [Boolean, null, String, Object, Array],
    required: false,
    skipCheck: true,
  },
});

const { name, formMessageId } = useFormField();
</script>

<template>
  <ErrorMessage
    :id="formMessageId"
    data-slot="form-message"
    as="p"
    :name="toValue(name)"
    :class="cn('text-destructive text-sm', props.class)"
  />
</template>
