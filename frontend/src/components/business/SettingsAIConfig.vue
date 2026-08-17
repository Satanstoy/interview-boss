<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { useModelGuard } from '@/composables/useModelGuard.js'
import { fetchMyLLMConfig, validateMyLLMConfig, updateMyLLMConfig, deleteMyLLMConfig } from '@/services/profileApi.js'
import { validateBaseUrl } from '@/utils/validate.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import ModelSelectField from '@/components/business/ModelSelectField.vue'

const { success: toastSuccess, error: toastError, warning: toastWarning } = useToast()
const { confirm: showConfirm } = useConfirm()
const { invalidateModelStatus, testModelConnection, testing } = useModelGuard()
const loading = ref(false)
const saving = ref(false)
const configured = ref(false)
const editKey = ref(false)
const showKey = ref(false)
const validating = ref(false)
const validationState = ref('')
const validationMessage = ref('')
const validatedFingerprint = ref('')

const settings = reactive({
  llm_api_key: '',
  llm_api_key_set: false,
  llm_base_url: '',
  llm_model: '',
  llm_timeout: 120,
  llm_api_format: 'auto',
  llm_thinking: false,
})

const form = reactive({
  llm_api_key: '',
  llm_base_url: '',
  llm_model: '',
  llm_timeout: 120,
  llm_api_format: 'auto',
  llm_thinking: false,
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
  form.llm_api_format = settings.llm_api_format || 'auto'
  form.llm_thinking = !!settings.llm_thinking
  validatedFingerprint.value = ''
  validationState.value = ''
  validationMessage.value = ''
}

const invalidateValidation = () => {
  validatedFingerprint.value = ''
  if (!validating.value) {
    validationState.value = ''
    validationMessage.value = ''
  }
}

const validationFingerprint = () => JSON.stringify({
  apiKey: form.llm_api_key.trim(),
  baseUrl: form.llm_base_url.trim(),
  model: form.llm_model.trim(),
  timeout: Number(form.llm_timeout) || 120,
  apiFormat: form.llm_api_format || 'auto',
})

const validateLocalFields = () => {
  if (!form.llm_base_url.trim()) {
    error.value = 'Base URL 不能为空'
    return false
  }
  const urlResult = validateBaseUrl(form.llm_base_url, 'Base URL')
  if (!urlResult.valid) {
    error.value = urlResult.error
    return false
  }
  if (!form.llm_model.trim()) {
    error.value = '模型名称不能为空'
    return false
  }
  return true
}

const buildConfigPayload = () => {
  const payload = {
    llm_base_url: form.llm_base_url.trim(),
    llm_model: form.llm_model.trim(),
    llm_timeout: Number(form.llm_timeout) || 120,
    llm_api_format: form.llm_api_format || 'auto',
    llm_thinking: !!form.llm_thinking,
  }
  if (form.llm_api_key.trim()) {
    payload.llm_api_key = form.llm_api_key.trim()
  }
  return payload
}

const validateFormConnection = async () => {
  error.value = ''
  if (!validateLocalFields()) return false

  validating.value = true
  validationState.value = ''
  validationMessage.value = '正在探测接口格式，请稍候...'
  const probeFingerprint = validationFingerprint()
  try {
    const result = await validateMyLLMConfig(buildConfigPayload())
    if (validationFingerprint() !== probeFingerprint) {
      validatedFingerprint.value = ''
      validationState.value = 'warning'
      validationMessage.value = '配置在探测期间发生变化，请重新检测接口'
      toastWarning(validationMessage.value)
      return false
    }
    if (result.connected && result.compatible) {
      validationState.value = 'success'
      validationMessage.value = result.message || '接口格式校验成功'
      validatedFingerprint.value = probeFingerprint
      return true
    }

    if (result.connected && result.suggested_format) {
      form.llm_api_format = result.suggested_format
      validatedFingerprint.value = ''
      validationState.value = 'warning'
      validationMessage.value = result.message || '已切换到检测到的接口格式，请再次保存确认'
      toastWarning(validationMessage.value)
      return false
    }

    validationState.value = 'error'
    validationMessage.value = result.error || result.message || '接口探测失败，请检查配置'
    toastError(validationMessage.value)
    return false
  } catch (e) {
    validationState.value = 'error'
    validationMessage.value = `接口探测失败：${e.message}`
    toastError(validationMessage.value)
    return false
  } finally {
    validating.value = false
  }
}

const handleFormatChange = (value) => {
  form.llm_api_format = value
  invalidateValidation()
}

const handleSave = async () => {
  error.value = ''
  if (!validateLocalFields()) return

  if (validatedFingerprint.value !== validationFingerprint()) {
    const valid = await validateFormConnection()
    if (!valid) return
  }

  saving.value = true
  try {
    await updateMyLLMConfig(buildConfigPayload())
    toastSuccess('AI 配置已保存')
    invalidateModelStatus()
    await loadConfig()
  } catch (e) {
    error.value = `保存失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

const handleDelete = async () => {
  if (!await showConfirm('确定要清除 AI 配置吗？清除后需要重新配置才能使用 AI 功能。')) return

  saving.value = true
  try {
    await deleteMyLLMConfig()
    toastSuccess('AI 配置已清除')
    invalidateModelStatus()
    await loadConfig()
  } catch (e) {
    error.value = `清除失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

const handleTestConnection = async () => {
  const status = await testModelConnection()
  if (status.connected) {
    toastSuccess(`连接成功：模型 ${status.model || ''} 可正常提供服务`)
  } else {
    toastError(status.error || '连接失败，请检查配置')
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
          <p v-if="settings.llm_api_key_set" class="text-xs text-muted-foreground mb-1.5">已设置 API Key，留空则保持不变</p>
          <div class="relative">
            <Input
              v-model="form.llm_api_key"
              :type="showKey ? 'text' : 'password'"
              placeholder="输入 API Key"
              class="font-mono pr-10"
              @input="invalidateValidation"
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
          <div class="flex gap-2">
            <Input
              v-model="form.llm_base_url"
              type="text"
              placeholder="https://api.openai.com/v1"
              class="font-mono flex-1"
              @input="invalidateValidation"
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              :disabled="saving || validating"
              @click="validateFormConnection"
            >
              {{ validating ? '探测中...' : '检测接口' }}
            </Button>
          </div>
        </div>

        <!-- Model -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">模型名称 <span class="text-destructive">*</span></Label>
          <ModelSelectField
            v-model="form.llm_model"
            placeholder="gpt-4o"
            @update:model-value="invalidateValidation"
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
            @input="invalidateValidation"
          />
        </div>

        <!-- 接口类型 -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">接口类型</Label>
          <Select v-model="form.llm_api_format" @update:model-value="handleFormatChange">
            <SelectTrigger class="w-full h-10 text-sm">
              <SelectValue placeholder="自动检测" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">自动检测（推荐）</SelectItem>
              <SelectItem value="chat">OpenAI Chat Completions</SelectItem>
              <SelectItem value="responses">OpenAI Responses</SelectItem>
              <SelectItem value="anthropic">Anthropic Messages</SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs text-muted-foreground mt-1.5">保存前会验证接口类型；如果检测到实际格式不同，会自动切换并提示你再次确认保存。</p>
        </div>

        <p
          v-if="validationMessage"
          class="text-xs"
          :class="validationState === 'success' ? 'text-emerald-600 dark:text-emerald-400' : validationState === 'warning' ? 'text-amber-600 dark:text-amber-400' : validationState === 'error' ? 'text-destructive' : 'text-muted-foreground'"
        >
          {{ validationMessage }}
        </p>

        <!-- 深度思考 -->
        <div>
          <Label class="text-xs font-semibold text-muted-foreground mb-1.5">深度思考</Label>
          <Select :model-value="form.llm_thinking ? '1' : '0'" @update:model-value="(v) => form.llm_thinking = v === '1'">
            <SelectTrigger class="w-full h-10 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">关闭（更快，推荐）</SelectItem>
              <SelectItem value="1">开启</SelectItem>
            </SelectContent>
          </Select>
          <p class="text-xs text-muted-foreground mt-1.5">mimo 关闭深度思考可显著提速，且 temperature 参数才会真正生效</p>
        </div>

        <!-- Actions -->
        <div class="flex gap-2 pt-1">
          <Button @click="handleSave" :disabled="saving || validating" size="sm">
            {{ saving ? '保存中...' : validating ? '检测中...' : '保存' }}
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
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">接口类型</span>
            <span class="font-mono text-foreground">{{ settings.llm_api_format === 'auto' ? '自动检测' : settings.llm_api_format }}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-muted-foreground w-16 shrink-0">深度思考</span>
            <span class="font-mono text-foreground">{{ settings.llm_thinking ? '开启' : '关闭' }}</span>
          </div>
        </div>
        <div class="flex gap-2">
          <Button variant="outline" size="sm" @click="handleTestConnection" :disabled="testing">
            {{ testing ? '测试中...' : '测试连接' }}
          </Button>
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
