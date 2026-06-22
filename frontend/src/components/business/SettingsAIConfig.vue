<script setup>
import { ref, reactive, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { fetchMyLLMConfig, updateMyLLMConfig, deleteMyLLMConfig } from '@/services/profileApi.js'
import { validateBaseUrl } from '@/utils/validate.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const loading = ref(false)
const saving = ref(false)
const configured = ref(false)
const editKey = ref(false)
const showKey = ref(false)

const settings = reactive({
  llm_api_key: '',
  llm_api_key_set: false,
  llm_base_url: '',
  llm_model: '',
  llm_timeout: 120,
})

const form = reactive({
  llm_api_key: '',
  llm_base_url: '',
  llm_model: '',
  llm_timeout: 120,
})

const error = ref('')

const loadConfig = async () => {
  loading.value = true
  try {
    const data = await fetchMyLLMConfig()
    configured.value = data.configured
    if (data.configured) {
      Object.assign(settings, data.settings)
    }
  } catch (e) {
    console.error('加载 LLM 配置失败', e)
  } finally {
    loading.value = false
  }
}

const startEdit = () => {
  showKey.value = false
  error.value = ''
  form.llm_api_key = ''
  form.llm_base_url = settings.llm_base_url || ''
  form.llm_model = settings.llm_model || ''
  form.llm_timeout = settings.llm_timeout || 120
}

const handleSave = async () => {
  error.value = ''

  if (!form.llm_base_url.trim()) {
    error.value = 'Base URL 不能为空'
    return
  }
  const urlResult = validateBaseUrl(form.llm_base_url, 'Base URL')
  if (!urlResult.valid) {
    error.value = urlResult.error
    return
  }
  if (!form.llm_model.trim()) {
    error.value = '模型名称不能为空'
    return
  }

  saving.value = true
  try {
    const payload = {
      llm_base_url: form.llm_base_url.trim(),
      llm_model: form.llm_model.trim(),
      llm_timeout: Number(form.llm_timeout) || 120,
    }
    if (form.llm_api_key) {
      payload.llm_api_key = form.llm_api_key.trim()
    }
    await updateMyLLMConfig(payload)
    toast.success('AI 配置已保存')
    await loadConfig()
  } catch (e) {
    error.value = `保存失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

const handleDelete = async () => {
  if (!window.confirm('确定要清除 AI 配置吗？清除后需要重新配置才能使用 AI 功能。')) return

  saving.value = true
  try {
    await deleteMyLLMConfig()
    toast.success('AI 配置已清除')
    await loadConfig()
  } catch (e) {
    error.value = `清除失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

onMounted(loadConfig)
</script>

<template>
  <div class="w-full space-y-8">
    <div>
      <h3 class="text-lg font-semibold text-foreground">AI 配置</h3>
      <p class="text-sm text-muted-foreground mt-1">配置大语言模型 API 连接参数</p>
    </div>

    <div class="rounded-xl border bg-card p-6 space-y-4">
      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-8">
        <div class="size-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>

      <!-- Edit form (highest priority after loading) -->
      <div v-else-if="editKey" class="space-y-4">
        <!-- API Key -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">API Key</Label>
          <div v-if="settings.llm_api_key_set && !editKey" class="flex items-center gap-2">
            <span class="flex-1 border border-input rounded-md px-3 py-2 text-sm shadow-xs font-mono bg-muted dark:bg-background text-muted-foreground select-none">
              {{ settings.llm_api_key }}
            </span>
            <Button variant="link" size="sm" @click="editKey = true; form.llm_api_key = ''" class="whitespace-nowrap">
              更换
            </Button>
          </div>
          <div v-else class="relative">
            <Input
              v-model="form.llm_api_key"
              :type="showKey ? 'text' : 'password'"
              placeholder="输入 API Key"
              class="font-mono pr-10"
            />
            <button
              @click="showKey = !showKey"
              type="button"
              class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition"
            >
              <svg v-if="showKey" class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" />
              </svg>
              <svg v-else class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Base URL -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">Base URL <span class="text-destructive">*</span></Label>
          <Input
            v-model="form.llm_base_url"
            type="text"
            placeholder="https://api.openai.com/v1"
            class="font-mono"
          />
        </div>

        <!-- Model -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">模型名称 <span class="text-destructive">*</span></Label>
          <Input
            v-model="form.llm_model"
            type="text"
            placeholder="gpt-4o"
            class="font-mono"
          />
        </div>

        <!-- Timeout -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">超时 (秒)</Label>
          <Input
            v-model.number="form.llm_timeout"
            type="number"
            :min="10"
            :max="600"
            placeholder="120"
          />
        </div>

        <!-- Actions -->
        <div class="flex gap-2 pt-1">
          <Button @click="handleSave" :disabled="saving" size="sm">
            {{ saving ? '保存中...' : '保存' }}
          </Button>
          <Button variant="outline" size="sm" @click="editKey = false">取消</Button>
        </div>
        <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
      </div>

      <!-- Unconfigured hint -->
      <div
        v-else-if="!configured"
        class="flex items-center gap-3 p-3 rounded-xl bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800"
      >
        <svg class="size-5 text-amber-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        <span class="text-sm text-amber-700 dark:text-amber-300">请先配置 API Key 才能使用 AI 功能</span>
        <Button variant="outline" size="sm" @click="startEdit(); editKey = true" class="ml-auto">
          立即配置
        </Button>
      </div>

      <!-- Configured summary -->
      <div v-else class="space-y-4">
        <div class="flex flex-col gap-2 text-sm">
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">API Key</span>
            <span class="font-mono text-foreground truncate">{{ settings.llm_api_key || '未设置' }}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">Base URL</span>
            <span class="font-mono text-foreground truncate">{{ settings.llm_base_url || '未设置' }}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">模型</span>
            <span class="font-mono text-foreground truncate">{{ settings.llm_model || '未设置' }}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">超时</span>
            <span class="font-mono text-foreground">{{ settings.llm_timeout || 120 }}s</span>
          </div>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" @click="startEdit(); editKey = true">
            修改配置
          </Button>
          <Button variant="outline" size="sm" @click="handleDelete" class="text-destructive">
            清除配置
          </Button>
        </div>
      </div>
    </div>
  </div>
</template>
