<template>
  <div class="space-y-6">
    <!-- Config panel -->
    <div v-if="!quizStarted" class="bg-white dark:bg-surface-800 rounded-xl border border-orange-200 dark:border-orange-800/50 p-6 space-y-6">
      <h2 class="text-lg font-bold text-gray-800 dark:text-gray-100">配置抽测</h2>

      <!-- Category selection -->
      <div>
        <label class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2 block">选择领域</label>
        <div class="flex flex-wrap gap-2">
          <button
            @click="selectedCat = ''"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedCat === '' ? 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 border-orange-300 dark:border-orange-700 font-semibold' : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
          >全部领域</button>
          <button
            v-for="(cnt, cat) in popularTags" :key="cat"
            @click="selectedCat = cat"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedCat === cat ? 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 border-orange-300 dark:border-orange-700 font-semibold' : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
          >{{ cat }} <span class="opacity-50 ml-0.5">{{ cnt }}</span></button>
        </div>
      </div>

      <!-- Difficulty selection -->
      <div>
        <label class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2 block">难度</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="opt in difficultyOptions" :key="opt.value"
            @click="selectedDifficulty = opt.value"
            class="text-xs px-3 py-1.5 rounded-full border transition-colors"
            :class="selectedDifficulty === opt.value ? 'bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 border-orange-300 dark:border-orange-700 font-semibold' : 'bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700'"
          >{{ opt.label }}</button>
        </div>
      </div>

      <!-- Count -->
      <div>
        <label class="text-sm font-semibold text-gray-600 dark:text-gray-400 mb-2 block">题目数量</label>
        <div class="flex items-center gap-3">
          <button @click="questionCount = Math.max(1, questionCount - 1)" class="w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center justify-center text-lg font-bold transition">-</button>
          <input v-model.number="questionCount" type="number" min="1" max="50" class="w-20 text-center border border-gray-300 dark:border-gray-600 rounded-lg px-2 py-1.5 text-sm bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 focus:ring-orange-500 focus:border-orange-500 dark:focus:ring-orange-400 dark:focus:border-orange-400" />
          <button @click="questionCount = Math.min(50, questionCount + 1)" class="w-9 h-9 rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 flex items-center justify-center text-lg font-bold transition">+</button>
        </div>
      </div>

      <!-- Start button -->
      <button @click="startQuiz" class="w-full bg-orange-600 dark:bg-orange-600 text-white font-bold py-3 rounded-lg hover:bg-orange-700 dark:hover:bg-orange-700 transition text-base shadow-sm">
        开始抽测
      </button>
    </div>

    <!-- Quiz mode -->
    <div v-else>
      <!-- Summary bar -->
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4 bg-orange-50 dark:bg-orange-900/30 border border-orange-200 dark:border-orange-800/50 rounded-lg px-4 py-3">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-gray-500 dark:text-gray-400">当前：</span>
          <span class="bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 px-2 py-0.5 rounded text-xs font-semibold">{{ selectedCat || '全部领域' }}</span>
          <span class="bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 px-2 py-0.5 rounded text-xs font-semibold">{{ selectedDifficultyLabel }}</span>
          <span class="text-gray-400 dark:text-gray-500">|</span>
          <span class="text-gray-600 dark:text-gray-400">共 {{ mockQuestions.length }} 题</span>
          <template v-if="quizSummary">
            <span class="text-gray-400 dark:text-gray-500">|</span>
            <span class="text-gray-600 dark:text-gray-400">已答 {{ quizSummary.answered }}/{{ quizSummary.total }}</span>
            <span class="font-bold" :class="scoreTextColor(quizSummary.avgScore)">均分 {{ quizSummary.avgScore }}</span>
          </template>
        </div>
        <div class="flex gap-2">
          <button @click="loadQuestions" class="text-sm bg-orange-600 dark:bg-orange-600 text-white font-semibold px-4 py-1.5 rounded-lg hover:bg-orange-700 dark:hover:bg-orange-700 transition">换一批</button>
          <button @click="quizStarted = false" class="text-sm bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-600 px-4 py-1.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition">重新配置</button>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="text-center py-10 text-gray-400 dark:text-gray-500 border-2 border-dashed border-gray-200 dark:border-gray-600 rounded-xl">
        <svg class="animate-spin h-8 w-8 text-orange-400 dark:text-orange-400 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        <p class="text-lg">正在加载题目...</p>
      </div>

      <!-- Empty -->
      <div v-else-if="mockQuestions.length === 0" class="text-center py-10 text-gray-400 dark:text-gray-500 border-2 border-dashed border-gray-200 dark:border-gray-600 rounded-xl">
        <p class="mb-2 text-lg">暂无符合条件的题目</p>
        <p class="text-sm">请调整筛选条件或录入更多面经数据。</p>
        <button @click="quizStarted = false" class="mt-4 text-sm bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 px-4 py-2 rounded-lg hover:bg-orange-200 dark:hover:bg-orange-900/50 transition">返回配置</button>
      </div>

      <!-- Questions -->
      <div v-for="(q, qIdx) in mockQuestions" :key="q.id" class="border border-orange-200 dark:border-orange-800/50 rounded-xl overflow-hidden bg-white dark:bg-surface-800 shadow-sm">
        <div class="p-5 bg-gradient-to-r from-orange-50 to-amber-50 dark:from-orange-900/30 dark:to-amber-900/30">
          <div class="flex items-start gap-4">
            <div class="flex flex-col items-center justify-center bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400 font-bold rounded-lg p-3 min-w-[56px] border border-orange-200 dark:border-orange-800/50">
              <span class="text-xs font-normal text-orange-400 dark:text-orange-500">第</span>
              <span class="text-xl leading-none">{{ qIdx + 1 }}</span>
              <span class="text-xs font-normal text-orange-400 dark:text-orange-500">题</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex gap-2 mb-2 items-center flex-wrap">
                <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400' : String(q.difficulty).includes('L2') ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400' : 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400'">
                  {{ q.difficulty || '-' }}
                </span>
                <span v-if="q.attempt_count > 0" class="bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-xs px-2 py-0.5 rounded font-medium">已刷 {{ q.attempt_count }} 次</span>
                <span v-else class="bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 text-xs px-2 py-0.5 rounded font-medium">新题</span>
                <button @click="handleToggleStar(q)" class="text-lg ml-1 transition-transform hover:scale-125" :title="q.is_starred ? '取消收藏' : '收藏'">
                  {{ q.is_starred ? '★' : '☆' }}
                </button>
                <span class="text-xs text-gray-400 dark:text-gray-500 ml-auto">频率 {{ q.frequency }}</span>
              </div>
              <h3 class="text-base lg:text-lg font-bold text-gray-800 dark:text-gray-100 leading-snug">{{ q.question }}</h3>
            </div>
          </div>
        </div>

        <!-- User answer input -->
        <div class="px-5 py-4 border-t border-orange-100 dark:border-orange-800/50 bg-white dark:bg-surface-800">
          <label class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1.5 block">你的回答</label>
          <textarea
            v-model="q._userAnswer"
            placeholder="在这里输入你的回答，然后点击「提交评估」让 AI 对比参考答案评分..."
            rows="5"
            class="w-full border border-gray-200 dark:border-gray-600 rounded-lg p-3 text-sm leading-relaxed bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 focus:ring-orange-500 dark:focus:ring-orange-400 focus:border-orange-500 dark:focus:border-orange-400 resize-y"
          ></textarea>
          <div class="flex gap-2 mt-2">
            <button
              @click="handleEvaluate(q)"
              :disabled="q._isEvaluating"
              class="bg-orange-600 dark:bg-orange-600 text-white font-semibold text-sm px-5 py-2 rounded-lg hover:bg-orange-700 dark:hover:bg-orange-700 transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <svg v-if="q._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              {{ q._isEvaluating ? '评估中...' : '提交评估' }}
            </button>
            <button
              v-if="q._userAnswer"
              @click="q._userAnswer = ''; q._evaluation = null"
              class="text-sm text-gray-500 dark:text-gray-400 px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-gray-700 transition"
            >清空</button>
          </div>
        </div>

        <!-- Evaluation result -->
        <div v-if="q._evaluation" class="px-5 py-4 border-t border-orange-100 dark:border-orange-800/50 bg-gradient-to-br from-orange-50 to-amber-50 dark:from-orange-900/30 dark:to-amber-900/30">
          <h4 class="text-sm font-bold text-gray-700 dark:text-gray-300 mb-3">评估结果</h4>

          <!-- Overall score -->
          <div class="flex items-center gap-3 mb-4">
            <span class="text-3xl font-extrabold" :class="scoreTextColor(q._evaluation.overall_score)">{{ q._evaluation.overall_score }}</span>
            <div class="flex-1">
              <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-3 overflow-hidden">
                <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(q._evaluation.overall_score)" :style="{ width: q._evaluation.overall_score + '%' }"></div>
              </div>
            </div>
            <span class="text-xs text-gray-400 dark:text-gray-500">/ 100</span>
          </div>

          <!-- Dimension scores -->
          <div class="space-y-2 mb-4">
            <div v-for="(val, key) in q._evaluation.dimensions" :key="key" class="flex items-start gap-2">
              <span class="text-xs text-gray-500 dark:text-gray-400 w-14 shrink-0 pt-0.5">{{ dimLabel[key] || key }}</span>
              <div class="flex-1">
                <div class="flex items-center gap-2">
                  <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-2 flex-1 overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                  </div>
                  <span class="text-xs font-bold w-8 text-right" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                </div>
                <p v-if="val.comment" class="text-xs text-gray-400 dark:text-gray-500 mt-0.5 leading-snug">{{ val.comment }}</p>
              </div>
            </div>
          </div>

          <!-- Strengths & Weaknesses -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
            <div v-if="q._evaluation.strengths?.length">
              <p class="text-xs font-semibold text-green-700 dark:text-green-400 mb-1">亮点</p>
              <ul class="space-y-1">
                <li v-for="s in q._evaluation.strengths" :key="s" class="text-xs text-gray-600 dark:text-gray-400 flex gap-1.5">
                  <span class="text-green-500 dark:text-green-400 shrink-0">+</span>{{ s }}
                </li>
              </ul>
            </div>
            <div v-if="q._evaluation.weaknesses?.length">
              <p class="text-xs font-semibold text-red-700 dark:text-red-400 mb-1">不足</p>
              <ul class="space-y-1">
                <li v-for="w in q._evaluation.weaknesses" :key="w" class="text-xs text-gray-600 dark:text-gray-400 flex gap-1.5">
                  <span class="text-red-500 dark:text-red-400 shrink-0">-</span>{{ w }}
                </li>
              </ul>
            </div>
          </div>

          <!-- Suggestions -->
          <div v-if="q._evaluation.suggestions">
            <p class="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-1">改进建议</p>
            <div class="text-sm text-gray-600 dark:text-gray-400 leading-relaxed answer-content" v-html="renderMarkdown(q._evaluation.suggestions)"></div>
          </div>
        </div>

        <!-- Practice history toggle -->
        <div v-if="q.attempt_count > 0" class="border-t border-orange-100 dark:border-orange-800/50">
          <button
            @click="toggleHistory(q)"
            class="w-full py-2.5 text-xs font-medium text-gray-500 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-orange-900/20 transition flex items-center justify-center gap-2"
          >
            <svg class="w-3.5 h-3.5 transition-transform" :class="{ 'rotate-90': q._showHistory }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
            {{ q._showHistory ? '收起练习记录' : `查看练习记录 (${q.attempt_count}次)` }}
          </button>
          <div v-if="q._showHistory" class="px-5 py-4 bg-gray-50 dark:bg-gray-800 border-t border-orange-100 dark:border-orange-800/50 space-y-2 max-h-64 overflow-y-auto custom-scrollbar">
            <div v-if="q._historyLoading" class="text-center py-3 text-xs text-gray-400 dark:text-gray-500">加载中...</div>
            <div v-else-if="q._history && q._history.length > 0">
              <div v-for="(h, hIdx) in q._history" :key="h.id" class="border-b border-gray-100 dark:border-gray-700 last:border-b-0">
                <div class="flex items-center gap-3 py-2 cursor-pointer hover:bg-gray-100/50 dark:hover:bg-gray-700/50 px-1 rounded" @click="h._expanded = !h._expanded">
                  <span class="text-xs text-gray-400 dark:text-gray-500 w-5 text-right shrink-0">#{{ q._history.length - hIdx }}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                      <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                      <span class="text-xs text-gray-300 dark:text-gray-600">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                    </div>
                    <p v-if="!h._expanded" class="text-xs text-gray-500 dark:text-gray-400 truncate">{{ h.user_answer?.slice(0, 80) }}{{ h.user_answer?.length > 80 ? '...' : '' }}</p>
                  </div>
                  <div class="w-16 shrink-0">
                    <div class="bg-gray-200 dark:bg-gray-700 rounded-full h-1.5 overflow-hidden">
                      <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                    </div>
                  </div>
                  <svg class="w-3.5 h-3.5 text-gray-400 dark:text-gray-500 transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                </div>
                <div v-if="h._expanded" class="pl-6 pr-2 pb-3 space-y-2">
                  <div>
                    <p class="text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">我的回答</p>
                    <p class="text-xs text-gray-600 dark:text-gray-400 bg-white dark:bg-gray-800 rounded p-2 border border-gray-100 dark:border-gray-700 whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                  </div>
                  <div v-if="h.evaluation_result">
                    <div class="flex items-center gap-3 mb-1">
                      <span class="text-xs font-semibold text-gray-500 dark:text-gray-400">维度评分：</span>
                      <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-xs text-gray-500 dark:text-gray-400">
                        {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                      </span>
                    </div>
                    <div v-if="h.evaluation_result.suggestions" class="text-xs text-gray-500 dark:text-gray-400">
                      <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 200) }}{{ h.evaluation_result.suggestions?.length > 200 ? '...' : '' }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-3 text-xs text-gray-400 dark:text-gray-500">暂无练习记录</div>
          </div>
        </div>

        <div class="border-t border-orange-100 dark:border-orange-800/50">
          <button
            @click="q._showAnswer = !q._showAnswer"
            class="w-full py-3 text-sm font-medium text-orange-600 dark:text-orange-400 hover:bg-orange-50 dark:hover:bg-orange-900/30 transition flex items-center justify-center gap-2"
          >
            {{ q._showAnswer ? '收起答案' : '查看答案' }}
          </button>
          <div v-if="q._showAnswer" class="p-6 bg-slate-50 dark:bg-gray-800 border-t border-orange-100 dark:border-orange-800/50">
            <!-- Edit mode -->
            <div v-if="q._isEditingAnswer" class="flex flex-col gap-3">
              <label class="text-xs font-semibold text-gray-600 dark:text-gray-400">编辑参考答案</label>
              <textarea
                v-model="q._editAnswer"
                rows="10"
                class="w-full border border-blue-300 dark:border-blue-700 rounded-lg p-3 text-sm leading-relaxed bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 focus:ring-blue-500 focus:border-blue-500 dark:focus:ring-blue-400 dark:focus:border-blue-400 resize-y font-mono"
              ></textarea>
              <div class="flex gap-2 justify-end">
                <button @click="q._isEditingAnswer = false" class="px-4 py-1.5 text-sm text-gray-600 dark:text-gray-400 border border-gray-300 dark:border-gray-600 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition">取消</button>
                <button @click="handleSaveAnswer(q)" :disabled="q._isSavingAnswer" class="px-4 py-1.5 text-sm text-white bg-blue-600 dark:bg-blue-600 rounded-lg hover:bg-blue-700 dark:hover:bg-blue-700 transition disabled:opacity-50">
                  {{ q._isSavingAnswer ? '保存中...' : '保存' }}
                </button>
              </div>
            </div>
            <!-- View mode -->
            <div v-else>
              <div v-if="q.ai_answer" class="relative">
                <button
                  @click="q._isEditingAnswer = true; q._editAnswer = q.ai_answer"
                  class="absolute top-0 right-0 text-xs text-blue-600 dark:text-blue-400 hover:text-blue-800 dark:hover:text-blue-300 bg-blue-50 dark:bg-blue-900/30 hover:bg-blue-100 dark:hover:bg-blue-900/50 px-2.5 py-1 rounded-md transition border border-blue-200 dark:border-blue-800"
                >编辑答案</button>
                <div class="text-gray-700 dark:text-gray-300 text-sm leading-relaxed answer-content" v-html="renderMarkdown(q.ai_answer)"></div>
              </div>
              <div v-else class="text-center py-4">
                <p class="text-gray-400 dark:text-gray-500 mb-3 text-sm">暂无 AI 答案。</p>
                <div class="flex gap-2 justify-center flex-wrap">
                  <button @click="handleGenerate(q)" :disabled="q._isLoadingAnswer" class="bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold px-5 py-2 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-900/50 transition text-sm disabled:opacity-50">
                    {{ q._isLoadingAnswer ? '生成中...' : 'AI 生成答案' }}
                  </button>
                  <button @click="q._isEditingAnswer = true; q._editAnswer = ''" class="bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 font-bold px-5 py-2 rounded-lg hover:bg-gray-200 dark:hover:bg-gray-600 transition text-sm">
                    手动编写
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { renderSafeMarkdown } from '../utils/markdown.js'
import { fetchRandomQuestions, generateAnswer as apiGenerateAnswer, evaluateAnswer, fetchPracticeHistory, updateRecord, toggleStar as apiToggleStar } from '../api/index.js'
import { sanitizeAgainstInjection, validateNumber } from '../utils/validate.js'
import { useToast, useConfirm } from '../composables/useNotification.js'

const toast = useToast()
const { confirm: showConfirm } = useConfirm()

const props = defineProps({
  popularTags: { type: Object, default: () => ({}) }
})

const difficultyOptions = [
  { value: '', label: '随机' },
  { value: 'L1', label: 'L1-基础' },
  { value: 'L2', label: 'L2-中等' },
  { value: 'L3', label: 'L3-困难' }
]

// Config state
const selectedCat = ref('')
const selectedDifficulty = ref('')
const questionCount = ref(10)

// Quiz state
const quizStarted = ref(false)
const isLoading = ref(false)
const mockQuestions = ref([])

const selectedDifficultyLabel = computed(() =>
  difficultyOptions.find(o => o.value === selectedDifficulty.value)?.label || '随机'
)

const startQuiz = () => {
  quizStarted.value = true
  loadQuestions()
}

const loadQuestions = async () => {
  // 检查是否有未保存的输入
  const hasInput = mockQuestions.value.some(q => q._userAnswer.trim())
  if (hasInput) {
    const confirmed = await showConfirm('当前有未提交的答案，确定要换一批吗？')
    if (!confirmed) return
  }
  const countResult = validateNumber(questionCount.value, 1, 50, '题目数量')
  if (!countResult.valid) {
    toast.warning(countResult.error)
    return
  }
  isLoading.value = true
  try {
    const data = await fetchRandomQuestions({
      count: countResult.value,
      cat1: selectedCat.value || undefined,
      difficulty: selectedDifficulty.value || undefined
    })
    mockQuestions.value = data.map(q => ({ ...q, _showAnswer: false, _isLoadingAnswer: false, _userAnswer: '', _evaluation: null, _isEvaluating: false, _showHistory: false, _history: null, _historyLoading: false, _isEditingAnswer: false, _editAnswer: '', _isSavingAnswer: false }))
  } catch (e) {
    console.error('获取题目失败', e)
    mockQuestions.value = []
  } finally {
    isLoading.value = false
  }
}

const handleGenerate = async (q) => {
  q._isLoadingAnswer = true
  try {
    const data = await apiGenerateAnswer(q.id)
    q.ai_answer = data.answer
    toast.success('答案已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    q._isLoadingAnswer = false
  }
}

const handleSaveAnswer = async (q) => {
  if (!q._editAnswer.trim()) {
    toast.warning('答案不能为空')
    return
  }
  try {
    sanitizeAgainstInjection(q._editAnswer, '答案内容')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  q._isSavingAnswer = true
  try {
    await updateRecord({ table_name: 'question_bank', record_id: q.id, update_data: { ai_answer: q._editAnswer } })
    q.ai_answer = q._editAnswer
    q._isEditingAnswer = false
    toast.success('答案已保存')
  } catch (e) {
    toast.error(`保存失败: ${e.message}`)
  } finally {
    q._isSavingAnswer = false
  }
}

const renderMarkdown = (text) => renderSafeMarkdown(text)

const handleEvaluate = async (q) => {
  if (!q._userAnswer.trim()) {
    toast.warning('请先输入你的答案')
    return
  }
  if (!q.ai_answer) {
    toast.warning('请先生成或查看 AI 参考答案')
    return
  }
  try {
    sanitizeAgainstInjection(q._userAnswer, '你的回答')
  } catch (e) {
    toast.warning(e.message)
    return
  }
  q._isEvaluating = true
  q._evaluation = null
  try {
    const data = await evaluateAnswer({
      question_id: q.id,
      question_text: q.question,
      user_answer: q._userAnswer,
      reference_answer: q.ai_answer
    })
    q._evaluation = data
    q.attempt_count = (q.attempt_count || 0) + 1
    q._history = null  // force reload history next time
    toast.success('评估完成')
  } catch (e) {
    toast.error(`评估失败: ${e.message}`)
  } finally {
    q._isEvaluating = false
  }
}

const scoreColor = (score) => {
  if (score >= 80) return 'bg-green-500 dark:bg-green-500'
  if (score >= 60) return 'bg-yellow-500 dark:bg-yellow-500'
  return 'bg-red-500 dark:bg-red-500'
}

const scoreTextColor = (score) => {
  if (score >= 80) return 'text-green-700 dark:text-green-400'
  if (score >= 60) return 'text-yellow-700 dark:text-yellow-400'
  return 'text-red-700 dark:text-red-400'
}

const dimLabel = { completeness: '完整性', depth: '深度', accuracy: '准确性', logic: '逻辑性' }

const handleToggleStar = async (q) => {
  try {
    const data = await apiToggleStar(q.id)
    q.is_starred = data.is_starred
  } catch (e) {
    toast.error(`操作失败: ${e.message}`)
  }
}

const quizSummary = computed(() => {
  const evaluated = mockQuestions.value.filter(q => q._evaluation)
  if (evaluated.length === 0) return null
  const avg = Math.round(evaluated.reduce((s, q) => s + q._evaluation.overall_score, 0) / evaluated.length)
  return { answered: evaluated.length, total: mockQuestions.value.length, avgScore: avg }
})

const toggleHistory = async (q) => {
  q._showHistory = !q._showHistory
  if (q._showHistory && !q._history) {
    q._historyLoading = true
    try {
      q._history = (await fetchPracticeHistory(q.id)).map(h => ({ ...h, _expanded: false }))
    } catch (e) {
      console.error('加载练习记录失败', e)
      q._history = []
    } finally {
      q._historyLoading = false
    }
  }
}
</script>
