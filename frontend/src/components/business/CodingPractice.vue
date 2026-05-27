<template>
  <div class="flex flex-col lg:flex-row gap-4 h-[calc(100vh-120px)]">
    <!-- ── 左侧面板：题目列表 + 错误统计 ── -->
    <div class="w-full lg:w-80 flex-shrink-0 flex flex-col gap-3 overflow-y-auto custom-scrollbar">
      <!-- 难度筛选 -->
      <div class="flex gap-2">
        <button
          v-for="d in ['', 'easy', 'medium', 'hard']"
          :key="d"
          @click="filterDifficulty = d; loadProblems()"
          :class="[
            'px-3 py-1 rounded-full text-xs font-medium transition-colors',
            filterDifficulty === d
              ? 'bg-primary-600 text-white'
              : 'bg-surface-100 text-ink-600 hover:bg-surface-200 dark:bg-surface-700 dark:text-ink-300 dark:hover:bg-surface-600'
          ]"
        >
          {{ d === '' ? '全部' : d === 'easy' ? '简单' : d === 'medium' ? '中等' : '困难' }}
        </button>
      </div>

      <!-- 题目列表 -->
      <div class="flex-1 space-y-2 overflow-y-auto custom-scrollbar">
        <div
          v-for="p in problems"
          :key="p.id"
          @click="selectProblem(p)"
          :class="[
            'p-3 rounded-lg cursor-pointer border transition-all',
            selectedProblem?.id === p.id
              ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
              : 'border-surface-200 dark:border-surface-600 hover:border-primary-300 bg-white dark:bg-surface-800'
          ]"
        >
          <div class="flex items-center justify-between">
            <span class="text-sm font-medium text-ink-800 dark:text-ink-100 truncate">{{ p.title }}</span>
            <span :class="[
              'text-xs px-2 py-0.5 rounded-full font-medium',
              p.difficulty === 'easy' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
              p.difficulty === 'medium' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' :
              'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
            ]">
              {{ p.difficulty === 'easy' ? '简' : p.difficulty === 'medium' ? '中' : '难' }}
            </span>
          </div>
          <div class="flex flex-wrap gap-1 mt-1.5">
            <span
              v-for="tag in (p.tags || []).slice(0, 3)"
              :key="tag"
              class="text-xs px-1.5 py-0.5 rounded bg-surface-100 dark:bg-surface-700 text-ink-500 dark:text-ink-400"
            >{{ tag }}</span>
          </div>
        </div>
        <div v-if="problems.length === 0" class="text-center text-ink-400 text-sm py-8">暂无题目</div>
      </div>

      <!-- 错误统计 -->
      <div class="bg-white dark:bg-surface-800 rounded-lg border border-surface-200 dark:border-surface-600 p-3">
        <h3 class="text-sm font-semibold text-ink-700 dark:text-ink-200 mb-2">错误统计</h3>
        <div v-if="errorStats" class="space-y-1.5">
          <div v-for="(count, cat) in errorStats.error_stats" :key="cat" class="flex items-center gap-2">
            <span class="text-xs text-ink-500 dark:text-ink-400 w-16">{{ categoryLabels[cat] || cat }}</span>
            <div class="flex-1 h-2 bg-surface-100 dark:bg-surface-700 rounded-full overflow-hidden">
              <div
                class="h-full rounded-full transition-all"
                :class="categoryColors[cat] || 'bg-gray-400'"
                :style="{ width: Math.min(100, (count / maxErrorCount) * 100) + '%' }"
              ></div>
            </div>
            <span class="text-xs text-ink-600 dark:text-ink-300 w-6 text-right">{{ count }}</span>
          </div>
          <div class="text-xs text-ink-400 mt-2 pt-2 border-t border-surface-200 dark:border-surface-600">
            总提交 {{ errorStats.total_submissions }} · 通过 {{ errorStats.passed_submissions }}
          </div>
        </div>
        <div v-else class="text-xs text-ink-400">暂无数据</div>
      </div>
    </div>

    <!-- ── 右侧面板：编码 + AI 反馈 ── -->
    <div class="flex-1 flex flex-col gap-3 min-w-0">
      <template v-if="selectedProblem">
        <!-- 题目描述（可折叠） -->
        <div class="bg-white dark:bg-surface-800 rounded-lg border border-surface-200 dark:border-surface-600">
          <button
            @click="showDescription = !showDescription"
            class="w-full flex items-center justify-between p-3 text-left"
          >
            <div class="flex items-center gap-2">
              <span class="text-sm font-semibold text-ink-800 dark:text-ink-100">{{ selectedProblem.title }}</span>
              <span :class="[
                'text-xs px-2 py-0.5 rounded-full',
                selectedProblem.difficulty === 'easy' ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' :
                selectedProblem.difficulty === 'medium' ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' :
                'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
              ]">
                {{ selectedProblem.difficulty === 'easy' ? '简单' : selectedProblem.difficulty === 'medium' ? '中等' : '困难' }}
              </span>
            </div>
            <svg :class="['w-4 h-4 text-ink-400 transition-transform', showDescription ? 'rotate-180' : '']" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
            </svg>
          </button>
          <div v-if="showDescription" class="px-3 pb-3 text-sm text-ink-600 dark:text-ink-300 prose-sm max-w-none border-t border-surface-200 dark:border-surface-600 pt-3" v-html="renderedDescription"></div>
        </div>

        <!-- 语言选择 + 操作按钮 -->
        <div class="flex items-center gap-2 flex-wrap">
          <button
            v-for="lang in ['python', 'c', 'java']"
            :key="lang"
            @click="currentLanguage = lang"
            :class="[
              'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
              currentLanguage === lang
                ? 'bg-primary-600 text-white'
                : 'bg-surface-100 text-ink-600 hover:bg-surface-200 dark:bg-surface-700 dark:text-ink-300'
            ]"
          >
            {{ langLabels[lang] }}
          </button>

          <div class="flex-1"></div>

          <button
            @click="submitCode('full_review')"
            :disabled="isSubmitting || !code.trim()"
            class="px-4 py-1.5 rounded-md text-sm font-medium bg-primary-600 text-white hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {{ isSubmitting ? (currentStep || '评审中...') : '提交评审' }}
          </button>
          <button
            v-if="lastSubmission"
            @click="submitCode('hint')"
            :disabled="isSubmitting || !code.trim()"
            class="px-4 py-1.5 rounded-md text-sm font-medium bg-surface-100 text-ink-600 hover:bg-surface-200 dark:bg-surface-700 dark:text-ink-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {{ isSubmitting ? '提示中...' : '请求提示' }}
          </button>
        </div>

        <!-- Monaco 编辑器 -->
        <div class="flex-1 min-h-[300px] rounded-lg overflow-hidden border border-surface-200 dark:border-surface-600">
          <CodeEditor
            v-model="code"
            :language="currentLanguage"
            :read-only="isSubmitting"
          />
        </div>

        <!-- 评分面板 -->
        <div
          v-if="scores && Object.keys(scores).length"
          class="bg-white dark:bg-surface-800 rounded-lg border border-surface-200 dark:border-surface-600 p-4"
        >
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-semibold text-ink-800 dark:text-ink-100">评审评分</h3>
            <div class="flex items-baseline gap-1">
              <span class="text-2xl font-bold" :class="totalScore >= 80 ? 'text-green-600 dark:text-green-400' : totalScore >= 60 ? 'text-yellow-600 dark:text-yellow-400' : 'text-red-600 dark:text-red-400'">{{ totalScore }}</span>
              <span class="text-sm text-ink-400">/100</span>
            </div>
          </div>
          <div class="space-y-2">
            <div v-for="(score, dim) in scores" :key="dim" class="flex items-center gap-2">
              <span class="text-xs text-ink-500 dark:text-ink-400 w-12">{{ categoryLabels[dim] || dim }}</span>
              <div class="flex-1 h-2 bg-surface-100 dark:bg-surface-700 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full transition-all"
                  :class="scoreBarColors[dim] || 'bg-gray-400'"
                  :style="{ width: (score / 5 * 100) + '%' }"
                ></div>
              </div>
              <span class="text-xs text-ink-600 dark:text-ink-300 w-8 text-right">{{ score }}/5</span>
            </div>
          </div>
          <div v-if="lastSubmission?.error_categories?.length" class="flex gap-1 mt-3 pt-3 border-t border-surface-200 dark:border-surface-600">
            <span
              v-for="cat in lastSubmission.error_categories"
              :key="cat"
              class="text-xs px-2 py-0.5 rounded-full bg-red-50 text-red-600 dark:bg-red-900/20 dark:text-red-400"
            >{{ categoryLabels[cat] || cat }}</span>
          </div>
        </div>

        <!-- AI 评审反馈（流式渲染） -->
        <div
          v-if="feedback"
          class="bg-white dark:bg-surface-800 rounded-lg border border-surface-200 dark:border-surface-600 p-4"
        >
          <h3 class="text-sm font-semibold text-ink-800 dark:text-ink-100 mb-3">详细评审</h3>
          <div class="prose-sm max-w-none text-ink-600 dark:text-ink-300" v-html="renderedFeedback"></div>
          <span v-if="isSubmitting" class="inline-block w-1.5 h-4 bg-primary-500 animate-pulse ml-0.5 mt-1"></span>
        </div>

        <!-- 参考答案 -->
        <div
          v-if="referenceAnswer"
          class="bg-white dark:bg-surface-800 rounded-lg border border-surface-200 dark:border-surface-600 p-4"
        >
          <h3 class="text-sm font-semibold text-ink-800 dark:text-ink-100 mb-3">最小改动参考答案</h3>
          <pre class="text-sm text-ink-700 dark:text-ink-200 bg-surface-50 dark:bg-surface-900 rounded-md p-3 overflow-x-auto whitespace-pre-wrap"><code>{{ referenceAnswer }}</code></pre>
        </div>
      </template>

      <!-- 未选题时的占位 -->
      <div v-else class="flex-1 flex items-center justify-center text-ink-400 text-sm">
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
const scores = ref(null)
const totalScore = ref(0)
const referenceAnswer = ref('')
const currentStep = ref('')

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
  code.value = ''
  try {
    const detail = await fetchCodingProblem(p.id)
    selectedProblem.value = detail
  } catch (e) {
    toast.error('加载题目详情失败')
  }
}

async function submitCode(mode) {
  if (!selectedProblem.value || !code.value.trim()) return

  isSubmitting.value = true
  feedback.value = ''
  scores.value = null
  totalScore.value = 0
  referenceAnswer.value = ''
  currentStep.value = ''

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
        feedback.value += event.content
      } else if (event.type === 'done') {
        scores.value = event.scores || null
        totalScore.value = event.total_score || 0
        referenceAnswer.value = event.reference_answer || ''
        lastSubmission.value = event
        loadErrorStats()
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
