<template>
  <div class="relative" ref="rootRef">
    <div class="flex gap-2">
      <Input
        v-model="modelInput"
        type="text"
        :placeholder="placeholder"
        class="font-mono flex-1"
        @input="emit('update:modelValue', modelInput)"
        @focus="onMainInputFocus"
      />
      <Button
        type="button"
        variant="outline"
        size="sm"
        @click="toggleDropdown"
        :disabled="loading && !isOpen"
      >
        <Loader2 v-if="loading" :size="14" class="animate-spin" />
        <Sparkles v-else :size="14" />
        <span class="ml-1">选择</span>
      </Button>
    </div>

    <Transition name="dropdown">
      <div
        v-if="isOpen"
        class="absolute top-full left-0 right-0 mt-1 rounded-xl border border-border bg-card shadow-lg z-50"
      >
        <div class="p-2 space-y-2">
          <!-- Search input -->
          <div class="relative">
            <Search
              :size="14"
              class="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
            />
            <Input
              ref="searchInputRef"
              v-model="searchQuery"
              type="text"
              placeholder="搜索模型名..."
              class="h-9 pl-8 font-mono text-xs"
              @keydown.down.prevent="moveActiveDown"
              @keydown.up.prevent="moveActiveUp"
              @keydown.enter.prevent="enterSelect"
              @keydown.escape="isOpen = false"
            />
          </div>

          <!-- Loading -->
          <div v-if="loading" class="flex items-center justify-center py-4">
            <Loader2 :size="16" class="animate-spin text-muted-foreground" />
            <span class="ml-2 text-xs text-muted-foreground">加载中...</span>
          </div>

          <!-- Error -->
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

          <!-- Empty -->
          <div
            v-else-if="filteredModels.length === 0"
            class="py-3 px-2 text-center"
          >
            <p class="text-xs text-muted-foreground">
              {{ searchQuery ? `未找到匹配 "${searchQuery}" 的模型` : '暂无可用模型' }}
            </p>
            <p v-if="searchQuery && models.length > 0" class="text-[10px] text-muted-foreground/70 mt-1">
              共 {{ models.length }} 个模型
            </p>
          </div>

          <!-- Model list -->
          <template v-else>
            <div class="max-h-72 overflow-y-auto custom-scrollbar" ref="listRef">
              <button
                v-for="(model, idx) in visibleModels"
                :key="model.id"
                :ref="(el) => setItemRef(el, idx)"
                @click="selectModel(model.id)"
                @mousemove="activeIndex = idx"
                class="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-left transition-colors"
                :class="
                  model.id === modelInput
                    ? 'bg-primary/10 text-primary'
                    : idx === activeIndex
                      ? 'bg-muted text-foreground'
                      : 'text-foreground hover:bg-muted'
                "
              >
                <Check v-if="model.id === modelInput" :size="14" class="shrink-0" />
                <div v-else class="size-3.5 shrink-0" />
                <span class="text-xs truncate font-mono">{{ model.id }}</span>
              </button>
            </div>
            <!-- Stats footer -->
            <div class="px-2 pt-1 pb-0.5 flex items-center justify-between text-[10px] text-muted-foreground/80 border-t border-border/50 mt-1">
              <span>
                {{ searchQuery ? `匹配 ${filteredModels.length} / ${models.length}` : `共 ${models.length} 个模型` }}
              </span>
              <span v-if="filteredModels.length > MAX_VISIBLE">仅显示前 {{ MAX_VISIBLE }} 条，请继续搜索</span>
            </div>
          </template>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { Sparkles, Check, Loader2, AlertCircle, Search } from '@lucide/vue'
import { fetchAvailableModels } from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'gpt-4o' },
})

const emit = defineEmits(['update:modelValue'])

const MAX_VISIBLE = 200

const rootRef = ref(null)
const searchInputRef = ref(null)
const listRef = ref(null)

const isOpen = ref(false)
const loading = ref(false)
const error = ref(null)
const models = ref([])
const searchQuery = ref('')
const modelInput = ref(props.modelValue)
const activeIndex = ref(0)
const itemRefs = ref([])

watch(
  () => props.modelValue,
  (val) => {
    modelInput.value = val
  },
)

function setItemRef(el, idx) {
  if (el) itemRefs.value[idx] = el
}

function onMainInputFocus() {
  // 主输入框聚焦时不自动打开下拉，避免与手动输入冲突
  // 仅当用户已经点过"选择"拉过列表，且想再次切换时，点击"选择"按钮即可
}

function toggleDropdown() {
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    // 每次打开时重置搜索词与高亮
    searchQuery.value = ''
    activeIndex.value = 0
    if (models.value.length === 0 && !error.value) {
      loadModels()
    }
    nextTick(() => {
      searchInputRef.value?.focus?.()
    })
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
  modelInput.value = modelId
  emit('update:modelValue', modelId)
  isOpen.value = false
  searchQuery.value = ''
  activeIndex.value = 0
}

const filteredModels = computed(() => {
  if (!searchQuery.value.trim()) return models.value
  const q = searchQuery.value.toLowerCase()
  return models.value.filter((m) => m.id && m.id.toLowerCase().includes(q))
})

const visibleModels = computed(() => filteredModels.value.slice(0, MAX_VISIBLE))

watch(filteredModels, () => {
  activeIndex.value = 0
})

function moveActiveDown() {
  if (visibleModels.value.length === 0) return
  activeIndex.value = Math.min(activeIndex.value + 1, visibleModels.value.length - 1)
  scrollActiveIntoView()
}

function moveActiveUp() {
  if (visibleModels.value.length === 0) return
  activeIndex.value = Math.max(activeIndex.value - 1, 0)
  scrollActiveIntoView()
}

function enterSelect() {
  const m = visibleModels.value[activeIndex.value]
  if (m) selectModel(m.id)
}

function scrollActiveIntoView() {
  nextTick(() => {
    const el = itemRefs.value[activeIndex.value]
    if (el && el.scrollIntoView) {
      el.scrollIntoView({ block: 'nearest' })
    }
  })
}

function handleClickOutside(e) {
  if (rootRef.value && !rootRef.value.contains(e.target)) {
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
  transform: translateY(-4px) scale(0.95);
}
</style>