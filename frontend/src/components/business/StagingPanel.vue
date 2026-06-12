<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import {
  AlertCircle,
  CheckCircle2,
  FileText,
  Image as ImageIcon,
  Link,
  Loader2,
  Sparkles,
  Upload,
  X,
} from '@lucide/vue'

import { createSubmitJob } from '@/services/dataApi.js'
import { useSubmitJobs, attachJob } from '@/composables/useSubmitJobs.js'
import { validateUrl, sanitizeAgainstInjection } from '@/utils/validate.js'

import Badge from '@/components/ui/badge/Badge.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import Label from '@/components/ui/label/Label.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import Textarea from '@/components/ui/textarea/Textarea.vue'

const props = defineProps({
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] },
  isAdmin: { type: Boolean, default: false },
})

const emit = defineEmits(['submitted'])

const { activeJobs } = useSubmitJobs()

const TEXT_MAX_LENGTH = 50000
const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_FILES = 20

const rawText = ref('')
const sourceUrl = ref('')
const fileInput = ref(null)
const images = ref([])
const isDragging = ref(false)
const isSubmitting = ref(false)
const submitError = ref('')
const submitSuccess = ref(false)

const importConfig = reactive({
  type: 'auto',
  season: props.activeSeason || '2027届暑期实习',
  target: 'personal',
})

const seasonOptions = computed(() => {
  const fromProps = props.availableSeasons.filter(Boolean)
  return fromProps.length ? fromProps : ['2027届暑期实习', '2026 春招', '2025 秋招']
})

const activeJobCount = computed(() =>
  activeJobs.value.filter(j => j.status === 'pending' || j.status === 'running').length
)

const textLineCount = computed(() =>
  rawText.value.split(/\r?\n/).filter(line => line.trim()).length
)

const inputValid = computed(() =>
  rawText.value.trim().length > 0 || images.value.length > 0
)

const submitLabel = computed(() => isSubmitting.value ? '提交中...' : '提交解析')

watch(() => props.activeSeason, (season) => {
  if (season) importConfig.season = season
})

watch(() => props.isAdmin, (isAdmin) => {
  if (!isAdmin) importConfig.target = 'personal'
}, { immediate: true })

function onDragOver(e) {
  e.preventDefault()
  isDragging.value = true
  e.dataTransfer.dropEffect = 'copy'
}

function onDragLeave(e) {
  e.preventDefault()
  isDragging.value = false
}

function onDrop(e) {
  e.preventDefault()
  isDragging.value = false
  handleFiles(Array.from(e.dataTransfer.files || []))
}

function onPaste(e) {
  const items = Array.from(e.clipboardData?.items || [])
  const imageFiles = items
    .filter(item => item.type.startsWith('image/'))
    .map(item => item.getAsFile())
    .filter(Boolean)
  if (imageFiles.length > 0) handleFiles(imageFiles)
}

function onFileChange(e) {
  handleFiles(Array.from(e.target.files || []))
  if (fileInput.value) fileInput.value.value = ''
}

function handleFiles(files) {
  submitError.value = ''

  for (const file of files) {
    if (!file.type.startsWith('image/')) continue
    if (images.value.length >= MAX_FILES) {
      submitError.value = `最多上传 ${MAX_FILES} 张图片`
      break
    }
    if (file.size > MAX_FILE_SIZE) {
      submitError.value = `图片 "${file.name}" 超过 10MB 限制`
      continue
    }

    images.value.push({
      id: `${Date.now()}-${Math.random()}`,
      file,
      preview: URL.createObjectURL(file),
    })
  }
}

function removeImage(index) {
  const item = images.value[index]
  if (item?.preview) URL.revokeObjectURL(item.preview)
  images.value.splice(index, 1)
}

function clearImages() {
  images.value.forEach(item => {
    if (item.preview) URL.revokeObjectURL(item.preview)
  })
  images.value = []
}

function triggerFileInput() {
  if (!isSubmitting.value) fileInput.value?.click()
}

function resetForm() {
  rawText.value = ''
  sourceUrl.value = ''
  clearImages()
  submitError.value = ''
  submitSuccess.value = false
}

async function onSubmit() {
  if (!inputValid.value || isSubmitting.value) return

  submitError.value = ''
  submitSuccess.value = false

  if (sourceUrl.value.trim()) {
    const urlResult = validateUrl(sourceUrl.value.trim())
    if (!urlResult.valid) {
      submitError.value = urlResult.error
      return
    }
  }

  if (rawText.value.trim()) {
    try {
      sanitizeAgainstInjection(rawText.value, '文本内容')
    } catch (error) {
      submitError.value = error.message
      return
    }
  }

  isSubmitting.value = true
  try {
    const formData = new FormData()
    formData.append('url', sourceUrl.value.trim())
    formData.append('text', rawText.value.slice(0, TEXT_MAX_LENGTH))
    formData.append('season', importConfig.season || props.activeSeason || '2027届暑期实习')
    formData.append('target', props.isAdmin ? importConfig.target : 'personal')

    if (importConfig.type !== 'auto') {
      formData.append('content_type', importConfig.type)
    }

    images.value.forEach(item => formData.append('files', item.file))

    const result = await createSubmitJob(formData)
    attachJob(result.job_id)
    emit('submitted', result)
    resetForm()
    submitSuccess.value = true
    toast.success('任务已提交，正在后台处理中')
    setTimeout(() => { submitSuccess.value = false }, 3000)
  } catch (error) {
    submitError.value = error.message || '提交失败'
    toast.error(submitError.value)
  } finally {
    isSubmitting.value = false
  }
}

defineExpose({ onSubmit, isSubmitting })
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4">
    <!-- Header bar -->
    <div class="flex flex-wrap items-center gap-2">
      <Badge v-if="activeJobCount > 0" variant="secondary" class="gap-1.5 text-xs">
        <span class="relative flex h-2 w-2">
          <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-75" />
          <span class="relative inline-flex h-2 w-2 rounded-full bg-primary" />
        </span>
        {{ activeJobCount }} 个任务处理中
      </Badge>
      <p class="text-xs text-muted-foreground">
        粘贴文本、补充截图或填写来源链接，提交后由后台任务完成提取和归档。
      </p>
    </div>

    <!-- Main: two equal columns -->
    <div class="grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
      <!-- Left: text -->
      <section class="flex min-h-0 flex-col gap-2">
        <div class="flex items-center gap-2">
          <FileText class="h-4 w-4 text-muted-foreground" />
          <Label class="text-sm font-medium">文本内容</Label>
          <span class="ml-auto text-xs tabular-nums text-muted-foreground">
            {{ rawText.length.toLocaleString() }} / {{ TEXT_MAX_LENGTH.toLocaleString() }}
            <template v-if="rawText"> · {{ textLineCount }} 行</template>
          </span>
        </div>
        <Textarea
          v-model="rawText"
          :maxlength="TEXT_MAX_LENGTH"
          placeholder="粘贴面经或 JD 内容..."
          class="min-h-0 flex-1 text-sm leading-relaxed"
          :disabled="isSubmitting"
          @paste="onPaste"
        />
      </section>

      <!-- Right: images -->
      <section class="flex min-h-0 flex-col gap-2">
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2">
            <ImageIcon class="h-4 w-4 text-muted-foreground" />
            <Label class="text-sm font-medium">截图补充</Label>
          </div>
          <div class="flex items-center gap-2">
            <span class="text-xs tabular-nums text-muted-foreground">{{ images.length }} / {{ MAX_FILES }}</span>
            <Button
              v-if="images.length > 0"
              variant="ghost"
              size="sm"
              class="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
              :disabled="isSubmitting"
              @click="clearImages"
            >
              清空
            </Button>
          </div>
        </div>

        <!-- Drop zone: fills remaining space -->
        <div
          class="group relative flex min-h-0 flex-1 cursor-pointer flex-col rounded-lg border-2 border-dashed transition-all"
          :class="[
            isDragging
              ? 'border-primary bg-primary/5'
              : 'border-muted-foreground/20 hover:border-primary/40 hover:bg-muted/30',
            isSubmitting && 'pointer-events-none opacity-60'
          ]"
          @click="triggerFileInput"
          @dragover="onDragOver"
          @dragleave="onDragLeave"
          @drop="onDrop"
        >
          <input
            ref="fileInput"
            type="file"
            accept="image/*"
            multiple
            class="hidden"
            :disabled="isSubmitting"
            @change="onFileChange"
          />

          <!-- Empty state -->
          <div v-if="images.length === 0" class="flex flex-1 flex-col items-center justify-center p-4">
            <div
              class="rounded-full p-2.5 transition-colors"
              :class="isDragging ? 'bg-primary/10' : 'bg-muted group-hover:bg-primary/10'"
            >
              <Upload
                class="h-5 w-5 transition-colors"
                :class="isDragging ? 'text-primary' : 'text-muted-foreground group-hover:text-primary'"
              />
            </div>
            <p class="mt-2.5 text-sm font-medium text-foreground">
              {{ isDragging ? '释放以上传图片' : '拖拽图片到此处，或点击选择' }}
            </p>
            <p class="mt-1 text-xs text-muted-foreground">PNG / JPG / GIF，单张 ≤ 10MB</p>
            <p class="mt-0.5 text-xs text-muted-foreground/60">支持 Ctrl+V 粘贴截图</p>
          </div>

          <!-- Image grid: fills dropzone -->
          <div v-else class="grid flex-1 grid-cols-2 content-start gap-2 overflow-y-auto p-3 sm:grid-cols-3">
            <div
              v-for="(img, index) in images"
              :key="img.id"
              class="group/img relative aspect-square overflow-hidden rounded-md border bg-muted"
            >
              <img :src="img.preview" :alt="`图片 ${index + 1}`" class="h-full w-full object-cover" />
              <button
                type="button"
                class="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-black/60 text-white opacity-0 transition-opacity hover:bg-black/80 group-hover/img:opacity-100"
                :disabled="isSubmitting"
                @click.stop="removeImage(index)"
              >
                <X class="h-3 w-3" />
              </button>
              <div class="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/55 to-transparent px-1 py-0.5">
                <p class="truncate text-[10px] text-white/85">{{ img.file.name }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- Bottom bar: URL + settings + actions -->
    <div class="flex flex-col gap-3 rounded-lg border bg-muted/30 p-3 sm:flex-row sm:items-end sm:p-4">
      <!-- Source URL -->
      <div class="flex-1 space-y-1.5">
        <Label class="text-xs font-medium text-muted-foreground">来源链接（可选）</Label>
        <div class="relative">
          <Link class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground pointer-events-none" />
          <Input
            v-model="sourceUrl"
            type="url"
            placeholder="https://..."
            class="pl-9"
            :disabled="isSubmitting"
          />
        </div>
      </div>

      <!-- Settings -->
      <div class="flex flex-wrap gap-2">
        <div class="space-y-1.5">
          <Label class="text-xs font-medium text-muted-foreground">类型</Label>
          <Select v-model="importConfig.type" :disabled="isSubmitting">
            <SelectTrigger class="h-9 w-[110px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="auto">自动识别</SelectItem>
              <SelectItem value="interview">面经</SelectItem>
              <SelectItem value="jd">JD</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div class="space-y-1.5">
          <Label class="text-xs font-medium text-muted-foreground">季节</Label>
          <Select v-model="importConfig.season" :disabled="isSubmitting">
            <SelectTrigger class="h-9 w-[140px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="season in seasonOptions" :key="season" :value="season">
                {{ season }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div v-if="props.isAdmin" class="space-y-1.5">
          <Label class="text-xs font-medium text-muted-foreground">提交到</Label>
          <Select v-model="importConfig.target" :disabled="isSubmitting">
            <SelectTrigger class="h-9 w-[110px] text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="personal">个人题库</SelectItem>
              <SelectItem value="public">公共题库</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <!-- Actions -->
      <div class="flex items-center gap-2 sm:self-end">
        <Button
          variant="ghost"
          size="sm"
          class="text-muted-foreground"
          :disabled="isSubmitting"
          @click="resetForm"
        >
          清空
        </Button>
        <Button
          size="sm"
          class="gap-1.5"
          :disabled="!inputValid || isSubmitting || rawText.length > TEXT_MAX_LENGTH"
          @click="onSubmit"
        >
          <Loader2 v-if="isSubmitting" class="h-3.5 w-3.5 animate-spin" />
          <Sparkles v-else class="h-3.5 w-3.5" />
          {{ submitLabel }}
        </Button>
      </div>
    </div>

    <!-- Messages -->
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-if="submitSuccess"
        class="flex items-center gap-2.5 rounded-lg border border-green-200 bg-green-50 px-4 py-2.5 text-sm text-green-700 dark:border-green-800 dark:bg-green-950/30 dark:text-green-300"
      >
        <CheckCircle2 class="h-4 w-4 shrink-0" />
        <span>已提交成功，任务正在后台处理。可继续提交或离开页面，右上角显示进度。</span>
      </div>
    </Transition>

    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 translate-y-1"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-1"
    >
      <div
        v-if="submitError"
        class="flex items-center gap-2.5 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-2.5 text-sm text-destructive"
      >
        <AlertCircle class="h-4 w-4 shrink-0" />
        <span>{{ submitError }}</span>
        <button
          type="button"
          class="ml-auto shrink-0 rounded p-0.5 transition-colors hover:bg-destructive/10"
          @click="submitError = ''"
        >
          <X class="h-3.5 w-3.5" />
        </button>
      </div>
    </Transition>
  </div>
</template>
