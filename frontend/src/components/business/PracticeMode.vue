<template>
  <div data-testid="practice-workspace" class="relative flex h-full min-h-0 w-full overflow-hidden bg-background">
    <!-- Mobile sidebar overlay -->
    <div v-if="mobileSidebarOpen" class="fixed inset-0 z-40 bg-black/40 md:hidden" @click="mobileSidebarOpen = false" />

    <aside
      data-testid="practice-queue-sidebar"
      class="sidebar-container z-30 shrink-0 flex-col overflow-hidden border-r border-border bg-background md:flex md:z-auto"
      :class="[
        queueCollapsed ? 'sidebar-collapsed' : '',
        mobileSidebarOpen ? 'fixed inset-y-0 left-0 z-50 flex w-64 md:relative md:w-auto' : 'hidden md:flex',
      ]"
      :style="{ width: queueCollapsed ? '0px' : '16rem' }"
    >
      <div class="flex shrink-0 items-center gap-2 p-2 sidebar-content">
        <div class="relative min-w-0 flex-1">
          <Search class="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <input v-model="deckQuery" type="search" class="h-8 w-full rounded-md border border-input bg-background pl-8 pr-2 text-xs text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring/20" placeholder="搜索当前题单" />
        </div>
        <AppTooltip text="收起题单侧栏" side="right">
          <Button variant="ghost" size="icon" class="size-7 shrink-0 text-muted-foreground" aria-label="收起题单侧栏" @click="queueCollapsed = true">
            <PanelLeftClose :size="14" />
          </Button>
        </AppTooltip>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2 custom-scrollbar sidebar-content">
        <button
          v-for="(question, questionIndex) in sessionQuestions"
          :key="question.id"
          type="button"
          class="group mb-1 flex w-full items-start gap-2 rounded-md p-2 text-left transition-colors"
          :class="questionIndex === currentIndex ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
          @click="currentIndex = questionIndex; resetState(); mobileSidebarOpen = false"
        >
          <span class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-[10px] tabular-nums" :class="questionIndex === currentIndex ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'">{{ questionIndex + 1 }}</span>
          <span class="min-w-0 flex-1">
            <span class="line-clamp-2 text-xs leading-5">{{ question.question }}</span>
            <span v-if="question.has_been_practiced" class="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground"><Check class="size-3" />熟练度 {{ question.proficiency || 0 }}/5</span>
          </span>
        </button>
        <p v-if="!sessionQuestions.length" class="px-2 py-8 text-center text-xs leading-5 text-muted-foreground">这个题单还没有可复习的题</p>
      </div>
    </aside>

    <div v-if="queueCollapsed" class="hidden shrink-0 flex-col items-center gap-1 px-2 py-2 sidebar-expand-buttons md:flex">
      <AppTooltip text="展开题单侧栏" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="展开题单侧栏" @click="queueCollapsed = false">
          <PanelLeft :size="14" />
        </Button>
      </AppTooltip>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <main data-testid="practice-main" class="min-h-0 flex-1 overflow-hidden">
        <div class="mx-auto flex h-full min-h-0 w-full max-w-4xl flex-col gap-3 overflow-hidden px-4 py-4 md:px-6 md:py-5">

    <Card v-if="currentQ" data-testid="practice-card" class="practice-card mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl p-0 shadow-sm">
      <div data-testid="practice-focus-card" class="contents">
      <div class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-6">
        <div class="flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
          <Button variant="ghost" size="icon" class="size-7 md:hidden" aria-label="展开题目列表" @click="mobileSidebarOpen = true">
            <PanelLeft :size="14" />
          </Button>
          <span class="font-semibold text-foreground">第 {{ currentIndex + 1 }} 题</span>
          <span>·</span>
          <span>高频 {{ currentQ.frequency || 0 }} 次</span>
          <span v-if="questionAttemptCount(currentQ)" class="hidden items-center gap-1 sm:inline-flex"><History class="size-3.5" />已练习 {{ questionAttemptCount(currentQ) }} 次</span>
          <span v-if="currentQ.has_been_practiced" class="hidden items-center gap-1 sm:inline-flex"><Target class="size-3.5" />熟练度 {{ currentQ.proficiency || 0 }}/5</span>
        </div>
        <div class="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
          <Button v-if="currentQ" data-testid="practice-add-to-deck" variant="ghost" size="sm" class="h-8 gap-1.5 px-2 text-xs text-muted-foreground" @click="openDeckPicker"><Plus class="size-3.5" />加入题单</Button>
          <AppTooltip v-if="currentQ" :text="currentQ.is_starred ? '取消收藏' : '收藏题目'">
            <Button variant="ghost" size="icon" class="text-muted-foreground hover:text-amber-500" :aria-label="currentQ.is_starred ? '取消收藏' : '收藏题目'" @click="toggleStar"><Star :size="17" :fill="currentQ.is_starred ? 'currentColor' : 'none'" /><span class="sr-only">{{ currentQ.is_starred ? '取消收藏' : '收藏' }}</span></Button>
          </AppTooltip>
          <Badge v-if="currentQ.difficulty" variant="outline" class="text-[10px]" :class="difficultyClass(currentQ.difficulty)">{{ currentQ.difficulty }}</Badge>
          <Badge variant="outline" class="max-w-32 truncate text-[10px]">{{ currentQ.cat1 || '未分类' }}</Badge>
        </div>
      </div>

      <div data-testid="practice-card-content" :key="currentQ.id" class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5 custom-scrollbar question-content-enter sm:px-6 md:px-12 md:py-7">
        <div class="flex flex-wrap items-center gap-1.5">
          <Badge v-for="tag in questionTags(currentQ).slice(0, 4)" :key="tag" variant="secondary" class="text-[10px]">{{ tag }}</Badge>
        </div>

        <div class="mx-auto flex min-h-0 w-full max-w-3xl flex-col py-6 text-center md:py-8" :class="answerRevealed ? 'flex-none justify-start' : 'flex-1 justify-center'">
          <h2 class="practice-question font-semibold leading-relaxed tracking-tight text-foreground">{{ currentQ.question }}</h2>

          <div v-if="!answerRevealed" class="mt-10 flex flex-col items-center gap-3">
            <Button data-testid="practice-show-answer" size="lg" class="gap-2 px-6" @click="answerRevealed = true"><Eye :size="17" />查看参考答案</Button>
            <span class="text-[11px] text-muted-foreground">Enter 查看答案 · ← → 切换题目</span>
          </div>

          <div v-else class="mt-10 text-left">
            <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-2 text-sm font-semibold text-foreground"><BookOpen class="size-4 text-primary" />AI 参考答案</div>
              <div class="flex items-center gap-1">
                <Button v-if="isAdmin" variant="ghost" size="sm" class="h-8 px-2 text-xs" @click="startEditAnswer"><Pencil class="mr-1.5 size-3.5" />编辑</Button>
                <Button v-if="isAdmin" variant="ghost" size="sm" class="h-8 px-2 text-xs" :disabled="qState._isLoadingAnswer" @click="handleGenerate"><RefreshCw class="mr-1.5 size-3.5" :class="{ 'animate-spin': qState._isLoadingAnswer }" />重新生成</Button>
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
              <p v-if="isAdmin" class="text-sm text-muted-foreground">这道题还没有参考答案</p>
              <p v-else class="text-sm text-muted-foreground">这道题还没有参考答案，请等待管理员生成</p>
              <Button v-if="isAdmin" size="sm" class="mt-4 gap-1.5" :disabled="qState._isLoadingAnswer" @click="handleGenerate"><Sparkles class="size-4" />AI 生成答案</Button>
            </div>

            <!-- 背诵稿（普通用户）：基于公共参考答案结合个人背景定制 -->
            <div v-if="!isAdmin && currentQ.ai_answer && !isFailedAnswer(currentQ.ai_answer)" class="mt-6 rounded-xl border border-border/80 bg-muted/30 p-4 md:p-5">
              <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div class="flex items-center gap-2 text-sm font-semibold text-foreground"><BookOpen class="size-4 text-primary" />我的背诵稿</div>
                <div v-if="qState._recitation" class="flex items-center gap-1">
                  <Button variant="ghost" size="sm" class="h-8 px-2 text-xs" @click="startEditRecitation"><Pencil class="mr-1.5 size-3.5" />编辑</Button>
                  <Button variant="ghost" size="sm" class="h-8 px-2 text-xs" :disabled="qState._isGeneratingRecitation" @click="handleGenerateRecitation"><RefreshCw class="mr-1.5 size-3.5" :class="{ 'animate-spin': qState._isGeneratingRecitation }" />重新生成</Button>
                </div>
              </div>

              <div v-if="qState._isEditingRecitation" class="flex flex-col gap-3">
                <textarea v-model="qState._editRecitation" rows="10" class="w-full resize-y rounded-lg border border-input bg-background p-3 text-sm leading-relaxed text-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"></textarea>
                <div class="flex justify-end gap-2">
                  <Button variant="outline" size="sm" @click="qState._isEditingRecitation = false">取消</Button>
                  <Button size="sm" :disabled="qState._isSavingRecitation" @click="handleSaveRecitation">{{ qState._isSavingRecitation ? '保存中...' : '保存背诵稿' }}</Button>
                </div>
              </div>
              <div v-else-if="qState._recitation" class="recitation-content text-sm leading-7 text-foreground" v-html="renderMarkdown(qState._recitation)"></div>
              <div v-else-if="qState._isGeneratingRecitation" class="flex flex-col items-center gap-2 py-4 text-primary">
                <Loader2 class="size-5 animate-spin" />
                <span class="text-xs">正在结合你的岗位/简历定制背诵稿...</span>
              </div>
              <Button v-else size="sm" class="gap-1.5" :disabled="qState._isGeneratingRecitation" @click="handleGenerateRecitation"><Sparkles class="size-4" />AI 定制我的背诵稿</Button>
            </div>
          </div>
        </div>

        <div v-if="answerRevealed" data-testid="practice-review-actions" class="mt-6 border-t border-border pt-5">
          <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p class="text-sm font-semibold text-foreground">记得怎么样？</p>
              <p class="mt-1 text-[11px] text-muted-foreground">先判断记忆程度，再进入下一题</p>
            </div>
            <div class="grid grid-cols-2 gap-2 sm:flex">
              <Button data-testid="practice-review-again" variant="outline" size="sm" class="gap-1.5" :disabled="reviewLoading" @click="markAndNext('again')"><RotateCcw class="size-3.5" />再复习 <span class="hidden text-[10px] text-muted-foreground md:inline">29 分钟</span></Button>
              <Button data-testid="practice-review-hard" variant="outline" size="sm" class="gap-1.5" :disabled="reviewLoading" @click="markAndNext('hard')"><Target class="size-3.5" />有点模糊 <span class="hidden text-[10px] text-muted-foreground md:inline">保守</span></Button>
              <Button data-testid="practice-review-good" size="sm" class="gap-1.5" :disabled="reviewLoading" @click="markAndNext('good')"><Check class="size-3.5" />记得了 <span class="hidden text-[10px] opacity-70 md:inline">继续</span></Button>
              <Button data-testid="practice-review-easy" variant="secondary" size="sm" class="gap-1.5" :disabled="reviewLoading" @click="markAndNext('easy')"><Zap class="size-3.5" />很熟 <span class="hidden text-[10px] text-muted-foreground md:inline">拉长</span></Button>
            </div>
          </div>
          <div class="mt-4 flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
            <Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="toggleSelfCheck"><Target class="size-3.5" />{{ showSelfCheck ? '收起自测' : '自测一下' }}</Button>
            <Button variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="toggleHistory"><History class="size-3.5" />练习记录<span v-if="questionAttemptCount(currentQ)" class="tabular-nums">({{ questionAttemptCount(currentQ) }})</span></Button>
            <Button variant="ghost" size="sm" class="ml-auto gap-1.5 text-muted-foreground" @click="answerRevealed = false"><RotateCcw class="size-3.5" />再想一遍</Button>
          </div>
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
      </div>
    </Card>

    <div v-else class="mx-auto flex min-h-0 w-full max-w-xl flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center">
      <div class="flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground"><List :size="26" /></div>
      <h2 class="mt-5 text-lg font-semibold text-foreground">{{ sessionKey === 'due' ? '今日复习已经完成' : '这个题单还没有题目' }}</h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">{{ sessionKey === 'due' ? '明天再来看看新的到期复习题，或者切换到全部题继续刷。' : '先收藏几道题，或者切换到全部题开始刷题。' }}</p>
      <div class="mt-5 flex gap-2"><Button variant="outline" @click="selectSession('all')">切换到全部题</Button></div>
    </div>

    <div v-if="currentQ" class="mx-auto flex shrink-0 w-full flex-wrap items-center justify-between gap-3 px-1">
      <Button variant="outline" class="gap-2" :disabled="currentIndex === 0" @click="goPrev"><ChevronLeft class="size-4" />上一题</Button>
      <span class="text-xs tabular-nums text-muted-foreground">{{ currentIndex + 1 }} / {{ sessionQuestions.length }}</span>
      <Button variant="outline" class="gap-2" @click="goNext">{{ isLastQuestion ? '完成一轮' : '下一题' }}<ChevronRight class="size-4" /></Button>
    </div>
        </div>
      </main>
    </div>
  </div>

  <AppDialog
    :open="showDeckPicker"
    title="加入题单"
    description="把当前这道题加入你的自定义题单，刷题记录会在所有题单之间共享。"
    size="sm"
    @update:open="showDeckPicker = $event"
  >
    <div class="px-6 pb-2">
      <template v-if="customDecks.length">
        <label class="mb-1.5 block text-xs font-semibold text-muted-foreground">选择题单</label>
        <select v-model="addDeckKey" class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none focus:border-ring focus:ring-1 focus:ring-ring/20">
          <option v-for="deck in customDecks" :key="deck.key" :value="deck.key">{{ deck.name }}</option>
        </select>
      </template>
      <div v-else class="rounded-lg border border-dashed border-border px-4 py-5 text-center">
        <p class="text-sm text-muted-foreground">还没有自定义题单</p>
        <Button variant="link" size="sm" class="mt-2" @click="showDeckPicker = false; emit('manage-decks')">先创建一个题单</Button>
      </div>
    </div>
    <template #footer>
      <div class="flex justify-end gap-2">
        <Button variant="outline" @click="showDeckPicker = false">取消</Button>
        <Button :disabled="!addDeckKey || !customDecks.length" @click="addCurrentToDeck">加入题单</Button>
      </div>
    </template>
  </AppDialog>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  BookOpen,
  Check,
  ChevronLeft,
  ChevronRight,
  Eye,
  History,
  Layers,
  Link2,
  List,
  Loader2,
  PanelLeft,
  PanelLeftClose,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Star,
  Target,
  Zap,
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import AppDialog from '@/components/common/AppDialog.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'
import { useToast } from '@/composables/useNotification.js'
import {
  dimLabel,
  isFailedAnswer,
  renderMarkdown,
  scoreColor,
  scoreTextColor,
  resetQState,
  generateAnswerForQuestion,
  generateRecitationForQuestion,
  saveRecitationForQuestion,
  saveAnswerForQuestion,
  evaluateAnswerForQuestion,
  loadHistory,
} from '@/composables/usePractice.js'

const props = defineProps({
  questions: { type: Array, default: () => [] },
  decks: { type: Array, default: () => [] },
  selectedDeckKey: { type: String, default: '' },
  reviewLoading: { type: Boolean, default: false },
  deckLoading: { type: Boolean, default: false },
  startIndex: { type: Number, default: 0 },
  isAdmin: { type: Boolean, default: false },
  practicedQuestions: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'answer-evaluated', 'toggle-star', 'navigate-to-interview', 'select-deck', 'review', 'add-to-deck', 'manage-decks'])
const toast = useToast()
const sessionKey = ref(props.selectedDeckKey || 'all')
const deckQuery = ref('')
const queueCollapsed = ref(false)
const mobileSidebarOpen = ref(false)
const currentIndex = ref(Math.max(0, props.startIndex))
const answerRevealed = ref(false)
const showSelfCheck = ref(false)
const showHistory = ref(false)
const rememberedIds = ref(new Set())
const showDeckPicker = ref(false)
const addDeckKey = ref('')
const qState = reactive({ _userAnswer: '', _evaluation: null, _isEvaluating: false, _isLoadingAnswer: false, _history: null, _historyLoading: false, _isEditingAnswer: false, _editAnswer: '', _isSavingAnswer: false, _recitation: '', _isGeneratingRecitation: false, _isEditingRecitation: false, _editRecitation: '', _isSavingRecitation: false })

function questionAttemptCount(question) {
  const info = props.practicedQuestions?.[question?.id] || {}
  return Number(question?.review_count || question?.attempt_count || info.attempt_count || info.count || 0)
}

function questionTags(question) {
  if (Array.isArray(question?.tags)) return question.tags.filter(Boolean).map(String)
  return String(question?.tags || '').split(',').map(tag => tag.trim()).filter(Boolean)
}

const starredQuestions = computed(() => props.questions.filter(question => question.is_starred))
const recommendedSessions = computed(() => [
  { key: 'starred', label: '收藏题', description: `${starredQuestions.value.length} 道收藏题`, count: starredQuestions.value.length, icon: Star, iconClass: 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400' },
  { key: 'all', label: '全部题', description: '按复习状态和频率刷题', count: props.questions.length, icon: Layers, iconClass: 'bg-primary/10 text-primary' },
])
const sessionIcons = { starred: Star, all: Layers }
const sessionIconClasses = {
  starred: 'bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
  all: 'bg-primary/10 text-primary',
}
const serverSessions = computed(() => props.decks.map(deck => ({
  key: deck.key,
  label: deck.name,
  description: `${deck.reviewed || 0}/${deck.total || 0} 已建立记忆`,
  count: Number(deck.total || 0),
  icon: sessionIcons[deck.key] || Layers,
  iconClass: sessionIconClasses[deck.key] || 'bg-primary/10 text-primary',
  progress: deck.progress || 0,
})))
const serverDeckMode = computed(() => props.decks.length > 0)
const sessionOptions = computed(() => serverDeckMode.value ? serverSessions.value : recommendedSessions.value)
const customDecks = computed(() => props.decks.filter(deck => deck.kind === 'custom'))
const sessionSource = computed(() => {
  if (serverDeckMode.value) return props.deckLoading ? [] : props.questions
  if (sessionKey.value === 'starred') return starredQuestions.value
  return props.questions
})
const sessionQuestions = computed(() => {
  const query = deckQuery.value.trim().toLowerCase()
  if (!query) return sessionSource.value
  return sessionSource.value.filter(question => [question.question, question.cat1, question.cat2, question.tags].some(value => String(value || '').toLowerCase().includes(query)))
})
const currentQ = computed(() => sessionQuestions.value[currentIndex.value] || null)
const isLastQuestion = computed(() => currentIndex.value >= sessionQuestions.value.length - 1)

const difficultyClass = (difficulty) => {
  const value = String(difficulty || '')
  if (value.includes('L3')) return 'border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-400'
  if (value.includes('L2')) return 'border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400'
  return 'border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-400'
}

function resetState() { resetQState(qState); qState._recitation = currentQ.value?.user_answer || ''; answerRevealed.value = false; showSelfCheck.value = false; showHistory.value = false }
function selectSession(key) {
  const option = sessionOptions.value.find(item => item.key === key)
  if (!option?.count) { toast.warning('这个题单还没有题目'); return }
  sessionKey.value = key
  currentIndex.value = 0
  deckQuery.value = ''
  resetState()
  if (serverDeckMode.value) emit('select-deck', key)
}
function goPrev() { if (currentIndex.value > 0) { currentIndex.value -= 1; resetState() } }
function goNext() {
  if (!sessionQuestions.value.length) return
  if (isLastQuestion.value) { currentIndex.value = 0; resetState(); toast.info('这一轮完成了，已回到第 1 题'); return }
  currentIndex.value += 1
  resetState()
}
function markAndNext(rating) {
  if (!currentQ.value?.id) return
  if (rating === 'good' || rating === 'easy') rememberedIds.value = new Set([...rememberedIds.value, currentQ.value.id])
  if (serverDeckMode.value) emit('review', { questionId: currentQ.value.id, rating })
  goNext()
}
function toggleStar() { if (currentQ.value) emit('toggle-star', currentQ.value) }
function openDeckPicker() {
  addDeckKey.value = customDecks.value[0]?.key || ''
  showDeckPicker.value = true
}
function addCurrentToDeck() {
  if (!currentQ.value?.id || !addDeckKey.value) return
  emit('add-to-deck', { deckKey: addDeckKey.value, questionId: currentQ.value.id })
  showDeckPicker.value = false
}
function toggleSelfCheck() { showSelfCheck.value = !showSelfCheck.value; if (!showSelfCheck.value) { qState._evaluation = null; qState._userAnswer = '' } }
async function toggleHistory() { showHistory.value = !showHistory.value; if (showHistory.value && !qState._history && currentQ.value) await loadHistory(currentQ.value.id, qState) }
function startEditAnswer() { qState._isEditingAnswer = true; qState._editAnswer = currentQ.value?.ai_answer || '' }
async function handleGenerate() { if (currentQ.value) await generateAnswerForQuestion(currentQ.value, qState) }
async function handleSaveAnswer() { if (currentQ.value) await saveAnswerForQuestion(currentQ.value, qState) }
function startEditRecitation() { qState._isEditingRecitation = true; qState._editRecitation = qState._recitation }
async function handleGenerateRecitation() { if (currentQ.value) await generateRecitationForQuestion(currentQ.value, qState) }
async function handleSaveRecitation() { if (currentQ.value) await saveRecitationForQuestion(currentQ.value, qState) }
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

watch(sessionQuestions, (questions) => {
  // 复习移除题卡导致队列缩短时，按当前题目 id 重新定位，避免跳过下一题
  const currentId = currentQ.value?.id
  if (currentId) {
    const idx = questions.findIndex(q => q.id === currentId)
    if (idx !== -1) {
      currentIndex.value = idx
      return
    }
  }
  if (currentIndex.value >= questions.length) currentIndex.value = Math.max(0, questions.length - 1)
})
watch(() => props.startIndex, (index) => { currentIndex.value = Math.min(Math.max(0, index), Math.max(0, sessionQuestions.value.length - 1)) })
watch(() => props.selectedDeckKey, (key) => { if (key) { sessionKey.value = key; currentIndex.value = 0; resetState() } })
onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))
</script>

<style scoped>
.sidebar-container {
  transition: width 380ms cubic-bezier(0.4, 0, 0.2, 1);
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
  to { opacity: 1; transform: translateX(0); }
}

.practice-card { container-type: size; }
.practice-question { font-size: clamp(1.125rem, min(2.5cqw, 4cqh), 1.75rem); }
.question-content-enter { animation: question-enter 0.25s ease both; }
.flashcard-answer :deep(h1), .flashcard-answer :deep(h2), .flashcard-answer :deep(h3) { margin-top: 1.25rem; margin-bottom: 0.55rem; font-weight: 650; line-height: 1.5; }
.flashcard-answer :deep(h1:first-child), .flashcard-answer :deep(h2:first-child), .flashcard-answer :deep(h3:first-child) { margin-top: 0; }
.flashcard-answer :deep(p) { margin: 0.6rem 0; }
.flashcard-answer :deep(ul), .flashcard-answer :deep(ol) { margin: 0.6rem 0; padding-left: 1.4rem; }
.flashcard-answer :deep(li) { margin: 0.25rem 0; }
.flashcard-answer :deep(code) { border-radius: 0.35rem; background: hsl(var(--muted)); padding: 0.1rem 0.3rem; font-size: 0.9em; }
@keyframes question-enter { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
