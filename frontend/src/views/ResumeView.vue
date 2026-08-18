<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { FileText, Upload, RefreshCw, Copy, Download, Trash2, Sparkles } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  uploadResume, getResume, deleteResume,
  getResumeText, getResumeOptimization, optimizeResume,
} from '@/services/resumeApi.js'
import { fetchPositions } from '@/services/profileApi.js'
import { useModelGuard } from '@/composables/useModelGuard.js'
import { useConfirm } from '@/composables/useNotification.js'
import { renderSafeMarkdown } from '@/utils/markdown.js'

const { ensureModelReady } = useModelGuard()
const { confirm: showConfirm } = useConfirm()

const resume = ref(null)          // { id, filename, created_at }
const rawText = ref('')           // 原文预览
const showRaw = ref(false)

const positions = ref([])         // 用户已配置岗位
const selectedPosition = ref('')
const manualPosition = ref('')
const useManual = ref(false)

const optimizing = ref(false)
const points = ref([])            // 当前/最近一次优化要点
const optimizedText = ref('')     // 流式全文（实时累积）
const savedOptimization = ref(null) // 存库结果（重进页面可见）
const optimizingErrors = ref('')

const hasResume = computed(() => !!resume.value)

let abortOptimize = null   // 当前 optimize SSE 的 AbortController（页面离开即中止）
const targetPosition = computed(() => (useManual.value ? manualPosition.value : selectedPosition.value))

const renderMarkdown = (text) => (text ? renderSafeMarkdown(text) : '')

async function loadResume() {
  try {
    const data = await getResume()
    resume.value = data.has_resume ? data.resume : null
  } catch {
    resume.value = null
  }
}

async function loadOptimization() {
  try {
    const data = await getResumeOptimization()
    savedOptimization.value = data.has_optimization ? data.optimization : null
  } catch {
    savedOptimization.value = null
  }
}

async function loadPositions() {
  try {
    const list = await fetchPositions()
    positions.value = Array.isArray(list) ? list.map(p => (typeof p === 'string' ? p : p.name)) : []
    if (!selectedPosition.value && positions.value.length) {
      selectedPosition.value = positions.value[0]
    }
  } catch {
    positions.value = []
  }
}

async function toggleRawText() {
  if (showRaw.value) { showRaw.value = false; return }
  if (!rawText.value && resume.value) {
    try {
      const data = await getResumeText()
      rawText.value = data.raw_text || ''
    } catch (e) {
      toast.error(`加载原文失败：${e.message || '请稍后重试'}`)
    }
  }
  showRaw.value = true
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await uploadResume(formData)
    toast.success('简历上传成功')
    resume.value = { id: res.id, filename: res.filename, created_at: null }
    rawText.value = ''
    showRaw.value = false
    savedOptimization.value = null
    points.value = []
    optimizedText.value = ''
  } catch (e) {
    toast.error(`上传失败：${e.message || '请稍后重试'}`)
  } finally {
    event.target.value = ''
  }
}

async function handleDelete() {
  const ok = await showConfirm('删除后简历原文与优化记录将不可恢复，确定删除？', {
    title: '删除简历',
    confirmLabel: '删除',
  })
  if (!ok) return
  try {
    await deleteResume()
    toast.success('简历已删除')
    resume.value = null
    rawText.value = ''
    savedOptimization.value = null
    points.value = []
    optimizedText.value = ''
  } catch (e) {
    toast.error(`删除失败：${e.message || '请稍后重试'}`)
  }
}

async function handleOptimize() {
  const position = targetPosition.value.trim()
  if (!position) {
    toast.error('请先选择或输入目标岗位')
    return
  }
  if (!hasResume.value) {
    toast.error('请先上传简历')
    return
  }
  const ready = await ensureModelReady({ action: '简历优化' })
  if (!ready) return

  optimizing.value = true
  optimizingErrors.value = ''
  points.value = []
  optimizedText.value = ''
  savedOptimization.value = null

  try {
    await optimizeResume(position, (event) => {
      if (event.type === 'points') {
        points.value = event.points || []
      } else if (event.type === 'delta') {
        optimizedText.value += event.content || ''
      } else if (event.type === 'done') {
        toast.success('优化完成，已保存')
        loadOptimization()
      } else if (event.type === 'error') {
        optimizingErrors.value = event.message || '优化失败'
      }
    }, {
      onController: (c) => { abortOptimize = c },
    })
  } catch (e) {
    optimizingErrors.value = e.message || '优化失败，请稍后重试'
  } finally {
    optimizing.value = false
  }
}

async function copyText() {
  const content = optimizedText.value || savedOptimization.value?.optimized_text || ''
  if (!content) return
  try {
    await navigator.clipboard.writeText(content)
    toast.success('已复制到剪贴板')
  } catch {
    toast.error('复制失败，请手动选择文本复制')
  }
}

function downloadMarkdown() {
  const content = optimizedText.value || savedOptimization.value?.optimized_text || ''
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `简历优化版-${targetPosition.value || '通用'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadResume()
  loadOptimization()
  loadPositions()
})

onUnmounted(() => {
  abortOptimize?.abort()
})
</script>

<template>
  <div class="flex min-h-0 flex-col gap-3 overflow-y-auto px-2 py-3 custom-scrollbar sm:gap-4 sm:px-4 sm:py-4 md:px-6 md:py-6">
    <!-- 简历卡片 -->
    <Card class="rounded-xl border border-border bg-card shadow-sm">
      <CardHeader>
        <CardTitle class="flex items-center gap-2">
          <FileText :size="18" class="text-primary" />
          我的简历
        </CardTitle>
        <CardDescription>上传 PDF 简历用于 AI 优化与模拟面试上下文</CardDescription>
      </CardHeader>
      <CardContent>
        <div v-if="!hasResume" class="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border p-8 text-center">
          <Upload :size="28" class="text-muted-foreground" />
          <p class="text-sm text-muted-foreground">尚未上传简历</p>
          <label class="cursor-pointer">
            <Button as-child variant="outline" size="sm">
              <span>上传 PDF 简历</span>
            </Button>
            <input type="file" accept=".pdf" class="hidden" @change="handleUpload" />
          </label>
        </div>
        <div v-else class="flex flex-col gap-3">
          <div class="flex flex-wrap items-center gap-3 rounded-xl border border-border/60 bg-muted/30 p-3">
            <FileText :size="18" class="shrink-0 text-primary" />
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm font-medium">{{ resume.filename }}</p>
              <p class="text-xs text-muted-foreground">已保存</p>
            </div>
            <div class="flex items-center gap-2">
              <Button variant="ghost" size="sm" @click="toggleRawText">
                {{ showRaw ? '收起原文' : '查看原文' }}
              </Button>
              <label class="cursor-pointer">
                <Button as-child variant="outline" size="sm">
                  <span class="flex items-center gap-1"><RefreshCw :size="14" />替换</span>
                </Button>
                <input type="file" accept=".pdf" class="hidden" @change="handleUpload" />
              </label>
              <Button variant="ghost" size="sm" class="text-destructive" aria-label="删除简历" @click="handleDelete">
                <Trash2 :size="14" />
              </Button>
            </div>
          </div>
          <pre v-if="showRaw && rawText" class="max-h-72 overflow-auto rounded-xl border border-border bg-muted/20 p-3 text-xs leading-6 whitespace-pre-wrap">{{ rawText }}</pre>
        </div>
      </CardContent>
    </Card>

    <!-- 优化卡片 -->
    <Card class="rounded-xl border border-border bg-card shadow-sm">
      <CardHeader>
        <CardTitle class="flex items-center gap-2">
          <Sparkles :size="18" class="text-primary" />
          简历优化
        </CardTitle>
        <CardDescription>选择目标岗位，AI 生成优化版简历与优化要点</CardDescription>
      </CardHeader>
      <CardContent class="flex flex-col gap-3">
        <div class="flex flex-col items-stretch gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <select
            v-model="selectedPosition"
            :disabled="useManual || !positions.length"
            class="h-10 w-full rounded-lg border border-border bg-card px-3 text-sm sm:h-9 sm:w-auto"
          >
            <option v-if="!positions.length" value="">暂无岗位，可在设置中添加</option>
            <option v-for="p in positions" :key="p" :value="p">{{ p }}</option>
          </select>
          <label class="flex items-center gap-2 text-sm text-muted-foreground">
            <input v-model="useManual" type="checkbox" class="h-4 w-4 rounded border-border" />
            手动输入岗位
          </label>
          <input
            v-if="useManual"
            v-model="manualPosition"
            placeholder="如：后端工程师（Go）"
            class="h-10 min-w-0 flex-1 rounded-lg border border-border bg-card px-3 text-sm sm:h-9 sm:min-w-56"
          />
        </div>
        <Button class="w-full sm:w-auto" :disabled="optimizing || !hasResume" @click="handleOptimize">
          <RefreshCw v-if="optimizing" :size="14" class="animate-spin" />
          <Sparkles v-else :size="14" />
          {{ optimizing ? '正在优化…' : '生成优化版' }}
        </Button>
        <p v-if="optimizingErrors" class="text-xs text-destructive">{{ optimizingErrors }}</p>
      </CardContent>
    </Card>

    <!-- 结果卡片 -->
    <Card v-if="optimizing || points.length || optimizedText || savedOptimization" class="rounded-xl border border-border bg-card shadow-sm">
      <CardHeader class="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <CardTitle class="flex items-center gap-2">
            <Sparkles :size="18" class="text-primary" />
            优化结果
          </CardTitle>
          <CardDescription v-if="savedOptimization || optimizedText">
            目标岗位：{{ savedOptimization?.position || targetPosition }} · 优化于 {{ savedOptimization?.optimized_at || '本次' }}
          </CardDescription>
        </div>
        <div class="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          <Button class="flex-1 sm:flex-none" variant="outline" size="sm" @click="copyText()" :disabled="!optimizedText && !savedOptimization?.optimized_text">
            <Copy :size="14" />
            复制
          </Button>
          <Button class="flex-1 sm:flex-none" variant="outline" size="sm" @click="downloadMarkdown" :disabled="!optimizedText && !savedOptimization?.optimized_text">
            <Download :size="14" />
            下载 .md
          </Button>
        </div>
      </CardHeader>
      <CardContent class="flex flex-col gap-4">
        <!-- 优化要点 -->
        <div v-if="(points.length || savedOptimization?.points?.length)" class="flex flex-col gap-2">
          <p class="text-sm font-medium">优化要点</p>
          <div class="flex flex-wrap gap-2">
            <Badge
              v-for="(p, i) in (points.length ? points : savedOptimization.points)"
              :key="i"
              variant="secondary"
              class="rounded-md px-2 py-1 text-xs font-normal"
            >
              {{ p }}
            </Badge>
          </div>
        </div>
        <!-- 优化版全文 -->
        <div class="min-w-0 rounded-xl border border-border/60 bg-muted/20 p-3">
          <div
            v-if="optimizedText || savedOptimization?.optimized_text"
            class="answer-content prose prose-sm dark:prose-invert max-w-none text-sm leading-6"
            v-html="renderMarkdown(optimizedText || savedOptimization.optimized_text)"
          ></div>
          <div v-else-if="optimizing" class="flex items-center gap-2 text-sm text-muted-foreground">
            <RefreshCw :size="14" class="animate-spin" />
            AI 正在生成优化版简历…
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>