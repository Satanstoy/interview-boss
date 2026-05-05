<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[100] flex items-start justify-center pt-[8vh] px-4">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('close')"></div>

        <!-- Modal -->
        <div class="relative bg-white rounded-3xl shadow-2xl w-full max-w-3xl max-h-[84vh] flex flex-col overflow-hidden animate-slide-up">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0 bg-gradient-to-r from-primary-50/50 to-accent-50/30">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-xl bg-gradient-brand flex items-center justify-center">
                <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
              </div>
              <h2 class="text-lg font-bold text-gray-800">系统配置</h2>
            </div>
            <button @click="emit('close')" class="p-2 rounded-xl text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-5 space-y-6">
            <!-- Model config: two columns -->
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <!-- Main LLM -->
              <div class="space-y-3.5 p-5 rounded-2xl border border-primary-100 bg-gradient-to-b from-primary-50/50 to-white">
                <h3 class="text-xs font-bold text-primary-600 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                  主模型 (LLM)
                </h3>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">API Key</label>
                  <div v-if="llmKeySet && !editLlmKey" class="flex items-center gap-2">
                    <span class="flex-1 border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 text-gray-500 select-none">{{ llmMasked }}</span>
                    <button @click="editLlmKey = true; form.llm_api_key = ''" type="button" class="text-xs text-primary-600 hover:text-primary-800 whitespace-nowrap font-medium">更换</button>
                  </div>
                  <div v-else class="relative">
                    <input
                      v-model="form.llm_api_key"
                      :type="showLlmKey ? 'text' : 'password'"
                      class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 pr-10 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200"
                      placeholder="输入 API Key"
                    />
                    <button @click="showLlmKey = !showLlmKey" type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition">
                      <svg v-if="showLlmKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">Base URL</label>
                  <input v-model="form.llm_base_url" type="text" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200" placeholder="https://api.openai.com/v1" />
                </div>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">模型名称</label>
                  <input v-model="form.llm_model" type="text" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200" placeholder="如 gpt-4o" />
                </div>
              </div>

              <!-- Embedding -->
              <div class="space-y-3.5 p-5 rounded-2xl border border-emerald-100 bg-gradient-to-b from-emerald-50/50 to-white">
                <h3 class="text-xs font-bold text-emerald-600 uppercase tracking-wider flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"/></svg>
                  Embedding 模型
                </h3>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">API Key</label>
                  <div v-if="embKeySet && !editEmbKey" class="flex items-center gap-2">
                    <span class="flex-1 border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 text-gray-500 select-none">{{ embMasked }}</span>
                    <button @click="editEmbKey = true; form.embedding_api_key = ''" type="button" class="text-xs text-emerald-600 hover:text-emerald-800 whitespace-nowrap font-medium">更换</button>
                  </div>
                  <div v-else class="relative">
                    <input
                      v-model="form.embedding_api_key"
                      :type="showEmbKey ? 'text' : 'password'"
                      class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 pr-10 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-emerald-200 focus:border-emerald-400 transition-all duration-200"
                      placeholder="输入 API Key"
                    />
                    <button @click="showEmbKey = !showEmbKey" type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 transition">
                      <svg v-if="showEmbKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"/></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
                    </button>
                  </div>
                </div>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">Base URL</label>
                  <input v-model="form.embedding_base_url" type="text" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-emerald-200 focus:border-emerald-400 transition-all duration-200" placeholder="https://api.openai.com/v1" />
                </div>
                <div>
                  <label class="text-xs font-semibold text-gray-600 mb-1.5 block">模型名称</label>
                  <input v-model="form.embedding_model" type="text" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 focus:bg-white focus:ring-2 focus:ring-emerald-200 focus:border-emerald-400 transition-all duration-200" placeholder="如 text-embedding-3-small" />
                </div>
              </div>
            </div>

            <!-- General settings -->
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">LLM 超时 (秒)</label>
                <input v-model="form.llm_timeout" type="number" min="10" max="600" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200" />
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">相似度阈值</label>
                <input v-model="form.similarity_threshold" type="number" step="0.01" min="0" max="1" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200" />
                <p class="text-xs text-gray-400 mt-1.5">题目聚类阈值 (0-1)</p>
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 mb-1.5 block">当前招聘季</label>
                <select v-model="form.active_season" class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200">
                  <option value="">未设置</option>
                  <option v-for="s in seasons" :key="s" :value="s">{{ s }}</option>
                </select>
                <div class="mt-2 flex gap-2">
                  <input v-model="newSeason" placeholder="新增招聘季" class="flex-1 border border-gray-200 rounded-xl px-3 py-2 text-xs bg-gray-50 focus:bg-white focus:ring-2 focus:ring-primary-200 focus:border-primary-400 transition-all duration-200" />
                  <button @click="addSeason" class="text-xs bg-primary-50 text-primary-700 px-3 py-2 rounded-xl hover:bg-primary-100 transition font-medium whitespace-nowrap border border-primary-200">添加</button>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between px-6 py-4 border-t border-gray-100 bg-gray-50/80 shrink-0">
            <p v-if="saveMessage" class="text-xs font-medium flex items-center gap-1.5" :class="saveSuccess ? 'text-emerald-600' : 'text-red-600'">
              <svg v-if="saveSuccess" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              {{ saveMessage }}
            </p>
            <span v-else></span>
            <div class="flex gap-3">
              <button @click="emit('close')" class="btn-secondary px-5">取消</button>
              <button
                @click="saveProfile"
                :disabled="isSaving"
                class="btn-primary px-6"
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

watch(() => props.visible, (val) => {
  if (val) {
    saveMessage.value = ''
    loadProfile()
  }
})

const saveProfile = async () => {
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
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
