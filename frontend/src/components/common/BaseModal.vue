<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4"
        :class="align === 'top' ? 'items-start pt-[8vh]' : 'items-center'"
        @keydown.esc="$emit('close')"
        tabindex="-1"
        ref="backdropEl"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-black/50 backdrop-blur-sm"
          @click="closeOnBackdrop && $emit('close')"
        />
        <!-- Panel -->
        <div
          class="relative w-full bg-white dark:bg-surface-800 rounded-2xl shadow-xl border border-surface-200/60 dark:border-ink-700/50 overflow-hidden"
          :class="[sizeClass, panelClass]"
          :style="maxWidth ? { maxWidth } : {}"
        >
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  maxWidth: { type: String, default: '' },
  size: { type: String, default: 'md' },
  align: { type: String, default: 'center' },
  closeOnBackdrop: { type: Boolean, default: true },
  panelClass: { type: String, default: '' },
})

defineEmits(['close'])

const backdropEl = ref(null)

const sizeClass = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  full: 'max-w-[90vw]',
}[props.size] || 'max-w-lg'

watch(() => props.visible, async (val) => {
  if (val) {
    await nextTick()
    backdropEl.value?.focus()
  }
})
</script>

<style scoped>
.modal-fade-enter-active {
  transition: opacity 0.25s ease;
}
.modal-fade-leave-active {
  transition: opacity 0.18s ease;
}
.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}
.modal-fade-enter-active > div:last-child {
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), opacity 0.25s ease;
}
.modal-fade-enter-from > div:last-child {
  opacity: 0;
  transform: scale(0.95) translateY(8px);
}

@media (prefers-reduced-motion: reduce) {
  .modal-fade-enter-active,
  .modal-fade-leave-active {
    transition-duration: 0.01ms !important;
  }
  .modal-fade-enter-active > div:last-child {
    transition-duration: 0.01ms !important;
  }
}
</style>
