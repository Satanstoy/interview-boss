<template>
  <div class="flex flex-col gap-4">
    <!-- ── 顶部配置卡片 ── -->
    <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
      <!-- Header -->
      <div class="border-b border-border px-5 py-4">
        <div class="flex items-center gap-3">
          <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
            <svg class="size-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
          </div>
          <div>
            <h3 class="text-sm font-bold text-foreground">手撕代码</h3>
            <p class="text-caption text-muted-foreground">选择难度，开始编码练习</p>
          </div>
        </div>
      </div>

      <div class="p-5 flex flex-col gap-5">
        <!-- 难度筛选 -->
        <div>
          <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            难度
          </label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="opt in difficultyOptions" :key="opt.value"
              @click="filterDifficulty = opt.value; loadProblems()"
              class="text-xs px-3 py-1.5 rounded-full border transition-colors"
              :class="filterDifficulty === opt.value ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
            >{{ opt.label }}</button>
          </div>
        </div>

        <!-- 语言 + 统计 -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <!-- 语言选择 -->
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
              编程语言
            </label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="lang in languageOptions" :key="lang.value"
                @click="currentLanguage = lang.value"
                class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                :class="currentLanguage === lang.value ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
              >{{ lang.label }}</button>
            </div>
          </div>

          <!-- 错误统计 -->
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
              错误统计
            </label>
            <div v-if="errorStats" class="flex flex-col gap-1.5">
              <div v-for="(count, cat) in errorStats.error_stats" :key="cat" class="flex items-center gap-2">
                <span class="text-xs text-muted-foreground w-16">{{ categoryLabels[cat] || cat }}</span>
                <div class="flex-1 h-2 bg-muted dark:bg-muted rounded-full overflow-hidden">
                  <div
                    class="h-full rounded-full transition-all"
                    :class="categoryColors[cat] || 'bg-muted-foreground'"
                    :style="{ width: Math.min(100, (count / maxErrorCount) * 100) + '%' }"
                  ></div>
                </div>
                <span class="text-xs text-muted-foreground w-6 text-right">{{ count }}</span>
              </div>
              <div class="text-xs text-muted-foreground mt-1 pt-1.5 border-t border-border">
                总提交 {{ errorStats.total_submissions }} · 通过 {{ errorStats.passed_submissions }}
              </div>
            </div>
            <div v-else class="text-xs text-muted-foreground">暂无数据</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── 加载状态 ── -->
    <div v-if="isLoading" class="text-center py-10 text-muted-foreground border-2 border-dashed border-border rounded-xl">
      <svg class="animate-spin h-8 w-8 text-primary-400 dark:text-primary-400 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
      <p class="text-lg">正在加载题目...</p>
    </div>

    <!-- ── 空状态 ── -->
    <div v-else-if="problems.length === 0" class="text-center py-10 text-muted-foreground border-2 border-dashed border-border rounded-xl">
      <p class="mb-2 text-lg">暂无符合条件的题目</p>
      <p class="text-sm">请调整筛选条件或联系管理员添加编程题。</p>
    </div>

    <!-- ── 题目列表 ── -->
    <div v-for="(p, pIdx) in problems" :key="p.id" class="border border-border rounded-xl overflow-hidden bg-card shadow-sm">
      <!-- 题目头部 -->
      <div class="p-4 border-b border-border">
        <div class="flex items-start gap-3">
          <div class="flex flex-col items-center justify-center bg-primary-100/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 font-bold rounded-lg p-2 min-w-[44px]">
            <span class="text-caption text-primary-400 dark:text-primary-500">第</span>
            <span class="text-xl leading-none">{{ pIdx + 1 }}</span>
            <span class="text-caption text-primary-400 dark:text-primary-500">题</span>
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex gap-2 mb-2 items-center flex-wrap">
              <span class="text-xs font-medium px-2 py-0.5 rounded" :class="p.difficulty === 'easy' ? 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400' : p.difficulty === 'medium' ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400' : 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400'">
                {{ p.difficulty === 'easy' ? '简单' : p.difficulty === 'medium' ? '中等' : '困难' }}
              </span>
              <span
                v-for="tag in (p.tags || []).slice(0, 3)"
                :key="tag"
                class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold"
              >{{ tag }}</span>
            </div>
            <h3 class="text-base lg:text-lg font-bold text-foreground leading-snug">{{ p.title }}</h3>
          </div>
        </div>
      </div>

      <!-- 题目描述（可折叠） -->
      <div class="border-t border-primary-100 dark:border-primary-800/50">
        <button
          @click="p._showDesc = !p._showDesc"
          class="w-full py-2.5 text-xs font-medium text-muted-foreground hover:bg-muted dark:hover:bg-primary-900/20 transition flex items-center justify-center gap-2"
        >
          <svg class="size-3.5 transition-transform" :class="{ 'rotate-90': p._showDesc }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
          {{ p._showDesc ? '收起题目描述' : '查看题目描述' }}
        </button>
        <div v-if="p._showDesc" class="px-5 py-4 bg-slate-50 dark:bg-card border-t border-primary-100 dark:border-primary-800/50 text-sm text-muted-foreground leading-relaxed answer-content" v-html="renderMarkdown(p.description)"></div>
      </div>

      <!-- 代码编辑器 + 操作 -->
      <div class="px-4 py-3 border-t border-border bg-card">
        <label class="text-xs font-semibold text-muted-foreground mb-1.5 block">你的代码</label>
        <div class="min-h-[260px] rounded-lg overflow-hidden border border-input mb-3">
          <CodeEditor
            v-model="p._code"
            :language="currentLanguage"
            :read-only="p._isSubmitting"
          />
        </div>
        <div class="flex gap-2 flex-wrap">
          <Button
            variant="default"
            size="sm"
            class="px-5 py-2 flex items-center gap-2"
            :disabled="p._isSubmitting || !p._code.trim()"
            @click="submitCode(p, 'full_review')"
          >
            <svg v-if="p._isSubmitting && p._currentMode === 'full_review'" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
            {{ p._isSubmitting && p._currentMode === 'full_review' ? (p._currentStep || '评审中...') : '提交评审' }}
          </Button>
          <Button
            variant="outline"
            size="sm"
            class="px-4 py-1.5"
            :disabled="p._isSubmitting || !p._code.trim() || p._hintCount >= 3"
            @click="submitCode(p, 'hint')"
          >
            {{ p._isSubmitting && p._currentMode === 'hint' ? '提示中...' : p._hintCount >= 3 ? '提示已用完' : `请求提示 (${p._hintCount}/3)` }}
          </Button>
          <Button
            v-if="p._code"
            variant="ghost"
            size="sm"
            class="px-3 py-2"
            @click="clearProblem(p)"
          >清空</Button>
        </div>
        <div v-if="p._hintCount >= 3 && !p._isSubmitting" class="text-xs text-amber-600 dark:text-amber-400 mt-1.5">
          提示机会已用完，请点击「提交评审」查看完整评分和参考答案
        </div>
      </div>

      <!-- 评审评分 -->
      <div v-if="p._scores && Object.keys(p._scores).length" class="px-5 py-4 border-t border-border bg-primary-50/40 dark:bg-primary-900/10">
        <h4 class="text-sm font-bold text-foreground mb-3">评审评分</h4>

        <!-- 总分 -->
        <div class="flex items-center gap-3 mb-4">
          <span class="text-3xl font-extrabold" :class="scoreTextColor(p._totalScore)">{{ p._totalScore }}</span>
          <div class="flex-1">
            <div class="bg-muted dark:bg-muted rounded-full h-3 overflow-hidden">
              <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(p._totalScore)" :style="{ width: p._totalScore + '%' }"></div>
            </div>
          </div>
          <span class="text-xs text-muted-foreground">/ 100</span>
        </div>

        <!-- 维度评分 -->
        <div class="flex flex-col gap-2 mb-4">
          <div v-for="(val, key) in p._scores" :key="key" class="flex items-start gap-2">
            <span class="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{{ categoryLabels[key] || key }}</span>
            <div class="flex-1">
              <div class="flex items-center gap-2">
                <div class="bg-muted dark:bg-muted rounded-full h-2 flex-1 overflow-hidden">
                  <div class="h-full rounded-full transition-all duration-500" :class="scoreBarColors[key] || 'bg-muted-foreground'" :style="{ width: (val / 5 * 100) + '%' }"></div>
                </div>
                <span class="text-xs text-muted-foreground w-8 text-right">{{ val }}/5</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 错误分类 -->
        <div v-if="p._lastSubmission?.error_categories?.length" class="flex gap-1 pt-3 border-t border-border">
          <span
            v-for="cat in p._lastSubmission.error_categories"
            :key="cat"
            class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
          >{{ categoryLabels[cat] || cat }}</span>
        </div>
      </div>

      <!-- 详细评审（可折叠） -->
      <div v-if="p._feedback" class="border-t border-primary-100 dark:border-primary-800/50">
        <button
          @click="p._showFeedback = !p._showFeedback"
          class="w-full py-2.5 text-xs font-medium text-muted-foreground hover:bg-muted dark:hover:bg-primary-900/20 transition flex items-center justify-center gap-2"
        >
          <svg class="size-3.5 transition-transform" :class="{ 'rotate-90': p._showFeedback }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
          {{ p._showFeedback ? '收起详细评审' : '查看详细评审' }}
        </button>
        <div v-if="p._showFeedback" class="px-5 py-4 bg-slate-50 dark:bg-card border-t border-primary-100 dark:border-primary-800/50">
          <div class="text-sm text-muted-foreground leading-relaxed answer-content" v-html="renderMarkdown(p._feedback)"></div>
          <span v-if="p._isSubmitting" class="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 mt-1"></span>
        </div>
      </div>

      <!-- 参考答案（可折叠） -->
      <div v-if="p._referenceAnswer" class="border-t border-primary-100 dark:border-primary-800/50">
        <button
          @click="p._showAnswer = !p._showAnswer"
          class="w-full py-3 text-sm font-medium text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/30 transition flex items-center justify-center gap-2"
        >
          {{ p._showAnswer ? '收起参考答案' : '查看参考答案' }}
        </button>
        <div v-if="p._showAnswer" class="p-6 bg-slate-50 dark:bg-card border-t border-primary-100 dark:border-primary-800/50">
          <div class="h-[240px] rounded-md overflow-hidden border border-border">
            <CodeEditor
              :model-value="cleanCode(p._referenceAnswer)"
              :language="currentLanguage"
              :read-only="true"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { Button } from '@/components/ui/button'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { useToast } from '@/composables/useNotification.js'
import CodeEditor from './CodeEditor.vue'
import {
  fetchCodingProblems,
  fetchCodingProblem,
  submitCodingCode,
  fetchCodingErrorStats,
} from '@/services/codingApi.js'

const { toast } = useToast()

// ── 配置 ──
const difficultyOptions = [
  { value: '', label: '全部' },
  { value: 'easy', label: '简单' },
  { value: 'medium', label: '中等' },
  { value: 'hard', label: '困难' },
]
const languageOptions = [
  { value: 'python', label: 'Python' },
  { value: 'c', label: 'C' },
  { value: 'java', label: 'Java' },
]

// ── 状态 ──
const problems = ref([])
const currentLanguage = ref('python')
const isLoading = ref(false)
const filterDifficulty = ref('')
const errorStats = ref(null)

// ── 常量 ──
const categoryLabels = {
  syntax: '语法',
  logic: '逻辑',
  algorithm: '算法',
  complexity: '复杂度',
  style: '风格',
}
const categoryColors = {
  syntax: 'bg-red-400',
  logic: 'bg-orange-400',
  algorithm: 'bg-purple-400',
  complexity: 'bg-blue-400',
  style: 'bg-gray-400',
}
const scoreBarColors = {
  syntax: 'bg-red-500',
  logic: 'bg-orange-500',
  algorithm: 'bg-purple-500',
  complexity: 'bg-blue-500',
  style: 'bg-gray-500',
}

// ── 计算属性 ──
const maxErrorCount = computed(() => {
  if (!errorStats.value?.error_stats) return 1
  return Math.max(1, ...Object.values(errorStats.value.error_stats))
})

// ── 工具函数 ──
const renderMarkdown = (text) => text ? renderSafeMarkdown(text) : ''
function cleanCode(text) {
  if (!text) return ''
  return text.replace(/^```[\w]*\n?/, '').replace(/\n?```$/, '').trim()
}
function scoreColor(score) {
  if (score >= 80) return 'bg-green-500 dark:bg-green-500'
  if (score >= 60) return 'bg-yellow-500 dark:bg-yellow-500'
  return 'bg-red-500 dark:bg-red-500'
}
function scoreTextColor(score) {
  if (score >= 80) return 'text-green-700 dark:text-green-400'
  if (score >= 60) return 'text-yellow-700 dark:text-yellow-400'
  return 'text-red-700 dark:text-red-400'
}

// ── 方法 ──
async function loadProblems() {
  isLoading.value = true
  try {
    const params = { page_size: 100 }
    if (filterDifficulty.value) params.difficulty = filterDifficulty.value
    const res = await fetchCodingProblems(params)
    problems.value = (res.problems || []).map(p => initProblemState(p))
    // 加载每道题的详情（获取 description）
    for (const p of problems.value) {
      try {
        const detail = await fetchCodingProblem(p.id)
        Object.assign(p, { description: detail.description, title: detail.title || p.title })
      } catch { /* skip */ }
    }
  } catch (e) {
    toast.error('加载题目失败')
    problems.value = []
  } finally {
    isLoading.value = false
  }
}

function initProblemState(p) {
  return {
    ...p,
    _code: '',
    _showDesc: false,
    _isSubmitting: false,
    _feedback: '',
    _scores: null,
    _totalScore: 0,
    _referenceAnswer: '',
    _lastSubmission: null,
    _currentStep: '',
    _currentMode: '',
    _hintCount: 0,
    _showFeedback: false,
    _showAnswer: false,
  }
}

function clearProblem(p) {
  p._code = ''
  p._feedback = ''
  p._scores = null
  p._totalScore = 0
  p._referenceAnswer = ''
  p._lastSubmission = null
  p._hintCount = 0
  p._currentMode = ''
  p._showFeedback = false
  p._showAnswer = false
}

async function submitCode(p, mode) {
  if (!p._code.trim()) return
  if (mode === 'hint' && p._hintCount >= 3) return

  p._isSubmitting = true
  p._currentMode = mode
  p._currentStep = ''

  if (mode === 'full_review') {
    p._feedback = ''
    p._scores = null
    p._totalScore = 0
    p._referenceAnswer = ''
    p._showFeedback = true
    p._showAnswer = false
  }

  const hintSeparator = mode === 'hint' && p._feedback ? '\n\n---\n\n' : ''

  const data = {
    problem_id: p.id,
    language: currentLanguage.value,
    code: p._code,
    mode,
  }
  if (mode === 'hint' && p._lastSubmission) {
    data.parent_submission_id = p._lastSubmission.submission_id
  }

  try {
    await submitCodingCode(data, (event) => {
      if (event.type === 'step') {
        p._currentStep = event.message
      } else if (event.type === 'chunk') {
        if (event.replace) {
          const historyEnd = hintSeparator ? p._feedback.indexOf(hintSeparator) : -1
          if (historyEnd >= 0) {
            p._feedback = p._feedback.substring(0, historyEnd + hintSeparator.length) + event.content
          } else if (mode === 'hint' && hintSeparator) {
            p._feedback = hintSeparator + event.content
          } else {
            p._feedback = event.content
          }
        } else {
          if (hintSeparator && !p._feedback.includes(hintSeparator)) {
            p._feedback += hintSeparator
          }
          p._feedback += event.content
        }
      } else if (event.type === 'done') {
        if (event.mode === 'hint') {
          p._hintCount = (event.hint_round || p._hintCount + 1)
          p._showFeedback = true
        }
        if (event.mode === 'full_review') {
          p._scores = event.scores || null
          p._totalScore = event.total_score || 0
          p._referenceAnswer = event.reference_answer || ''
          loadErrorStats()
        }
        p._lastSubmission = event
      } else if (event.type === 'error') {
        toast.error(event.message || '评审失败')
      }
    })
  } catch (e) {
    toast.error('提交失败，请重试')
  } finally {
    p._isSubmitting = false
    p._currentStep = ''
  }
}

async function loadErrorStats() {
  try {
    errorStats.value = await fetchCodingErrorStats()
  } catch { /* silent */ }
}

// ── 生命周期 ──
onMounted(() => {
  loadProblems()
  loadErrorStats()
})
</script>
