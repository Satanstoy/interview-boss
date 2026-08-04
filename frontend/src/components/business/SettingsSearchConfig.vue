<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Loader2, Search, ShieldCheck, Trash2, Wifi } from '@lucide/vue'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import {
  deleteMySearchConfig,
  fetchMySearchConfig,
  testMySearchConfig,
  updateMySearchConfig,
} from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const { success: toastSuccess, error: toastError } = useToast()
const { confirm: showConfirm } = useConfirm()

const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const showKey = ref(false)
const error = ref('')
const testMessage = ref('')
const providers = ref([])
const savedProvider = ref('none')

const form = reactive({
  provider: 'none',
  api_key: '',
  base_url: '',
})

const settings = reactive({
  configured: false,
  api_key: '',
  api_key_set: false,
})

const selectedProvider = computed(() =>
  providers.value.find((item) => item.id === form.provider),
)

const baseUrlPlaceholder = computed(() => {
  if (form.provider === 'tavily') return '可选，例如 https://api.tavily.com/search'
  if (form.provider === 'brave') return '可选，例如 https://api.search.brave.com/res/v1/web/search'
  if (form.provider === 'bocha') return '可选，例如 https://api.bochaai.com/v1/web-search'
  return '留空使用系统默认地址'
})

const loadConfig = async () => {
  loading.value = true
  error.value = ''
  try {
    const data = await fetchMySearchConfig()
    providers.value = data.providers || []
    Object.assign(settings, {
      configured: Boolean(data.configured),
      ...(data.settings || {}),
    })
    form.provider = data.settings?.provider || 'none'
    savedProvider.value = form.provider
    form.api_key = ''
    form.base_url = data.settings?.base_url || ''
  } catch (e) {
    error.value = `加载失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  error.value = ''
  testMessage.value = ''
  if (form.provider !== 'none' && form.provider !== savedProvider.value && !form.api_key.trim()) {
    error.value = '切换服务商后请输入新的 API Key'
    return
  }
  if (form.provider !== 'none' && !settings.api_key_set && !form.api_key.trim()) {
    error.value = '请输入 API Key'
    return
  }

  saving.value = true
  try {
    const payload = {
      provider: form.provider,
      base_url: form.base_url.trim(),
    }
    if (form.api_key.trim()) payload.api_key = form.api_key.trim()
    await updateMySearchConfig(payload)
    toastSuccess(form.provider === 'none' ? '联网搜索已关闭' : '联网搜索配置已保存')
    await loadConfig()
  } catch (e) {
    error.value = `保存失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

const handleTest = async () => {
  error.value = ''
  testMessage.value = ''
  testing.value = true
  try {
    const data = await testMySearchConfig('Redis 缓存面试题 官方文档')
    testMessage.value = `连接成功，返回 ${data.count || 0} 条结果`
    toastSuccess('搜索服务连接成功')
  } catch (e) {
    error.value = `测试失败: ${e.message}`
    toastError('搜索服务连接失败')
  } finally {
    testing.value = false
  }
}

const handleDelete = async () => {
  if (!await showConfirm('确定要清除联网搜索配置吗？')) return
  saving.value = true
  try {
    await deleteMySearchConfig()
    toastSuccess('联网搜索配置已清除')
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
      <div class="flex items-center gap-2">
        <Search :size="18" class="text-primary" />
        <h3 class="text-lg font-semibold text-foreground">联网搜索</h3>
      </div>
      <p class="mt-1 text-sm text-muted-foreground">
        为答案生成提供最新的官方文档、技术实践和可靠来源，搜索结果只作为参考资料。
      </p>
    </div>

    <div class="rounded-xl border bg-card p-6 space-y-5">
      <div v-if="loading" class="flex items-center justify-center py-8">
        <Loader2 :size="22" class="animate-spin text-primary" />
      </div>

      <template v-else>
        <div class="space-y-2">
          <Label class="text-xs font-semibold text-muted-foreground">搜索服务商</Label>
          <select
            v-model="form.provider"
            class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
          >
            <option v-for="provider in providers" :key="provider.id" :value="provider.id">
              {{ provider.label }}
            </option>
          </select>
          <p v-if="selectedProvider" class="text-xs text-muted-foreground">
            {{ selectedProvider.description }}
          </p>
        </div>

        <template v-if="form.provider !== 'none'">
          <div class="space-y-2">
            <Label class="text-xs font-semibold text-muted-foreground">API Key</Label>
            <div class="relative">
              <Input
                v-model="form.api_key"
                :type="showKey ? 'text' : 'password'"
                :placeholder="settings.api_key_set ? '已配置，留空表示继续使用当前 Key' : '输入 API Key'"
                class="pr-20 font-mono"
              />
              <button
                type="button"
                class="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground hover:text-foreground"
                @click="showKey = !showKey"
              >
                {{ showKey ? '隐藏' : '显示' }}
              </button>
            </div>
            <p class="text-[11px] text-muted-foreground">当前 Key：{{ settings.api_key || '未设置' }}</p>
          </div>

          <div class="space-y-2">
            <Label class="text-xs font-semibold text-muted-foreground">Base URL（可选）</Label>
            <Input v-model="form.base_url" :placeholder="baseUrlPlaceholder" class="font-mono" />
            <p class="text-xs text-muted-foreground">只有使用代理或自定义网关时才需要填写。</p>
          </div>
        </template>

        <div class="flex flex-wrap items-center gap-2 pt-1">
          <Button :disabled="saving" size="sm" @click="handleSave">
            {{ saving ? '保存中...' : '保存配置' }}
          </Button>
          <Button
            v-if="form.provider !== 'none' && settings.configured"
            variant="outline"
            size="sm"
            :disabled="testing || saving"
            @click="handleTest"
          >
            <Wifi v-if="!testing" :size="14" />
            <Loader2 v-else :size="14" class="animate-spin" />
            <span class="ml-1">测试连接</span>
          </Button>
          <Button
            v-if="settings.configured"
            variant="outline"
            size="sm"
            class="text-destructive"
            :disabled="saving"
            @click="handleDelete"
          >
            <Trash2 :size="14" />
            <span class="ml-1">清除</span>
          </Button>
        </div>

        <div class="flex items-start gap-2 rounded-lg border border-primary/20 bg-primary/5 p-3 text-xs text-muted-foreground">
          <ShieldCheck :size="15" class="mt-0.5 shrink-0 text-primary" />
          <span>搜索服务商只会用于当前账户的答案增强。API Key 会被掩码显示，不会返回完整内容。</span>
        </div>
        <p v-if="testMessage" class="text-xs text-emerald-600 dark:text-emerald-400">{{ testMessage }}</p>
        <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
      </template>
    </div>
  </div>
</template>
