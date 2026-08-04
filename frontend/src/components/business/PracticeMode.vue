<template>
  <div data-testid="practice-workspace" class="flex min-w-0 flex-col gap-4">
    <section data-testid="practice-session-picker" class="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-5">
        <div class="flex min-w-0 items-center gap-3">
          <div class="flex size-9 shrink-0 items-center justify-center rounded-xl bg-gradient-brand shadow-sm">
            <Layers class="size-5 text-white" />
          </div>
          <div class="min-w-0">
            <h3 class="text-sm font-bold text-foreground">刷题</h3>
            <p class="text-caption text-muted-foreground">先回忆，再翻牌；用短时间重复高频八股</p>
          </div>
          <Badge variant="outline" class="hidden text-[10px] text-muted-foreground sm:inline-flex">闪卡模式</Badge>
        </div>

        <div v-if="currentQ" class="flex min-w-0 flex-wrap items-center justify-end gap-2 md:gap-3">
          <div class="hidden text-right sm:block">
            <div class="text-[11px] font-medium text-muted-foreground">{{ selectedSession?.label }}</div>
            <div class="text-xs tabular-nums text-foreground">{{ currentIndex + 1 }} / {{ sessionQuestions.length }}</div>
          </div>
          <div class="h-1.5 w-20 overflow-hidden rounded-full bg-muted md:w-32">
            <div class="h-full rounded-full bg-primary transition-all duration-300" :style="{ width: `${progressPercentage}%` }"></div>
          </div>
          <Button variant="ghost" size="icon" class="text-muted-foreground hover:text-amber-500" @click="toggleStar">
            <Star :size="17" :fill="currentQ.is_starred ? 'currentColor' : 'none'" />
            <span class="sr-only">{{ currentQ.is_starred ? '取消收藏' : '收藏' }}</span>
          </Button>
          <Button variant="outline" size="sm" class="gap-1.5" @click="emit('close')">
            <X class="size-3.5" />返回题库
          </Button>
        </div>
        <Button v-else variant="outline" size="sm" class="gap-1.5" @click="emit('close')">
          <X class="size-3.5" />返回题库
        </Button>
      </div>

      <div class="flex flex-col gap-4 p-4 md:p-5">
        <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <p class="text-xs font-semibold text-muted-foreground">选择刷题题单</p>
            <p class="mt-1 text-xs text-muted-foreground">当前筛选题库共 {{ questions.length }} 题，收藏题可以直接单独复习</p>
          </div>
          <div class="relative w-full md:max-w-xs">
            <Search class="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <input v-model="deckQuery" type="search" class="h-9 w-full rounded-xl border border-input bg-background pl-9 pr-3 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20" placeholder="搜索当前题单..." />
          </div>
        </div>

        <div class="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <button
            v-for="option in recommendedSessions"
            :key="option.key"
            :data-testid="`practice-session-${option.key}`"
            :disabled="option.count === 0"
            type="button"
            class="group flex min-w-0 items-center gap-3 rounded-xl border px-3 py-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45"
            :class="sessionKey === option.key ? 'border-primary/40 bg-primary/5 text-foreground shadow-sm' : 'border-border bg-card text-muted-foreground hover:border-primary/25 hover:bg-muted/50 hover:text-foreground'"
            @click="selectSession(option.key)"
          >
            <span class="flex size-9 shrink-0 items-center justify-center rounded-xl" :class="sessionKey === option.key ? option.iconClass : 'bg-muted text-muted-foreground'">
              <component :is="option.icon" :size="16" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-sm font-semibold">{{ option.label }}</span>
              <span class="mt-0.5 block truncate text-[11px] text-muted-foreground">{{ option.description }}</span>
            </span>
            <span class="shrink-0 text-xs tabular-nums text-muted-foreground">{{ option.count }}</span>
          </button>
        </div>

        <div class="flex flex-col gap-2 border-t border-border pt-4 sm:flex-row sm:items-center">
          <p class="shrink-0 text-xs font-semibold text-muted-foreground">按难度</p>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="option in difficultySessions"
              :key="option.key"
              :data-testid="`practice-session-${option.key}`"
              :disabled="option.count === 0"
              type="button"
              class="inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-45"
              :class="sessionKey === option.key ? 'border-primary/40 bg-primary/5 text-primary' : 'border-border bg-card text-muted-foreground hover:bg-muted hover:text-foreground'"
              @click="selectSession(option.key)"
            >
              <span class="size-2 rounded-full" :class="option.dotClass"></span>
              {{ option.label }}
              <span class="tabular-nums text-muted-foreground">{{ option.count }}</span>
            </button>
          </div>
        </div>

        <div class="flex items-start gap-2 rounded-xl border border-primary/15 bg-primary/5 p-3">
          <Lightbulb class="mt-0.5 size-4 shrink-0 text-primary" />
          <div>
            <p class="text-xs font-medium text-foreground">背题小提示</p>
            <p class="mt-1 text-[11px] leading-relaxed text-muted-foreground">先用自己的话说出 3 个关键词，再展开答案核对，记忆会更牢。</p>
          </div>
        </div>
      </div>
    </section>

    <Card v-if="currentQ" data-testid="practice-card" class="mx-auto w-full max-w-6xl overflow-hidden p-0 shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-6">
        <div class="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <span class="font-semibold text-foreground">第 {{ currentIndex + 1 }} 题</span>
          <span>·</span>
          <span>高频 {{ currentQ.frequency || 0 }} 次</span>
          <span v-if="questionAttemptCount(currentQ)" class="hidden items-center gap-1 sm:inline-flex"><History class="size-3.5" />已练习 {{ questionAttemptCount(currentQ) }} 次</span>
        </div>
        <div class="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
          <Badge v-if="currentQ.difficulty" variant="outline" class="text-[10px]" :class="difficultyClass(currentQ.difficulty)">{{ currentQ.difficulty }}</Badge>
          <Badge variant="outline" class="max-w-32 truncate text-[10px]">{{ currentQ.cat1 || '未分类' }}</Badge>
        </div>
      </div>

      <div :key="currentQ.id" class="flex min-h-[28rem] flex-col px-4 py-7 question-content-enter sm:px-6 md:min-h-[32rem] md:px-12 md:py-10 lg:min-h-[calc(100vh-22rem)]">
        <div class="flex flex-wrap items-center gap-1.5">
          <Badge v-for="tag in questionTags(currentQ).slice(0, 4)" :key="tag" variant="secondary" class="text-[10px]">{{ tag }}</Badge>
        </div>

        <div class="mx-auto flex w-full max-w-3xl flex-1 flex-col justify-center py-10 text-center md:py-14">
          <p class="mb-5 text-xs font-medium uppercase tracking-[0.18em] text-primary">Interview flashcard</p>
          <h2 class="text-xl font-semibold leading-relaxed tracking-tight text-foreground md:text-3xl md:leading-relaxed">{{ currentQ.question }}</h2>
          <p v-if="!answerRevealed" class="mx-auto mt-5 max-w-xl text-sm leading-relaxed text-muted-foreground">先在脑中组织答案，想清楚“是什么、为什么、怎么做”，再翻开卡片。</p>

          <div v-if="!answerRevealed" class="mt-10 flex flex-col items-center gap-3">
            <Button data-testid="practice-show-answer" size="lg" class="gap-2 px-6" @click="answerRevealed = true"><Eye :size="17" />查看参考答案</Button>
            <span class="text-[11px] text-muted-foreground">Enter 查看答案 · ← → 切换题目</span>
          </div>

          <div v-else class="mt-10 text-left">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-2 text-sm font-semibold text-foreground"><BookOpen class="size-4 text-primary" />AI 参考答案</div>
              <div class="flex items-center gap-1">
                <Button variant="ghost" size="sm" class="h-8 px-2 text-xs" @click="startEditAnswer"><Pencil class="mr-1.5 size-3.5" />编辑</Button>
                <Button variant="ghost" size="sm" class="h-8 px-2 text-xs" :disabled="qState._isLoadingAnswer" @click="handleGenerate"><RefreshCw class="mr-1.5 size-3.5" :class="{ 'animate-spin': qState._isLoadingAnswer }" />重新生成</Button>
              </div>
            </div>

            <div v-if="qState._isEditingAnswer" class="flex flex-col gap-3">
              <textarea v-model="qState._editAnswer" rows="12" class="w-full resize-y rounded-lg border border-input bg-background p-3 text-sm leading-relaxed text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"></textarea>
              <div class="flex justify-end gap-2">
                <Button variant="outline" size="sm" @click="qState._isEditingAnswer = false">取消</Button>
                <Button size="sm" :disabled="qState._isSavingAnswer" @click="handleSaveAnswer">{{ qState._isSavingAnswer ? '保存中...' : '保存答案' }}</Button>
              </div>
            </div>
            <div v-else-if="currentQ.ai_answer && !isFailedAnswer(currentQ.ai_answer)" class="flashcard-answer rounded-xl border border-border/80 bg-muted/30 p-4 text-sm leading-7 text-foreground md:p-6" v-html="renderMarkdown(currentQ.ai_answer)"></div>
            <div v-else class="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
              <p class="text-sm text-muted-foreground">这道题还没有参考答案</p>
              <Button size="sm" class="mt-4 gap-1.5" :disabled="qState._isLoadingAnswer" @click="handleGenerate"><Sparkles class="size-4" />AI 生成答案</Button>
            </div>
          </div>
        </div>

        <div v-if="answerRevealed" class="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4">
          <div class="flex items-center gap-2">
            <Button variant="outline" size="sm" class="gap-1.5" @click="toggleSelfCheck"><Target class="size-3.5" />{{ showSelfCheck ? '收起自测' : '自测一下' }}</Button>
            <Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="toggleHistory"><History class="size-3.5" />练习记录<span v-if="questionAttemptCount(currentQ)" class="tabular-nums">({{ questionAttemptCount(currentQ) }})</span></Button>
          </div>
          <Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="answerRevealed = false"><RotateCcw class="size-3.5" />再想一遍</Button>
        </div>

        <div v-if="showSelfCheck" class="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4 md:p-5">
          <div class="mb-3 flex items-center gap-2"><Target class="size-4 text-primary" /><div><p class="text-sm font-semibold text-foreground">用自己的话复述</p><p class="mt-0.5 text-[11px] text-muted-foreground">不必写完整，先列出你记住的关键点</p></div></div>
          <textarea v-model="qState._userAnswer" class="min-h-28 w-full resize-y rounded-lg border border-input bg-background p-3 text-sm leading-relaxed text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20" placeholder="例如：先说结论，再补充原理、场景和注意事项..." @keydown="onTextareaKeydown"></textarea>
          <div class="mt-3 flex items-center gap-2"><Button size="sm" :disabled="qState._isEvaluating || !qState._userAnswer.trim()" @click="handleEvaluate"><Loader2 v-if="qState._isEvaluating" class="mr-1.5 size-3.5 animate-spin" />{{ qState._isEvaluating ? '评估中...' : '提交评估' }}</Button><span class="text-[11px] text-muted-foreground">Ctrl / ⌘ + Enter</span></div>
          <div v-if="qState._evaluation" class="mt-4 rounded-lg border border-border bg-card p-4"><div class="flex items-center gap-3"><span class="text-2xl font-bold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span><div class="min-w-0 flex-1"><div class="h-2 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full transition-all" :class="scoreColor(qState._evaluation.overall_score)" :style="{ width: `${qState._evaluation.overall_score}%` }"></div></div><p class="mt-1 text-[11px] text-muted-foreground">{{ evaluationSummary(qState._evaluation) }}</p></div></div></div>
        </div>

        <div v-if="showHistory" class="mt-4 rounded-xl border border-border bg-muted/30 p-4">
          <div class="mb-3 flex items-center justify-between"><p class="text-sm font-semibold text-foreground">练习记录</p><span v-if="qState._historyLoading" class="text-xs text-muted-foreground">加载中...</span></div>
          <div v-if="qState._history?.length" class="flex flex-col gap-2"><div v-for="(history, historyIndex) in qState._history" :key="history.id || historyIndex" class="rounded-lg border border-border bg-card p-3"><div class="flex items-center gap-2 text-xs"><span class="font-semibold" :class="scoreTextColor(history.score)">{{ history.score }} 分</span><span class="text-muted-foreground">{{ formatHistoryDate(history.created_at) }}</span></div><p class="mt-2 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{{ history.user_answer }}</p></div></div>
          <p v-else-if="!qState._historyLoading" class="py-3 text-center text-xs text-muted-foreground">暂无练习记录，先完成一次自测吧。</p>
        </div>

        <div v-if="currentQ.sources?.length" class="mt-5 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground"><Link2 class="size-3.5" /><span>出处：</span><button v-for="(source, sourceIndex) in currentQ.sources" :key="sourceIndex" type="button" class="rounded-md border border-border bg-card px-2 py-1 transition hover:border-primary/30 hover:text-primary" @click="emit('navigate-to-interview', { source, questionId: currentQ.id })">{{ source.company || '未知公司' }} · {{ source.round || '未知轮次' }}</button></div>
      </div>
    </Card>

    <div v-else class="mx-auto flex min-h-80 w-full max-w-xl flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center">
      <div class="flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground"><List :size="26" /></div>
      <h2 class="mt-5 text-lg font-semibold text-foreground">这个题单还没有题目</h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">先收藏几道题，或者切换到全部题库开始刷题。</p>
      <div class="mt-5 flex gap-2"><Button variant="outline" @click="selectSession('all')">查看全部题库</Button><Button @click="emit('close')">返回题库</Button></div>
    </div>

    <div v-if="currentQ" class="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3">
      <Button variant="outline" class="gap-2" :disabled="currentIndex === 0" @click="goPrev"><ChevronLeft class="size-4" />上一题<span class="hidden text-[11px] text-muted-foreground md:inline">←</span></Button>
      <div class="flex items-center gap-2"><Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="markAndNext(false)"><RotateCcw class="size-3.5" />再复习</Button><Button size="sm" class="gap-1.5" @click="markAndNext(true)"><Check class="size-3.5" />记住了</Button></div>
      <Button variant="outline" class="gap-2" @click="goNext">{{ isLastQuestion ? '完成一轮' : '下一题' }}<span class="hidden text-[11px] text-muted-foreground md:inline">→</span><ChevronRight class="size-4" /></Button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  Flame,
  History,
  Layers,
  Lightbulb,
  Link2,
  List,
  Loader2,
  Pencil,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Star,
  Target,
  X,
  Zap,
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useToast } from '@/composables/useNotification.js'
import {
  dimLabel,
  isFailedAnswer,
  renderMarkdown,
  scoreColor,
  scoreTextColor,
  resetQState,
  generateAnswerForQuestion,
  saveAnswerForQuestion,
  evaluateAnswerForQuestion,
  loadHistory,
} from '@/composables/usePractice.js'

const props = defineProps({
  questions: { type: Array, default: () => [] },
  startIndex: { type: Number, default: 0 },
  isAdmin: { type: Boolean, default: false },
  practicedQuestions: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'answer-evaluated', 'toggle-star', 'navigate-to-interview'])
const toast = useToast()
const sessionKey = ref('quick')
const deckQuery = ref('')
const currentIndex = ref(Math.max(0, props.startIndex))
const answerRevealed = ref(false)
const showSelfCheck = ref(false)
const showHistory = ref(false)
const rememberedIds = ref(new Set())
const qState = reactive({ _userAnswer: '', _evaluation: null, _isEvaluating: false, _isLoadingAnswer: false, _history: null, _historyLoading: false, _isEditingAnswer: false, _editAnswer: '', _isSavingAnswer: false })

function questionAttemptCount(question) {
  const info = props.practicedQuestions?.[question?.id] || {}
  return Number(question?.attempt_count || info.attempt_count || info.count || 0)
}

function questionTags(question) {
  if (Array.isArray(question?.tags)) return question.tags.filter(Boolean).map(String)
  return String(question?.tags || '').split(',').map(tag => tag.trim()).filter(Boolean)
}

const starredQuestions = computed(() => props.questions.filter(question => question.is_starred))
const unpracticedQuestions = computed(() => props.questions.filter(question => questionAttemptCount(question) === 0))
const quickQuestions = computed(() => [...props.questions].sort((a, b) => {
  const attemptDiff = questionAttemptCount(a) - questionAttemptCount(b)
  if (attemptDiff !== 0) return attemptDiff
  return Number(b.frequency || b.dyn_frequency || 0) - Number(a.frequency || a.dyn_frequency || 0)
}).slice(0, 10))
const recommendedSessions = computed(() => [
  { key: 'quick', label: '今日速成', description: `先刷 ${quickQuestions.value.length} 道高频题`, count: quickQuestions.value.length, icon: Zap, iconClass: 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400' },
  { key: 'starred', label: '收藏题', description: `${starredQuestions.value.length} 道收藏题`, count: starredQuestions.value.length, icon: Star, iconClass: 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400' },
  { key: 'unpracticed', label: '待复习', description: `${unpracticedQuestions.value.length} 道还没练过`, count: unpracticedQuestions.value.length, icon: Flame, iconClass: 'bg-rose-100 text-rose-600 dark:bg-rose-900/30 dark:text-rose-400' },
  { key: 'all', label: '全部题库', description: '按当前筛选结果刷题', count: props.questions.length, icon: Layers, iconClass: 'bg-primary/10 text-primary' },
])
const difficultySessions = computed(() => [
  { key: 'l1', label: 'L1 基础', count: props.questions.filter(question => String(question.difficulty || '').includes('L1')).length, dotClass: 'bg-emerald-500' },
  { key: 'l2', label: 'L2 进阶', count: props.questions.filter(question => String(question.difficulty || '').includes('L2')).length, dotClass: 'bg-amber-500' },
  { key: 'l3', label: 'L3 挑战', count: props.questions.filter(question => String(question.difficulty || '').includes('L3')).length, dotClass: 'bg-rose-500' },
])
const sessionSource = computed(() => {
  if (sessionKey.value === 'quick') return quickQuestions.value
  if (sessionKey.value === 'starred') return starredQuestions.value
  if (sessionKey.value === 'unpracticed') return unpracticedQuestions.value
  if (sessionKey.value === 'l1') return props.questions.filter(question => String(question.difficulty || '').includes('L1'))
  if (sessionKey.value === 'l2') return props.questions.filter(question => String(question.difficulty || '').includes('L2'))
  if (sessionKey.value === 'l3') return props.questions.filter(question => String(question.difficulty || '').includes('L3'))
  return props.questions
})
const sessionQuestions = computed(() => {
  const query = deckQuery.value.trim().toLowerCase()
  if (!query) return sessionSource.value
  return sessionSource.value.filter(question => [question.question, question.cat1, question.cat2, question.tags].some(value => String(value || '').toLowerCase().includes(query)))
})
const currentQ = computed(() => sessionQuestions.value[currentIndex.value] || null)
const selectedSession = computed(() => [...recommendedSessions.value, ...difficultySessions.value].find(item => item.key === sessionKey.value))
const isLastQuestion = computed(() => currentIndex.value >= sessionQuestions.value.length - 1)
const progressPercentage = computed(() => sessionQuestions.value.length ? Math.round(((currentIndex.value + 1) / sessionQuestions.value.length) * 100) : 0)

const difficultyClass = (difficulty) => {
  const value = String(difficulty || '')
  if (value.includes('L3')) return 'border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-400'
  if (value.includes('L2')) return 'border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400'
  return 'border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-400'
}

function resetState() { resetQState(qState); answerRevealed.value = false; showSelfCheck.value = false; showHistory.value = false }
function selectSession(key) {
  const option = [...recommendedSessions.value, ...difficultySessions.value].find(item => item.key === key)
  if (!option?.count) { toast.warning('这个题单还没有题目'); return }
  sessionKey.value = key
  currentIndex.value = 0
  deckQuery.value = ''
  resetState()
}
function goPrev() { if (currentIndex.value > 0) { currentIndex.value -= 1; resetState() } }
function goNext() {
  if (!sessionQuestions.value.length) return
  if (isLastQuestion.value) { currentIndex.value = 0; resetState(); toast.info('这一轮完成了，已回到第 1 题'); return }
  currentIndex.value += 1
  resetState()
}
function markAndNext(remembered) { if (currentQ.value?.id && remembered) rememberedIds.value = new Set([...rememberedIds.value, currentQ.value.id]); goNext() }
function toggleStar() { if (currentQ.value) emit('toggle-star', currentQ.value) }
function toggleSelfCheck() { showSelfCheck.value = !showSelfCheck.value; if (!showSelfCheck.value) { qState._evaluation = null; qState._userAnswer = '' } }
async function toggleHistory() { showHistory.value = !showHistory.value; if (showHistory.value && !qState._history && currentQ.value) await loadHistory(currentQ.value.id, qState) }
function startEditAnswer() { qState._isEditingAnswer = true; qState._editAnswer = currentQ.value?.ai_answer || '' }
async function handleGenerate() { if (currentQ.value) await generateAnswerForQuestion(currentQ.value, qState) }
async function handleSaveAnswer() { if (currentQ.value) await saveAnswerForQuestion(currentQ.value, qState) }
async function handleEvaluate() { if (!currentQ.value) return; const result = await evaluateAnswerForQuestion(currentQ.value, qState); if (result) emit('answer-evaluated', { questionId: currentQ.value.id, score: result.overall_score }) }
function evaluationSummary(evaluation) { return Object.entries(evaluation?.dimensions || {}).map(([key, value]) => `${dimLabel[key] || key} ${value.score}`).join(' · ') || '已完成一次自测' }
function formatHistoryDate(date) { return date ? String(date).slice(0, 16).replace('T', ' ') : '刚刚' }
function onTextareaKeydown(event) { if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') { event.preventDefault(); handleEvaluate() } }
function onGlobalKeydown(event) {
  if (event.key === 'Escape') { emit('close'); return }
  const target = event.target
  if (target instanceof HTMLElement && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
  if (event.key === 'ArrowLeft') { event.preventDefault(); goPrev() }
  else if (event.key === 'ArrowRight') { event.preventDefault(); goNext() }
  else if (event.key === 'Enter' && currentQ.value && !answerRevealed.value) { event.preventDefault(); answerRevealed.value = true }
}

watch(sessionQuestions, (questions) => { if (currentIndex.value >= questions.length) currentIndex.value = Math.max(0, questions.length - 1) })
watch(() => props.startIndex, (index) => { currentIndex.value = Math.min(Math.max(0, index), Math.max(0, sessionQuestions.value.length - 1)) })
onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))
</script>

<style scoped>
.question-content-enter { animation: question-enter 0.25s ease both; }
.flashcard-answer :deep(h1), .flashcard-answer :deep(h2), .flashcard-answer :deep(h3) { margin-top: 1.25rem; margin-bottom: 0.55rem; font-weight: 650; line-height: 1.5; }
.flashcard-answer :deep(h1:first-child), .flashcard-answer :deep(h2:first-child), .flashcard-answer :deep(h3:first-child) { margin-top: 0; }
.flashcard-answer :deep(p) { margin: 0.6rem 0; }
.flashcard-answer :deep(ul), .flashcard-answer :deep(ol) { margin: 0.6rem 0; padding-left: 1.4rem; }
.flashcard-answer :deep(li) { margin: 0.25rem 0; }
.flashcard-answer :deep(code) { border-radius: 0.35rem; background: hsl(var(--muted)); padding: 0.1rem 0.3rem; font-size: 0.9em; }
@keyframes question-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
