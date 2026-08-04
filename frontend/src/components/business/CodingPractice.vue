<template>
  <div class="flex flex-col gap-4">
    <!-- 题库配置态：结构与 MockInterview 的配置卡片保持一致 -->
    <div v-if="!activeProblem" class="rounded-xl border border-border bg-card shadow-sm overflow-hidden">
      <div class="border-b border-border px-4 py-3">
        <div class="flex items-center justify-between gap-3">
          <div class="flex items-center gap-3">
            <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
              <Code2 :size="19" class="text-white" />
            </div>
            <div>
              <h3 class="text-sm font-bold text-foreground">手撕代码</h3>
              <p class="text-caption text-muted-foreground">选择题目和难度，开始代码练习</p>
            </div>
          </div>
          <Button size="sm" class="gap-1.5" @click="importDialogOpen = true">
            <Sparkles :size="14" /> AI 导入题目
          </Button>
        </div>
      </div>

      <div class="p-4 flex flex-col gap-4">
        <!-- Library scope -->
        <div>
          <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <BookOpen :size="14" /> 题库范围
          </label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="item in libraryViews"
              :key="item.value"
              @click="selectLibraryView(item.value)"
              class="text-xs px-3 py-1.5 rounded-full border transition-colors inline-flex items-center gap-1.5"
              :class="libraryView === item.value && !selectedPlaylistId
                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold'
                : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
            >
              <component :is="item.icon" :size="13" />
              {{ item.label }}
            </button>
            <button
              v-for="playlist in playlists"
              :key="`playlist-${playlist.id}`"
              @click="selectPlaylist(playlist.id)"
              class="text-xs px-3 py-1.5 rounded-full border transition-colors inline-flex items-center gap-1.5"
              :class="selectedPlaylistId === playlist.id
                ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold'
                : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
            >
              <ListPlus :size="13" /> {{ playlist.name }} <span class="opacity-50">{{ playlist.problem_count }}</span>
            </button>
            <button
              @click="playlistDialogOpen = true"
              class="text-xs px-3 py-1.5 rounded-full border border-dashed border-border text-muted-foreground hover:bg-muted transition-colors inline-flex items-center gap-1.5"
            ><Plus :size="13" /> 新建题单</button>
          </div>
        </div>

        <!-- Search + difficulty -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <Search :size="14" /> 搜索题目
            </label>
            <div class="relative">
              <Search :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input v-model="searchQuery" class="h-9 pl-8 text-xs" placeholder="按题目或描述搜索" @keyup.enter="loadProblems" />
            </div>
          </div>
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <Zap :size="14" /> 难度
            </label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="opt in difficultyOptions"
                :key="opt.value || 'all'"
                @click="filterDifficulty = opt.value; loadProblems()"
                class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                :class="filterDifficulty === opt.value
                  ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold'
                  : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
              >{{ opt.label }}</button>
            </div>
          </div>
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5">
            <div class="text-caption text-muted-foreground">当前题目</div>
            <div class="mt-0.5 text-lg font-bold text-foreground">{{ problemTotal }}</div>
          </div>
          <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5">
            <div class="text-caption text-muted-foreground">已收藏</div>
            <div class="mt-0.5 text-lg font-bold text-amber-600">{{ favoriteCount }}</div>
          </div>
          <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5">
            <div class="text-caption text-muted-foreground">已通过</div>
            <div class="mt-0.5 text-lg font-bold text-emerald-600">{{ errorStats?.passed_submissions || 0 }}</div>
          </div>
          <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5">
            <div class="text-caption text-muted-foreground">总提交</div>
            <div class="mt-0.5 text-lg font-bold text-foreground">{{ errorStats?.total_submissions || 0 }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 题库列表：复用模拟面试的题目卡片语言 -->
    <div v-if="!activeProblem">
      <div v-if="isLoading" class="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground shadow-sm">
        <Loader2 :size="24" class="mx-auto mb-3 animate-spin text-primary" /> 正在加载题目...
      </div>
      <div v-else-if="!problems.length" class="rounded-xl border-2 border-dashed border-border py-10 text-center text-muted-foreground">
        <Code2 :size="28" class="mx-auto mb-3 opacity-60" />
        <p class="text-base">暂无符合条件的题目</p>
        <p class="mt-1 text-xs">请调整筛选条件，或使用 AI 导入 Markdown 题目。</p>
        <Button variant="outline" size="sm" class="mt-4 gap-1.5" @click="importDialogOpen = true"><Sparkles :size="14" /> AI 导入题目</Button>
      </div>
      <div v-else class="flex flex-col gap-4">
        <div v-for="(problem, index) in problems" :key="problem.id" class="border border-border rounded-xl overflow-hidden bg-card shadow-sm">
          <div class="p-4 border-b border-border">
            <div class="flex items-start gap-3">
              <div class="flex flex-col items-center justify-center bg-primary-100/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 font-bold rounded-lg p-2 min-w-[44px]">
                <span class="text-caption text-primary-400 dark:text-primary-500">第</span>
                <span class="text-xl leading-none">{{ index + 1 }}</span>
                <span class="text-caption text-primary-400 dark:text-primary-500">题</span>
              </div>
              <div class="flex-1 min-w-0">
                <div class="flex gap-2 mb-2 items-center flex-wrap">
                  <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold">{{ problem.source_type === 'imported' ? '我的题目' : '高频手撕' }}</span>
                  <span class="text-xs font-medium px-2 py-0.5 rounded" :class="difficultyClass(problem.difficulty)">{{ difficultyLabel(problem.difficulty) }}</span>
                  <span v-if="problem.attempt_count > 0" class="bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-xs px-2 py-0.5 rounded font-medium">已刷 {{ problem.attempt_count }} 次</span>
                  <span v-else class="bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 text-xs px-2 py-0.5 rounded font-medium">新题</span>
                  <button
                    :aria-label="problem.is_favorite ? '取消收藏' : '收藏题目'"
                    class="ml-1 text-lg leading-none transition-transform hover:scale-125"
                    :class="problem.is_favorite ? 'text-amber-500' : 'text-muted-foreground'"
                    @click.stop="toggleFavorite(problem)"
                  >{{ problem.is_favorite ? '★' : '☆' }}</button>
                  <span class="text-xs text-muted-foreground ml-auto">{{ problem.expected_complexity || '复杂度待补充' }}</span>
                </div>
                <h3 class="text-base lg:text-lg font-bold text-foreground leading-snug">{{ problem.title }}</h3>
                <div v-if="problem.tags?.length" class="mt-2 flex flex-wrap gap-1.5">
                  <span v-for="tag in problem.tags.slice(0, 4)" :key="tag" class="text-[11px] px-2 py-0.5 rounded-full bg-muted text-muted-foreground">{{ tag }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="px-4 py-3 border-t border-border bg-card flex items-center justify-between gap-3">
            <span class="text-xs text-muted-foreground">{{ problem.is_solved ? '已通过，可以继续巩固' : '先独立完成，再查看 AI 评审' }}</span>
            <Button size="sm" class="gap-1.5 px-4" @click="selectProblem(problem)"><Code2 :size="14" /> 开始练习</Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 练习态：结构与模拟面试的 summary + question card 对齐 -->
    <div v-else>
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4 bg-primary-50/60 dark:bg-primary-900/15 border border-border rounded-xl px-4 py-3">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-muted-foreground">当前：</span>
          <Badge variant="outline" class="bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">{{ activeProblem.source_type === 'imported' ? '我的题目' : '高频手撕' }}</Badge>
          <Badge variant="outline" class="bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">{{ difficultyLabel(activeProblem.difficulty) }}</Badge>
          <span class="text-muted-foreground/50">|</span>
          <span class="text-muted-foreground truncate max-w-[240px]">{{ activeProblem.title }}</span>
          <template v-if="activeProblem.attempt_count">
            <span class="text-muted-foreground/50">|</span>
            <span class="text-muted-foreground">已刷 {{ activeProblem.attempt_count }} 次</span>
          </template>
        </div>
        <div class="flex gap-2">
          <Button variant="default" size="sm" class="gap-1.5 px-4" @click="selectNextProblem"><ChevronRight :size="14" /> 换一道</Button>
          <Button variant="outline" size="sm" class="gap-1.5 px-4" @click="activeProblem = null"><BookOpen :size="14" /> 返回题库</Button>
        </div>
      </div>

      <div class="border border-border rounded-xl overflow-hidden bg-card shadow-sm">
        <div class="p-4 border-b border-border">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2 mb-2">
                <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold">题目 {{ activeProblem.id }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded" :class="difficultyClass(activeProblem.difficulty)">{{ difficultyLabel(activeProblem.difficulty) }}</span>
                <span v-if="activeProblem.expected_complexity" class="text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-mono">{{ activeProblem.expected_complexity }}</span>
              </div>
              <h2 class="text-lg font-bold text-foreground leading-snug">{{ activeProblem.title }}</h2>
            </div>
            <button
              :aria-label="activeProblem.is_favorite ? '取消收藏' : '收藏题目'"
              class="text-xl transition-transform hover:scale-110"
              :class="activeProblem.is_favorite ? 'text-amber-500' : 'text-muted-foreground'"
              @click="toggleFavorite(activeProblem)"
            >{{ activeProblem.is_favorite ? '★' : '☆' }}</button>
          </div>
        </div>

        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4 p-4">
          <div class="rounded-xl border border-border overflow-hidden">
            <div class="border-b border-border px-4 py-3 flex items-center justify-between">
              <div>
                <div class="text-xs font-semibold text-foreground">题目描述</div>
                <div class="text-caption text-muted-foreground mt-0.5">先讲思路，再写代码</div>
              </div>
              <ListPlus :size="15" class="text-muted-foreground" />
            </div>
            <div class="px-4 py-3 max-h-[520px] overflow-y-auto custom-scrollbar">
              <div class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem.description)" />
              <div v-if="activeProblem.tags?.length" class="mt-5 flex flex-wrap gap-1.5 border-t border-border pt-3">
                <span v-for="tag in activeProblem.tags" :key="tag" class="text-xs px-2.5 py-1 rounded-full bg-muted text-muted-foreground">{{ tag }}</span>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-border overflow-hidden">
            <div class="border-b border-border px-4 py-2.5 flex items-center justify-between gap-2">
              <div class="flex items-center gap-1">
                <span class="text-xs font-semibold text-foreground mr-1">你的代码</span>
                <button
                  v-for="language in languageOptions"
                  :key="language.value"
                  @click="currentLanguage = language.value"
                  class="text-xs px-2.5 py-1 rounded-full border transition-colors"
                  :class="currentLanguage === language.value ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted'"
                >{{ language.label }}</button>
              </div>
              <span v-if="activeProblem._isSubmitting" class="flex items-center gap-1 text-caption text-primary"><Loader2 :size="12" class="animate-spin" /> {{ activeProblem._currentStep || '分析中' }}</span>
            </div>
            <div class="h-[390px] p-2">
              <CodeEditor v-model="activeProblem._code" :language="currentLanguage" :read-only="activeProblem._isSubmitting" />
            </div>
            <div class="border-t border-border bg-card px-3 py-3 flex flex-wrap items-center justify-between gap-2">
              <Button variant="ghost" size="sm" class="text-xs text-muted-foreground" @click="clearProblem(activeProblem)">清空代码</Button>
              <div class="flex gap-2">
                <Button variant="outline" size="sm" class="gap-1.5" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3" @click="submitCode(activeProblem, 'hint')"><Zap :size="14" /> 提示 {{ activeProblem._hintCount }}/3</Button>
                <Button size="sm" class="gap-1.5" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()" @click="submitCode(activeProblem, 'full_review')"><Sparkles :size="14" /> 提交评审</Button>
              </div>
            </div>
          </div>
        </div>

        <!-- Evaluation result -->
        <div v-if="activeProblem._feedback || activeProblem._scores" class="px-5 py-4 border-t border-border bg-primary-50/40 dark:bg-primary-900/10">
          <div class="flex items-center justify-between gap-3 mb-3">
            <h4 class="text-sm font-bold text-foreground flex items-center gap-1.5"><Sparkles :size="15" class="text-primary" /> AI 评估结果</h4>
            <div v-if="activeProblem._scores" class="flex items-baseline gap-1"><span class="text-3xl font-extrabold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}</span><span class="text-xs text-muted-foreground">/ 100</span></div>
          </div>
          <div v-if="activeProblem._scores" class="flex flex-col gap-2 mb-4">
            <div v-for="(score, key) in activeProblem._scores" :key="key" class="flex items-center gap-2">
              <span class="text-xs text-muted-foreground w-14 shrink-0">{{ categoryLabels[key] || key }}</span>
              <div class="bg-muted rounded-full h-2 flex-1 overflow-hidden"><div class="h-full rounded-full transition-all" :class="scoreColor(score * 20)" :style="{ width: `${score / 5 * 100}%` }" /></div>
              <span class="text-xs font-bold w-8 text-right" :class="scoreTextColor(score * 20)">{{ score }}/5</span>
            </div>
          </div>
          <div v-if="activeProblem._feedback" class="answer-content prose prose-sm max-w-none dark:prose-invert" v-html="renderMarkdown(activeProblem._feedback)" />
          <div v-if="activeProblem._referenceAnswer" class="mt-4 border-t border-border pt-3">
            <div class="text-xs font-semibold text-primary mb-2">参考答案（基于你的代码最小修改）</div>
            <div class="h-56 rounded-lg overflow-hidden border border-border"><CodeEditor :model-value="cleanCode(activeProblem._referenceAnswer)" :language="currentLanguage" :read-only="true" /></div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI 导入 -->
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
          <div class="flex flex-col gap-1.5"><label class="text-xs font-semibold text-foreground">告诉 AI 你想怎么整理（可选）</label><Textarea v-model="importPrompt" :rows="3" placeholder="例如：提取所有二叉树和链表题，统一补充输入输出、约束和复杂度，难度按面试难度标注。" /></div>
          <p v-if="importError" class="text-xs text-destructive">{{ importError }}</p>
        </div>
        <DialogFooter><Button variant="outline" @click="importDialogOpen = false">取消</Button><Button class="gap-1.5" :disabled="isImporting || !importMarkdown" @click="importProblems"><Loader2 v-if="isImporting" :size="14" class="animate-spin" /><Sparkles v-else :size="14" /> {{ isImporting ? 'AI 整理中...' : '开始导入' }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- 题单 -->
    <Dialog v-model:open="playlistDialogOpen">
      <DialogContent class="max-w-md">
        <DialogHeader><DialogTitle>{{ activeProblem ? '加入题单' : '新建题单' }}</DialogTitle><DialogDescription>{{ activeProblem ? '选择一个题单，方便下次集中复习。' : '为你的专项训练建立一个清晰的复习路径。' }}</DialogDescription></DialogHeader>
        <div v-if="activeProblem && playlists.length" class="flex max-h-48 flex-col gap-1 overflow-y-auto"><Button v-for="playlist in playlists" :key="playlist.id" variant="outline" class="h-10 justify-between" @click="addToPlaylist(playlist)"><span class="flex items-center gap-2"><ListPlus :size="14" /> {{ playlist.name }}</span><span class="text-xs text-muted-foreground">{{ playlist.problem_count }} 题</span></Button></div>
        <div class="flex flex-col gap-3"><div class="flex flex-col gap-1.5"><label class="text-xs font-semibold">{{ activeProblem ? '新建题单' : '题单名称' }}</label><Input v-model="playlistName" placeholder="例如：字节后端高频题" @keyup.enter="createPlaylist" /></div><div v-if="!activeProblem" class="flex flex-col gap-1.5"><label class="text-xs font-semibold">描述（可选）</label><Textarea v-model="playlistDescription" :rows="2" placeholder="这个题单用于什么场景？" /></div></div>
        <DialogFooter><Button variant="outline" @click="playlistDialogOpen = false">取消</Button><Button :disabled="isCreatingPlaylist || !playlistName.trim()" @click="createPlaylist">{{ isCreatingPlaylist ? '创建中...' : '创建题单' }}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BookOpen, ChevronRight, Code2, FilePlus2, ListPlus, Loader2, Plus, Search, Sparkles, Star, Upload, Zap } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { useToast } from '@/composables/useNotification.js'
import CodeEditor from './CodeEditor.vue'
import { addCodingPlaylistItem, createCodingPlaylist, fetchCodingErrorStats, fetchCodingPlaylists, fetchCodingProblem, fetchCodingProblems, importCodingProblems, submitCodingCode, toggleCodingFavorite } from '@/services/codingApi.js'

const { toast } = useToast()
const difficultyOptions = [{ value: '', label: '全部' }, { value: 'easy', label: '简单' }, { value: 'medium', label: '中等' }, { value: 'hard', label: '困难' }]
const languageOptions = [{ value: 'python', label: 'Python' }, { value: 'c', label: 'C' }, { value: 'java', label: 'Java' }]
const libraryViews = [{ value: 'all', label: '全部题目', icon: BookOpen }, { value: 'favorites', label: '我的收藏', icon: Star }]
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

const favoriteCount = computed(() => problems.value.filter(problem => problem.is_favorite).length)
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

async function selectProblem(problem) {
  activeProblem.value = problem
  try { Object.assign(problem, await fetchCodingProblem(problem.id)) } catch (error) { toast.error(error.message || '获取题目详情失败') }
}

function selectLibraryView(view) { libraryView.value = view; selectedPlaylistId.value = null; loadProblems() }
function selectPlaylist(id) { selectedPlaylistId.value = id; libraryView.value = 'all'; loadProblems() }

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
      if (event.type === 'done') { if (event.mode === 'hint') problem._hintCount = event.hint_round || problem._hintCount + 1; if (event.mode === 'full_review') { problem._scores = event.scores || null; problem._totalScore = event.total_score || 0; problem._referenceAnswer = event.reference_answer || ''; loadErrorStats() } problem._lastSubmission = event }
      if (event.type === 'error') toast.error(event.message || '评审失败')
    })
  } catch (error) { toast.error(error.message || '提交失败，请重试') } finally { problem._isSubmitting = false; problem._currentStep = '' }
}

async function loadErrorStats() { try { errorStats.value = await fetchCodingErrorStats() } catch { /* optional */ } }
onMounted(() => { loadPlaylists(); loadProblems(); loadErrorStats() })
</script>
