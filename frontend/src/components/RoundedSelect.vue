<template>
  <div ref="containerRef" class="relative inline-block" :class="wrapperClass">
    <!-- Trigger -->
    <button
      type="button"
      @click="toggle"
      @keydown.escape="close"
      @keydown.enter.prevent="toggle"
      @keydown.arrow-down.prevent="openAndFocus(0)"
      class="flex items-center justify-between gap-2 w-full border border-surface-200 dark:border-ink-600 rounded-xl text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-200 transition-all duration-200 hover:border-surface-300 dark:hover:border-ink-500 focus:outline-none focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400"
      :class="[sizeClass, triggerClass]"
    >
      <span class="truncate" :class="!selectedLabel ? 'text-ink-400 dark:text-ink-500' : ''">
        {{ selectedLabel || placeholder || '请选择' }}
      </span>
      <svg class="w-4 h-4 shrink-0 text-ink-400 dark:text-ink-500 transition-transform duration-200" :class="{ 'rotate-180': isOpen }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/>
      </svg>
    </button>

    <!-- Dropdown -->
    <Transition name="dropdown">
      <div
        v-if="isOpen"
        class="absolute z-50 w-full mt-1.5 bg-white dark:bg-surface-800 border border-surface-200 dark:border-ink-600 rounded-xl shadow-lg dark:shadow-glass-dark overflow-hidden"
        :class="dropdownClass"
      >
        <div class="max-h-60 overflow-y-auto custom-scrollbar py-1">
          <button
            v-for="(opt, idx) in options"
            :key="opt.value"
            :ref="el => { if (el) optionRefs[idx] = el }"
            type="button"
            @click="selectOption(opt)"
            @mouseenter="highlightedIndex = idx"
            class="w-full text-left px-3.5 py-2 text-sm transition-colors duration-100 flex items-center justify-between gap-2"
            :class="[
              opt.value === modelValue
                ? 'bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 font-medium'
                : highlightedIndex === idx
                  ? 'bg-surface-50 dark:bg-ink-800 text-ink-800 dark:text-ink-200'
                  : 'text-ink-700 dark:text-ink-300 hover:bg-surface-50 dark:hover:bg-ink-800'
            ]"
          >
            <span class="truncate">{{ opt.label }}</span>
            <svg v-if="opt.value === modelValue" class="w-4 h-4 shrink-0 text-primary-500 dark:text-primary-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
            </svg>
          </button>
          <div v-if="options.length === 0" class="px-3.5 py-3 text-sm text-ink-400 dark:text-ink-500 text-center">
            暂无选项
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] }, // [{value, label}]
  placeholder: { type: String, default: '' },
  size: { type: String, default: 'md' }, // 'sm' | 'md' | 'lg'
  wrapperClass: { type: String, default: '' },
  triggerClass: { type: String, default: '' },
  dropdownClass: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue'])

const isOpen = ref(false)
const highlightedIndex = ref(-1)
const containerRef = ref(null)
const optionRefs = ref({})

const sizeClass = computed(() => ({
  sm: 'px-3 py-1.5 text-xs',
  md: 'px-3.5 py-2.5 text-sm',
  lg: 'px-4 py-3 text-base',
}[props.size] || 'px-3.5 py-2.5 text-sm'))

const selectedLabel = computed(() => {
  const found = props.options.find(o => o.value === props.modelValue)
  return found ? found.label : ''
})

const toggle = () => {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    highlightedIndex.value = props.options.findIndex(o => o.value === props.modelValue)
  }
}

const close = () => {
  isOpen.value = false
  highlightedIndex.value = -1
}

const openAndFocus = (idx) => {
  isOpen.value = true
  highlightedIndex.value = idx
  nextTick(() => optionRefs.value[idx]?.focus())
}

const selectOption = (opt) => {
  emit('update:modelValue', opt.value)
  close()
}

const handleClickOutside = (e) => {
  if (containerRef.value && !containerRef.value.contains(e.target)) {
    close()
  }
}

const handleKeydown = (e) => {
  if (!isOpen.value) return
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    highlightedIndex.value = Math.min(highlightedIndex.value + 1, props.options.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
  } else if (e.key === 'Enter' && highlightedIndex.value >= 0) {
    e.preventDefault()
    selectOption(props.options[highlightedIndex.value])
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeydown)
})
</script>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px) scale(0.98);
}
</style>
