<template>
  <div class="relative">
    <AppTooltip :text="currentModel || '选择模型'">
      <button
        @click="toggleDropdown"
        type="button"
        class="flex items-center justify-center size-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
        :class="isOpen ? 'text-foreground bg-muted' : ''"
      >
        <Sparkles :size="16" />
      </button>
    </AppTooltip>

    <Transition name="dropdown">
      <div
        v-if="isOpen"
        class="absolute bottom-full left-0 mb-1 w-64 max-h-80 overflow-y-auto rounded-xl border border-border bg-card shadow-lg z-50"
      >
        <div class="p-2">
          <div v-if="loading" class="flex items-center justify-center py-4">
            <Loader2 :size="16" class="animate-spin text-muted-foreground" />
            <span class="ml-2 text-xs text-muted-foreground">加载中...</span>
          </div>

          <div v-else-if="error" class="py-3 px-2 text-center">
            <AlertCircle :size="16" class="mx-auto mb-1 text-destructive" />
            <p class="text-xs text-destructive">{{ error }}</p>
            <button
              @click="loadModels"
              class="mt-2 text-xs text-primary hover:underline"
            >
              重试
            </button>
          </div>

          <div v-else-if="models.length === 0" class="py-3 px-2 text-center">
            <p class="text-xs text-muted-foreground">暂无可用模型</p>
          </div>

          <template v-else>
            <button
              v-for="model in models"
              :key="model.id"
              @click="selectModel(model.id)"
              class="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors"
              :class="model.id === currentModel
                ? 'bg-primary/10 text-primary'
                : 'text-foreground hover:bg-muted'"
            >
              <Check v-if="model.id === currentModel" :size="14" class="shrink-0" />
              <div v-else class="size-3.5 shrink-0" />
              <span class="text-xs truncate">{{ model.name }}</span>
            </button>
          </template>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Sparkles, ChevronDown, Check, Loader2, AlertCircle } from '@lucide/vue'
import { fetchAvailableModels } from '@/services/profileApi.js'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  currentModel: { type: String, default: '' },
})

const emit = defineEmits(['select'])

const isOpen = ref(false)
const loading = ref(false)
const error = ref(null)
const models = ref([])

const displayModel = computed(() => {
  if (!props.currentModel) return '模型'
  const parts = props.currentModel.split('/')
  return parts[parts.length - 1] || props.currentModel
})

function toggleDropdown() {
  isOpen.value = !isOpen.value
  if (isOpen.value && models.value.length === 0) {
    loadModels()
  }
}

async function loadModels() {
  loading.value = true
  error.value = null
  try {
    const res = await fetchAvailableModels()
    models.value = res.models || []
    if (res.error) {
      error.value = res.error
    }
  } catch (e) {
    error.value = '获取模型列表失败'
    console.error('Failed to load models:', e)
  } finally {
    loading.value = false
  }
}

function selectModel(modelId) {
  emit('select', modelId)
  isOpen.value = false
}

function handleClickOutside(e) {
  if (!e.target.closest('.relative')) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
</script>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.15s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(4px) scale(0.95);
}
</style>
