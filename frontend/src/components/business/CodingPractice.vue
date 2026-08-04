<template>
  <div class="relative flex h-full overflow-hidden bg-background">
    <div
      v-if="!sidebarCollapsed"
      class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden"
      @click="sidebarCollapsed = true"
    />

    <!-- ── 左侧边栏：题目列表 ── -->
    <div
      class="sidebar-container z-30 border-r border-border bg-background flex flex-col shrink-0 overflow-hidden md:z-auto"
      :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      :style="{ width: sidebarCollapsed ? '0px' : '288px' }"
    >
      <!-- 难度筛选 -->
      <div class="p-3 border-b border-border sidebar-content">
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="opt in difficultyOptions" :key="opt.value"
            @click="filterDifficulty = opt.value; loadProblems()"
            class="text-xs px-2.5 py-1 rounded-lg border transition-colors"
            :class="filterDifficulty === opt.value
              ? 'bg-primary/10 text-primary border-primary/30 font-semibold'
              : 'text-muted-foreground border-border hover:bg-accent/50'"
          >{{ opt.label }}</button>
        </div>
      </div>

      <!-- 题目列表 -->
      <div class="flex-1 overflow-y-auto custom-scrollbar p-2 sidebar-content">
        <div v-if="problems.length === 0" class="p-4 text-center text-sm text-muted-foreground">
          暂无题目
        </div>
        <div v-else class="flex flex-col gap-0.5">
          <div
            v-for="p in problems"
            :key="p.id"
            @click="selectProblem(p)"
            class="group flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-all duration-150 text-left"
            :class="activeProblem?.id === p.id ? 'bg-accent' : 'hover:bg-accent/50'"
          >
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate text-foreground">{{ p.title }}</div>
              <div class="text-[11px] mt-0.5 truncate text-muted-foreground">
                <span :class="p.difficulty === 'easy' ? 'text-green-600 dark:text-green-400' : p.difficulty === 'medium' ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'">
                  {{ p.difficulty === 'easy' ? '简单' : p.difficulty === 'medium' ? '中等' : '困难' }}
                </span>
                <span v-if="p.tags?.length"> · {{ p.tags.slice(0, 2).join(', ') }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 侧边栏底部统计 -->
      <div v-if="errorStats" class="p-3 border-t border-border sidebar-content">
        <div class="text-[11px] text-muted-foreground mb-1.5">错误统计</div>
        <div class="flex flex-col gap-1">
          <div v-for="(count, cat) in errorStats.error_stats" :key="cat" class="flex items-center gap-2">
            <span class="text-[11px] text-muted-foreground w-12">{{ categoryLabels[cat] || cat }}</span>
            <div class="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
              <div class="h-full rounded-full transition-all" :class="categoryColors[cat] || 'bg-muted-foreground'" :style="{ width: Math.min(100, (count / maxErrorCount) * 100) + '%' }"></div>
            </div>
            <span class="text-[11px] text-muted-foreground w-4 text-right">{{ count }}</span>
          </div>
        </div>
        <div class="text-[11px] text-muted-foreground mt-1.5 pt-1.5 border-t border-border">
          总提交 {{ errorStats.total_submissions }} · 通过 {{ errorStats.passed_submissions }}
        </div>
      </div>

      <!-- 折叠按钮 -->
      <div class="p-2 border-t border-border sidebar-content">
        <Button variant="ghost" size="icon" aria-label="收起题目列表" @click="sidebarCollapsed = true" class="shrink-0">
          <PanelLeftClose :size="14" />
        </Button>
      </div>
    </div>

    <!-- 侧边栏折叠后的展开按钮 -->
    <div v-if="sidebarCollapsed" class="hidden flex-col items-center py-3 px-2 gap-1 shrink-0 border-r border-border sidebar-expand-buttons md:flex">
      <Button variant="ghost" size="icon" aria-label="展开题目列表" @click="sidebarCollapsed = false" class="shrink-0">
        <PanelLeft :size="16" />
      </Button>
    </div>

    <!-- ── 主内容区 ── -->
    <div class="flex-1 flex flex-col min-w-0">
      <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2 md:hidden">
        <Button
          variant="outline"
          size="sm"
          class="h-8 shrink-0 gap-1.5 rounded-lg text-xs"
          aria-label="选择题目"
          @click="sidebarCollapsed = false"
        >
          <PanelLeft :size="14" />
          <span>选择题目</span>
        </Button>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {{ activeProblem?.title || '手撕代码' }}
        </span>
      </div>

      <!-- 空状态 -->
      <div v-if="!activeProblem" class="flex-1 flex items-center justify-center">
        <div class="flex flex-col items-center max-w-2xl mx-auto px-6">
          <div class="size-20 mx-auto mb-6 rounded-xl bg-primary/10 flex items-center justify-center">
            <Code :size="40" class="text-primary" />
          </div>
          <h2 class="text-3xl font-bold text-foreground mb-3 text-center">开始编码练习</h2>
          <p class="text-muted-foreground mb-8 text-center text-lg">从左侧选择一道题目开始手撕代码</p>
          <div class="grid grid-cols-2 gap-4 w-full max-w-lg">
            <button
              v-for="suggestion in problemSuggestions"
              :key="suggestion.title"
              @click="filterDifficulty = suggestion.filter; loadProblems()"
              class="flex items-start gap-3 p-4 rounded-xl border border-border bg-card hover:bg-accent/50 hover:border-primary/30 transition-all text-left group"
            >
              <div class="size-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 group-hover:bg-primary/20 transition-colors">
                <component :is="suggestion.icon" :size="20" class="text-primary" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">{{ suggestion.title }}</div>
                <div class="text-xs text-muted-foreground mt-1">{{ suggestion.description }}</div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <!-- 选中题目后的主区域 -->
      <template v-else>
        <!-- 题目头部 -->
        <div class="flex items-center justify-between px-6 py-1.5 shrink-0">
          <div class="min-w-0 flex-1">
            <span class="truncate text-sm font-semibold text-foreground">{{ activeProblem.title }}</span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <span :class="[
              'rounded-lg px-2 py-0.5 text-[11px]',
              activeProblem.difficulty === 'easy' ? 'bg-green-500/10 text-green-600 dark:text-green-400' :
              activeProblem.difficulty === 'medium' ? 'bg-yellow-500/10 text-yellow-600 dark:text-yellow-400' :
              'bg-red-500/10 text-red-600 dark:text-red-400'
            ]">
              {{ activeProblem.difficulty === 'easy' ? '简单' : activeProblem.difficulty === 'medium' ? '中等' : '困难' }}
            </span>
            <span
              v-for="tag in (activeProblem.tags || []).slice(0, 3)"
              :key="tag"
              class="bg-muted/60 rounded-lg px-2 py-0.5 text-[11px] text-muted-foreground"
            >{{ tag }}</span>
          </div>
        </div>

        <!-- 滚动内容区 -->
        <div ref="mainContent" class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
          <div class="max-w-4xl mx-auto px-6 pt-6 pb-6 flex flex-col gap-4">

            <!-- 题目描述（可折叠） -->
            <div>
              <button
                @click="activeProblem._showDesc = !activeProblem._showDesc"
                class="group flex items-center gap-1.5 rounded-md px-1 py-0.5 text-sm font-medium text-foreground hover:bg-muted/70 transition-colors"
              >
                <svg :class="['size-3.5 transition-transform', activeProblem._showDesc ? 'rotate-90' : '']" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                查看题目描述
              </button>
              <div v-if="activeProblem._showDesc" class="mt-2 text-sm text-muted-foreground leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(activeProblem.description)"></div>
            </div>

            <!-- 代码编辑器 -->
            <div>
              <div class="text-xs font-semibold text-muted-foreground mb-2">你的代码</div>
              <div class="min-h-[300px] rounded-xl overflow-hidden border border-border shadow-sm">
                <CodeEditor
                  v-model="activeProblem._code"
                  :language="currentLanguage"
                  :read-only="activeProblem._isSubmitting"
                />
              </div>
            </div>

            <!-- 评审评分 -->
            <div v-if="activeProblem._scores && Object.keys(activeProblem._scores).length" class="rounded-xl border border-border bg-card overflow-hidden">
              <div class="px-5 py-4 bg-primary-50/40 dark:bg-primary-900/10">
                <h4 class="text-sm font-bold text-foreground mb-3">评审评分</h4>
                <div class="flex items-center gap-3 mb-4">
                  <span class="text-3xl font-extrabold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}</span>
                  <div class="flex-1">
                    <div class="bg-muted rounded-full h-3 overflow-hidden">
                      <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(activeProblem._totalScore)" :style="{ width: activeProblem._totalScore + '%' }"></div>
                    </div>
                  </div>
                  <span class="text-xs text-muted-foreground">/ 100</span>
                </div>
                <div class="flex flex-col gap-2 mb-4">
                  <div v-for="(val, key) in activeProblem._scores" :key="key" class="flex items-start gap-2">
                    <span class="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{{ categoryLabels[key] || key }}</span>
                    <div class="flex-1">
                      <div class="flex items-center gap-2">
                        <div class="bg-muted rounded-full h-2 flex-1 overflow-hidden">
                          <div class="h-full rounded-full transition-all duration-500" :class="scoreBarColors[key] || 'bg-muted-foreground'" :style="{ width: (val / 5 * 100) + '%' }"></div>
                        </div>
                        <span class="text-xs text-muted-foreground w-8 text-right">{{ val }}/5</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="activeProblem._lastSubmission?.error_categories?.length" class="flex gap-1 pt-3 border-t border-border">
                  <span v-for="cat in activeProblem._lastSubmission.error_categories" :key="cat" class="text-xs px-2 py-0.5 rounded-lg bg-red-500/10 text-red-600 dark:text-red-400">{{ categoryLabels[cat] || cat }}</span>
                </div>
              </div>
            </div>

            <!-- 详细评审（可折叠） -->
            <div v-if="activeProblem._feedback">
              <button
                @click="activeProblem._showFeedback = !activeProblem._showFeedback"
                class="group flex items-center gap-1.5 rounded-md px-1 py-0.5 text-sm font-medium text-foreground hover:bg-muted/70 transition-colors"
              >
                <svg :class="['size-3.5 transition-transform', activeProblem._showFeedback ? 'rotate-90' : '']" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                查看详细评审
              </button>
              <div v-if="activeProblem._showFeedback" class="mt-2 rounded-xl border border-border bg-card p-4">
                <div class="text-sm text-muted-foreground leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(activeProblem._feedback)"></div>
                <span v-if="activeProblem._isSubmitting" class="inline-block w-1.5 h-4 bg-primary animate-pulse ml-0.5 mt-1 rounded-sm"></span>
              </div>
            </div>

            <!-- 参考答案（可折叠） -->
            <div v-if="activeProblem._referenceAnswer">
              <button
                @click="activeProblem._showAnswer = !activeProblem._showAnswer"
                class="group flex items-center gap-1.5 rounded-md px-1 py-0.5 text-sm font-medium text-primary hover:bg-primary/5 transition-colors"
              >
                <svg :class="['size-3.5 transition-transform', activeProblem._showAnswer ? 'rotate-90' : '']" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                查看参考答案
              </button>
              <div v-if="activeProblem._showAnswer" class="mt-2 rounded-xl border border-border bg-card p-4">
                <div class="h-[240px] rounded-lg overflow-hidden border border-border">
                  <CodeEditor
                    :model-value="cleanCode(activeProblem._referenceAnswer)"
                    :language="currentLanguage"
                    :read-only="true"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部操作区 -->
        <div class="shrink-0 border-t border-border">
          <div class="max-w-4xl mx-auto px-6 py-3">
            <div class="chat-input-area flex flex-col gap-2 p-2 bg-muted rounded-xl">
              <!-- 语言选择 + 操作按钮 -->
              <div class="flex items-center gap-2 px-1">
                <button
                  v-for="lang in languageOptions" :key="lang.value"
                  @click="currentLanguage = lang.value"
                  class="text-xs px-2.5 py-1 rounded-lg border transition-colors"
                  :class="currentLanguage === lang.value
                    ? 'bg-primary/10 text-primary border-primary/30 font-semibold'
                    : 'text-muted-foreground border-border hover:bg-accent/50'"
                >{{ lang.label }}</button>
              </div>
              <!-- 操作按钮 -->
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-xs"
                    @click="clearProblem(activeProblem)"
                  >
                    清空
                  </Button>
                  <div v-if="activeProblem._hintCount >= 3 && !activeProblem._isSubmitting" class="text-[11px] text-amber-600 dark:text-amber-400 ml-2">
                    提示已用完
                  </div>
                </div>
                <div class="flex items-center gap-1.5">
                  <Button
                    variant="outline"
                    size="sm"
                    class="rounded-lg px-3 text-xs"
                    :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3"
                    @click="submitCode(activeProblem, 'hint')"
                  >
                    {{ activeProblem._isSubmitting && activeProblem._currentMode === 'hint' ? '提示中...' : `提示 (${activeProblem._hintCount}/3)` }}
                  </Button>
                  <Button
                    size="sm"
                    class="rounded-lg px-4 text-xs"
                    :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()"
                    @click="submitCode(activeProblem, 'full_review')"
                  >
                    <svg v-if="activeProblem._isSubmitting && activeProblem._currentMode === 'full_review'" class="animate-spin h-3.5 w-3.5 mr-1.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                    {{ activeProblem._isSubmitting && activeProblem._currentMode === 'full_review' ? (activeProblem._currentStep || '评审中...') : '提交评审' }}
                  </Button>
                </div>
              </div>
            </div>
            <div class="mt-2 flex items-center justify-between px-1">
              <span class="text-[11px] text-muted-foreground">支持 Python · C · Java</span>
              <span class="text-[11px] text-muted-foreground">AI 评审代码并给出评分和参考答案</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Code, PanelLeft, PanelLeftClose, Zap, Target, BookOpen, Flame } from '@lucide/vue'
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
const problemSuggestions = [
  { icon: Zap, title: '快速入门', description: '从简单题开始热身', filter: 'easy' },
  { icon: Target, title: '专项突破', description: '中等难度巩固基础', filter: 'medium' },
  { icon: Flame, title: '进阶挑战', description: '困难题提升硬实力', filter: 'hard' },
  { icon: BookOpen, title: '全部题目', description: '浏览所有编程题', filter: '' },
]

// ── 状态 ──
const problems = ref([])
const activeProblem = ref(null)
const currentLanguage = ref('python')
const isLoading = ref(false)
const filterDifficulty = ref('')
const errorStats = ref(null)
const isMobileViewport = () => window.matchMedia('(max-width: 767px)').matches
const sidebarCollapsed = ref(isMobileViewport())
const mainContent = ref(null)

// ── 常量 ──
const categoryLabels = {
  syntax: '语法', logic: '逻辑', algorithm: '算法', complexity: '复杂度', style: '风格',
}
const categoryColors = {
  syntax: 'bg-red-400', logic: 'bg-orange-400', algorithm: 'bg-purple-400', complexity: 'bg-blue-400', style: 'bg-gray-400',
}
const scoreBarColors = {
  syntax: 'bg-red-500', logic: 'bg-orange-500', algorithm: 'bg-purple-500', complexity: 'bg-blue-500', style: 'bg-gray-500',
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
  if (score >= 80) return 'bg-green-500'
  if (score >= 60) return 'bg-yellow-500'
  return 'bg-red-500'
}
function scoreTextColor(score) {
  if (score >= 80) return 'text-green-700 dark:text-green-400'
  if (score >= 60) return 'text-yellow-700 dark:text-yellow-400'
  return 'text-red-700 dark:text-red-400'
}
function initProblemState(p) {
  return {
    ...p,
    _code: '', _showDesc: false, _isSubmitting: false,
    _feedback: '', _scores: null, _totalScore: 0,
    _referenceAnswer: '', _lastSubmission: null,
    _currentStep: '', _currentMode: '', _hintCount: 0,
    _showFeedback: false, _showAnswer: false,
  }
}

// ── 方法 ──
async function loadProblems() {
  isLoading.value = true
  try {
    const params = { page_size: 100 }
    if (filterDifficulty.value) params.difficulty = filterDifficulty.value
    const res = await fetchCodingProblems(params)
    problems.value = (res.problems || []).map(p => initProblemState(p))
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

function selectProblem(p) {
  activeProblem.value = p
  if (isMobileViewport()) sidebarCollapsed.value = true
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
  const data = { problem_id: p.id, language: currentLanguage.value, code: p._code, mode }
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
          if (hintSeparator && !p._feedback.includes(hintSeparator)) p._feedback += hintSeparator
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

onMounted(() => {
  loadProblems()
  loadErrorStats()
})
</script>

<style scoped>
/* Sidebar animation — aligned with ChatView */
.sidebar-container {
  transition: width 380ms cubic-bezier(0.4, 0, 0.2, 1);
}

@media (max-width: 767px) {
  .sidebar-container {
    position: absolute;
    inset: 0 auto 0 0;
    width: min(82vw, 288px) !important;
    max-width: calc(100vw - 24px);
    box-shadow: 18px 0 40px rgba(0, 0, 0, 0.12);
    transform: translateX(0);
    transition: transform 220ms ease-out;
  }

  .sidebar-container.sidebar-collapsed {
    transform: translateX(-100%);
    pointer-events: none;
  }
}

.sidebar-content {
  transition: opacity 200ms ease-out;
}

.sidebar-collapsed .sidebar-content {
  opacity: 0;
  pointer-events: none;
}

.sidebar-expand-buttons {
  animation: sidebarExpandButtons 280ms cubic-bezier(0, 0, 0.2, 1) 100ms both;
}

@keyframes sidebarExpandButtons {
  from { opacity: 0; transform: translateX(-4px); }
  to   { opacity: 1; transform: translateX(0); }
}
</style>
