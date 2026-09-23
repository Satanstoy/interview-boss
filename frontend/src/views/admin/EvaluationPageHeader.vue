<script setup>
import AppPageHeader from '@/components/common/AppPageHeader.vue'

defineProps({
  title: { type: String, required: true },
  description: { type: String, default: '' },
})
</script>

<template>
  <div class="space-y-5">
    <AppPageHeader
      :title="title"
      :description="description"
    >
      <template v-if="$slots.actions" #actions>
        <slot name="actions" />
      </template>
    </AppPageHeader>
  </div>
</template>
