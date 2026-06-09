<template>
  <Dialog :open="open" @update:open="$emit('update:open', $event)">
    <DialogContent :class="maxWidthClass" :show-close-button="showCloseButton">
      <DialogHeader v-if="title || description || $slots.header">
        <slot name="header">
          <DialogTitle v-if="title">{{ title }}</DialogTitle>
          <DialogDescription v-if="description">{{ description }}</DialogDescription>
        </slot>
      </DialogHeader>

      <slot />

      <DialogFooter v-if="$slots.footer">
        <slot name="footer" />
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup>
import { computed } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  maxWidth: { type: String, default: '' },
  size: { type: String, default: 'md' },
  showCloseButton: { type: Boolean, default: true },
  closeOnBackdrop: { type: Boolean, default: true },
})

defineEmits(['update:open'])

const sizeMap = {
  sm: 'sm:max-w-sm',
  md: 'sm:max-w-lg',
  lg: 'sm:max-w-2xl',
  xl: 'sm:max-w-4xl',
  full: 'sm:max-w-[90vw]',
}

const maxWidthClass = computed(() => {
  if (props.maxWidth) return props.maxWidth
  return sizeMap[props.size] || 'sm:max-w-lg'
})
</script>
