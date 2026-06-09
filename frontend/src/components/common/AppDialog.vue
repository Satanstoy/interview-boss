<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4"
        @keydown.esc="$emit('update:open', false)"
        tabindex="-1"
        ref="dialogRef"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-black/50 backdrop-blur-sm transition-opacity"
          @click="closeOnBackdrop && $emit('update:open', false)"
        />

        <!-- Panel -->
        <div
          class="relative w-full bg-white dark:bg-surface-800 rounded-2xl shadow-xl border border-surface-200/60 dark:border-ink-700/50 overflow-hidden"
          :class="maxWidthClass"
          :style="maxWidth ? { maxWidth } : {}"
        >
          <!-- Header -->
          <div v-if="title || description || $slots.header" class="px-6 pt-6 pb-0">
            <slot name="header">
              <h2 class="text-lg font-semibold text-ink-900 dark:text-ink-50">{{ title }}</h2>
              <p v-if="description" class="mt-1 text-sm text-ink-500 dark:text-ink-400">{{ description }}</p>
            </slot>
          </div>

          <!-- Content -->
          <div class="px-6 py-5">
            <slot />
          </div>

          <!-- Footer -->
          <div
            v-if="$slots.footer"
            class="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end px-6 py-4 border-t border-border/50 bg-surface-50/30 dark:bg-ink-800/30"
          >
            <slot name="footer" />
          </div>

          <!-- Close button -->
          <button
            v-if="showCloseButton"
            type="button"
            class="absolute top-4 right-4 inline-flex items-center justify-center w-7 h-7 rounded-md text-ink-400 hover:text-ink-600 hover:bg-surface-100 dark:hover:bg-ink-700 transition-colors"
            @click="$emit('update:open', false)"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            <span class="sr-only">关闭</span>
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

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

const dialogRef = ref(null)

const sizeMap = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  full: 'max-w-[90vw]',
}

const maxWidthClass = computed(() => {
  if (props.maxWidth) return ''
  return sizeMap[props.size] || 'max-w-lg'
})

watch(() => props.open, async (val) => {
  if (val) {
    await nextTick()
    dialogRef.value?.focus()
    document.body.style.overflow = 'hidden'
  } else {
    document.body.style.overflow = ''
  }
})
</script>

<style scoped>
.dialog-fade-enter-active {
  transition: opacity 0.25s ease;
}
.dialog-fade-leave-active {
  transition: opacity 0.18s ease;
}
.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}
.dialog-fade-enter-active > div:last-child {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease;
}
.dialog-fade-enter-from > div:last-child {
  opacity: 0;
  transform: scale(0.95) translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .dialog-fade-enter-active,
  .dialog-fade-leave-active {
    transition-duration: 0.01ms !important;
  }
  .dialog-fade-enter-active > div:last-child {
    transition-duration: 0.01ms !important;
  }
}
</style>
