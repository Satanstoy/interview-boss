<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[100] flex items-start justify-center pt-[10vh] px-4">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40" @click="emit('close')"></div>

        <!-- Modal -->
        <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[80vh] flex flex-col overflow-hidden">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
            <h2 class="text-lg font-bold text-gray-800">系统配置</h2>
            <button @click="emit('close')" class="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-6 py-5 space-y-5">
            <!-- Model config: two columns -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <!-- Main LLM -->
              <div class="space-y-3 p-4 rounded-xl border border-blue-100 bg-blue-50/40">
                <h3 class="text-xs font-bold text-blue-700 uppercase tracking-wide">主模型 (LLM)</h3>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">API Key</label>
                  <div v-if="llmKeySet && !editLlmKey" class="flex items-center gap-2">
                    <span class="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono bg-gray-50 text-gray-500 select-none">{{ llmMasked }}</span>
                    <button @click="editLlmKey = true; form.llm_api_key = ''" type="button" class="text-xs text-blue-600 hover:text-blue-800 whitespace-nowrap">更换</button>
                  </div>
                  <div v-else class="relative">
                    <input
                      v-model="form.llm_api_key"
                      :type="showLlmKey ? 'text' : 'password'"
                      class="w-full border border-gray-300 rounded-lg px-3 py-2 pr-10 text-sm font-mono focus:ring-blue-500 focus:border-blue-500"
                      placeholder="输入 API Key"
                    />
                    <button @click="showLlmKey = !showLlmKey" type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      <svg v-if="showLlmKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" /></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">Base URL</label>
                  <input v-model="form.llm_base_url" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-blue-500 focus:border-blue-500" placeholder="https://api.openai.com/v1" />
                </div>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">模型名称</label>
                  <input v-model="form.llm_model" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-blue-500 focus:border-blue-500" placeholder="如 gpt-4o" />
                </div>
              </div>

              <!-- Embedding -->
              <div class="space-y-3 p-4 rounded-xl border border-emerald-100 bg-emerald-50/40">
                <h3 class="text-xs font-bold text-emerald-700 uppercase tracking-wide">Embedding 模型</h3>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">API Key</label>
                  <div v-if="embKeySet && !editEmbKey" class="flex items-center gap-2">
                    <span class="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono bg-gray-50 text-gray-500 select-none">{{ embMasked }}</span>
                    <button @click="editEmbKey = true; form.embedding_api_key = ''" type="button" class="text-xs text-emerald-600 hover:text-emerald-800 whitespace-nowrap">更换</button>
                  </div>
                  <div v-else class="relative">
                    <input
                      v-model="form.embedding_api_key"
                      :type="showEmbKey ? 'text' : 'password'"
                      class="w-full border border-gray-300 rounded-lg px-3 py-2 pr-10 text-sm font-mono focus:ring-emerald-500 focus:border-emerald-500"
                      placeholder="输入 API Key"
                    />
                    <button @click="showEmbKey = !showEmbKey" type="button" class="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      <svg v-if="showEmbKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21" /></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">Base URL</label>
                  <input v-model="form.embedding_base_url" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-emerald-500 focus:border-emerald-500" placeholder="https://api.openai.com/v1" />
                </div>
                <div>
                  <label class="text-xs font-medium text-gray-600 mb-1 block">模型名称</label>
                  <input v-model="form.embedding_model" type="text" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-emerald-500 focus:border-emerald-500" placeholder="如 text-embedding-3-small" />
                </div>
              </div>
            </div>

            <!-- General settings -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">LLM 超时 (秒)</label>
                <input v-model="form.llm_timeout" type="number" min="10" max="600" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500" />
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">相似度阈值</label>
                <input v-model="form.similarity_threshold" type="number" step="0.01" min="0" max="1" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500" />
                <p class="text-xs text-gray-400 mt-1">题目聚类阈值 (0-1)</p>
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">当前招聘季</label>
                <select v-model="form.active_season" class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500">
                  <option value="">未设置</option>
                  <option v-for="s in seasons" :key="s" :value="s">{{ s }}</option>
                </select>
                <div class="mt-1.5 flex gap-2">
                  <input v-model="newSeason" placeholder="新增招聘季" class="flex-1 border border-gray-300 rounded-lg px-3 py-1.5 text-xs focus:ring-indigo-500 focus:border-indigo-500" />
                  <button @click="addSeason" class="text-xs bg-indigo-100 text-indigo-700 px-3 py-1.5 rounded-lg hover:bg-indigo-200 transition font-medium whitespace-nowrap">添加</button>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50 shrink-0">
            <p v-if="saveMessage" class="text-xs" :class="saveSuccess ? 'text-green-600' : 'text-red-600'">{{ saveMessage }}</p>
            <span v-else></span>
            <div class="flex gap-3">
              <button @click="emit('close')" class="px-4 py-2 text-sm text-gray-600 hover:bg-gray-200 rounded-lg transition">取消</button>
              <button
                @click="saveProfile"
                :disabled="isSaving"
                class="bg-indigo-600 text-white font-semibold text-sm px-6 py-2 rounded-lg hover:bg-indigo-700 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ isSaving ? '保存中...' : '保存配置' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </transition>
  </teleport>
</template>

<script setup>
import { ref, reactive, watch } from 'vue'
import { fetchProfile, updateProfile } from '../api/index.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
  activeSeason: { type: String, default: '' }
})

const emit = defineEmits(['close', 'update:activeSeason'])

const seasons = ref([])
const isSaving = ref(false)
const saveMessage = ref('')
const saveSuccess = ref(false)
const newSeason = ref('')
const showLlmKey = ref(false)
const showEmbKey = ref(false)
const llmKeySet = ref(false)
const embKeySet = ref(false)
const llmMasked = ref('')
const embMasked = ref('')
const editLlmKey = ref(false)
const editEmbKey = ref(false)

const form = reactive({
  active_season: '',
  llm_model: '',
  llm_api_key: '',
  llm_base_url: '',
  embedding_model: '',
  embedding_api_key: '',
  embedding_base_url: '',
  similarity_threshold: 0.85,
  llm_timeout: 120
})

const loadProfile = async () => {
  try {
    const data = await fetchProfile()
    const s = data.settings
    form.active_season = s.active_season || ''
    form.llm_model = s.llm_model || ''
    form.llm_base_url = s.llm_base_url || ''
    form.embedding_model = s.embedding_model || ''
    form.embedding_base_url = s.embedding_base_url || ''
    form.similarity_threshold = parseFloat(s.similarity_threshold) || 0.85
    form.llm_timeout = parseInt(s.llm_timeout) || 120
    llmKeySet.value = !!s.llm_api_key_set
    embKeySet.value = !!s.embedding_api_key_set
    llmMasked.value = s.llm_api_key || ''
    embMasked.value = s.embedding_api_key || ''
    editLlmKey.value = false
    editEmbKey.value = false
    form.llm_api_key = ''
    form.embedding_api_key = ''
    seasons.value = data.available_seasons || []
  } catch (e) {
    console.error('加载配置失败', e)
  }
}

// 每次打开弹窗时重新加载配置
watch(() => props.visible, (val) => {
  if (val) {
    saveMessage.value = ''
    loadProfile()
  }
})

const saveProfile = async () => {
  // 前端校验必填字段
  const required = {
    llm_model: '主模型名称',
    llm_base_url: '主模型 Base URL',
    embedding_model: 'Embedding 模型名称',
    embedding_base_url: 'Embedding Base URL'
  }
  const empty = Object.entries(required).filter(([k]) => !form[k]?.trim())
  if (empty.length > 0) {
    const names = empty.map(([, label]) => label).join('、')
    saveMessage.value = `${names} 不能为空`
    saveSuccess.value = false
    return
  }

  isSaving.value = true
  saveMessage.value = ''
  try {
    const payload = {
      active_season: form.active_season,
      llm_model: form.llm_model,
      llm_base_url: form.llm_base_url,
      embedding_model: form.embedding_model,
      embedding_base_url: form.embedding_base_url,
      similarity_threshold: String(form.similarity_threshold),
      llm_timeout: String(form.llm_timeout)
    }
    if (form.llm_api_key) payload.llm_api_key = form.llm_api_key
    if (form.embedding_api_key) payload.embedding_api_key = form.embedding_api_key

    await updateProfile(payload)
    saveMessage.value = '配置已保存（已同步到 .env）'
    saveSuccess.value = true
    llmKeySet.value = llmKeySet.value || !!form.llm_api_key
    embKeySet.value = embKeySet.value || !!form.embedding_api_key
    editLlmKey.value = false
    editEmbKey.value = false
    form.llm_api_key = ''
    form.embedding_api_key = ''
    emit('update:activeSeason', form.active_season)
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e) {
    saveMessage.value = `保存失败: ${e.message}`
    saveSuccess.value = false
  } finally {
    isSaving.value = false
  }
}

const addSeason = () => {
  const val = newSeason.value.trim()
  if (val && !seasons.value.includes(val)) {
    seasons.value.push(val)
    form.active_season = val
    newSeason.value = ''
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}
</style>
