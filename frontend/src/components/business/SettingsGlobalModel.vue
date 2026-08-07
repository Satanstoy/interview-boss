<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useToast } from '@/composables/useNotification.js'
import { getSSE } from '@/services/http.js'
import {
  fetchProfile,
  updateProfile,
  fetchGlobalEmbeddingConfig,
  updateGlobalEmbeddingConfig,
  testGlobalLLM,
  testGlobalEmbedding,
} from '@/services/profileApi.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Loader2, Cpu, Sparkles } from '@lucide/vue'

const { success: toastSuccess, error: toastError } = useToast()

// ── 全局 LLM ──
const llmForm = reactive({ llm_model: '', llm_base_url: '', llm_api_key: '', llm_timeout: '120', llm_api_key_set: false })
const llmSaving = ref(false)
const llmTesting = ref(false)

// ── Embedding ──
const embForm = reactive({ backend: 'auto', model_repo: '', model_dir: '', api_model: '', api_key: '', dimension: '512', api_key_set: false })
const embSaving = ref(false)
const embTesting = ref(false)
const recomputeInfo = ref(null)

let sseAbort = null

onMounted(async () => {
  try {
    const profile = await fetchProfile({ noCache: true })
    const s = profile.settings || {}
    llmForm.llm_model = s.llm_model || ''
    llmForm.llm_base_url = s.llm_base_url || ''
    llmForm.llm_api_key = s.llm_api_key || ''
    llmForm.llm_timeout = String(s.llm_timeout || '120')
    llmForm.llm_api_key_set = !!s.llm_api_key_set
  } catch (e) {
    toastError('加载全局 LLM 配置失败：' + e.message)
  }
  await loadEmbedding()
})

onBeforeUnmount(() => {
  if (sseAbort) sseAbort.abort()
})

const saveGlobalLLM = async () => {
  llmSaving.value = true
  try {
    const settings = {
      llm_model: llmForm.llm_model,
      llm_base_url: llmForm.llm_base_url,
      llm_timeout: llmForm.llm_timeout,
    }
    if (llmForm.llm_api_key) settings.llm_api_key = llmForm.llm_api_key
    await updateProfile(settings)
    toastSuccess('全局 LLM 配置已保存')
    llmForm.llm_api_key = ''
    llmForm.llm_api_key_set = true
  } catch (e) {
    toastError('保存失败：' + e.message)
  } finally {
    llmSaving.value = false
  }
}

const handleTestGlobalLLM = async () => {
  llmTesting.value = true
  try {
    const status = await testGlobalLLM()
    if (status.connected) toastSuccess(`连接成功：模型 ${status.model || ''} 可正常使用`)
    else toastError(status.error || '连接失败')
  } catch (e) {
    toastError('测试失败：' + e.message)
  } finally {
    llmTesting.value = false
  }
}

const loadEmbedding = async () => {
  try {
    const data = await fetchGlobalEmbeddingConfig()
    const s = data.settings || {}
    embForm.backend = s.backend || 'auto'
    embForm.model_repo = s.model_repo || ''
    embForm.model_dir = s.model_dir || ''
    embForm.api_model = s.api_model || ''
    embForm.api_key = s.api_key || ''
    embForm.dimension = String(s.dimension || '512')
    embForm.api_key_set = !!s.api_key_set
  } catch (e) {
    toastError('加载 embedding 配置失败：' + e.message)
  }
}

const saveEmbedding = async () => {
  embSaving.value = true
  recomputeInfo.value = null
  if (sseAbort) { sseAbort.abort(); sseAbort = null }
  try {
    const settings = { backend: embForm.backend, dimension: Number(embForm.dimension) }
    if (embForm.api_model) settings.api_model = embForm.api_model
    if (embForm.api_key) settings.api_key = embForm.api_key
    const result = await updateGlobalEmbeddingConfig(settings)
    embForm.api_key = ''
    embForm.api_key_set = true
    toastSuccess('Embedding 配置已保存')
    if (result.recompute_triggered && result.recompute_job_id) {
      recomputeInfo.value = { message: '模型已更换，正在后台重算全部向量...' }
      subscribeRecompute(result.recompute_job_id)
    }
  } catch (e) {
    toastError('保存失败：' + e.message)
  } finally {
    embSaving.value = false
  }
}

const subscribeRecompute = (jobId) => {
  const controller = new AbortController()
  sseAbort = controller
  getSSE(`/api/jobs/${jobId}/stream`, (event) => {
    if (event.type === 'done') {
      recomputeInfo.value = { message: '重算完成' }
      if (sseAbort) { sseAbort.abort(); sseAbort = null }
    } else if (event.type === 'error') {
      recomputeInfo.value = { message: '重算失败：' + (event.message || '') }
      if (sseAbort) { sseAbort.abort(); sseAbort = null }
    } else {
      recomputeInfo.value = { message: event.message || `进度 ${event.current || 0}/${event.total || 0}` }
    }
  }, { signal: controller.signal })
}

const handleTestEmbedding = async () => {
  embTesting.value = true
  try {
    const result = await testGlobalEmbedding({
      backend: embForm.backend,
      api_key: embForm.api_key || undefined,
      api_model: embForm.api_model || undefined,
      model_dir: embForm.model_dir || undefined,
      dimension: embForm.dimension,
    })
    if (result.ok) toastSuccess(`连接成功：维度 ${result.dimension}`)
    else toastError(result.error || '连接失败')
  } catch (e) {
    toastError('测试失败：' + e.message)
  } finally {
    embTesting.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- 全局 LLM -->
    <div class="rounded-xl border bg-card p-6">
      <div class="flex items-center gap-2 mb-4">
        <Sparkles class="size-4 text-primary" />
        <h3 class="text-sm font-semibold">全局 LLM 配置</h3>
        <span class="text-xs text-muted-foreground ml-2">用户未配置自己的模型时回退到此配置</span>
      </div>
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>Base URL</Label>
          <Input v-model="llmForm.llm_base_url" placeholder="https://api.openai.com/v1" />
        </div>
        <div class="space-y-1.5">
          <Label>模型名称</Label>
          <Input v-model="llmForm.llm_model" placeholder="gpt-4o" />
        </div>
        <div class="space-y-1.5">
          <Label>API Key {{ llmForm.llm_api_key_set ? '（已配置，留空保持不变）' : '' }}</Label>
          <Input v-model="llmForm.llm_api_key" type="password" :placeholder="llmForm.llm_api_key_set ? '••••••••' : 'sk-...'" />
        </div>
        <div class="space-y-1.5">
          <Label>超时（秒）</Label>
          <Input v-model="llmForm.llm_timeout" type="number" min="5" max="600" />
        </div>
        <div class="flex gap-2">
          <Button size="sm" @click="saveGlobalLLM" :disabled="llmSaving">
            <Loader2 v-if="llmSaving" class="size-3.5 animate-spin" /> {{ llmSaving ? '保存中...' : '保存' }}
          </Button>
          <Button variant="outline" size="sm" @click="handleTestGlobalLLM" :disabled="llmTesting">
            <Loader2 v-if="llmTesting" class="size-3.5 animate-spin" /> {{ llmTesting ? '测试中...' : '测试连接' }}
          </Button>
        </div>
      </div>
    </div>

    <!-- Embedding -->
    <div class="rounded-xl border bg-card p-6">
      <div class="flex items-center gap-2 mb-4">
        <Cpu class="size-4 text-primary" />
        <h3 class="text-sm font-semibold">Embedding 配置</h3>
        <span class="text-xs text-muted-foreground ml-2">更换模型后自动全量重算向量</span>
      </div>
      <div class="space-y-4">
        <div class="space-y-1.5">
          <Label>后端模式</Label>
          <Select v-model="embForm.backend">
            <SelectTrigger class="w-[220px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">自动（ONNX 优先）</SelectItem>
              <SelectItem value="onnx">ONNX 本地模型</SelectItem>
              <SelectItem value="siliconflow">SiliconFlow API</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <template v-if="embForm.backend === 'siliconflow'">
          <div class="space-y-1.5">
            <Label>模型名</Label>
            <Input v-model="embForm.api_model" placeholder="BAAI/bge-m3" />
          </div>
          <div class="space-y-1.5">
            <Label>API Key {{ embForm.api_key_set ? '（已配置，留空保持不变）' : '' }}</Label>
            <Input v-model="embForm.api_key" type="password" :placeholder="embForm.api_key_set ? '••••••••' : 'sk-...'" />
          </div>
        </template>
        <template v-else>
          <div class="space-y-1.5">
            <Label>模型目录</Label>
            <Input v-model="embForm.model_dir" placeholder="/app/models/bge-small-zh-v1.5" />
          </div>
        </template>
        <div class="space-y-1.5">
          <Label>向量维度</Label>
          <Input v-model="embForm.dimension" type="number" min="1" placeholder="512" />
        </div>
        <div class="flex gap-2">
          <Button size="sm" @click="saveEmbedding" :disabled="embSaving">
            <Loader2 v-if="embSaving" class="size-3.5 animate-spin" /> {{ embSaving ? '保存中...' : '保存' }}
          </Button>
          <Button variant="outline" size="sm" @click="handleTestEmbedding" :disabled="embTesting">
            <Loader2 v-if="embTesting" class="size-3.5 animate-spin" /> {{ embTesting ? '测试中...' : '测试连接' }}
          </Button>
        </div>
        <p v-if="recomputeInfo" class="text-xs text-amber-600 dark:text-amber-400">
          {{ recomputeInfo.message }}
        </p>
      </div>
    </div>
  </div>
</template>
