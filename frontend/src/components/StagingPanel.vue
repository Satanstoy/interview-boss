<template>
  <div class="bg-white rounded-xl shadow-md border border-gray-200 mb-6 lg:mb-10 overflow-hidden">
    <div class="bg-gray-50 p-4 border-b border-gray-200 flex items-center gap-4">
      <label class="font-semibold text-gray-700 whitespace-nowrap">来源链接 (URL):</label>
      <input
        v-model="sourceUrl"
        type="text"
        class="flex-1 border border-gray-300 rounded-lg p-2 focus:ring-blue-500 focus:border-blue-500"
        placeholder="粘贴小红书/牛客网帖子链接 (用于去重，避免重复录入)"
      />
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 divide-x divide-gray-100">
      <div class="p-4 lg:p-6 flex flex-col">
        <label class="block text-sm font-semibold text-gray-700 mb-2">文本内容</label>
        <textarea
          v-model="stagedText"
          class="flex-1 w-full border border-gray-300 rounded-lg p-3 focus:ring-blue-500 focus:border-blue-500 resize-none"
          placeholder="在此处粘贴面经或 JD 的纯文本内容（可与右侧图片组合提交）..."
        ></textarea>
      </div>

      <div
        class="p-4 lg:p-6 flex flex-col transition-colors relative"
        :class="isDragging ? 'bg-blue-50' : ''"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop.prevent="handleDrop"
      >
        <div class="flex justify-between items-center mb-2">
          <label class="block text-sm font-semibold text-gray-700">图片 ({{ stagedFiles.length }} 张)</label>
          <div>
            <input type="file" multiple class="hidden" ref="fileInput" @change="handleFileSelect" accept="image/*" />
            <button @click="$refs.fileInput.click()" class="text-xs bg-gray-200 text-gray-700 px-3 py-1 rounded hover:bg-gray-300 transition">
              + 选择图片
            </button>
          </div>
        </div>

        <div class="flex-1 border-2 border-dashed border-gray-300 rounded-lg p-4 overflow-y-auto max-h-48 bg-gray-50">
          <div v-if="stagedFiles.length === 0" class="h-full flex flex-col items-center justify-center text-gray-400">
            <svg class="h-8 w-8 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
            <p class="text-sm">拖拽图片到此处，或使用 Ctrl+V 粘贴</p>
          </div>

          <div v-else class="flex flex-wrap gap-3">
            <div v-for="(item, index) in stagedFiles" :key="item.id" class="relative group">
              <img :src="item.preview" class="h-24 w-24 object-cover rounded-md border border-gray-300 shadow-sm" @error="handleImgError" />
              <button @click="removeFile(index)" class="absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition shadow">
                <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="bg-gray-50 border-t border-gray-200 p-4 flex flex-col items-center">
      <div class="flex gap-4 w-full justify-end mb-4">
        <button @click="clearStaging" :disabled="isUploading" class="px-5 py-2 rounded-lg text-gray-600 hover:bg-gray-200 transition">
          清空
        </button>
        <button
          @click="submitAll"
          :disabled="isUploading || (!stagedText.trim() && stagedFiles.length === 0)"
          class="bg-blue-600 text-white font-bold px-8 py-2 rounded-lg hover:bg-blue-700 transition shadow-md disabled:bg-blue-300 disabled:cursor-not-allowed flex items-center gap-2"
        >
          <svg v-if="isUploading" class="animate-spin h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
          {{ isUploading ? 'AI 正在解析中...' : '提交解析' }}
        </button>
      </div>

      <div v-if="uploadResult" class="text-green-600 font-medium w-full text-center bg-green-50 p-2 rounded">
        解析成功！类型：<span class="font-bold ml-1">{{ uploadResult.type }}</span>
      </div>
      <div v-if="uploadError" class="text-red-600 font-medium w-full text-center bg-red-50 p-2 rounded">
        {{ uploadError }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { submitData } from '../api/index.js'

const emit = defineEmits(['submitted'])

const props = defineProps({
  activeSeason: { type: String, default: '' }
})

const sourceUrl = ref('')
const stagedText = ref('')
const stagedFiles = ref([])
const isDragging = ref(false)
const isUploading = ref(false)
const uploadResult = ref(null)
const uploadError = ref(null)

const handleImgError = (e) => {
  e.target.src = 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iOTYiIGhlaWdodD0iOTYiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjEwMCUiIGhlaWdodD0iMTAwJSIgZmlsbD0iI2U1ZTdlYiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0ibWlkZGxlIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjOWNhM2FmIiBmb250LXNpemU9IjE0Ij7lm77niYc8L3RleHQ+PC9zdmc+'
  e.target.alt = '图片加载失败'
}

const addFileToStaging = (file) => {
  if (!file.type.startsWith('image/')) return
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
  isUploading.value = true
  uploadResult.value = null
  uploadError.value = null

  const formData = new FormData()
  formData.append('url', sourceUrl.value)
  formData.append('text', stagedText.value)
  formData.append('season', props.activeSeason || '')
  stagedFiles.value.forEach(item => formData.append('files', item.file))

  try {
    const data = await submitData(formData)
    uploadResult.value = data
    stagedFiles.value.forEach(item => URL.revokeObjectURL(item.preview))
    stagedFiles.value = []
    stagedText.value = ''
    emit('submitted')
  } catch (err) {
    uploadError.value = err.message
  } finally {
    isUploading.value = false
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
