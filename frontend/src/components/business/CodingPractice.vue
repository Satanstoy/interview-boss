<template>
  <div class="flex h-full min-h-0 flex-col gap-4 overflow-hidden">
    <section class="shrink-0 rounded-xl border border-border bg-card shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-4 px-4 py-4 md:px-5">
        <div class="flex min-w-0 items-center gap-3">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <Code2 :size="21" />
          </div>
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h1 class="truncate text-base font-bold text-foreground md:text-lg">手撕代码</h1>
              <Badge variant="secondary" class="hidden sm:inline-flex">AI 评审</Badge>
            </div>
            <p class="mt-0.5 truncate text-xs text-muted-foreground">像 LeetCode 一样刷题、收藏、整理题单，面试前快速复习</p>
          </div>
        </div>
        <div class="flex items-center gap-2 text-xs text-muted-foreground">
          <span class="hidden items-center gap-1.5 sm:flex"><BookOpen :size="14" /> {{ problemTotal }} 道题</span>
          <span v-if="errorStats" class="hidden items-center gap-1.5 md:flex"><CheckCircle2 :size="14" class="text-emerald-500" /> 已通过 {{ errorStats.passed_submissions || 0 }} 次</span>
          <Button size="sm" class="gap-1.5" @click="importDialogOpen = true">
            <Sparkles :size="15" />
            <span>AI 导入题目</span>
          </Button>
        </div>
      </div>
      <div class="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-border px-4 py-2.5 text-xs text-muted-foreground md:px-5">
        <span class="flex items-center gap-1.5"><Star :size="14" class="text-amber-500" /> 收藏题目后可一键复习</span>
        <span class="flex items-center gap-1.5"><ListPlus :size="14" class="text-primary" /> 用题单组织专项训练</span>
        <span class="hidden items-center gap-1.5 lg:flex"><Clock3 :size="14" /> 提示最多 3 轮，保留面试节奏</span>
      </div>
    </section>

    <section class="flex min-h-0 flex-1 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div v-if="!sidebarCollapsed" class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden" @click="sidebarCollapsed = true" />

      <aside
        class="coding-sidebar z-30 flex w-[286px] shrink-0 flex-col overflow-hidden border-r border-border bg-card md:z-auto"
        :class="{ 'coding-sidebar-collapsed': sidebarCollapsed }"
      >
        <div class="flex shrink-0 items-center justify-between border-b border-border px-3 py-2.5">
          <div class="text-xs font-semibold text-foreground">题库</div>
          <Button variant="ghost" size="icon-sm" aria-label="收起题库侧栏" @click="sidebarCollapsed = true">
            <PanelLeftClose :size="15" />
          </Button>
        </div>

        <div class="flex flex-col gap-2 border-b border-border p-3">
          <div class="relative">
            <Search :size="15" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input v-model="searchQuery" class="h-8 pl-9 text-xs" placeholder="搜索题目或内容" @keyup.enter="loadProblems" />
          </div>
          <div class="flex items-center gap-1 rounded-lg bg-muted p-1">
            <Button
              v-for="item in libraryViews"
              :key="item.value"
              variant="ghost"
              size="sm"
              class="h-7 flex-1 gap-1 px-2 text-xs"
              :class="libraryView === item.value ? 'bg-card text-primary shadow-sm hover:bg-card' : 'text-muted-foreground'"
              @click="selectLibraryView(item.value)"
            >
              <component :is="item.icon" :size="13" />
              {{ item.label }}
            </Button>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <Button
              v-for="opt in difficultyOptions"
              :key="opt.value || 'all'"
              variant="ghost"
              size="xs"
              class="h-6 rounded-full border px-2 text-[11px]"
              :class="filterDifficulty === opt.value ? 'border-primary/30 bg-primary/10 text-primary' : 'border-border text-muted-foreground'"
              @click="filterDifficulty = opt.value; loadProblems()"
            >{{ opt.label }}</Button>
          </div>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2 custom-scrollbar">
          <div class="mb-2 flex items-center justify-between px-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            <span>{{ libraryView === 'favorites' ? '我的收藏' : selectedPlaylistId ? selectedPlaylistName : '全部题目' }}</span>
            <span>{{ problemTotal }}</span>
          </div>
          <div v-if="isLoading" class="flex flex-col gap-2 px-2 py-4">
            <div v-for="n in 5" :key="n" class="h-12 animate-pulse rounded-lg bg-muted" />
          </div>
          <div v-else-if="!problems.length" class="px-3 py-8 text-center">
            <Bookmark :size="22" class="mx-auto mb-2 text-muted-foreground/60" />
            <p class="text-xs font-medium text-foreground">这里还没有题目</p>
            <p class="mt-1 text-[11px] leading-relaxed text-muted-foreground">可以调整筛选，或用 AI 导入你的 Markdown 题库。</p>
          </div>
          <div v-else class="flex flex-col gap-0.5">
            <Button
              v-for="problem in problems"
              :key="problem.id"
              variant="ghost"
              class="group h-auto w-full justify-start gap-2.5 rounded-lg px-3 py-2.5 text-left"
              :class="activeProblem?.id === problem.id ? 'bg-accent text-foreground hover:bg-accent' : 'text-foreground hover:bg-muted'"
              @click="selectProblem(problem)"
            >
              <span class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px]" :class="problem.is_solved ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-600' : 'border-border text-muted-foreground'">
                <CheckCircle2 v-if="problem.is_solved" :size="12" />
                <span v-else>{{ problem.id }}</span>
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-xs font-medium">{{ problem.title }}</span>
                <span class="mt-1 flex items-center gap-1.5 truncate text-[10px] text-muted-foreground">
                  <span :class="difficultyClass(problem.difficulty)">{{ difficultyLabel(problem.difficulty) }}</span>
                  <span v-if="problem.attempt_count">· {{ problem.attempt_count }} 次提交</span>
                  <span v-if="problem.source_type === 'imported'" class="text-primary">· 我的题目</span>
                </span>
              </span>
              <Star v-if="problem.is_favorite" :size="13" class="shrink-0 fill-amber-400 text-amber-500" />
            </Button>
          </div>
        </div>

        <div class="shrink-0 border-t border-border p-2">
          <div class="mb-1 flex items-center justify-between px-2">
            <span class="text-[11px] font-semibold text-muted-foreground">我的题单</span>
            <Button variant="ghost" size="icon-xs" aria-label="新建题单" @click="playlistDialogOpen = true"><Plus :size="14" /></Button>
          </div>
          <div v-if="!playlists.length" class="px-2 pb-1 text-[11px] text-muted-foreground">创建题单，按专题整理复习路径</div>
          <div v-else class="flex max-h-24 flex-col gap-0.5 overflow-y-auto">
            <Button
              v-for="playlist in playlists"
              :key="playlist.id"
              variant="ghost"
              size="sm"
              class="h-7 justify-start gap-2 px-2 text-xs font-normal"
              :class="selectedPlaylistId === playlist.id ? 'bg-primary/10 text-primary' : 'text-muted-foreground'"
              @click="selectPlaylist(playlist.id)"
            >
              <ListPlus :size="13" />
              <span class="min-w-0 flex-1 truncate">{{ playlist.name }}</span>
              <span class="text-[10px] opacity-70">{{ playlist.problem_count }}</span>
            </Button>
          </div>
        </div>
      </aside>

      <div v-if="sidebarCollapsed" class="hidden shrink-0 flex-col items-center gap-2 border-r border-border p-2 md:flex">
        <Button variant="ghost" size="icon-sm" aria-label="展开题库侧栏" @click="sidebarCollapsed = false"><PanelLeft :size="16" /></Button>
        <Button variant="ghost" size="icon-sm" aria-label="打开导入题目" @click="importDialogOpen = true"><FilePlus2 :size="16" /></Button>
      </div>

      <main class="min-w-0 flex-1 overflow-y-auto custom-scrollbar">
        <div class="flex min-h-full flex-col">
          <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2 md:hidden">
            <Button variant="outline" size="sm" class="h-8 gap-1.5 text-xs" @click="sidebarCollapsed = false"><PanelLeft :size="14" /> 题库</Button>
            <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">{{ activeProblem?.title || '选择一道题开始' }}</span>
          </div>

          <div v-if="!activeProblem" class="flex min-h-[560px] flex-1 items-center justify-center px-6 py-12">
            <div class="max-w-lg text-center">
              <div class="mx-auto mb-5 flex size-16 items-center justify-center rounded-2xl bg-primary/10 text-primary"><Code2 :size="32" /></div>
              <h2 class="text-xl font-bold text-foreground">选择一道题，开始手撕</h2>
              <p class="mt-2 text-sm leading-relaxed text-muted-foreground">收藏题目、加入题单，或者把你的 Markdown 面经交给 AI，建立真正属于你的代码题库。</p>
              <div class="mt-6 flex flex-wrap justify-center gap-2">
                <Button variant="outline" size="sm" class="gap-1.5" @click="selectLibraryView('favorites')"><Star :size="14" /> 查看收藏</Button>
                <Button size="sm" class="gap-1.5" @click="importDialogOpen = true"><Sparkles :size="14" /> AI 导入 Markdown</Button>
              </div>
            </div>
          </div>

          <template v-else>
            <div class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3 md:px-5">
              <div class="flex min-w-0 items-center gap-2">
                <span class="text-xs text-muted-foreground">题目 {{ activeProblem.id }}</span>
                <h2 class="truncate text-sm font-bold text-foreground md:text-base">{{ activeProblem.title }}</h2>
                <Badge :class="difficultyBadgeClass(activeProblem.difficulty)">{{ difficultyLabel(activeProblem.difficulty) }}</Badge>
                <Badge v-if="activeProblem.source_type === 'imported'" variant="outline" class="hidden sm:inline-flex">我的题目</Badge>
              </div>
              <div class="flex items-center gap-1">
                <Button variant="ghost" size="sm" class="gap-1.5 text-xs" :class="activeProblem.is_favorite ? 'text-amber-600' : 'text-muted-foreground'" @click="toggleFavorite(activeProblem)">
                  <Star :size="15" :class="activeProblem.is_favorite ? 'fill-amber-400' : ''" />
                  <span class="hidden sm:inline">{{ activeProblem.is_favorite ? '已收藏' : '收藏' }}</span>
                </Button>
                <Button variant="outline" size="sm" class="gap-1.5 text-xs" @click="playlistDialogOpen = true"><ListPlus :size="14" /> 加入题单</Button>
              </div>
            </div>

            <div class="grid flex-1 gap-4 p-4 md:p-5 lg:grid-cols-[minmax(280px,0.9fr)_minmax(390px,1.1fr)]">
              <section class="flex min-h-0 flex-col rounded-xl border border-border bg-background">
                <div class="flex items-center justify-between border-b border-border px-4 py-3">
                  <div>
                    <div class="text-xs font-semibold text-foreground">题目描述</div>
                    <div class="mt-0.5 text-[11px] text-muted-foreground">先说清楚思路，再开始写代码</div>
                  </div>
                  <Badge v-if="activeProblem.expected_complexity" variant="outline" class="font-mono text-[10px]">{{ activeProblem.expected_complexity }}</Badge>
                </div>
                <div class="min-h-0 flex-1 overflow-y-auto px-4 py-4 custom-scrollbar">
                  <div class="answer-content prose prose-sm max-w-none text-sm leading-relaxed dark:prose-invert" v-html="renderMarkdown(activeProblem.description)" />
                  <div v-if="activeProblem.tags?.length" class="mt-6 flex flex-wrap gap-1.5 border-t border-border pt-4">
                    <Badge v-for="tag in activeProblem.tags" :key="tag" variant="secondary" class="text-[10px]">{{ tag }}</Badge>
                  </div>
                </div>
              </section>

              <section class="flex min-h-0 flex-col gap-3">
                <div class="flex min-h-[460px] flex-1 flex-col overflow-hidden rounded-xl border border-border bg-background">
                  <div class="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-2">
                    <div class="flex items-center gap-1">
                      <span class="px-2 text-xs font-semibold text-foreground">代码</span>
                      <Button
                        v-for="language in languageOptions"
                        :key="language.value"
                        variant="ghost"
                        size="xs"
                        class="h-6 px-2 text-[11px]"
                        :class="currentLanguage === language.value ? 'bg-primary/10 text-primary' : 'text-muted-foreground'"
                        @click="currentLanguage = language.value"
                      >{{ language.label }}</Button>
                    </div>
                    <div class="flex items-center gap-1">
                      <span v-if="activeProblem._isSubmitting" class="mr-1 flex items-center gap-1 text-[11px] text-primary"><Loader2 :size="12" class="animate-spin" /> {{ activeProblem._currentStep || 'AI 分析中' }}</span>
                      <Button variant="ghost" size="xs" class="text-[11px] text-muted-foreground" @click="clearProblem(activeProblem)">清空</Button>
                    </div>
                  </div>
                  <div class="min-h-0 flex-1 p-2">
                    <CodeEditor v-model="activeProblem._code" :language="currentLanguage" :read-only="activeProblem._isSubmitting" />
                  </div>
                  <div class="flex flex-wrap items-center justify-between gap-2 border-t border-border bg-muted/40 px-3 py-2">
                    <span class="text-[11px] text-muted-foreground">支持 Python · C · Java</span>
                    <div class="flex items-center gap-1.5">
                      <Button variant="outline" size="sm" class="h-8 gap-1.5 text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3" @click="submitCode(activeProblem, 'hint')">
                        <Zap :size="13" /> {{ activeProblem._isSubmitting && activeProblem._currentMode === 'hint' ? '提示中...' : `提示 ${activeProblem._hintCount}/3` }}
                      </Button>
                      <Button size="sm" class="h-8 gap-1.5 text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()" @click="submitCode(activeProblem, 'full_review')">
                        <Sparkles :size="13" /> {{ activeProblem._isSubmitting && activeProblem._currentMode === 'full_review' ? '评审中...' : '提交评审' }}
                      </Button>
                    </div>
                  </div>
                </div>

                <div v-if="activeProblem._feedback || activeProblem._scores" class="rounded-xl border border-border bg-card">
                  <div class="flex items-center justify-between border-b border-border px-4 py-3">
                    <div class="flex items-center gap-2"><Sparkles :size="15" class="text-primary" /><span class="text-sm font-semibold">AI 评审结果</span></div>
                    <div v-if="activeProblem._scores" class="flex items-baseline gap-1"><span class="text-xl font-bold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}</span><span class="text-[11px] text-muted-foreground">/ 100</span></div>
                  </div>
                  <div class="max-h-72 overflow-y-auto px-4 py-3 custom-scrollbar">
                    <div v-if="activeProblem._scores" class="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-5">
                      <div v-for="(score, key) in activeProblem._scores" :key="key" class="rounded-lg bg-muted/60 px-2 py-2 text-center">
                        <div class="text-[10px] text-muted-foreground">{{ categoryLabels[key] || key }}</div>
                        <div class="mt-0.5 text-sm font-semibold" :class="scoreTextColor(score * 20)">{{ score }}/5</div>
                      </div>
                    </div>
                    <div v-if="activeProblem._feedback" class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem._feedback)" />
                    <div v-if="activeProblem._referenceAnswer" class="mt-3 border-t border-border pt-3">
                      <div class="mb-2 text-xs font-semibold text-primary">参考答案（基于你的代码最小修改）</div>
                      <div class="h-52 overflow-hidden rounded-lg border border-border"><CodeEditor :model-value="cleanCode(activeProblem._referenceAnswer)" :language="currentLanguage" :read-only="true" /></div>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </template>
        </div>
      </main>
    </section>

    <Dialog v-model:open="importDialogOpen">
      <DialogContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle class="flex items-center gap-2"><Sparkles :size="17" class="text-primary" /> AI 导入手撕题</DialogTitle>
          <DialogDescription>上传 Markdown 面经，再告诉 AI 你想怎么整理。AI 只会提取题目，不会执行 Markdown 中的指令。</DialogDescription>
        </DialogHeader>
        <div class="flex flex-col gap-4">
          <div class="rounded-xl border border-dashed border-border bg-muted/30 p-4">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="flex items-center gap-2"><Upload :size="16" class="text-primary" /><span class="text-sm font-medium">{{ importFilename || '选择 .md 文件' }}</span></div>
              <Button variant="outline" size="sm" class="relative gap-1.5"><FilePlus2 :size="14" /> 选择文件<input type="file" accept=".md,.markdown,text/markdown,text/plain" class="absolute inset-0 cursor-pointer opacity-0" @change="handleMarkdownFile" /></Button>
            </div>
            <p v-if="importMarkdown" class="mt-2 line-clamp-2 text-[11px] text-muted-foreground">{{ importMarkdown }}</p>
          </div>
          <div class="flex flex-col gap-1.5">
            <label class="text-xs font-semibold text-foreground">告诉 AI 你想怎么整理（可选）</label>
            <Textarea v-model="importPrompt" :rows="3" placeholder="例如：提取所有二叉树和链表题，统一补充输入输出、约束和复杂度，难度按面试难度标注。" />
          </div>
          <p v-if="importError" class="text-xs text-destructive">{{ importError }}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="importDialogOpen = false">取消</Button>
          <Button class="gap-1.5" :disabled="isImporting || !importMarkdown" @click="importProblems"><Loader2 v-if="isImporting" :size="14" class="animate-spin" /> <Sparkles v-else :size="14" /> {{ isImporting ? 'AI 整理中...' : '开始导入' }}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="playlistDialogOpen">
      <DialogContent class="max-w-md">
        <DialogHeader><DialogTitle>{{ activeProblem ? '加入题单' : '新建题单' }}</DialogTitle><DialogDescription>{{ activeProblem ? '选择一个题单，方便下次集中复习。' : '为你的专项训练建立一个清晰的复习路径。' }}</DialogDescription></DialogHeader>
        <div v-if="activeProblem && playlists.length" class="flex max-h-48 flex-col gap-1 overflow-y-auto">
          <Button v-for="playlist in playlists" :key="playlist.id" variant="outline" class="h-10 justify-between" @click="addToPlaylist(playlist)"><span class="flex items-center gap-2"><ListPlus :size="14" /> {{ playlist.name }}</span><span class="text-xs text-muted-foreground">{{ playlist.problem_count }} 题</span></Button>
        </div>
        <div class="flex flex-col gap-3">
          <div class="flex flex-col gap-1.5"><label class="text-xs font-semibold">{{ activeProblem ? '新建题单' : '题单名称' }}</label><Input v-model="playlistName" placeholder="例如：字节后端高频题" @keyup.enter="createPlaylist" /></div>
          <div v-if="!activeProblem" class="flex flex-col gap-1.5"><label class="text-xs font-semibold">描述（可选）</label><Textarea v-model="playlistDescription" :rows="2" placeholder="这个题单用于什么场景？" /></div>
        </div>
        <DialogFooter><Button variant="outline" @click="playlistDialogOpen = false">取消</Button><Button :disabled="isCreatingPlaylist || !playlistName.trim()" @click="createPlaylist">{{ isCreatingPlaylist ? '创建中...' : '创建题单' }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BookOpen, Bookmark, CheckCircle2, Code2, Clock3, FilePlus2, ListPlus, Loader2, PanelLeft, PanelLeftClose, Plus, Search, Sparkles, Star, Upload, Zap } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { useToast } from '@/composables/useNotification.js'
import CodeEditor from './CodeEditor.vue'
import {
  addCodingPlaylistItem,
  createCodingPlaylist,
  fetchCodingErrorStats,
  fetchCodingPlaylists,
  fetchCodingProblem,
  fetchCodingProblems,
  importCodingProblems,
  submitCodingCode,
  toggleCodingFavorite,
} from '@/services/codingApi.js'

const { toast } = useToast()
const difficultyOptions = [{ value: '', label: '全部' }, { value: 'easy', label: '简单' }, { value: 'medium', label: '中等' }, { value: 'hard', label: '困难' }]
const languageOptions = [{ value: 'python', label: 'Python' }, { value: 'c', label: 'C' }, { value: 'java', label: 'Java' }]
const libraryViews = [{ value: 'all', label: '全部', icon: BookOpen }, { value: 'favorites', label: '收藏', icon: Star }]
const categoryLabels = { syntax: '语法', logic: '逻辑', algorithm: '算法', complexity: '复杂度', style: '风格' }

const problems = ref([])
const activeProblem = ref(null)
const playlists = ref([])
const errorStats = ref(null)
const problemTotal = ref(0)
const libraryView = ref('all')
const selectedPlaylistId = ref(null)
const filterDifficulty = ref('')
const searchQuery = ref('')
const currentLanguage = ref('python')
const isLoading = ref(false)
const sidebarCollapsed = ref(typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches)
const importDialogOpen = ref(false)
const importMarkdown = ref('')
const importFilename = ref('')
const importPrompt = ref('')
const importError = ref('')
const isImporting = ref(false)
const playlistDialogOpen = ref(false)
const playlistName = ref('')
const playlistDescription = ref('')
const isCreatingPlaylist = ref(false)

const selectedPlaylistName = computed(() => playlists.value.find(item => item.id === selectedPlaylistId.value)?.name || '题单')
const difficultyLabel = (value) => ({ easy: '简单', medium: '中等', hard: '困难' }[value] || '中等')
const difficultyClass = (value) => ({ easy: 'text-emerald-600 dark:text-emerald-400', medium: 'text-amber-600 dark:text-amber-400', hard: 'text-rose-600 dark:text-rose-400' }[value] || 'text-muted-foreground')
const difficultyBadgeClass = (value) => ({ easy: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20', medium: 'bg-amber-500/10 text-amber-600 border-amber-500/20', hard: 'bg-rose-500/10 text-rose-600 border-rose-500/20' }[value] || '')
const renderMarkdown = (text) => text ? renderSafeMarkdown(text) : ''
const cleanCode = (text) => (text || '').replace(/^```[\w]*\n?/, '').replace(/\n?```$/, '').trim()
const scoreTextColor = (score) => score >= 80 ? 'text-emerald-600 dark:text-emerald-400' : score >= 60 ? 'text-amber-600 dark:text-amber-400' : 'text-rose-600 dark:text-rose-400'

function initProblemState(problem) {
  return { ...problem, _code: '', _isSubmitting: false, _feedback: '', _scores: null, _totalScore: 0, _referenceAnswer: '', _lastSubmission: null, _currentStep: '', _currentMode: '', _hintCount: 0 }
}

async function loadPlaylists() {
  try { playlists.value = await fetchCodingPlaylists() } catch { playlists.value = [] }
}

async function loadProblems() {
  isLoading.value = true
  try {
    const params = { page_size: 100, difficulty: filterDifficulty.value, search: searchQuery.value.trim() }
    if (libraryView.value === 'favorites') params.scope = 'favorites'
    if (selectedPlaylistId.value) { params.scope = 'playlist'; params.playlist_id = selectedPlaylistId.value }
    const result = await fetchCodingProblems(params)
    const previous = activeProblem.value
    problems.value = (result.problems || []).map((problem) => {
      const next = initProblemState(problem)
      if (previous?.id === problem.id) {
        Object.assign(next, {
          description: previous.description,
          _code: previous._code,
          _isSubmitting: previous._isSubmitting,
          _feedback: previous._feedback,
          _scores: previous._scores,
          _totalScore: previous._totalScore,
          _referenceAnswer: previous._referenceAnswer,
          _lastSubmission: previous._lastSubmission,
          _currentStep: previous._currentStep,
          _currentMode: previous._currentMode,
          _hintCount: previous._hintCount,
        })
      }
      return next
    })
    problemTotal.value = result.total || 0
    if (activeProblem.value) {
      const same = problems.value.find(item => item.id === activeProblem.value.id)
      activeProblem.value = same || null
    }
  } catch (error) {
    toast.error(error.message || '加载题目失败')
    problems.value = []
    problemTotal.value = 0
  } finally { isLoading.value = false }
}

async function selectProblem(problem) {
  if (activeProblem.value?.id === problem.id && activeProblem.value.description) return
  activeProblem.value = problem
  try {
    const detail = await fetchCodingProblem(problem.id)
    Object.assign(problem, detail)
    activeProblem.value = problem
  } catch (error) { toast.error(error.message || '获取题目详情失败') }
  if (typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches) sidebarCollapsed.value = true
}

function selectLibraryView(view) {
  libraryView.value = view
  selectedPlaylistId.value = null
  loadProblems()
}

function selectPlaylist(id) {
  selectedPlaylistId.value = id
  libraryView.value = 'all'
  loadProblems()
}

async function toggleFavorite(problem) {
  try {
    const result = await toggleCodingFavorite(problem.id)
    problem.is_favorite = result.is_favorite
    const listProblem = problems.value.find(item => item.id === problem.id)
    if (listProblem) listProblem.is_favorite = result.is_favorite
    if (libraryView.value === 'favorites' && !result.is_favorite) problems.value = problems.value.filter(item => item.id !== problem.id)
  } catch (error) { toast.error(error.message || '收藏操作失败') }
}

async function createPlaylist() {
  if (!playlistName.value.trim()) return
  isCreatingPlaylist.value = true
  try {
    const playlist = await createCodingPlaylist({ name: playlistName.value.trim(), description: playlistDescription.value.trim() })
    playlists.value.unshift(playlist)
    playlistName.value = ''
    playlistDescription.value = ''
    if (!activeProblem.value) playlistDialogOpen.value = false
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
    const result = await importCodingProblems({ prompt: importPrompt.value.trim(), markdown: importMarkdown.value, filename: importFilename.value || '导入题目.md' })
    importDialogOpen.value = false
    importMarkdown.value = ''
    importFilename.value = ''
    importPrompt.value = ''
    await loadPlaylists()
    await loadProblems()
    const first = result.created?.[0] && problems.value.find(problem => problem.id === result.created[0].id)
    if (first) await selectProblem(first)
    toast.success(`已导入 ${result.created?.length || 0} 道题目${result.duplicates?.length ? `，跳过 ${result.duplicates.length} 道重复题目` : ''}`)
  } catch (error) {
    importError.value = error.message || '导入失败，请稍后重试'
  } finally { isImporting.value = false }
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
      if (event.type === 'chunk') {
        if (event.replace) problem._feedback = event.content
        else { if (separator && !problem._feedback.includes(separator)) problem._feedback += separator; problem._feedback += event.content }
      }
      if (event.type === 'done') {
        if (event.mode === 'hint') problem._hintCount = event.hint_round || problem._hintCount + 1
        if (event.mode === 'full_review') { problem._scores = event.scores || null; problem._totalScore = event.total_score || 0; problem._referenceAnswer = event.reference_answer || ''; loadErrorStats() }
        problem._lastSubmission = event
      }
      if (event.type === 'error') toast.error(event.message || '评审失败')
    })
  } catch (error) { toast.error(error.message || '提交失败，请重试') } finally { problem._isSubmitting = false; problem._currentStep = '' }
}

async function loadErrorStats() { try { errorStats.value = await fetchCodingErrorStats() } catch { /* optional */ } }

onMounted(() => { loadPlaylists(); loadProblems(); loadErrorStats() })
</script>

<style scoped>
.coding-sidebar { transition: width 220ms ease, transform 220ms ease; }
@media (max-width: 767px) {
  .coding-sidebar { position: absolute; inset: 0 auto 0 0; width: min(84vw, 286px); max-width: calc(100vw - 24px); box-shadow: 18px 0 40px rgba(0, 0, 0, .14); }
  .coding-sidebar-collapsed { transform: translateX(-105%); pointer-events: none; }
}
</style>
