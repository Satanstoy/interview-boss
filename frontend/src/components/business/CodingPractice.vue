<template>
  <div class="relative flex h-full overflow-hidden bg-background">
    <div
      v-if="!sidebarCollapsed"
      class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden"
      @click="sidebarCollapsed = true"
    />

    <!-- Coding library sidebar: same shell as ChatView's conversation list -->
    <div
      class="sidebar-container z-30 border-r border-border bg-background flex flex-col shrink-0 overflow-hidden md:z-auto"
      :class="{ 'sidebar-collapsed': sidebarCollapsed }"
      :style="{ width: sidebarCollapsed ? '0px' : '16rem' }"
    >
      <div class="flex shrink-0 items-center gap-2 p-2 sidebar-content">
        <Button class="flex-1 gap-1.5" size="sm" @click="activeProblem = null">
          <Code2 :size="16" />
          手撕代码
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="size-7 shrink-0 text-muted-foreground"
          aria-label="收起题库侧栏"
          @click="sidebarCollapsed = true"
        >
          <PanelLeftClose :size="14" />
        </Button>
      </div>

      <div class="flex-1 overflow-y-auto custom-scrollbar px-2 pb-2 sidebar-content">
        <div class="flex items-center justify-between px-2 py-2">
          <div>
            <div class="text-sm font-semibold text-foreground">题库</div>
            <div class="mt-0.5 text-[11px] text-muted-foreground">{{ problemTotal }} 道手撕题</div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            class="size-7 text-muted-foreground"
            aria-label="AI 导入题目"
            @click="importDialogOpen = true"
          >
            <Sparkles :size="14" />
          </Button>
        </div>

        <div class="relative px-1">
          <Search :size="14" class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            v-model="searchQuery"
            class="h-8 rounded-lg border-0 bg-muted pl-8 text-xs shadow-none"
            placeholder="搜索题目"
            @keyup.enter="loadProblems"
          />
        </div>

        <div class="mt-3 flex flex-wrap gap-1.5 px-1">
          <button
            v-for="option in difficultyOptions"
            :key="option.value || 'all'"
            class="rounded-full px-2.5 py-1 text-[11px] transition-colors"
            :class="filterDifficulty === option.value
              ? 'bg-primary/10 font-medium text-primary'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="filterDifficulty = option.value; loadProblems()"
          >{{ option.label }}</button>
        </div>

        <div class="mt-3 flex flex-col gap-0.5">
          <button
            v-for="item in libraryViews"
            :key="item.value"
            class="group relative flex w-full items-center gap-2 rounded-md p-2 text-left text-sm transition-colors"
            :class="libraryView === item.value && !selectedPlaylistId
              ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
              : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
            @click="selectLibraryView(item.value)"
          >
            <component :is="item.icon" :size="14" class="shrink-0" />
            <span class="truncate">{{ item.label }}</span>
            <span v-if="item.value === 'favorites'" class="ml-auto text-[11px] text-muted-foreground">{{ favoriteCount }}</span>
          </button>
        </div>

        <div class="mt-4 border-t border-border/60 pt-3">
          <div class="flex items-center justify-between px-2 pb-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">题单</span>
            <Button
              variant="ghost"
              size="icon"
              class="size-6 text-muted-foreground"
              aria-label="新建题单"
              @click="playlistDialogOpen = true"
            >
              <Plus :size="13" />
            </Button>
          </div>
          <button
            v-for="playlist in playlists"
            :key="`playlist-${playlist.id}`"
            class="flex w-full items-center gap-2 rounded-md p-2 text-left text-sm transition-colors"
            :class="selectedPlaylistId === playlist.id
              ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
              : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
            @click="selectPlaylist(playlist.id)"
          >
            <ListPlus :size="14" class="shrink-0" />
            <span class="min-w-0 flex-1 truncate">{{ playlist.name }}</span>
            <span class="text-[11px] text-muted-foreground">{{ playlist.problem_count }}</span>
          </button>
          <div v-if="!playlists.length" class="px-2 py-2 text-[11px] text-muted-foreground">还没有题单</div>
        </div>

        <div class="mt-4 border-t border-border/60 pt-3">
          <div class="flex items-center justify-between px-2 pb-1">
            <span class="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">题目</span>
            <Loader2 v-if="isLoading" :size="13" class="animate-spin text-primary" />
          </div>
          <div v-if="!problems.length && !isLoading" class="px-2 py-3 text-xs text-muted-foreground">暂无符合条件的题目</div>
          <button
            v-for="problem in problems"
            :key="problem.id"
            class="group flex w-full items-center gap-2 rounded-md p-2 text-left text-sm transition-colors"
            :class="activeProblem?.id === problem.id
              ? 'bg-sidebar-accent font-medium text-sidebar-accent-foreground'
              : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
            @click="selectProblem(problem)"
          >
            <div class="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Code2 :size="13" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="truncate">{{ problem.title }}</div>
              <div class="mt-0.5 truncate text-[11px] text-muted-foreground">
                {{ difficultyLabel(problem.difficulty) }} · {{ problem.attempt_count || 0 }} 次练习
              </div>
            </div>
            <span v-if="problem.is_favorite" class="shrink-0 text-amber-500">★</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Sidebar collapsed: same affordance as ChatView -->
    <div v-if="sidebarCollapsed" class="hidden flex-col items-center gap-1 px-2 py-2 shrink-0 sidebar-expand-buttons md:flex">
      <Button variant="ghost" size="icon" class="size-7" aria-label="展开题库侧栏" @click="sidebarCollapsed = false">
        <PanelLeft :size="14" />
      </Button>
      <Button variant="ghost" size="icon" class="size-7" aria-label="AI 导入题目" @click="importDialogOpen = true">
        <Sparkles :size="14" />
      </Button>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Mobile header mirrors ChatView's session switcher -->
      <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2 md:hidden">
        <Button
          variant="outline"
          size="sm"
          class="h-8 shrink-0 gap-1.5 rounded-lg text-xs"
          aria-label="切换题库"
          @click="sidebarCollapsed = false"
        >
          <PanelLeft :size="14" />
          <span>切换题库</span>
        </Button>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">{{ activeProblem?.title || '手撕代码' }}</span>
      </div>

      <!-- Empty state mirrors ChatView's centered start screen -->
      <div v-if="!activeProblem" class="flex min-h-0 flex-1 flex-col overflow-y-auto custom-scrollbar">
        <div class="flex min-h-full w-full max-w-2xl flex-col items-center px-6 pb-8 pt-16 mx-auto">
          <div class="mx-auto mb-6 flex size-20 items-center justify-center rounded-xl bg-primary/10">
            <Code2 :size="40" class="text-primary" />
          </div>
          <h2 class="mb-3 text-center text-3xl font-bold text-foreground">开始手撕代码</h2>
          <p class="mb-8 text-center text-lg text-muted-foreground">从左侧题库选择一道题，开始你的代码面试练习</p>

          <div class="grid w-full max-w-lg grid-cols-2 gap-4">
            <button
              class="group flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/30 hover:bg-accent/50"
              @click="selectLibraryView('all'); sidebarCollapsed = false"
            >
              <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 transition-colors group-hover:bg-primary/20">
                <BookOpen :size="20" class="text-primary" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">全部题目</div>
                <div class="mt-1 text-xs text-muted-foreground">浏览 {{ problemTotal }} 道手撕题</div>
              </div>
            </button>
            <button
              class="group flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/30 hover:bg-accent/50"
              @click="selectLibraryView('favorites'); sidebarCollapsed = false"
            >
              <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 transition-colors group-hover:bg-amber-500/20">
                <Star :size="20" class="text-amber-500" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">我的收藏</div>
                <div class="mt-1 text-xs text-muted-foreground">{{ favoriteCount }} 道待复习</div>
              </div>
            </button>
            <button
              class="group flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/30 hover:bg-accent/50"
              @click="playlistDialogOpen = true"
            >
              <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-sky-500/10 transition-colors group-hover:bg-sky-500/20">
                <ListPlus :size="20" class="text-sky-500" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">专项题单</div>
                <div class="mt-1 text-xs text-muted-foreground">按目标组织复习路径</div>
              </div>
            </button>
            <button
              class="group flex items-start gap-3 rounded-xl border border-border bg-card p-4 text-left transition-all hover:border-primary/30 hover:bg-accent/50"
              @click="importDialogOpen = true"
            >
              <div class="flex size-10 shrink-0 items-center justify-center rounded-lg bg-violet-500/10 transition-colors group-hover:bg-violet-500/20">
                <Sparkles :size="20" class="text-violet-500" />
              </div>
              <div>
                <div class="text-sm font-semibold text-foreground">AI 导入题目</div>
                <div class="mt-1 text-xs text-muted-foreground">Prompt + Markdown 整理面经</div>
              </div>
            </button>
          </div>

          <div class="mt-8 grid w-full max-w-lg grid-cols-3 gap-3">
            <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5 text-center">
              <div class="text-lg font-bold text-foreground">{{ problemTotal }}</div>
              <div class="text-[11px] text-muted-foreground">题目</div>
            </div>
            <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5 text-center">
              <div class="text-lg font-bold text-amber-600">{{ favoriteCount }}</div>
              <div class="text-[11px] text-muted-foreground">收藏</div>
            </div>
            <div class="rounded-xl border border-border bg-muted/30 px-3 py-2.5 text-center">
              <div class="text-lg font-bold text-emerald-600">{{ errorStats?.passed_submissions || 0 }}</div>
              <div class="text-[11px] text-muted-foreground">已通过</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Active problem: same header / message stream / composer rhythm as ChatView -->
      <template v-else>
        <div class="hidden items-center justify-between px-6 py-1.5 shrink-0 md:flex">
          <div class="min-w-0 flex-1">
            <div class="flex max-w-full items-center gap-2 px-1 py-0.5 text-left">
              <Code2 :size="14" class="shrink-0 text-primary" />
              <span class="truncate text-sm font-semibold text-foreground">{{ activeProblem.title }}</span>
              <button
                :aria-label="activeProblem.is_favorite ? '取消收藏' : '收藏题目'"
                class="shrink-0 text-base leading-none transition-transform hover:scale-110"
                :class="activeProblem.is_favorite ? 'text-amber-500' : 'text-muted-foreground'"
                @click="toggleFavorite(activeProblem)"
              >{{ activeProblem.is_favorite ? '★' : '☆' }}</button>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <Badge variant="outline" class="rounded-full bg-muted/60 px-2 py-0.5 text-[11px] text-muted-foreground">{{ difficultyLabel(activeProblem.difficulty) }}</Badge>
            <Button variant="ghost" size="sm" class="h-7 gap-1.5 px-2 text-xs text-muted-foreground" @click="activeProblem = null">
              <BookOpen :size="13" /> 返回题库
            </Button>
            <Button variant="ghost" size="sm" class="h-7 gap-1.5 px-2 text-xs text-muted-foreground" @click="selectNextProblem">
              换一道 <ChevronRight :size="13" />
            </Button>
          </div>
        </div>

        <div class="flex min-h-0 flex-1 overflow-y-auto custom-scrollbar">
          <div class="mx-auto w-full max-w-3xl px-6 pb-8 pt-8">
            <div class="mb-8 group">
              <div class="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
                <div class="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Code2 :size="16" />
                </div>
                <span class="font-medium">手撕代码题目</span>
                <span class="text-muted-foreground/50">·</span>
                <span>{{ activeProblem.source_type === 'imported' ? '我的题目' : '高频手撕' }}</span>
                <span v-if="activeProblem.attempt_count" class="text-muted-foreground/60">· 已练习 {{ activeProblem.attempt_count }} 次</span>
              </div>
              <div class="prose-chat text-sm leading-relaxed">
                <h1 class="mb-3 text-2xl font-bold text-foreground">{{ activeProblem.title }}</h1>
                <div v-html="renderMarkdown(activeProblem.description)" />
              </div>
              <div v-if="activeProblem.tags?.length" class="mt-4 flex flex-wrap gap-1.5">
                <span v-for="tag in activeProblem.tags" :key="tag" class="rounded-full bg-muted px-2.5 py-1 text-xs text-muted-foreground">{{ tag }}</span>
              </div>
              <div class="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                <span v-if="activeProblem.expected_complexity" class="rounded-full bg-muted/60 px-2.5 py-1 font-mono">复杂度 {{ activeProblem.expected_complexity }}</span>
                <button class="rounded-full px-2.5 py-1 text-primary hover:bg-primary/10" @click="playlistDialogOpen = true">+ 加入题单</button>
              </div>
            </div>

            <!-- AI evaluation is rendered like an assistant response, without a heavy IDE card -->
            <div v-if="activeProblem._feedback || activeProblem._scores" class="mb-8">
              <div class="mb-3 flex items-center gap-2 text-xs text-muted-foreground">
                <div class="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Sparkles :size="15" />
                </div>
                <span class="font-medium">AI 评审</span>
                <span v-if="activeProblem._totalScore" class="ml-auto text-sm font-bold" :class="scoreTextColor(activeProblem._totalScore)">{{ activeProblem._totalScore }}/100</span>
              </div>
              <div v-if="activeProblem._scores" class="mb-4 flex flex-col gap-2 rounded-xl border border-border/50 bg-muted/30 p-3">
                <div v-for="(score, key) in activeProblem._scores" :key="key" class="flex items-center gap-2">
                  <span class="w-14 shrink-0 text-xs text-muted-foreground">{{ categoryLabels[key] || key }}</span>
                  <div class="h-2 flex-1 overflow-hidden rounded-full bg-muted"><div class="h-full rounded-full transition-all" :class="scoreColor(score * 20)" :style="{ width: `${score / 5 * 100}%` }" /></div>
                  <span class="w-8 text-right text-xs font-bold" :class="scoreTextColor(score * 20)">{{ score }}/5</span>
                </div>
              </div>
              <div v-if="activeProblem._feedback" class="prose-chat text-sm leading-relaxed" v-html="renderMarkdown(activeProblem._feedback)" />
              <div v-if="activeProblem._referenceAnswer" class="mt-5 border-t border-border/50 pt-4">
                <div class="mb-2 text-xs font-medium text-muted-foreground">参考答案（基于你的代码最小修改）</div>
                <div class="h-56 overflow-hidden rounded-lg border border-border/50 bg-muted/30"><CodeEditor :model-value="cleanCode(activeProblem._referenceAnswer)" :language="currentLanguage" :read-only="true" /></div>
              </div>
            </div>
          </div>
        </div>

        <!-- Composer-like fixed coding area mirrors ChatView's input composer -->
        <div class="shrink-0">
          <div class="mx-auto w-full max-w-3xl px-6 pb-4">
            <div class="chat-input-area flex flex-col gap-2 rounded-xl bg-muted p-2">
              <div class="flex items-center justify-between gap-2 px-1">
                <div class="flex items-center gap-1">
                  <span class="mr-1 text-xs font-medium text-foreground">你的代码</span>
                  <button
                    v-for="language in languageOptions"
                    :key="language.value"
                    class="rounded-full px-2.5 py-1 text-[11px] transition-colors"
                    :class="currentLanguage === language.value ? 'bg-background font-medium text-foreground shadow-sm' : 'text-muted-foreground hover:bg-background/70 hover:text-foreground'"
                    @click="currentLanguage = language.value"
                  >{{ language.label }}</button>
                </div>
                <span v-if="activeProblem._isSubmitting" class="flex items-center gap-1 text-[11px] text-primary"><Loader2 :size="12" class="animate-spin" /> {{ activeProblem._currentStep || '分析中' }}</span>
                <button v-else class="rounded-lg px-2 py-1 text-[11px] text-muted-foreground hover:bg-background hover:text-foreground" @click="clearProblem(activeProblem)">清空</button>
              </div>
              <div class="h-[280px] overflow-hidden rounded-lg border border-border/50 bg-background">
                <CodeEditor v-model="activeProblem._code" :language="currentLanguage" :read-only="activeProblem._isSubmitting" />
              </div>
              <div class="flex items-center justify-between gap-2 px-1">
                <span class="text-[11px] text-muted-foreground">先独立完成，再让 AI 给出提示或评审</span>
                <div class="flex gap-2">
                  <Button variant="outline" size="sm" class="h-8 gap-1.5 rounded-lg text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim() || activeProblem._hintCount >= 3" @click="submitCode(activeProblem, 'hint')"><Zap :size="13" /> 提示 {{ activeProblem._hintCount }}/3</Button>
                  <Button size="sm" class="h-8 gap-1.5 rounded-lg text-xs" :disabled="activeProblem._isSubmitting || !activeProblem._code.trim()" @click="submitCode(activeProblem, 'full_review')"><Sparkles :size="13" /> 提交评审</Button>
                </div>
              </div>
            </div>
            <div class="mt-2 flex items-center justify-between px-1">
              <span class="text-[11px] text-muted-foreground">代码会保存在当前题目中</span>
              <span class="text-[11px] text-muted-foreground">支持 Python / C / Java</span>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- AI import dialog -->
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

    <!-- Playlist dialog -->
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
import { BookOpen, ChevronRight, Code2, FilePlus2, ListPlus, Loader2, PanelLeft, PanelLeftClose, Plus, Search, Sparkles, Star, Upload, Zap } from '@lucide/vue'
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
const isMobileViewport = () => window.matchMedia('(max-width: 767px)').matches
const sidebarCollapsed = ref(isMobileViewport())

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
  if (isMobileViewport()) sidebarCollapsed.value = true
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

<style scoped>
/* Keep the coding workbench motion and collapse behavior in lockstep with ChatView. */
.sidebar-container {
  transition: width 380ms cubic-bezier(0.4, 0, 0.2, 1);
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

.chat-input-area textarea {
  background-color: transparent !important;
  border: none !important;
  outline: none !important;
  box-shadow: none !important;
  -webkit-appearance: none !important;
  appearance: none !important;
  font-family: inherit;
  color: var(--foreground);
}
</style>
