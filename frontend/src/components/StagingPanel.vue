<template>
  <div class="bg-white dark:bg-surface-800 rounded-2xl shadow-md border border-surface-200 dark:border-ink-600 mb-4 overflow-hidden">
    <!-- Header -->
    <div class="bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 px-5 py-3 border-b border-surface-200 dark:border-ink-600">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-500 flex items-center justify-center shadow-sm">
          <svg class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
        </div>
        <div>
          <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100">导入面经 / JD</h3>
          <p class="text-xs text-ink-500 dark:text-ink-400">粘贴文本或拖拽图片，AI 自动识别提取面试题</p>
        </div>
      </div>
    </div>

    <div class="bg-surface-50/50 dark:bg-surface-900/50 p-4 border-b border-surface-200 dark:border-ink-600 flex items-center gap-4">
      <label class="font-semibold text-ink-700 dark:text-ink-300 whitespace-nowrap text-sm">来源链接</label>
      <input
        v-model="sourceUrl"
        type="text"
        class="flex-1 border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-800 focus:border-blue-400 transition-all duration-200"
        placeholder="粘贴小红书/牛客网帖子链接（可选，用于去重）"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 divide-x divide-gray-100 dark:divide-gray-700">
      <div class="p-3 lg:p-4 flex flex-col">
        <label class="block text-sm font-semibold text-ink-700 dark:text-ink-300 mb-2">文本内容</label>
        <textarea
          v-model="stagedText"
          class="flex-1 w-full border border-surface-300 dark:border-ink-600 rounded-lg p-3 bg-white dark:bg-ink-800 text-ink-800 dark:text-ink-100 focus:ring-blue-500 focus:border-blue-500 dark:focus:ring-blue-400 dark:focus:border-blue-400 resize-none"
          placeholder="在此处粘贴面经或 JD 的纯文本内容（可与右侧图片组合提交）..."
        ></textarea>
      </div>

      <div
        class="p-3 lg:p-4 flex flex-col transition-colors relative"
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

    <div class="bg-surface-50/80 dark:bg-surface-900/80 border-t border-surface-200 dark:border-ink-600 p-4 flex flex-col items-center">
      <!-- 类型和季节选择 -->
      <div class="flex gap-4 w-full mb-4">
        <div class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">导入类型</label>
          <RoundedSelect
            v-model="importType"
            :options="[
              { value: 'auto', label: '自动识别' },
              { value: 'jd', label: 'JD (职位描述)' },
              { value: 'interview', label: '面经' }
            ]"
            wrapper-class="w-full"
            trigger-class="w-full"
          />
        </div>
        <div class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">招聘季节</label>
          <RoundedSelect
            v-model="selectedSeason"
            :options="seasonOptions"
            wrapper-class="w-full"
            trigger-class="w-full"
          />
          <input v-if="selectedSeason === 'custom'" v-model="customSeason" placeholder="输入招聘季名称" class="mt-2 w-full border border-surface-200 dark:border-ink-600 rounded-xl px-3.5 py-2.5 text-sm bg-white dark:bg-surface-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 transition-all duration-200" />
        </div>
        <div v-if="isAdmin" class="flex-1">
          <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">提交到</label>
          <RoundedSelect
            v-model="importTarget"
            :options="[
              { value: 'personal', label: '个人题库' },
              { value: 'public', label: '公共题库' }
            ]"
            wrapper-class="w-full"
            trigger-class="w-full"
          />
        </div>
      </div>

      <div class="flex gap-4 w-full justify-end mb-4">
        <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2.5 rounded-xl text-ink-600 dark:text-ink-400 hover:bg-surface-200 dark:hover:bg-ink-700 transition border border-surface-200 dark:border-ink-600">
          清空
        </button>
        <button
          @click="submitAll"
          :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
          class="bg-gradient-to-r from-blue-600 to-indigo-600 text-white font-bold px-8 py-2.5 rounded-xl hover:from-blue-700 hover:to-indigo-700 transition-all shadow-md hover:shadow-lg disabled:from-blue-300 disabled:to-indigo-300 dark:disabled:from-blue-800 dark:disabled:to-indigo-800 disabled:cursor-not-allowed flex items-center gap-2 active:scale-[0.98]"
        >
          <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          {{ isUploading ? '处理中...' : '提交解析' }}
        </button>
      </div>

      <!-- 进度指示器 -->
      <div v-if="isUploading" class="w-full py-3">
        <!-- 进度条 -->
        <div class="w-full bg-surface-200 dark:bg-ink-700 rounded-full h-1.5 mb-3 overflow-hidden">
          <div
            class="h-full rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 transition-all duration-700 ease-out"
            :style="{ width: `${((submitStepList.findIndex(s => s.active) + 1) / submitStepsDef.length) * 100}%` }"
          ></div>
        </div>
        <!-- 步骤标签 -->
        <div class="flex items-center justify-center gap-2 mb-2">
          <template v-for="(s, idx) in submitStepList" :key="s.key">
            <div class="flex items-center gap-1.5">
              <span
                class="inline-flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold transition-all duration-300"
                :class="s.active ? 'bg-blue-500 text-white animate-pulse-slow' : s.done ? 'bg-blue-500 text-white' : 'bg-surface-200 dark:bg-ink-600 text-ink-400 dark:text-ink-500'"
              >
                <svg v-if="s.done" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                <span v-else>{{ idx + 1 }}</span>
              </span>
              <span class="text-xs whitespace-nowrap" :class="s.active ? 'text-blue-600 dark:text-blue-400 font-semibold' : s.done ? 'text-ink-500 dark:text-ink-400' : 'text-ink-300 dark:text-ink-600'">{{ s.label }}</span>
            </div>
            <svg v-if="s.key !== 'save'" class="w-3 h-3 text-surface-300 dark:text-ink-600 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
          </template>
        </div>
        <!-- 当前步骤消息 + 详情 -->
        <div class="text-center">
          <span class="text-xs text-ink-500 dark:text-ink-400">{{ submitProgress.message }}</span>
          <span v-if="progressDetail" class="text-xs text-ink-400 dark:text-ink-500 ml-2">· {{ progressDetail }}</span>
        </div>
      </div>

      <div v-if="uploadResult" class="w-full bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800/40 rounded-xl p-4">
        <div class="flex items-center gap-2 mb-3">
          <svg class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          <span class="text-green-700 dark:text-green-300 font-semibold text-sm">提交成功</span>
          <span class="text-xs text-green-600/70 dark:text-green-400/60 bg-green-100 dark:bg-green-800/30 px-2 py-0.5 rounded-full">
            {{ uploadResult.doc_type || 'Interview' }} · {{ uploadResult.target === 'public' ? '公共题库' : '个人题库' }}
          </span>
        </div>
        <!-- 统计信息 -->
        <div v-if="resultSummary" class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-3">
          <div class="bg-white dark:bg-surface-800 rounded-lg px-3 py-2 text-center border border-green-100 dark:border-green-800/30">
            <div class="text-lg font-bold text-ink-800 dark:text-ink-100">{{ resultSummary.questionCount }}</div>
            <div class="text-[11px] text-ink-400 dark:text-ink-500">提取题目</div>
          </div>
          <div v-if="resultSummary.matchedCount != null" class="bg-white dark:bg-surface-800 rounded-lg px-3 py-2 text-center border border-green-100 dark:border-green-800/30">
            <div class="text-lg font-bold text-ink-800 dark:text-ink-100">{{ resultSummary.matchedCount }}<span class="text-xs text-ink-400">已有</span> / {{ resultSummary.unmatchedCount }}<span class="text-xs text-ink-400">新题</span></div>
            <div class="text-[11px] text-ink-400 dark:text-ink-500">匹配结果</div>
          </div>
          <div v-if="resultSummary.qualityScore != null" class="bg-white dark:bg-surface-800 rounded-lg px-3 py-2 text-center border border-green-100 dark:border-green-800/30">
            <div class="text-lg font-bold" :class="resultSummary.qualityScore >= 7 ? 'text-green-600 dark:text-green-400' : resultSummary.qualityScore >= 4 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-500'">{{ resultSummary.qualityScore }}/10</div>
            <div class="text-[11px] text-ink-400 dark:text-ink-500">质量评分</div>
          </div>
          <div v-if="resultSummary.elapsed" class="bg-white dark:bg-surface-800 rounded-lg px-3 py-2 text-center border border-green-100 dark:border-green-800/30">
            <div class="text-lg font-bold text-ink-800 dark:text-ink-100">{{ resultSummary.elapsed.toFixed(1) }}<span class="text-xs text-ink-400">s</span></div>
            <div class="text-[11px] text-ink-400 dark:text-ink-500">处理耗时</div>
          </div>
        </div>
        <!-- 分类分布 -->
        <div v-if="resultSummary?.categories" class="flex flex-wrap gap-1.5">
          <span
            v-for="(count, cat) in resultSummary.categories"
            :key="cat"
            class="inline-flex items-center gap-1 text-xs bg-green-100 dark:bg-green-800/30 text-green-700 dark:text-green-300 px-2 py-1 rounded-md"
          >
            {{ cat }}<span class="font-semibold">×{{ count }}</span>
          </span>
        </div>
      </div>
      <div v-if="uploadError" class="text-red-600 dark:text-red-400 font-medium w-full text-center bg-red-50 dark:bg-red-900/30 p-2 rounded">
        {{ uploadError }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed, nextTick } from 'vue'
import { submitDataSSE } from '../api/index.js'
import RoundedSelect from './RoundedSelect.vue'
import { validateUrl, validateFiles, sanitizeText, sanitizeAgainstInjection } from '../utils/validate.js'
import { getFriendlyError } from '../utils/http.js'

const emit = defineEmits(['submitted'])

const props = defineProps({
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] },
  isAdmin: { type: Boolean, default: false },
})

const seasonOptions = computed(() => [
  ...props.availableSeasons.map(s => ({ value: s, label: s })),
  { value: 'custom', label: '自定义...' },
])

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)
const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)
const submitProgress = ref({ step: '', message: '', data: null })
const progressHistory = ref([]) // 收集所有步骤的数据用于成功后展示
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

const progressDetail = computed(() => {
  const d = submitProgress.value.data
  if (!d) return ''
  const parts = []
  if (d.question_count != null) parts.push(`${d.question_count}题`)
  if (d.categories) {
    const cats = Object.entries(d.categories).map(([k, v]) => `${k}×${v}`).join(', ')
    if (cats) parts.push(cats)
  }
  if (d.quality_score != null) parts.push(`质量 ${d.quality_score}/10`)
  if (d.elapsed_seconds != null) parts.push(`${d.elapsed_seconds}s`)
  if (d.matched_count != null) parts.push(`${d.matched_count}道已有, ${d.unmatched_count}道新题`)
  return parts.join(' | ')
})

const resultSummary = computed(() => {
  if (!uploadResult.value?._history) return null
  const hist = uploadResult.value._history
  const result = {}
  for (const evt of hist) {
    if (evt.question_count != null) result.questionCount = evt.question_count
    if (evt.categories) result.categories = evt.categories
    if (evt.quality_score != null) result.qualityScore = evt.quality_score
    if (evt.matched_count != null) { result.matchedCount = evt.matched_count; result.unmatchedCount = evt.unmatched_count }
    if (evt.elapsed_seconds != null) result.elapsed = (result.elapsed || 0) + evt.elapsed_seconds
  }
  return result.questionCount != null ? result : null
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
  submitProgress.value = { step: '', message: '', data: null }

  // 强制等两帧渲染：nextTick 确保 Vue 更新 DOM，requestAnimationFrame 确保浏览器绘制
  await nextTick()
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))

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
        submitProgress.value = { step: event.step, message: event.message || '', data: event.data || null }
        if (event.data) {
          progressHistory.value.push({ step: event.step, message: event.message, ...event.data })
        }
      }
    })
    uploadResult.value = { ...data, _history: progressHistory.value }
    stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
    stagedFiles.value = []
    stagedText.value = ''
    emit('submitted')
  } catch (err) {
    uploadError.value = getFriendlyError(err, '提交失败，请稍后重试')
  } finally {
    isUploading.value = false
    submitProgress.value = { step: '', message: '', data: null }
    progressHistory.value = []
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
