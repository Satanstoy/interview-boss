<template>
  <div class="bg-white dark:bg-surface-800 rounded-xl shadow-md border border-surface-200 dark:border-ink-600 mb-6 lg:mb-10 overflow-hidden">
    <div class="bg-surface-50 dark:bg-surface-900 p-4 border-b border-surface-200 dark:border-ink-600 flex items-center gap-4">
      <label class="font-semibold text-ink-700 dark:text-ink-300 whitespace-nowrap">来源链接 (URL):</label>
      <input
        v-model="sourceUrl"
        type="text"
        class="flex-1 border border-surface-300 dark:border-ink-600 rounded-lg p-2 bg-white dark:bg-ink-800 text-ink-800 dark:text-ink-100 focus:ring-blue-500 focus:border-blue-500 dark:focus:ring-blue-400 dark:focus:border-blue-400"
        placeholder="粘贴小红书/牛客网帖子链接 (用于去重，避免重复录入)"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 divide-x divide-gray-100 dark:divide-gray-700">
      <div class="p-4 lg:p-6 flex flex-col">
        <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-2">文本内容</label>
        <textarea
          v-model="stagedText"
          class="flex-1 w-full border border-surface-300 dark:border-ink-600 rounded-lg p-3 bg-white dark:bg-ink-800 text-ink-800 dark:text-ink-100 focus:ring-blue-500 focus:border-blue-500 dark:focus:ring-blue-400 dark:focus:border-blue-400 resize-none"
          placeholder="在此处粘贴面经或 JD 的纯文本内容（可与右侧图片组合提交）..."
        ></textarea>
      </div>

      <div
        class="p-4 lg:p-6 flex flex-col transition-colors relative"
        :class="isDragging ? 'bg-blue-50 dark:bg-blue-900/30' : ''"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleDrop"
      >
        <div class="flex justify-between items-center mb-2">
          <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300">图片 ({{ stagedFiles.length }} 张)</label>
          <div>
            <input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect" accept="image/*" />
            <button @click="$refs.fileInput.click()" class="text-sm bg-surface-200 dark:bg-ink-700 text-ink-700 dark:text-ink-300 px-4 py-2.5 min-h-[44px] rounded-lg hover:bg-gray-300 dark:hover:bg-gray-600 transition">
              + 选择图片
            </button>
          </div>
        </div>

        <div class="flex-1 border-2 border-dashed border-surface-300 dark:border-ink-600 rounded-lg p-4 overflow-y-auto max-h-48 bg-surface-50 dark:bg-ink-800 custom-scrollbar">
          <div v-if="stagedFiles.length === 0" class="h-full flex flex-col items-center justify-center text-ink-400 dark:text-ink-500">
            <svg class="h-8 w-8 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <p class="text-sm">拖拽图片到此处，或使用 Ctrl+V 粘贴（移动端点击上方按钮选择）</p>
          </div>

          <div v-else class="flex flex-wrap gap-3">
            <div v-for="(item, index) in stagedFiles" :key="item.id" class="relative group">
              <img :src="item.preview" class="h-24 w-24 object-cover rounded-md border border-surface-300 dark:border-ink-600 shadow-sm" @error="handleImgError" />
              <button @click="removeFile(index)" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition shadow">
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="bg-surface-50 dark:bg-surface-900 border-t border-surface-200 dark:border-ink-600 p-4 flex flex-col items-center">
      <!-- 类型和季节选择 -->
      <div class="flex gap-4 w-full mb-4">
        <div class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">导入类型</label>
          <select v-model="importType" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
            <option value="auto">自动识别</option>
            <option value="jd">JD (职位描述)</option>
            <option value="interview">面经</option>
          </select>
        </div>
        <div class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">招聘季节</label>
          <select v-model="selectedSeason" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
            <option v-for="s in availableSeasons" :key="s" :value="s">{{ s }}</option>
            <option value="custom">自定义...</option>
          </select>
          <input v-if="selectedSeason === 'custom'" v-model="customSeason" placeholder="输入招聘季名称" class="mt-2 w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
        </div>
        <div v-if="isAdmin" class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">提交到</label>
          <select v-model="importTarget" class="w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200">
            <option value="personal">个人题库</option>
            <option value="public">公共题库</option>
          </select>
        </div>
      </div>

      <div class="flex gap-4 w-full justify-end mb-4">
        <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2 rounded-lg text-ink-600 dark:text-ink-400 hover:bg-surface-200 dark:hover:bg-ink-700 transition">
          清空
        </button>
        <button
          @click="submitAll"
          :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
          class="bg-blue-600 text-white font-bold px-8 py-2 rounded-lg hover:bg-blue-700 transition shadow-md disabled:bg-blue-300 dark:disabled:bg-blue-800 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          {{ isUploading ? '处理中...' : '提交解析' }}
        </button>
      </div>

      <!-- 进度指示器 -->
      <div v-if="isUploading" class="w-full flex items-center justify-center gap-3 py-2">
        <div class="flex items-center gap-2">
          <template v-for="s in submitStepList" :key="s.key">
            <div class="flex items-center gap-1.5">
              <span
                class="inline-block w-2 h-2 rounded-full transition-colors duration-300"
                :class="s.active ? 'bg-blue-500 animate-pulse-slow' : s.done ? 'bg-blue-300 dark:bg-blue-600' : 'bg-gray-300 dark:bg-gray-600'"
              ></span>
              <span class="text-xs whitespace-nowrap" :class="s.active ? 'text-blue-600 dark:text-blue-400 font-medium' : s.done ? 'text-blue-300 dark:text-blue-600' : 'text-gray-400 dark:text-gray-500'">{{ s.label }}</span>
            </div>
            <svg v-if="s.key !== 'save'" class="w-3 h-3 text-gray-300 dark:text-gray-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
          </template>
        </div>
        <span class="text-xs text-gray-500 dark:text-gray-400 ml-2">{{ submitProgress.message }}</span>
      </div>

      <div v-if="uploadResult" class="text-green-600 dark:text-green-400 font-medium w-full text-center bg-green-50 dark:bg-green-900/30 p-2 rounded">
        解析成功！类型：<span class="font-bold ml-1">{{ uploadResult.doc_type || uploadResult.type }}</span>
      </div>
      <div v-if="uploadError" class="text-red-600 dark:text-red-400 font-medium w-full text-center bg-red-50 dark:bg-red-900/30 p-2 rounded">
        {{ uploadError }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { submitDataSSE } from '../api/index.js'
import { validateUrl, validateFiles, sanitizeText, sanitizeAgainstInjection } from '../utils/validate.js'
import { getFriendlyError } from '../utils/http.js'

const emit = defineEmits(['submitted'])

const props = defineProps({
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] },
  isAdmin: { type: Boolean, default: false },
})

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)
const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)
const submitProgress = ref({ step: '', message: '' })
const submitStepsDef = [
  { key: 'extract', label: '提取内容' },
  { key: 'fill', label: '补全信息' },
  { key: 'tag', label: '标注题目' },
  { key: 'match', label: '匹配聚类' },
  { key: 'save', label: '保存入库' },
]
const submitStepList = computed(() => {
  const curIdx = submitStepsDef.findIndex(s => s.key === submitProgress.value.step)
  return submitStepsDef.map((s, i) => ({
    ...s,
    active: i === curIdx,
    done: curIdx >= 0 && i < curIdx,
  }))
})

// 类型和季节选择
const importType = ref('auto')
const selectedSeason = ref(props.activeSeason || '')
const customSeason = ref('')
const importTarget = ref('personal')

// 监听 activeSeason 变化
watch(() => props.activeSeason, (val) => {
  if (val && !selectedSeason.value) {
    selectedSeason.value = val
  }
})

const handleImgError = (e) => {
  e.target.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iOTYiIGhlaWdodD0iOTYiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI2U1ZTdlYiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0ibWlkZGxlIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjOWNhM2FmIiBmb250LXNpemU9IjE0Ij7lm77niYc8L3RleHQ+PC9zdmc+'
  e.target.alt = '图片加载失败'
}

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB per file
const MAX_FILES = 20

const addFileToStaging = (file) => {
  if (!file.type.startsWith('image/')) return
  if (stagedFiles.value.length >= MAX_FILES) {
    uploadError.value = `最多上传 ${MAX_FILES} 张图片`
    return
  }
  if (file.size > MAX_FILE_SIZE) {
    uploadError.value = `图片 "${file.name}" 超过 10MB 限制`
    return
  }
  stagedFiles.value.push({
    id: Date.now() + Math.random(),
    file,
    preview: URL.createObjectURL(file)
  })
}

const handleDrop = (e) => {
  isDragging.value = false
  Array.from(e.dataTransfer.files).forEach(addFileToStaging)
}

const handleFileSelect = (e) => {
  Array.from(e.target.files).forEach(addFileToStaging)
  e.target.value = null
}

const removeFile = (index) => {
  URL.revokeObjectURL(stagedFiles.value[index].preview)
  stagedFiles.value.splice(index, 1)
}

const clearStaging = () => {
  stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
  stagedFiles.value = []
  stagedText.value = ''
  sourceUrl.value = ''
  uploadResult.value = null
  uploadError.value = null
}

const submitAll = async () => {
  if (!stagedText.value.trim() && stagedFiles.value.length === 0) return

  // 验证 URL（如果提供）
  if (sourceUrl.value.trim()) {
    const urlResult = validateUrl(sourceUrl.value)
    if (!urlResult.valid) {
      uploadError.value = urlResult.error
      return
    }
  }

  // 检测文本内容中的注入攻击
  if (stagedText.value.trim()) {
    try {
      sanitizeAgainstInjection(stagedText.value, '文本内容')
    } catch (e) {
      uploadError.value = e.message
      return
    }
  }

  // 验证文件
  if (stagedFiles.value.length > 0) {
    const fileResult = validateFiles(stagedFiles.value.map(f => f.file))
    if (!fileResult.valid) {
      uploadError.value = fileResult.error
      return
    }
  }

  isUploading.value = true
  uploadResult.value = null
  uploadError.value = null
  submitProgress.value = { step: '', message: '' }

  const formData = new FormData()
  formData.append('url', sanitizeText(sourceUrl.value, 2048))
  formData.append('text', stagedText.value.slice(0, 100000)) // 100KB text limit

  // 处理季节选择
  let season = selectedSeason.value
  if (season === 'custom') {
    season = customSeason.value.trim()
  }
  formData.append('season', season || props.activeSeason || '2027届暑期实习')

  // 处理类型选择
  if (importType.value !== 'auto') {
    formData.append('content_type', importType.value)
  }

  // 处理目标选择
  formData.append('target', importTarget.value)

  stagedFiles.value.forEach(item => formData.append('files', item.file))

  try {
    const data = await submitDataSSE(formData, (event) => {
      if (event.step) {
        submitProgress.value = { step: event.step, message: event.message || '' }
      }
    })
    uploadResult.value = data
    stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
    stagedFiles.value = []
    stagedText.value = ''
    emit('submitted')
  } catch (err) {
    uploadError.value = getFriendlyError(err, '提交失败，请稍后重试')
  } finally {
    isUploading.value = false
    submitProgress.value = { step: '', message: '' }
  }
}

const handleGlobalPaste = (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return
  for (const item of e.clipboardData.items) {
    if (item.type.indexOf('image') !== -1) {
      addFileToStaging(item.getAsFile())
    } else if (item.type === 'text/plain') {
      item.getAsString((text) => {
        stagedText.value += (stagedText.value ? '\n' : '') + text
      })
    }
  }
}

onMounted(() => window.addEventListener('paste', handleGlobalPaste))
onUnmounted(() => window.removeEventListener('paste', handleGlobalPaste))
</script>
