<template>
  <div class="relative flex h-full min-h-0 overflow-hidden bg-background">
    <div
      v-if="!sidebarCollapsed"
      class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden"
      @click="sidebarCollapsed = true"
    />

    <!-- 题目列表侧栏：交互与 ChatView 的会话侧栏保持一致 -->
    <section
      class="problem-list-panel sidebar-container z-30 flex shrink-0 flex-col overflow-hidden border-r border-border bg-background md:z-auto"
      :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      :style="{ width: sidebarCollapsed ? '0px' : '16rem' }"
    >
      <div class="flex shrink-0 items-center gap-2 p-2 sidebar-content">
        <div class="relative min-w-0 flex-1">
          <Search :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input v-model="searchQuery" class="h-8 rounded-lg border-0 bg-muted pl-8 text-xs shadow-none" placeholder="搜索当前题单" @keyup.enter="refreshProblems" />
        </div>
        <Button size="sm" variant="outline" class="h-8 shrink-0 gap-1.5 rounded-lg px-2.5 text-xs" @click="importDialogOpen = true">
          <Sparkles :size="13" /> <span class="hidden xl:inline">AI 导入</span>
        </Button>
        <AppTooltip text="收起题目列表" side="right">
          <Button variant="ghost" size="sm" class="h-10 shrink-0 gap-1.5 px-2 text-muted-foreground md:size-7 md:px-0" aria-label="收起题目列表" @click="sidebarCollapsed = true">
            <PanelLeftClose :size="14" />
            <span class="text-xs md:hidden">收起</span>
          </Button>
        </AppTooltip>
      </div>

      <div class="min-h-0 flex-1 overflow-y-auto p-2 custom-scrollbar sidebar-content">
        <div v-if="!problems.length && !isLoading" class="px-3 py-10 text-center text-xs text-muted-foreground">
          当前题单暂无题目
        </div>
        <div
          v-for="(problem, index) in problems"
          :key="problem.id"
          role="button"
          tabindex="0"
          class="group relative flex w-full items-start gap-2 rounded-lg p-2.5 text-left transition-colors"
          :class="activeProblem?.id === problem.id ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'"
          @click="selectProblem(problem)"
          @keydown.enter="selectProblem(problem)"
        >
          <span class="mt-0.5 w-6 shrink-0 text-right font-mono text-[11px] text-muted-foreground">{{ index + 1 }}</span>
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm" :class="activeProblem?.id === problem.id ? 'font-medium' : ''">{{ problem.title }}</span>
            <span class="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span>{{ difficultyLabel(problem.difficulty) }}</span>
              <span v-if="problem.attempt_count">· {{ problem.attempt_count }} 次</span>
              <span v-if="problem.is_solved" class="text-emerald-600 dark:text-emerald-400">· 已通过</span>
            </span>
          </span>
          <Star v-if="problem.is_favorite" :size="14" :stroke-width="1.8" class="mt-0.5 shrink-0 fill-amber-400 text-amber-500" />
          <div v-if="canManageProblems" class="relative shrink-0">
            <AppTooltip text="管理题目">
              <button
                type="button"
                class="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground opacity-100 transition hover:bg-muted hover:text-foreground md:size-7 md:opacity-0 md:group-hover:opacity-100 md:focus:opacity-100"
                :class="openProblemMenuId === problem.id ? 'bg-muted opacity-100' : ''"
                :aria-label="`管理题目 ${problem.title}`"
                @click.stop="toggleProblemMenu(problem.id)"
              >
                <Ellipsis class="size-4" />
              </button>
            </AppTooltip>
            <div v-if="openProblemMenuId === problem.id" class="absolute right-0 top-8 z-30 min-w-36 rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg">
              <button type="button" class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-destructive hover:bg-destructive/10" @click.stop="removeProblemFromCurrentList(problem)">
                <Trash2 class="size-3.5" />{{ selectedListKey === 'favorites' ? '取消收藏' : '移出当前题单' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div v-if="sidebarCollapsed" class="hidden shrink-0 flex-col items-center gap-1 px-2 py-2 sidebar-expand-buttons md:flex">
      <AppTooltip text="展开题目列表" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="展开题目列表" @click="sidebarCollapsed = false">
          <PanelLeft :size="14" />
        </Button>
      </AppTooltip>
    </div>

    <div class="flex min-h-0 flex-1">
      <!-- Current problem opens on the right; on mobile it replaces the list -->
      <section class="problem-detail-panel flex min-w-0 flex-1 flex-col" :class="{ 'is-detail-open': activeProblem }">
        <template v-if="activeProblem">
          <div class="flex min-h-12 shrink-0 flex-wrap items-center gap-1.5 px-2 py-1.5 sm:gap-2 sm:px-3 md:h-11 md:min-h-11 md:flex-nowrap md:py-0">
            <Button variant="ghost" size="sm" class="h-10 gap-1 px-2 text-xs text-muted-foreground md:hidden" @click="activeProblem = null; sidebarCollapsed = false"><ArrowLeft :size="13" /> 题目列表</Button>
            <div class="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{{ activeProblem.title }}</div>
            <AppTooltip :text="activeProblem.is_favorite ? '取消收藏' : '收藏题目'">
              <button :aria-label="activeProblem.is_favorite ? '取消收藏' : '收藏题目'" class="inline-flex h-10 shrink-0 items-center justify-center gap-1.5 rounded-md px-2 text-xs transition-colors hover:bg-muted md:size-7 md:px-0" :class="activeProblem.is_favorite ? 'text-amber-500' : 'text-muted-foreground'" @click="toggleFavorite(activeProblem)">
                <Star :size="16" :stroke-width="1.8" :fill="activeProblem.is_favorite ? 'currentColor' : 'none'" />
                <span class="md:sr-only">{{ activeProblem.is_favorite ? '取消收藏' : '收藏' }}</span>
              </button>
            </AppTooltip>
            <Button variant="ghost" size="sm" class="h-10 gap-1 px-2 text-xs text-muted-foreground md:h-7" @click="openAddToPlaylist"><ListPlus :size="13" /> 加入题单</Button>
            <Button variant="ghost" size="sm" class="h-10 gap-1 px-2 text-xs text-muted-foreground md:h-7" @click="selectNextProblem">下一题 <ChevronRight :size="13" /></Button>
          </div>

          <div class="grid shrink-0 grid-cols-2 gap-1 border-y border-border px-2 py-1.5 md:hidden">
            <Button size="sm" :variant="mobilePane === 'problem' ? 'secondary' : 'ghost'" class="h-10 gap-1.5 text-xs" @click="mobilePane = 'problem'"><BookOpen :size="14" />题目与评审</Button>
            <Button size="sm" :variant="mobilePane === 'code' ? 'secondary' : 'ghost'" class="h-10 gap-1.5 text-xs" @click="mobilePane = 'code'"><Code2 :size="14" />代码编辑器</Button>
          </div>

          <div class="flex min-h-0 flex-1 flex-row">
            <!-- Problem statement -->
            <section class="min-h-0 min-w-0 flex-1 flex-col overflow-hidden border-r border-border md:flex-[0_0_44%]" :class="mobilePane === 'problem' ? 'flex' : 'hidden md:flex'">
              <div class="flex shrink-0 items-center gap-1 px-4">
                <button class="rounded-md px-2.5 py-2 text-xs font-medium transition-colors" :class="contentTab === 'description' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'" @click="contentTab = 'description'">题目描述</button>
                <button class="rounded-md px-2.5 py-2 text-xs font-medium transition-colors" :class="contentTab === 'review' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'" @click="contentTab = 'review'">AI 评审<span v-if="activeProblem._feedback || activeProblem._scores" class="ml-1 text-primary">•</span></button>
                <button v-if="activeProblem._referenceAnswer" class="rounded-md px-2.5 py-2 text-xs font-medium transition-colors" :class="contentTab === 'answer' ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'" @click="contentTab = 'answer'">参考答案</button>
              </div>
              <div class="min-h-0 flex-1 overflow-y-auto px-5 py-5 custom-scrollbar">
                <div v-if="contentTab === 'description'" class="tab-content">
                  <div class="mb-4 flex flex-wrap items-center gap-2">
                    <span class="rounded bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">{{ activeProblem.source_type === 'imported' ? '我的题目' : '高频手撕' }}</span>
                    <span class="rounded px-2 py-0.5 text-xs font-medium" :class="difficultyClass(activeProblem.difficulty)">{{ difficultyLabel(activeProblem.difficulty) }}</span>
                    <span v-if="activeProblem.is_solved" class="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">已通过</span>
                  </div>
                  <h1 class="mb-4 text-xl font-bold leading-snug text-foreground">{{ activeProblem.title }}</h1>
                  <div class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem.description)" />
                  <div v-if="activeProblem.tags?.length" class="mt-6 flex flex-wrap gap-1.5 pt-4">
                    <span v-for="tag in activeProblem.tags" :key="tag" class="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">{{ tag }}</span>
                  </div>
                  <div class="mt-5 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span v-if="activeProblem.attempt_count">已练习 {{ activeProblem.attempt_count }} 次</span>
                    <span v-if="activeProblem.expected_complexity">复杂度 {{ activeProblem.expected_complexity }}</span>
                  </div>
                </div>

                <div v-else-if="contentTab === 'review'" class="tab-content space-y-5">
                  <div v-if="!activeProblem._feedback && !activeProblem._scores" class="py-12 text-center text-sm text-muted-foreground">提交代码后，AI 评审结果会显示在这里。</div>
                  <template v-else>
                    <div v-if="activeProblem._scores" class="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
                      <div class="mb-3 flex items-baseline justify-between"><span class="text-xs font-medium text-foreground">代码能力评分</span><span class="text-2xl font-bold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}<span class="text-xs font-normal text-muted-foreground">/100</span></span></div>
                      <div v-for="(score, key) in activeProblem._scores" :key="key" class="flex items-center gap-2"><span class="w-14 shrink-0 text-xs text-muted-foreground">{{ categoryLabels[key] || key }}</span><div class="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full" :class="scoreColor(score * 20)" :style="{ width: `${score / 5 * 100}%` }" /></div><span class="w-8 text-right text-xs font-bold" :class="scoreTextColor(score * 20)">{{ score }}/5</span></div>
                    </div>
                    <div v-if="activeProblem._feedback" class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem._feedback)" />
                  </template>
                </div>

                <div v-else class="tab-content space-y-3">
                  <p class="text-xs text-muted-foreground">这是基于你当前代码生成的最小修改参考答案。</p>
                  <div class="h-[520px] overflow-hidden rounded-lg border border-border bg-muted/30"><CodeEditor :model-value="cleanCode(activeProblem._referenceAnswer)" :language="currentLanguage" :read-only="true" /></div>
                </div>
              </div>
            </section>

            <!-- Editor -->
            <section class="min-h-0 min-w-0 flex-1 flex-col overflow-hidden" :class="mobilePane === 'code' ? 'flex' : 'hidden md:flex'">
              <div class="flex h-11 shrink-0 items-center justify-between gap-2 px-3">
                <div class="flex min-w-0 items-center gap-2">
                  <span class="mr-1 shrink-0 text-xs font-semibold text-foreground">代码</span>
                  <Select v-model="codingMode">
                  <SelectTrigger class="h-10 w-[min(34vw,126px)] shrink-0 rounded-lg border-0 bg-muted/70 px-2 text-xs shadow-none sm:w-[126px] md:h-8 md:px-2.5">
                      <SelectValue placeholder="选择模式" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem v-for="mode in codingModeOptions" :key="mode.value" :value="mode.value">{{ mode.label }}</SelectItem>
                    </SelectContent>
                  </Select>
                  <Select v-model="currentLanguage">
                  <SelectTrigger class="h-10 w-[min(30vw,124px)] shrink-0 rounded-lg border-0 bg-muted/70 px-2 text-xs shadow-none sm:w-[124px] md:h-8 md:px-2.5">
                      <SelectValue placeholder="选择语言" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem v-for="language in languageOptions" :key="language.value" :value="language.value">{{ language.label }}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <span v-if="activeProblem._isSubmitting" class="flex items-center gap-1 text-[11px] text-primary"><Loader2 :size="12" class="animate-spin" /> {{ activeProblem._currentStep || '分析中' }}</span>
                <button v-else class="min-h-10 rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground md:min-h-0" @click="clearProblem(activeProblem)">重置代码</button>
              </div>
              <div class="min-h-0 flex-1 bg-muted/20 p-2"><div class="h-full min-h-[300px] overflow-hidden rounded-md border border-border/60 bg-background"><CodeEditor v-model="activeProblem._code" :language="currentLanguage" :read-only="activeProblem._isSubmitting" /></div></div>
              <div class="flex shrink-0 items-center justify-between gap-3 px-3 py-2.5">
                <span class="hidden text-[11px] text-muted-foreground sm:inline">先独立完成，再查看 AI 提示</span>
                <div class="ml-auto flex gap-2">
                  <Button variant="outline" size="sm" class="h-10 gap-1.5 rounded-lg text-xs md:h-8" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3" @click="submitCode(activeProblem, 'hint')"><Zap :size="13" /> 提示 {{ activeProblem._hintCount }}/3</Button>
                  <Button size="sm" class="h-10 gap-1.5 rounded-lg text-xs md:h-8" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()" @click="submitCode(activeProblem, 'full_review')"><Sparkles :size="13" /> 提交评审</Button>
                </div>
              </div>
            </section>
          </div>
        </template>
        <div v-else class="flex flex-1 items-center justify-center text-sm text-muted-foreground">从左侧题目列表选择一道题</div>
      </section>
    </div>

    <Dialog v-model:open="importDialogOpen">
      <DialogContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2"><Sparkles :size="17" class="text-primary" /> AI 导入手撕题</DialogTitle>
          <DialogDescription>
            当前题单：{{ selectedListLabel }}。<span v-if="currentPlaylistId">导入后会自动加入当前题单。</span><span v-else>当前是系统列表，导入题目会进入全部题目；选择自定义题单后会自动归档。</span>
          </DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-4">
          <div class="rounded-xl border border-dashed border-border bg-muted/30 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-2"><Upload :size="16" class="text-primary" /><span class="text-sm font-medium">{{ importFilename || '选择 .md 文件' }}</span></div>
              <Button variant="outline" size="sm" class="relative gap-1.5"><FilePlus2 :size="14" /> 选择文件<input type="file" accept=".md,.markdown,text/markdown,text/plain" class="absolute inset-0 cursor-pointer opacity-0" @change="handleMarkdownFile" /></Button>
            </div>
            <p v-if="importMarkdown" class="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{{ importMarkdown }}</p>
          </div>
          <div class="flex flex-col gap-1.5"><label class="text-xs font-semibold text-foreground">告诉 AI 你想怎么整理（可选）</label><Textarea v-model="importPrompt" :rows="3" placeholder="例如：提取所有二叉树和链表题，统一补充输入输出、约束和复杂度，难度按面试难度标注。" /></div>
          <p v-if="importError" class="text-xs text-destructive">{{ importError }}</p>
        </div>
        <DialogFooter><Button variant="outline" @click="importDialogOpen = false">取消</Button><Button class="gap-1.5" :disabled="isImporting || !importMarkdown" @click="importProblems"><Loader2 v-if="isImporting" :size="14" class="animate-spin" /><Sparkles v-else :size="14" /> {{ isImporting ? 'AI 整理中...' : '开始导入' }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="playlistDialogOpen">
      <DialogContent class="max-w-md">
        <DialogHeader><DialogTitle>加入题单</DialogTitle><DialogDescription>选择一个题单，方便下次集中复习。新建题单请使用全局题单选择器底部的入口。</DialogDescription></DialogHeader>
        <div v-if="playlists.length" class="flex max-h-48 flex-col gap-1 overflow-y-auto"><Button v-for="playlist in playlists" :key="playlist.id" variant="outline" class="h-10 justify-between" @click="addToPlaylist(playlist)"><span class="flex items-center gap-2"><ListPlus :size="14" /> {{ playlist.name }}</span><span class="text-xs text-muted-foreground">{{ playlist.problem_count }} 题</span></Button></div>
        <div v-else class="py-6 text-center text-sm text-muted-foreground">还没有自定义题单，请先在全局题单选择器底部创建。</div>
        <DialogFooter><Button variant="outline" @click="playlistDialogOpen = false">关闭</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, ref, watch } from 'vue'
import { ArrowLeft, BookOpen, ChevronRight, Code2, Ellipsis, FilePlus2, ListPlus, Loader2, PanelLeft, PanelLeftClose, Search, Sparkles, Star, Trash2, Upload, Zap } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import AppTooltip from '@/components/common/AppTooltip.vue'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { useToast } from '@/composables/useNotification.js'
import { useModelGuard } from '@/composables/useModelGuard.js'
import CodeEditor from './CodeEditor.vue'
import { addCodingPlaylistItem, fetchCodingProblem, fetchCodingProblems, importCodingProblems, removeCodingPlaylistItem, submitCodingCode, toggleCodingFavorite } from '@/services/codingApi.js'

const { toast } = useToast()
const languageOptions = [
  { value: 'python', label: 'Python' },
  { value: 'javascript', label: 'JavaScript' },
  { value: 'typescript', label: 'TypeScript' },
  { value: 'java', label: 'Java' },
  { value: 'cpp', label: 'C++' },
  { value: 'c', label: 'C' },
  { value: 'go', label: 'Go' },
  { value: 'rust', label: 'Rust' },
  { value: 'kotlin', label: 'Kotlin' },
  { value: 'swift', label: 'Swift' },
  { value: 'csharp', label: 'C#' },
  { value: 'php', label: 'PHP' },
  { value: 'ruby', label: 'Ruby' },
  { value: 'sql', label: 'SQL' },
]
const codingModeOptions = [
  { value: 'leetcode', label: 'LeetCode 模式' },
  { value: 'acm', label: 'ACM 模式' },
]
const categoryLabels = { syntax: '语法', logic: '逻辑', algorithm: '算法', complexity: '复杂度', style: '风格' }
const codingNavigation = inject('codingNavigation')

const problems = ref([])
const activeProblem = ref(null)
const contentTab = ref('description')
const mobilePane = ref('problem')
const isMobileViewport = () => window.matchMedia('(max-width: 767px)').matches
const sidebarCollapsed = ref(isMobileViewport())
const playlists = codingNavigation.playlists
const selectedListKey = codingNavigation.selectedListKey
const searchQuery = ref('')
const currentLanguage = ref('python')
const codingMode = ref('leetcode')
const isLoading = ref(false)
const importDialogOpen = ref(false)
const importMarkdown = ref('')
const importFilename = ref('')
const importPrompt = ref('')
const importError = ref('')
const isImporting = ref(false)
const playlistDialogOpen = ref(false)
const openProblemMenuId = ref(null)

const currentPlaylistId = computed(() => {
  if (!/^\d+$/.test(String(selectedListKey.value))) return null
  return Number(selectedListKey.value)
})
const canManageProblems = computed(() => selectedListKey.value !== 'all')
const selectedPlaylist = computed(() => playlists.value.find(item => item.id === currentPlaylistId.value) || null)
const selectedListLabel = computed(() => selectedPlaylist.value?.name || (selectedListKey.value === 'favorites' ? '我的收藏' : '全部题目'))
const difficultyLabel = (value) => ({ easy: '简单', medium: '中等', hard: '困难' }[value] || '中等')
const difficultyClass = (value) => ({ easy: 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400', medium: 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400', hard: 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400' }[value] || 'bg-muted text-muted-foreground')
const renderMarkdown = (text) => text ? renderSafeMarkdown(text) : ''
const cleanCode = (text) => (text || '').replace(/^```[\w]*\n?/, '').replace(/\n?```$/, '').trim()
const scoreTextColor = (score) => score >= 80 ? 'text-green-700 dark:text-green-400' : score >= 60 ? 'text-yellow-700 dark:text-yellow-400' : 'text-red-700 dark:text-red-400'
const scoreColor = (score) => score >= 80 ? 'bg-green-500' : score >= 60 ? 'bg-yellow-500' : 'bg-red-500'

function initProblemState(problem) {
  return { ...problem, _code: '', _isSubmitting: false, _feedback: '', _scores: null, _totalScore: 0, _referenceAnswer: '', _lastSubmission: null, _currentStep: '', _currentMode: '', _hintCount: 0 }
}

async function loadProblems() {
  isLoading.value = true
  try {
    const params = { page_size: 100, search: searchQuery.value.trim() }
    if (selectedListKey.value === 'favorites') params.scope = 'favorites'
    if (currentPlaylistId.value) { params.scope = 'playlist'; params.playlist_id = currentPlaylistId.value }
    const result = await fetchCodingProblems(params)
    const previous = activeProblem.value
    problems.value = (result.problems || []).map(problem => {
      const next = initProblemState(problem)
      if (previous?.id === problem.id) Object.assign(next, { description: previous.description, _code: previous._code, _isSubmitting: previous._isSubmitting, _feedback: previous._feedback, _scores: previous._scores, _totalScore: previous._totalScore, _referenceAnswer: previous._referenceAnswer, _lastSubmission: previous._lastSubmission, _currentStep: previous._currentStep, _currentMode: previous._currentMode, _hintCount: previous._hintCount })
      return next
    })
    if (activeProblem.value) activeProblem.value = problems.value.find(item => item.id === activeProblem.value.id) || null
  } catch (error) {
    toast.error(error.message || '加载题目失败')
    problems.value = []
  } finally { isLoading.value = false }
}

async function refreshProblems(openFirst = false) {
  await loadProblems()
  if (openFirst && problems.value[0]) await selectProblem(problems.value[0])
}

async function refreshForSelectedList() {
  activeProblem.value = null
  contentTab.value = 'description'
  await refreshProblems(true)
}

watch(selectedListKey, (value, previousValue) => {
  if (value !== previousValue) refreshForSelectedList()
})

async function selectProblem(problem) {
  openProblemMenuId.value = null
  activeProblem.value = problem
  contentTab.value = 'description'
  mobilePane.value = 'problem'
  if (isMobileViewport()) sidebarCollapsed.value = true
  try { Object.assign(problem, await fetchCodingProblem(problem.id)) } catch (error) { toast.error(error.message || '获取题目详情失败') }
}

function toggleProblemMenu(problemId) {
  openProblemMenuId.value = openProblemMenuId.value === problemId ? null : problemId
}

function selectNextProblem() {
  if (!problems.value.length) return
  const index = problems.value.findIndex(problem => problem.id === activeProblem.value?.id)
  selectProblem(problems.value[(index + 1) % problems.value.length])
}

async function toggleFavorite(problem) {
  try {
    const result = await toggleCodingFavorite(problem.id)
    problem.is_favorite = result.is_favorite
    const listProblem = problems.value.find(item => item.id === problem.id)
    if (listProblem) listProblem.is_favorite = result.is_favorite
    if (selectedListKey.value === 'favorites' && !result.is_favorite) {
      problems.value = problems.value.filter(item => item.id !== problem.id)
      activeProblem.value = problems.value[0] || null
    }
  } catch (error) { toast.error(error.message || '收藏操作失败') }
}

async function removeProblemFromCurrentList(problem) {
  openProblemMenuId.value = null
  try {
    if (selectedListKey.value === 'favorites') {
      await toggleCodingFavorite(problem.id)
      problems.value = problems.value.filter(item => item.id !== problem.id)
      if (activeProblem.value?.id === problem.id) activeProblem.value = problems.value[0] || null
      toast.success('已取消收藏')
      return
    }

    if (currentPlaylistId.value) {
      await removeCodingPlaylistItem(currentPlaylistId.value, problem.id)
      problems.value = problems.value.filter(item => item.id !== problem.id)
      const playlist = playlists.value.find(item => item.id === currentPlaylistId.value)
      if (playlist) playlist.problem_count = Math.max(0, playlist.problem_count - 1)
      if (activeProblem.value?.id === problem.id) activeProblem.value = problems.value[0] || null
      toast.success('已移出当前题单')
    }
  } catch (error) { toast.error(error.message || '管理题目失败') }
}

function openAddToPlaylist() {
  playlistDialogOpen.value = true
}

async function addToPlaylist(playlist) {
  if (!activeProblem.value) return
  try {
    const result = await addCodingPlaylistItem(playlist.id, activeProblem.value.id)
    if (result.added) playlist.problem_count += 1
    playlistDialogOpen.value = false
    toast.success(result.added ? `已加入「${playlist.name}」` : '题目已经在这个题单里')
  } catch (error) { toast.error(error.message || '加入题单失败') }
}

async function handleMarkdownFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importFilename.value = file.name
  importMarkdown.value = await file.text()
  importError.value = ''
  event.target.value = ''
}

async function importProblems() {
  if (!importMarkdown.value.trim()) return
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: 'AI 导入题目' })) return
  isImporting.value = true
  importError.value = ''
  try {
    const result = await importCodingProblems({ prompt: importPrompt.value.trim(), markdown: importMarkdown.value, filename: importFilename.value || '导入题目.md', playlist_id: currentPlaylistId.value || undefined })
    importDialogOpen.value = false
    importMarkdown.value = ''
    importFilename.value = ''
    importPrompt.value = ''
    await codingNavigation.loadPlaylists()
    await refreshProblems(true)
    toast.success(`已导入 ${result.created?.length || 0} 道题目${result.duplicates?.length ? `，跳过 ${result.duplicates.length} 道重复题目` : ''}`)
  } catch (error) { importError.value = error.message || '导入失败，请稍后重试' } finally { isImporting.value = false }
}

function clearProblem(problem) {
  problem._code = ''
  problem._feedback = ''
  problem._scores = null
  problem._totalScore = 0
  problem._referenceAnswer = ''
  problem._lastSubmission = null
  problem._hintCount = 0
  problem._currentMode = ''
  contentTab.value = 'description'
}

async function submitCode(problem, mode) {
  if (!problem._code.trim() || (mode === 'hint' && problem._hintCount >= 3)) return
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: mode === 'hint' ? 'AI 提示' : '提交评审' })) return
  problem._isSubmitting = true
  problem._currentMode = mode
  problem._currentStep = ''
  if (mode === 'full_review') { problem._feedback = ''; problem._scores = null; problem._totalScore = 0; problem._referenceAnswer = '' }
  const separator = mode === 'hint' && problem._feedback ? '\n\n---\n\n' : ''
  const data = { problem_id: problem.id, language: currentLanguage.value, coding_mode: codingMode.value, code: problem._code, mode }
  if (mode === 'hint' && problem._lastSubmission) data.parent_submission_id = problem._lastSubmission.submission_id
  try {
    await submitCodingCode(data, (event) => {
      if (event.type === 'step') problem._currentStep = event.message
      if (event.type === 'chunk') { if (event.replace) problem._feedback = event.content; else { if (separator && !problem._feedback.includes(separator)) problem._feedback += separator; problem._feedback += event.content } }
      if (event.type === 'done') {
        if (event.mode === 'hint') problem._hintCount = event.hint_round || problem._hintCount + 1
        if (event.mode === 'full_review') { problem._scores = event.scores || null; problem._totalScore = event.total_score || 0; problem._referenceAnswer = event.reference_answer || '' }
        problem._lastSubmission = event
        contentTab.value = 'review'
      }
      if (event.type === 'error') toast.error(event.message || '评审失败')
    })
  } catch (error) { toast.error(error.message || '提交失败，请重试') } finally { problem._isSubmitting = false; problem._currentStep = '' }
}

onMounted(async () => {
  await Promise.all([codingNavigation.loadPlaylists(), loadProblems()])
  if (problems.value[0]) await selectProblem(problems.value[0])
})
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

@media (max-width: 767px) {
  .sidebar-container {
    position: absolute;
    inset: 0 auto 0 0;
    width: min(82vw, 256px) !important;
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
</style>
