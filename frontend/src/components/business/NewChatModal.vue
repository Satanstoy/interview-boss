<template>
  <AppDialog :open="visible" size="md" @update:open="emit('close')">
    <div>
          <!-- Header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-surface-200 dark:border-ink-600">
            <h3 class="text-base font-bold text-ink-800 dark:text-ink-100">新建面试对话</h3>
            <button @click="emit('close')" class="p-1 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-700 transition">
              <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
          </div>

          <!-- Body -->
          <div class="p-6 space-y-5">
            <!-- Mode selection -->
            <div>
              <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-2.5 block">选择面试模式</label>
              <div class="grid grid-cols-2 gap-3">
                <button @click="mode = 'jd_resume'"
                  class="relative p-4 rounded-xl border-2 text-left transition-all"
                  :class="mode === 'jd_resume'
                    ? 'border-primary-500 dark:border-primary-400 bg-primary-50/50 dark:bg-primary-900/20'
                    : 'border-surface-200 dark:border-ink-600 hover:border-surface-300 dark:hover:border-ink-500'">
                  <div class="text-sm font-semibold text-ink-800 dark:text-ink-100 mb-1">JD + 简历定制</div>
                  <div class="text-xs text-ink-400 dark:text-ink-500">上传目标岗位 JD 和简历，AI 针对性提问</div>
                  <div v-if="mode === 'jd_resume'" class="absolute top-2 right-2 size-5 rounded-full bg-primary-500 dark:bg-primary-400 flex items-center justify-center">
                    <svg class="size-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                  </div>
                </button>

                <button @click="mode = 'free_practice'"
                  class="relative p-4 rounded-xl border-2 text-left transition-all"
                  :class="mode === 'free_practice'
                    ? 'border-primary-500 dark:border-primary-400 bg-primary-50/50 dark:bg-primary-900/20'
                    : 'border-surface-200 dark:border-ink-600 hover:border-surface-300 dark:hover:border-ink-500'">
                  <div class="text-sm font-semibold text-ink-800 dark:text-ink-100 mb-1">自由练习</div>
                  <div class="text-xs text-ink-400 dark:text-ink-500">从题库随机出题，自由练习面试</div>
                  <div v-if="mode === 'free_practice'" class="absolute top-2 right-2 size-5 rounded-full bg-primary-500 dark:bg-primary-400 flex items-center justify-center">
                    <svg class="size-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/></svg>
                  </div>
                </button>
              </div>
            </div>

            <!-- JD Resume mode: upload section -->
            <div v-if="mode === 'jd_resume'" class="space-y-4">
              <!-- JD selection -->
              <div>
                <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">选择 JD（可选）</label>
                <Select :model-value="selectedJdId != null ? String(selectedJdId) : ''" @update:model-value="selectedJdId = $event ? Number($event) : null">
                  <SelectTrigger class="w-full h-9 text-sm">
                    <SelectValue placeholder="选择目标 JD" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">不选择 JD</SelectItem>
                    <SelectItem v-for="jd in jdList" :key="jd.id" :value="String(jd.id)">{{ (jd.company || '未知公司') + ' · ' + (jd.job_title || '未知岗位') }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <!-- Resume upload -->
              <div>
                <label class="text-xs font-semibold text-ink-600 dark:text-ink-400 mb-1.5 block">简历</label>

                <!-- 已保存简历选项 -->
                <div v-if="savedResume" class="mb-3">
                  <label class="flex items-center gap-2.5 p-3 rounded-xl border border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/20 cursor-pointer transition hover:bg-emerald-50 dark:hover:bg-emerald-900/30">
                    <input type="checkbox" v-model="useSavedResume" class="rounded border-emerald-300 dark:border-emerald-700 text-emerald-600 focus:ring-emerald-200 dark:focus:ring-emerald-800" />
                    <div class="flex-1 min-w-0">
                      <span class="text-sm font-medium text-emerald-700 dark:text-emerald-300">使用已保存的简历</span>
                      <span class="block text-xs text-emerald-500 dark:text-emerald-400 truncate">{{ savedResume.filename }}</span>
                    </div>
                  </label>
                </div>
                <div v-else class="mb-3">
                  <p class="text-xs text-ink-400 dark:text-ink-500">
                    您还没有上传简历，去
                    <button @click="$emit('close')" class="text-primary-600 dark:text-primary-400 underline">个人信息页面</button>
                    上传
                  </p>
                </div>

                <!-- 或者上传新简历 -->
                <div v-if="!useSavedResume">
                <div class="border-2 border-dashed border-surface-300 dark:border-ink-600 rounded-xl p-4 text-center hover:border-primary-400 dark:hover:border-primary-500 transition cursor-pointer"
                  @click="$refs.fileInput.click()"
                  @dragover.prevent="dragover = true"
                  @dragleave="dragover = false"
                  @drop.prevent="handleDrop"
                  :class="dragover ? 'border-primary-400 dark:border-primary-500 bg-primary-50/30 dark:bg-primary-900/10' : ''">
                  <input ref="fileInput" type="file" accept=".pdf" class="hidden" @change="handleFileSelect" />
                  <div v-if="!resumeFileName">
                    <svg class="size-8 mx-auto text-ink-300 dark:text-ink-600 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
                    <div class="text-xs text-ink-400 dark:text-ink-500">点击上传或拖拽 PDF 文件</div>
                  </div>
                  <div v-else class="flex items-center justify-center gap-2">
                    <svg class="size-5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                    <span class="text-sm text-ink-700 dark:text-ink-300">{{ resumeFileName }}</span>
                    <button @click.stop="clearResume" class="text-ink-400 hover:text-red-500 transition">
                      <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
                    </button>
                  </div>
                </div>
                </div><!-- /v-if="!useSavedResume" -->
              </div>
            </div>
          </div>

          <!-- Footer -->
          <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-surface-200 dark:border-ink-600 bg-surface-50 dark:bg-surface-900">
            <button @click="emit('close')" class="px-4 py-2 text-sm text-ink-600 dark:text-ink-400 hover:bg-surface-100 dark:hover:bg-ink-700 rounded-xl transition">取消</button>
            <button @click="handleCreate" :disabled="creating || (mode === 'jd_resume' && !selectedJdId && !resumeText && !useSavedResume)"
              class="px-5 py-2 text-sm font-semibold text-white bg-primary-600 dark:bg-primary-600 rounded-xl hover:bg-primary-700 dark:hover:bg-primary-700 transition disabled:opacity-50 disabled:cursor-not-allowed">
              {{ creating ? '创建中...' : '开始面试' }}
            </button>
          </div>
        </div>
  </AppDialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { upload } from '@/services/http.js'
import { getResume } from '@/services/resumeApi.js'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import AppDialog from '@/components/common/AppDialog.vue'

defineProps({
  visible: { type: Boolean, default: false },
  jdList: { type: Array, default: () => [] },
})
const emit = defineEmits(['close', 'create'])

const mode = ref('free_practice')
const selectedJdId = ref(null)
const resumeText = ref('')
const resumeFileName = ref('')
const creating = ref(false)
const dragover = ref(false)
const savedResume = ref(null)  // 用户已保存的简历
const useSavedResume = ref(false)  // 是否使用已保存的简历

// PDF text extraction via backend (authenticated)
async function extractPdfText(file) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const data = await upload('/api/chat/extract-pdf', formData)
    return data.text || ''
  } catch (e) {
    console.error('PDF extraction failed:', e)
    throw e
  }
}

async function handleFileSelect(e) {
  const file = e.target.files?.[0]
  if (!file) return
  await processFile(file)
}

function handleDrop(e) {
  dragover.value = false
  const file = e.dataTransfer?.files?.[0]
  if (file && file.type === 'application/pdf') {
    processFile(file)
  }
}

async function processFile(file) {
  resumeFileName.value = file.name
  try {
    resumeText.value = await extractPdfText(file)
  } catch {
    resumeFileName.value = ''
    resumeText.value = ''
  }
}

function clearResume() {
  resumeFileName.value = ''
  resumeText.value = ''
}

async function handleCreate() {
  creating.value = true
  try {
    // 决定使用哪个简历文本：新上传的 > 已保存的
    let finalResumeText = resumeText.value || null
    if (!finalResumeText && useSavedResume.value && savedResume.value) {
      // 已保存的简历文本需要从后端获取（getResume 不返回 raw_text）
      // 这里传一个标记，让后端自动加载
      finalResumeText = '__saved__'
    }
    emit('create', {
      mode: mode.value,
      jd_id: selectedJdId.value,
      resume_text: finalResumeText,
    })
  } finally {
    creating.value = false
  }
}

async function loadSavedResume() {
  try {
    const data = await getResume()
    savedResume.value = data.has_resume ? data.resume : null
    useSavedResume.value = !!savedResume.value  // 有简历默认选中
  } catch {
    savedResume.value = null
  }
}

watch(() => mode.value, () => {
  selectedJdId.value = null
  resumeText.value = ''
  resumeFileName.value = ''
  useSavedResume.value = !!savedResume.value
})

// 加载已保存的简历
loadSavedResume()
</script>

