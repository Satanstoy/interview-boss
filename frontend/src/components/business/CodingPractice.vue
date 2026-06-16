<template>
  <div class="flex flex-col lg:flex-row gap-4 h-[calc(100vh-120px)]">
    <!-- ── 左侧面板：品牌头部 + 题目列表 + 错误统计 ── -->
    <div class="w-full lg:w-80 flex-shrink-0 flex flex-col gap-3">
      <!-- 品牌头部卡片 -->
      <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <div class="border-b border-border px-5 py-4">
          <div class="flex items-center gap-3">
            <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
              <svg class="size-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
            </div>
            <div>
              <h3 class="text-sm font-bold text-foreground">手撕代码</h3>
              <p class="text-caption text-muted-foreground">选择题目开始编码练习</p>
            </div>
          </div>
        </div>

        <div class="p-4 flex flex-col gap-3">
          <!-- 难度筛选 -->
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              难度
            </label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="d in ['', 'easy', 'medium', 'hard']"
                :key="d"
                @click="filterDifficulty = d; loadProblems()"
                class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                :class="filterDifficulty === d ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
              >
                {{ d === '' ? '全部' : d === 'easy' ? '简单' : d === 'medium' ? '中等' : '困难' }}
              </button>
            </div>
          </div>

          <!-- 题目列表 -->
          <div class="flex-1 flex flex-col gap-2 overflow-y-auto custom-scrollbar max-h-[calc(100vh-420px)]">
            <div
              v-for="(p, pIdx) in problems"
              :key="p.id"
              @click="selectProblem(p)"
              :class="[
                'p-3 rounded-xl cursor-pointer border transition-all',
                selectedProblem?.id === p.id
                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20 shadow-sm'
                  : 'border-border hover:border-primary-300 bg-card'
              ]"
            >
              <div class="flex items-start gap-3">
                <div class="flex flex-col items-center justify-center bg-primary-100/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 font-bold rounded-lg p-2 min-w-[36px]">
                  <span class="text-base leading-none">{{ pIdx + 1 }}</span>
                </div>
                <div class="flex-1 min-w-0">
                  <span class="text-sm font-medium text-foreground truncate block mb-1.5">{{ p.title }}</span>
                  <div class="flex flex-wrap items-center gap-1.5">
                    <span class="text-xs font-medium px-2 py-0.5 rounded" :class="p.difficulty === 'easy' ? 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400' : p.difficulty === 'medium' ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400' : 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400'">
                      {{ p.difficulty === 'easy' ? '简单' : p.difficulty === 'medium' ? '中等' : '困难' }}
                    </span>
                    <span
                      v-for="tag in (p.tags || []).slice(0, 3)"
                      :key="tag"
                      class="text-xs px-1.5 py-0.5 rounded bg-muted dark:bg-muted text-muted-foreground"
                    >{{ tag }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="problems.length === 0" class="text-center text-muted-foreground text-sm py-8">暂无题目</div>
          </div>
        </div>
      </div>

      <!-- 错误统计 -->
      <div class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <button
          @click="showErrorStats = !showErrorStats"
          class="w-full flex items-center justify-between px-4 py-3 text-left border-b border-border"
        >
          <h3 class="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
            <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
            错误统计
          </h3>
          <svg :class="['size-3.5 text-muted-foreground transition-transform', showErrorStats ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" /></svg>
        </button>
        <div v-if="showErrorStats" class="p-4">
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
            <div class="text-xs text-muted-foreground mt-2 pt-2 border-t border-border">
              总提交 {{ errorStats.total_submissions }} · 通过 {{ errorStats.passed_submissions }}
            </div>
          </div>
          <div v-else class="text-xs text-muted-foreground">暂无数据</div>
        </div>
      </div>
    </div>

    <!-- ── 右侧面板：编码 + AI 反馈 ── -->
    <div class="flex-1 flex flex-col gap-3 min-w-0">
      <template v-if="selectedProblem">
        <!-- 题目描述（可折叠） -->
        <div class="bg-card rounded-xl border border-border shadow-sm">
          <button
            @click="showDescription = !showDescription"
            class="w-full flex items-center justify-between p-3 text-left"
          >
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-foreground">{{ selectedProblem.title }}</span>
              <span :class="[
                'text-xs px-2 py-0.5 rounded-full',
                selectedProblem.difficulty === 'easy' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
                selectedProblem.difficulty === 'medium' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' :
                'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
              ]">
                {{ selectedProblem.difficulty === 'easy' ? '简单' : selectedProblem.difficulty === 'medium' ? '中等' : '困难' }}
              </span>
            </div>
            <svg :class="['size-4 text-muted-foreground transition-transform', showDescription ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div v-if="showDescription" class="px-3 pb-3 text-sm text-muted-foreground prose-sm max-w-none border-t border-border pt-3" v-html="renderedDescription"></div>
        </div>

        <!-- 语言选择 + 操作按钮 -->
        <div class="bg-card rounded-xl border border-border shadow-sm px-4 py-3 flex items-center gap-2 flex-wrap">
          <button
            v-for="lang in ['python', 'c', 'java']"
            :key="lang"
            @click="currentLanguage = lang"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="currentLanguage === lang ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
          >
            {{ langLabels[lang] }}
          </button>

          <div class="flex-1"></div>

          <Button
            variant="ghost"
            size="sm"
            @click="clearCurrentProblem"
          >
            清空记录
          </Button>
          <div class="relative group">
            <Button
              variant="default"
              size="sm"
              class="px-5 py-2 flex items-center gap-2"
              @click="submitCode('full_review')"
              :disabled="isSubmitting || !code.trim()"
            >
              <svg v-if="isSubmitting && currentMode === 'full_review'" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              {{ isSubmitting && currentMode === 'full_review' ? (currentStep || '评审中...') : '提交评审' }}
            </Button>
            <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 text-xs text-white bg-gray-900 dark:bg-gray-100 dark:text-foreground rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
              AI 评审代码并给出评分和参考答案
            </div>
          </div>
          <div class="relative group">
            <Button
              variant="outline"
              size="sm"
              class="px-4 py-1.5"
              @click="submitCode('hint')"
              :disabled="isSubmitting || !code.trim() || hintCount >= 3"
            >
              {{ isSubmitting && currentMode === 'hint' ? '提示中...' : hintCount >= 3 ? '提示已用完' : `请求提示 (${hintCount}/3)` }}
            </Button>
            <div class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2 py-1 text-xs text-white bg-gray-900 dark:bg-gray-100 dark:text-foreground rounded opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
              {{ hintCount >= 3 ? '提示机会已用完，请提交评审' : '获取渐进式提示，最多 3 次' }}
            </div>
          </div>
        </div>
        <div v-if="hintCount >= 3 && !isSubmitting" class="text-xs text-amber-600 dark:text-amber-400 -mt-1">
          提示机会已用完，请点击「提交评审」查看完整评分和参考答案
        </div>

        <!-- Monaco 编辑器 -->
        <div class="flex-1 min-h-[300px] rounded-xl overflow-hidden border border-border shadow-sm">
          <CodeEditor
            v-model="code"
            :language="currentLanguage"
            :read-only="isSubmitting"
          />
        </div>

        <!-- 评分面板 -->
        <div
          v-if="scores && Object.keys(scores).length"
          class="bg-card rounded-xl border border-border shadow-sm overflow-hidden"
        >
          <div class="px-5 py-4 border-t border-border bg-primary-50/40 dark:bg-primary-900/10">
            <h4 class="text-sm font-bold text-foreground mb-3">评审评分</h4>

            <!-- 总分 -->
            <div class="flex items-center gap-3 mb-4">
              <span class="text-3xl font-extrabold" :class="totalScore >= 80 ? 'text-green-700 dark:text-green-400' : totalScore >= 60 ? 'text-yellow-700 dark:text-yellow-400' : 'text-red-700 dark:text-red-400'">{{ totalScore }}</span>
              <div class="flex-1">
                <div class="bg-muted dark:bg-muted rounded-full h-3 overflow-hidden">
                  <div class="h-full rounded-full transition-all duration-500" :class="totalScore >= 80 ? 'bg-green-500 dark:bg-green-500' : totalScore >= 60 ? 'bg-yellow-500 dark:bg-yellow-500' : 'bg-red-500 dark:bg-red-500'" :style="{ width: totalScore + '%' }"></div>
                </div>
              </div>
              <span class="text-xs text-muted-foreground">/ 100</span>
            </div>

            <!-- 维度评分 -->
            <div class="flex flex-col gap-2 mb-4">
              <div v-for="(score, dim) in scores" :key="dim" class="flex items-start gap-2">
                <span class="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{{ categoryLabels[dim] || dim }}</span>
                <div class="flex-1">
                  <div class="flex items-center gap-2">
                    <div class="bg-muted dark:bg-muted rounded-full h-2 flex-1 overflow-hidden">
                      <div class="h-full rounded-full transition-all duration-500" :class="scoreBarColors[dim] || 'bg-muted-foreground'" :style="{ width: (score / 5 * 100) + '%' }"></div>
                    </div>
                    <span class="text-xs font-bold w-8 text-right" :class="(score / 5 * 100) >= 80 ? 'text-green-700 dark:text-green-400' : (score / 5 * 100) >= 60 ? 'text-yellow-700 dark:text-yellow-400' : 'text-red-700 dark:text-red-400'">{{ score }}/5</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 错误分类 -->
            <div v-if="lastSubmission?.error_categories?.length" class="flex gap-1 pt-3 border-t border-border">
              <span
                v-for="cat in lastSubmission.error_categories"
                :key="cat"
                class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
              >{{ categoryLabels[cat] || cat }}</span>
            </div>
          </div>
        </div>

        <!-- AI 评审反馈（流式渲染） -->
        <div
          v-if="feedback"
          class="bg-card rounded-xl border border-border shadow-sm overflow-hidden"
        >
          <div class="border-b border-border px-4 py-3">
            <h4 class="text-sm font-bold text-foreground">详细评审</h4>
          </div>
          <div class="p-4">
            <div class="prose-sm max-w-none text-muted-foreground" v-html="renderedFeedback"></div>
            <span v-if="isSubmitting" class="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 mt-1"></span>
          </div>
        </div>

        <!-- 参考答案 -->
        <div
          v-if="referenceAnswer"
          class="bg-card rounded-xl border border-border shadow-sm overflow-hidden"
        >
          <div class="border-b border-border px-4 py-3">
            <h4 class="text-sm font-bold text-foreground">最小改动参考答案</h4>
          </div>
          <div class="p-4">
            <div class="h-[200px] rounded-md overflow-hidden border border-border dark:border-border">
              <CodeEditor
                :model-value="cleanReferenceAnswer"
                :language="currentLanguage"
                :read-only="true"
              />
            </div>
          </div>
        </div>
      </template>

      <!-- 未选题时的占位 -->
      <div v-else class="flex-1 flex items-center justify-center text-muted-foreground text-sm">
        <div class="text-center">
          <div class="text-4xl mb-3 opacity-30">{ }</div>
          <div>选择一道题目开始练习</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
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

// ── 状态 ──
const problems = ref([])
const selectedProblem = ref(null)
const currentLanguage = ref('python')
const code = ref('')
const isSubmitting = ref(false)
const feedback = ref('')
const lastSubmission = ref(null)
const showDescription = ref(true)
const filterDifficulty = ref('')
const errorStats = ref(null)
const showErrorStats = ref(true)
const scores = ref(null)
const totalScore = ref(0)
const referenceAnswer = ref('')
const currentStep = ref('')
const hintCount = ref(0)
const currentMode = ref('')

// ── 常量 ──
const langLabels = { python: 'Python', c: 'C', java: 'Java' }
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
const renderedDescription = computed(() =>
  selectedProblem.value ? renderSafeMarkdown(selectedProblem.value.description) : ''
)
const renderedFeedback = computed(() => feedback.value ? renderSafeMarkdown(feedback.value) : '')
const cleanReferenceAnswer = computed(() => {
  if (!referenceAnswer.value) return ''
  // 去掉 markdown 代码块包裹（```python ... ``` 或 ``` ... ```）
  return referenceAnswer.value.replace(/^```[\w]*\n?/, '').replace(/\n?```$/, '').trim()
})
const maxErrorCount = computed(() => {
  if (!errorStats.value?.error_stats) return 1
  return Math.max(1, ...Object.values(errorStats.value.error_stats))
})

// ── 方法 ──
async function loadProblems() {
  try {
    const params = { page_size: 100 }
    if (filterDifficulty.value) params.difficulty = filterDifficulty.value
    const res = await fetchCodingProblems(params)
    problems.value = res.problems || []
  } catch (e) {
    toast.error('加载题目失败')
  }
}

async function selectProblem(p) {
  selectedProblem.value = p
  feedback.value = ''
  lastSubmission.value = null
  showDescription.value = true
  scores.value = null
  totalScore.value = 0
  referenceAnswer.value = ''
  hintCount.value = 0
  currentMode.value = ''
  try {
    const detail = await fetchCodingProblem(p.id)
    selectedProblem.value = detail
  } catch (e) {
    toast.error('加载题目详情失败')
  }
}

function clearCurrentProblem() {
  feedback.value = ''
  lastSubmission.value = null
  scores.value = null
  totalScore.value = 0
  referenceAnswer.value = ''
  hintCount.value = 0
  currentMode.value = ''
}

async function submitCode(mode) {
  if (!selectedProblem.value || !code.value.trim()) return
  if (mode === 'hint' && hintCount.value >= 3) return

  isSubmitting.value = true
  currentMode.value = mode
  currentStep.value = ''
  // hint 模式不清空之前的 feedback，保留历史提示
  if (mode === 'full_review') {
    feedback.value = ''
    scores.value = null
    totalScore.value = 0
    referenceAnswer.value = ''
  }
  // hint 模式：在 feedback 末尾加分隔标记
  const hintSeparator = mode === 'hint' && feedback.value ? '\n\n---\n\n' : ''

  const data = {
    problem_id: selectedProblem.value.id,
    language: currentLanguage.value,
    code: code.value,
    mode,
  }
  if (mode === 'hint' && lastSubmission.value) {
    data.parent_submission_id = lastSubmission.value.submission_id
  }

  try {
    await submitCodingCode(data, (event) => {
      if (event.type === 'step') {
        currentStep.value = event.message
      } else if (event.type === 'chunk') {
        if (event.replace) {
          // replace 模式：用新内容替换当前 chunk 流（避免重复）
          // 保留 hint 历史部分，只替换当前 hint 的流式内容
          const historyEnd = hintSeparator ? feedback.value.indexOf(hintSeparator) : -1
          if (historyEnd >= 0) {
            feedback.value = feedback.value.substring(0, historyEnd + hintSeparator.length) + event.content
          } else if (mode === 'hint' && hintSeparator) {
            feedback.value = hintSeparator + event.content
          } else {
            feedback.value = event.content
          }
        } else {
          if (hintSeparator && !feedback.value.includes(hintSeparator)) {
            feedback.value += hintSeparator
          }
          feedback.value += event.content
        }
      } else if (event.type === 'done') {
        // hint 模式不显示评分
        if (event.mode === 'hint') {
          hintCount.value = (event.hint_round || hintCount.value + 1)
        }
        if (event.mode === 'full_review') {
          scores.value = event.scores || null
          totalScore.value = event.total_score || 0
          referenceAnswer.value = event.reference_answer || ''
          loadErrorStats()
        }
        lastSubmission.value = event
      } else if (event.type === 'error') {
        toast.error(event.message || '评审失败')
      }
    })
  } catch (e) {
    toast.error('提交失败，请重试')
  } finally {
    isSubmitting.value = false
    currentStep.value = ''
  }
}

async function loadErrorStats() {
  try {
    errorStats.value = await fetchCodingErrorStats()
  } catch (e) {
    // silent
  }
}

// ── 生命周期 ──
onMounted(() => {
  loadProblems()
  loadErrorStats()
})
</script>
