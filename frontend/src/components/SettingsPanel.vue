<template>
  <teleport to="body">
    <transition name="fade">
      <div v-if="visible" class="fixed inset-0 z-[100] flex items-start justify-center pt-[8vh] px-4">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="emit('close')"></div>

        <!-- Modal -->
        <div class="relative bg-white dark:bg-surface-800 rounded-3xl shadow-2xl w-full max-w-3xl max-h-[84vh] flex flex-col overflow-hidden animate-slide-up">
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 dark:border-gray-700 shrink-0 bg-gradient-to-r from-primary-50/50 to-accent-50/30 dark:from-primary-900/20 dark:to-accent-900/10">
            <div class="flex items-center gap-3">
              <div class="w-9 h-9 rounded-xl bg-gradient-brand flex items-center justify-center">
                <svg class="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
              </div>
              <h2 class="text-lg font-bold text-gray-800 dark:text-gray-100">系统配置</h2>
            </div>
            <button @click="emit('close')" class="p-2 rounded-xl text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition">
              <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="flex-1 overflow-y-auto custom-scrollbar px-6 py-5 space-y-6">
            <!-- Model config -->
            <div class="space-y-3.5 p-5 rounded-2xl border border-primary-100 dark:border-primary-800 bg-gradient-to-b from-primary-50/50 to-white dark:from-primary-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-primary-600 dark:text-primary-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
                主模型 (LLM)
              </h3>
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">API Key</label>
                <div v-if="llmKeySet && !editLlmKey" class="flex items-center gap-2">
                  <span class="flex-1 border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 dark:bg-surface-900 text-gray-500 dark:text-gray-400 select-none">{{ llmMasked }}</span>
                  <button @click="editLlmKey = true; form.llm_api_key = ''" type="button" class="text-xs text-primary-600 hover:text-primary-800 dark:text-primary-400 dark:hover:text-primary-300 whitespace-nowrap font-medium">更换</button>
                </div>
                <div v-else class="relative">
                  <input
                    v-model="form.llm_api_key"
                    :type="showLlmKey ? 'text' : 'password'"
                    class="w-full border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 pr-10 text-sm font-mono bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200"
                    placeholder="输入 API Key"
                  />
                  <button @click="showLlmKey = !showLlmKey" type="button" class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition">
                    <svg v-if="showLlmKey" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.878 9.878L3 3m6.878 6.878L21 21"/></svg>
                    <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"/></svg>
                  </button>
                </div>
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">Base URL</label>
                <input v-model="form.llm_base_url" type="text" class="w-full border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" placeholder="https://api.openai.com/v1" />
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">模型名称</label>
                <input v-model="form.llm_model" type="text" class="w-full border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 text-sm font-mono bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" placeholder="如 gpt-4o" />
              </div>
            </div>

            <!-- General settings -->
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">LLM 超时 (秒)</label>
                <input v-model="form.llm_timeout" type="number" min="10" max="600" class="w-full border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 text-sm bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
              </div>
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">当前招聘季</label>
                <select v-model="form.active_season" class="w-full border border-gray-200 dark:border-gray-600 rounded-xl px-3.5 py-2.5 text-sm bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
                  <option value="">未设置</option>
                  <option v-for="s in seasons" :key="s" :value="s">{{ s }}</option>
                </select>
                <div class="mt-2 flex gap-2">
                  <input v-model="newSeason" placeholder="新增招聘季" class="flex-1 border border-gray-200 dark:border-gray-600 rounded-xl px-3 py-2 text-xs bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
                  <button @click="addSeason" class="text-xs bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 px-3 py-2 rounded-xl hover:bg-primary-100 dark:hover:bg-primary-900/50 transition font-medium whitespace-nowrap border border-primary-200 dark:border-primary-800">添加</button>
                </div>
              </div>
            </div>

            <!-- Taxonomy config -->
            <div class="space-y-3.5 p-5 rounded-2xl border border-accent-100 dark:border-accent-800 bg-gradient-to-b from-accent-50/50 to-white dark:from-accent-900/20 dark:to-surface-800">
              <h3 class="text-xs font-bold text-accent-600 dark:text-accent-400 uppercase tracking-wider flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>
                分类管理
              </h3>

              <!-- Job position -->
              <div>
                <label class="text-xs font-semibold text-gray-600 dark:text-gray-400 mb-1.5 block">目标岗位</label>
                <div class="flex gap-2 flex-wrap mb-2">
                  <button
                    v-for="pos in availablePositions" :key="pos"
                    @click="onSwitchPosition(pos)"
                    :class="taxonomy.job_position === pos
                      ? 'bg-accent-100 dark:bg-accent-900/40 text-accent-700 dark:text-accent-300 border-accent-300 dark:border-accent-700'
                      : 'bg-white dark:bg-surface-900 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:border-accent-300 dark:hover:border-accent-700'"
                    class="px-3 py-1.5 text-xs rounded-lg border transition-all font-medium"
                  >{{ pos }}</button>
                </div>
                <div class="flex gap-2">
                  <input v-model="newPositionInput" placeholder="新增岗位" class="flex-1 border border-gray-200 dark:border-gray-600 rounded-xl px-3 py-2 text-xs bg-gray-50 dark:bg-surface-900 text-gray-800 dark:text-gray-100 focus:bg-white dark:focus:bg-surface-800 focus:ring-2 focus:ring-accent-200 dark:focus:ring-accent-800 focus:border-accent-400 transition-all duration-200" />
                  <button @click="addPosition" class="text-xs bg-accent-50 dark:bg-accent-900/30 text-accent-700 dark:text-accent-400 px-3 py-2 rounded-xl hover:bg-accent-100 dark:hover:bg-accent-900/50 transition font-medium whitespace-nowrap border border-accent-200 dark:border-accent-800">添加</button>
                </div>
              </div>

              <!-- Category list -->
              <div class="space-y-2">
                <div class="flex items-center justify-between">
                  <label class="text-xs font-semibold text-gray-600 dark:text-gray-400">一级大类 / 二级子类</label>
                  <button @click="addCat1" class="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-medium flex items-center gap-1">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                    添加大类
                  </button>
                </div>

                <div v-for="(cat, ci) in taxonomy.categories" :key="ci"
                  class="rounded-xl border border-gray-200 dark:border-gray-600 bg-white dark:bg-surface-900 overflow-hidden">
                  <!-- cat1 header -->
                  <div class="flex items-center gap-2 px-3 py-2.5 bg-gray-50 dark:bg-surface-800 border-b border-gray-100 dark:border-gray-700">
                    <button @click="cat._open = !cat._open" class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition">
                      <svg :class="{'rotate-90': cat._open}" class="w-4 h-4 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
                    </button>
                    <input v-model="cat.cat1"
                      class="flex-1 text-sm font-semibold bg-transparent border-none outline-none text-gray-800 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500"
                      placeholder="如 A.项目经验与设计" />
                    <span class="text-xs text-gray-400 dark:text-gray-500">{{ cat.children.length }} 个子类</span>
                    <button @click="removeCat1(ci)" class="text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400 transition p-1">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                    </button>
                  </div>
                  <!-- cat2 children -->
                  <div v-if="cat._open" class="p-3 space-y-1.5">
                    <div v-for="(child, ci2) in cat.children" :key="ci2" class="flex items-center gap-2">
                      <span class="text-gray-300 dark:text-gray-600 text-xs">-</span>
                      <input v-model="cat.children[ci2]"
                        class="flex-1 text-sm bg-transparent border-none outline-none text-gray-700 dark:text-gray-200 placeholder-gray-400 dark:placeholder-gray-500"
                        placeholder="如 A1.系统设计" />
                      <button @click="cat.children.splice(ci2, 1)" class="text-gray-300 dark:text-gray-600 hover:text-red-500 dark:hover:text-red-400 transition p-0.5">
                        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                      </button>
                    </div>
                    <button @click="cat.children.push('')" class="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-medium mt-1 flex items-center gap-1">
                      <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4"/></svg>
                      添加子类
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-between px-6 py-4 border-t border-gray-100 dark:border-gray-700 bg-gray-50/80 dark:bg-surface-900/80 shrink-0">
            <p v-if="saveMessage" class="text-xs font-medium flex items-center gap-1.5" :class="saveSuccess ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'">
              <svg v-if="saveSuccess" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              {{ saveMessage }}
            </p>
            <span v-else></span>
            <div class="flex gap-3">
              <button @click="emit('close')" :disabled="isSaving" class="btn-secondary px-5">取消</button>
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
import { fetchProfile, updateProfile, switchPosition } from '../api/index.js'
import { validateSeason, validateNumber, validateSettingsField, validateApiKey, validateBaseUrl } from '../utils/validate.js'
import { useToast } from '../composables/useNotification.js'

const toast = useToast()

const props = defineProps({
  visible: { type: Boolean, default: false },
  activeSeason: { type: String, default: '' }
})

const availablePositions = ref([])
const newPositionInput = ref('')

const taxonomy = reactive({
  job_position: 'agent开发/大模型应用开发/大模型开发',
  categories: []
})

const emit = defineEmits(['close', 'update:activeSeason'])

const seasons = ref([])
const isSaving = ref(false)
const saveMessage = ref('')
const saveSuccess = ref(false)
const newSeason = ref('')
const showLlmKey = ref(false)
const llmKeySet = ref(false)
const llmMasked = ref('')
const editLlmKey = ref(false)
const originalPosition = ref('')

const addCat1 = () => {
  taxonomy.categories.push({ cat1: '', children: [''], _open: true })
}
const removeCat1 = (index) => {
  taxonomy.categories.splice(index, 1)
}

const onSwitchPosition = async (pos) => {
  if (pos === taxonomy.job_position) return
  try {
    await switchPosition(pos)
    taxonomy.job_position = pos
    originalPosition.value = pos
    // 重新加载该岗位的分类
    const data = await fetchProfile()
    const s = data.settings
    if (s.taxonomy_config) {
      try {
        const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
        taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
      } catch { taxonomy.categories = [] }
    } else {
      taxonomy.categories = []
    }
    availablePositions.value = data.settings.available_positions || [pos]
    toast.success(`已切换到岗位：${pos}`)
  } catch (e) {
    toast.error(`切换失败: ${e.message}`)
  }
}

const addPosition = async () => {
  const pos = newPositionInput.value.trim()
  if (!pos) return
  if (availablePositions.value.includes(pos)) {
    toast.warning('该岗位已存在')
    return
  }
  newPositionInput.value = ''
  await onSwitchPosition(pos)
}

const form = reactive({
  active_season: '',
  llm_model: '',
  llm_api_key: '',
  llm_base_url: '',
  llm_timeout: 120
})

const loadProfile = async () => {
  try {
    const data = await fetchProfile()
    const s = data.settings
    form.active_season = s.active_season || ''
    form.llm_model = s.llm_model || ''
    form.llm_base_url = s.llm_base_url || ''
    form.llm_timeout = parseInt(s.llm_timeout) || 120
    llmKeySet.value = !!s.llm_api_key_set
    llmMasked.value = s.llm_api_key || ''
    editLlmKey.value = false
    form.llm_api_key = ''
    seasons.value = data.available_seasons || []

    // 加载分类体系和岗位列表
    availablePositions.value = s.available_positions || ['agent开发/大模型应用开发/大模型开发']
    if (s.taxonomy_config) {
      try {
        const tc = typeof s.taxonomy_config === 'string' ? JSON.parse(s.taxonomy_config) : s.taxonomy_config
        taxonomy.job_position = tc.job_position || s.current_job_position || 'agent开发/大模型应用开发/大模型开发'
        taxonomy.categories = (tc.categories || []).map(c => ({ ...c, _open: false }))
        originalPosition.value = taxonomy.job_position
      } catch { /* ignore parse error */ }
    }
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
  // 验证必填字段
  const requiredFields = {
    llm_model: '主模型名称',
    llm_base_url: '主模型 Base URL',
  }
  for (const [key, label] of Object.entries(requiredFields)) {
    const result = validateSettingsField(form[key], label)
    if (!result.valid) {
      saveMessage.value = result.error
      saveSuccess.value = false
      return
    }
  }

  // 验证 Base URL 格式
  const urlResult = validateBaseUrl(form.llm_base_url, '主模型 Base URL')
  if (!urlResult.valid) {
    saveMessage.value = urlResult.error
    saveSuccess.value = false
    return
  }

  // 验证数字字段
  const timeoutResult = validateNumber(form.llm_timeout, 10, 600, 'LLM 超时')
  if (!timeoutResult.valid) {
    saveMessage.value = timeoutResult.error
    saveSuccess.value = false
    return
  }

  // 验证可选 API Key
  if (form.llm_api_key) {
    const keyResult = validateApiKey(form.llm_api_key)
    if (!keyResult.valid) {
      saveMessage.value = keyResult.error
      saveSuccess.value = false
      return
    }
  }

  isSaving.value = true
  saveMessage.value = ''
  try {
    const payload = {
      active_season: form.active_season,
      llm_model: form.llm_model.trim(),
      llm_base_url: form.llm_base_url.trim(),
      llm_timeout: String(form.llm_timeout)
    }
    if (form.llm_api_key) payload.llm_api_key = form.llm_api_key.trim()

    // 分类体系
    const validCategories = taxonomy.categories
      .filter(c => c.cat1.trim())
      .map(c => ({ cat1: c.cat1.trim(), children: c.children.filter(x => x.trim()) }))
    if (validCategories.length > 0) {
      payload.taxonomy_config = JSON.stringify({ job_position: taxonomy.job_position, categories: validCategories })
    }

    await updateProfile(payload)
    llmKeySet.value = llmKeySet.value || !!form.llm_api_key
    editLlmKey.value = false
    form.llm_api_key = ''
    emit('update:activeSeason', form.active_season)

    saveMessage.value = '配置已保存'
    saveSuccess.value = true
    originalPosition.value = taxonomy.job_position
    setTimeout(() => { saveMessage.value = '' }, 3000)
  } catch (e) {
    saveMessage.value = `保存失败: ${e.message}`
    saveSuccess.value = false
  } finally {
    isSaving.value = false
  }
}

const addSeason = async () => {
  const result = validateSeason(newSeason.value)
  if (!result.valid) {
    saveMessage.value = result.error
    saveSuccess.value = false
    return
  }
  if (seasons.value.includes(result.value)) {
    saveMessage.value = '该招聘季已存在'
    saveSuccess.value = false
    return
  }
  seasons.value.push(result.value)
  form.active_season = result.value
  newSeason.value = ''

  // 立即保存到后端，避免用户关闭面板导致丢失
  try {
    await updateProfile({ active_season: result.value })
    emit('update:activeSeason', result.value)
    toast.success(`招聘季「${result.value}」已添加并设为当前`)
  } catch (e) {
    saveMessage.value = `添加失败: ${e.message}`
    saveSuccess.value = false
    // 回滚本地状态
    seasons.value = seasons.value.filter(s => s !== result.value)
  }
}
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
