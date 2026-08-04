<template>
  <div class="flex h-full min-h-0 flex-col bg-background">
    <!-- LeetCode-style list selector: one current list controls the whole page -->
    <header class="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <Code2 :size="17" class="shrink-0 text-primary" />
        <span class="shrink-0 text-sm font-semibold text-foreground">手撕代码</span>
        <Select :model-value="selectedListKey" @update:model-value="selectList">
          <SelectTrigger class="h-8 w-[190px] rounded-lg text-xs">
            <SelectValue placeholder="选择题单" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部题目</SelectItem>
            <SelectItem value="favorites">我的收藏</SelectItem>
            <SelectItem v-for="playlist in playlists" :key="playlist.id" :value="String(playlist.id)">
              {{ playlist.name }}（{{ playlist.problem_count }}）
            </SelectItem>
          </SelectContent>
        </Select>
        <Button variant="ghost" size="icon" class="size-8 shrink-0 text-muted-foreground" aria-label="新建题单" @click="openCreatePlaylist">
          <Plus :size="15" />
        </Button>
      </div>
      <span class="hidden text-xs text-muted-foreground sm:inline">{{ problemTotal }} 道题</span>
    </header>

    <div class="flex min-h-0 flex-1">
      <!-- Current playlist problem list -->
      <section class="problem-list-panel flex min-w-0 w-full flex-col border-r border-border lg:w-[320px] lg:flex-none" :class="{ 'is-detail-open': activeProblem }">
        <div class="flex shrink-0 items-center gap-2 border-b border-border p-3">
          <div class="relative min-w-0 flex-1">
            <Search :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input v-model="searchQuery" class="h-8 rounded-lg border-0 bg-muted pl-8 text-xs shadow-none" placeholder="搜索当前题单" @keyup.enter="refreshProblems" />
          </div>
          <Button size="sm" variant="outline" class="h-8 shrink-0 gap-1.5 rounded-lg px-2.5 text-xs" @click="importDialogOpen = true">
            <Sparkles :size="13" /> <span class="hidden xl:inline">AI 导入</span>
          </Button>
        </div>
        <div class="flex shrink-0 items-center justify-between border-b border-border/60 px-4 py-2">
          <span class="truncate text-xs font-medium text-foreground">{{ selectedListLabel }}</span>
          <Loader2 v-if="isLoading" :size="13" class="animate-spin text-primary" />
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2 custom-scrollbar">
          <div v-if="!problems.length && !isLoading" class="px-3 py-10 text-center text-xs text-muted-foreground">
            当前题单暂无题目
          </div>
          <button
            v-for="(problem, index) in problems"
            :key="problem.id"
            class="group flex w-full items-start gap-2 rounded-lg p-2.5 text-left transition-colors"
            :class="activeProblem?.id === problem.id ? 'bg-primary/10 text-foreground' : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground'"
            @click="selectProblem(problem)"
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
            <span v-if="problem.is_favorite" class="shrink-0 text-amber-500">★</span>
          </button>
        </div>
      </section>

      <!-- Current problem opens on the right; on mobile it replaces the list -->
      <section class="problem-detail-panel flex min-w-0 flex-1 flex-col" :class="{ 'is-detail-open': activeProblem }">
        <template v-if="activeProblem">
          <div class="flex h-11 shrink-0 items-center gap-2 border-b border-border px-3">
            <Button variant="ghost" size="sm" class="h-7 gap-1 px-2 text-xs text-muted-foreground lg:hidden" @click="activeProblem = null"><ArrowLeft :size="13" /> 题目列表</Button>
            <div class="min-w-0 flex-1 truncate text-sm font-semibold text-foreground">{{ activeProblem.title }}</div>
            <button :aria-label="activeProblem.is_favorite ? '取消收藏' : '收藏题目'" class="shrink-0 text-lg leading-none transition-transform hover:scale-110" :class="activeProblem.is_favorite ? 'text-amber-500' : 'text-muted-foreground'" @click="toggleFavorite(activeProblem)">{{ activeProblem.is_favorite ? '★' : '☆' }}</button>
            <Button variant="ghost" size="sm" class="hidden h-7 gap-1 px-2 text-xs text-muted-foreground sm:flex" @click="openAddToPlaylist"><ListPlus :size="13" /> 加入题单</Button>
            <Button variant="ghost" size="sm" class="h-7 gap-1 px-2 text-xs text-muted-foreground" @click="selectNextProblem">下一题 <ChevronRight :size="13" /></Button>
          </div>

          <div class="flex min-h-0 flex-1 flex-col xl:flex-row">
            <!-- Problem statement -->
            <section class="flex min-h-[300px] min-w-0 flex-1 flex-col overflow-hidden border-b border-border xl:w-[44%] xl:flex-none xl:border-b-0 xl:border-r">
              <div class="flex shrink-0 items-center gap-1 border-b border-border px-4">
                <button class="border-b-2 px-2.5 py-3 text-xs font-medium transition-colors" :class="contentTab === 'description' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'" @click="contentTab = 'description'">题目描述</button>
                <button class="border-b-2 px-2.5 py-3 text-xs font-medium transition-colors" :class="contentTab === 'review' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'" @click="contentTab = 'review'">AI 评审<span v-if="activeProblem._feedback || activeProblem._scores" class="ml-1 text-primary">•</span></button>
                <button v-if="activeProblem._referenceAnswer" class="border-b-2 px-2.5 py-3 text-xs font-medium transition-colors" :class="contentTab === 'answer' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'" @click="contentTab = 'answer'">参考答案</button>
              </div>
              <div class="min-h-0 flex-1 overflow-y-auto px-5 py-5 custom-scrollbar">
                <div v-if="contentTab === 'description'">
                  <div class="mb-4 flex flex-wrap items-center gap-2">
                    <span class="rounded bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400">{{ activeProblem.source_type === 'imported' ? '我的题目' : '高频手撕' }}</span>
                    <span class="rounded px-2 py-0.5 text-xs font-medium" :class="difficultyClass(activeProblem.difficulty)">{{ difficultyLabel(activeProblem.difficulty) }}</span>
                    <span v-if="activeProblem.is_solved" class="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">已通过</span>
                  </div>
                  <h1 class="mb-4 text-xl font-bold leading-snug text-foreground">{{ activeProblem.title }}</h1>
                  <div class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem.description)" />
                  <div v-if="activeProblem.tags?.length" class="mt-6 flex flex-wrap gap-1.5 border-t border-border pt-4">
                    <span v-for="tag in activeProblem.tags" :key="tag" class="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">{{ tag }}</span>
                  </div>
                  <div class="mt-5 flex flex-wrap gap-3 text-xs text-muted-foreground">
                    <span v-if="activeProblem.attempt_count">已练习 {{ activeProblem.attempt_count }} 次</span>
                    <span v-if="activeProblem.expected_complexity">复杂度 {{ activeProblem.expected_complexity }}</span>
                  </div>
                </div>

                <div v-else-if="contentTab === 'review'" class="space-y-5">
                  <div v-if="!activeProblem._feedback && !activeProblem._scores" class="py-12 text-center text-sm text-muted-foreground">提交代码后，AI 评审结果会显示在这里。</div>
                  <template v-else>
                    <div v-if="activeProblem._scores" class="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
                      <div class="mb-3 flex items-baseline justify-between"><span class="text-xs font-medium text-foreground">代码能力评分</span><span class="text-2xl font-bold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}<span class="text-xs font-normal text-muted-foreground">/100</span></span></div>
                      <div v-for="(score, key) in activeProblem._scores" :key="key" class="flex items-center gap-2"><span class="w-14 shrink-0 text-xs text-muted-foreground">{{ categoryLabels[key] || key }}</span><div class="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full" :class="scoreColor(score * 20)" :style="{ width: `${score / 5 * 100}%` }" /></div><span class="w-8 text-right text-xs font-bold" :class="scoreTextColor(score * 20)">{{ score }}/5</span></div>
                    </div>
                    <div v-if="activeProblem._feedback" class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem._feedback)" />
                  </template>
                </div>

                <div v-else class="space-y-3">
                  <p class="text-xs text-muted-foreground">这是基于你当前代码生成的最小修改参考答案。</p>
                  <div class="h-[520px] overflow-hidden rounded-lg border border-border bg-muted/30"><CodeEditor :model-value="cleanCode(activeProblem._referenceAnswer)" :language="currentLanguage" :read-only="true" /></div>
                </div>
              </div>
            </section>

            <!-- Editor -->
            <section class="flex min-h-[420px] min-w-0 flex-1 flex-col overflow-hidden">
              <div class="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border px-3">
                <div class="flex items-center gap-1">
                  <span class="mr-1 text-xs font-semibold text-foreground">代码</span>
                  <button v-for="language in languageOptions" :key="language.value" class="rounded-full px-2.5 py-1 text-[11px] transition-colors" :class="currentLanguage === language.value ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'" @click="currentLanguage = language.value">{{ language.label }}</button>
                </div>
                <span v-if="activeProblem._isSubmitting" class="flex items-center gap-1 text-[11px] text-primary"><Loader2 :size="12" class="animate-spin" /> {{ activeProblem._currentStep || '分析中' }}</span>
                <button v-else class="rounded-md px-2 py-1 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground" @click="clearProblem(activeProblem)">重置代码</button>
              </div>
              <div class="min-h-0 flex-1 bg-muted/20 p-2"><div class="h-full min-h-[300px] overflow-hidden rounded-md border border-border/60 bg-background"><CodeEditor v-model="activeProblem._code" :language="currentLanguage" :read-only="activeProblem._isSubmitting" /></div></div>
              <div class="flex shrink-0 items-center justify-between gap-3 border-t border-border px-3 py-2.5">
                <span class="hidden text-[11px] text-muted-foreground sm:inline">先独立完成，再查看 AI 提示</span>
                <div class="ml-auto flex gap-2">
                  <Button variant="outline" size="sm" class="h-8 gap-1.5 rounded-lg text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3" @click="submitCode(activeProblem, 'hint')"><Zap :size="13" /> 提示 {{ activeProblem._hintCount }}/3</Button>
                  <Button size="sm" class="h-8 gap-1.5 rounded-lg text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()" @click="submitCode(activeProblem, 'full_review')"><Sparkles :size="13" /> 提交评审</Button>
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
        <DialogHeader><DialogTitle>{{ playlistDialogMode === 'add' ? '加入题单' : '新建题单' }}</DialogTitle><DialogDescription>{{ playlistDialogMode === 'add' ? '选择一个题单，方便下次集中复习。' : '创建题单后，它会出现在顶部选择器中。' }}</DialogDescription></DialogHeader>
        <div v-if="playlistDialogMode === 'add' && playlists.length" class="flex max-h-48 flex-col gap-1 overflow-y-auto"><Button v-for="playlist in playlists" :key="playlist.id" variant="outline" class="h-10 justify-between" @click="addToPlaylist(playlist)"><span class="flex items-center gap-2"><ListPlus :size="14" /> {{ playlist.name }}</span><span class="text-xs text-muted-foreground">{{ playlist.problem_count }} 题</span></Button></div>
        <div class="flex flex-col gap-3"><div class="flex flex-col gap-1.5"><label class="text-xs font-semibold">{{ playlistDialogMode === 'add' ? '新建题单' : '题单名称' }}</label><Input v-model="playlistName" placeholder="例如：字节后端高频题" @keyup.enter="createPlaylist" /></div><div v-if="playlistDialogMode !== 'add'" class="flex flex-col gap-1.5"><label class="text-xs font-semibold">描述（可选）</label><Textarea v-model="playlistDescription" :rows="2" placeholder="这个题单用于什么场景？" /></div></div>
        <DialogFooter><Button variant="outline" @click="playlistDialogOpen = false">取消</Button><Button :disabled="isCreatingPlaylist || !playlistName.trim()" @click="createPlaylist">{{ isCreatingPlaylist ? '创建中...' : '创建题单' }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ArrowLeft, ChevronRight, Code2, FilePlus2, ListPlus, Loader2, Plus, Search, Sparkles, Upload, Zap } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { useToast } from '@/composables/useNotification.js'
import CodeEditor from './CodeEditor.vue'
import { addCodingPlaylistItem, createCodingPlaylist, fetchCodingPlaylists, fetchCodingProblem, fetchCodingProblems, importCodingProblems, submitCodingCode, toggleCodingFavorite } from '@/services/codingApi.js'

const { toast } = useToast()
const languageOptions = [{ value: 'python', label: 'Python' }, { value: 'c', label: 'C' }, { value: 'java', label: 'Java' }]
const categoryLabels = { syntax: '语法', logic: '逻辑', algorithm: '算法', complexity: '复杂度', style: '风格' }

const problems = ref([])
const activeProblem = ref(null)
const contentTab = ref('description')
const playlists = ref([])
const problemTotal = ref(0)
const selectedListKey = ref('all')
const searchQuery = ref('')
const currentLanguage = ref('python')
const isLoading = ref(false)
const importDialogOpen = ref(false)
const importMarkdown = ref('')
const importFilename = ref('')
const importPrompt = ref('')
const importError = ref('')
const isImporting = ref(false)
const playlistDialogOpen = ref(false)
const playlistDialogMode = ref('create')
const playlistName = ref('')
const playlistDescription = ref('')
const isCreatingPlaylist = ref(false)

const currentPlaylistId = computed(() => {
  if (!/^\d+$/.test(String(selectedListKey.value))) return null
  return Number(selectedListKey.value)
})
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

async function loadPlaylists() {
  try {
    playlists.value = await fetchCodingPlaylists()
    if (currentPlaylistId.value && !playlists.value.some(item => item.id === currentPlaylistId.value)) selectedListKey.value = 'all'
  } catch { playlists.value = [] }
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
    problemTotal.value = result.total || 0
    if (activeProblem.value) activeProblem.value = problems.value.find(item => item.id === activeProblem.value.id) || null
  } catch (error) {
    toast.error(error.message || '加载题目失败')
    problems.value = []
    problemTotal.value = 0
  } finally { isLoading.value = false }
}

async function refreshProblems(openFirst = false) {
  await loadProblems()
  if (openFirst && problems.value[0]) await selectProblem(problems.value[0])
}

async function selectList(value) {
  selectedListKey.value = value
  activeProblem.value = null
  contentTab.value = 'description'
  await refreshProblems(true)
}

async function selectProblem(problem) {
  activeProblem.value = problem
  contentTab.value = 'description'
  try { Object.assign(problem, await fetchCodingProblem(problem.id)) } catch (error) { toast.error(error.message || '获取题目详情失败') }
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

function openCreatePlaylist() {
  playlistDialogMode.value = 'create'
  playlistName.value = ''
  playlistDescription.value = ''
  playlistDialogOpen.value = true
}

function openAddToPlaylist() {
  playlistDialogMode.value = 'add'
  playlistName.value = ''
  playlistDescription.value = ''
  playlistDialogOpen.value = true
}

async function createPlaylist() {
  if (!playlistName.value.trim()) return
  isCreatingPlaylist.value = true
  try {
    const playlist = await createCodingPlaylist({ name: playlistName.value.trim(), description: playlistDescription.value.trim() })
    playlists.value.unshift(playlist)
    playlistName.value = ''
    playlistDescription.value = ''
    if (playlistDialogMode.value === 'create') {
      playlistDialogOpen.value = false
      await selectList(String(playlist.id))
    }
    toast.success('题单已创建')
  } catch (error) { toast.error(error.message || '创建题单失败') } finally { isCreatingPlaylist.value = false }
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
  isImporting.value = true
  importError.value = ''
  try {
    const result = await importCodingProblems({ prompt: importPrompt.value.trim(), markdown: importMarkdown.value, filename: importFilename.value || '导入题目.md', playlist_id: currentPlaylistId.value || undefined })
    importDialogOpen.value = false
    importMarkdown.value = ''
    importFilename.value = ''
    importPrompt.value = ''
    await loadPlaylists()
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
  problem._isSubmitting = true
  problem._currentMode = mode
  problem._currentStep = ''
  if (mode === 'full_review') { problem._feedback = ''; problem._scores = null; problem._totalScore = 0; problem._referenceAnswer = '' }
  const separator = mode === 'hint' && problem._feedback ? '\n\n---\n\n' : ''
  const data = { problem_id: problem.id, language: currentLanguage.value, code: problem._code, mode }
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
  await Promise.all([loadPlaylists(), loadProblems()])
  if (problems.value[0]) await selectProblem(problems.value[0])
})
</script>
