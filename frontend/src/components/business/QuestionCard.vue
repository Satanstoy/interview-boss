<template>
  <div
    :class="contentOnly
      ? 'bg-muted/30 dark:bg-muted/15 relative group answer-section'
      : 'overflow-hidden rounded-xl border border-border bg-card shadow-sm transition-all duration-200 hover:border-border dark:hover:border-border' + (isSelected(question.id) ? ' border-primary/40 dark:border-primary/30 ring-2 ring-primary/15 dark:ring-primary/20' : '')"
  >
    <!-- Card header (normal mode only) -->
    <div v-if="!contentOnly" class="p-4 flex gap-3 items-start cursor-pointer hover:bg-muted/40 dark:hover:bg-muted/20 transition-colors duration-200" @click="$emit('toggle-answer', question)">
      <div class="flex items-center self-stretch" @click.stop>
        <input type="checkbox" :checked="isSelected(question.id)" @change="$emit('toggle-item', question.id)"
          class="size-4 rounded border-input text-primary shadow-xs focus-visible:ring-3 focus-visible:ring-ring/50 cursor-pointer transition">
      </div>

      <div class="flex-1 min-w-0">
        <!-- Question text (primary — most prominent) -->
        <div class="flex items-start gap-2 group mb-2">
          <h3 class="text-[15px] font-semibold text-foreground leading-snug flex-1">{{ question.question }}</h3>
          <AppTooltip v-if="canShare" text="分享到公共题库">
            <Button
              variant="ghost" size="sm" class="size-7 p-0 text-muted-foreground hover:text-primary"
              aria-label="分享到公共题库"
              @click.stop="$emit('share', question)"
            >
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"/></svg>
            </Button>
          </AppTooltip>
          <AppTooltip v-if="canEdit" text="编辑题目">
            <button @click.stop="startEditQuestion"
              class="flex min-h-9 shrink-0 items-center gap-1 rounded-md px-2 text-muted-foreground transition-all duration-200 hover:bg-muted hover:text-primary sm:min-h-0 sm:px-1 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100">
              <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
              <span class="text-xs sm:hidden">编辑</span>
            </button>
          </AppTooltip>
        </div>

        <!-- Metadata row (secondary — smaller, lighter) -->
        <div class="flex gap-1.5 items-center flex-wrap">
          <!-- Frequency: prominent badge -->
          <span class="inline-flex flex-col items-center justify-center bg-red-50 dark:bg-red-900/25 text-red-600 dark:text-red-400 font-bold rounded-md px-2 py-1 min-w-[36px] border border-red-100 dark:border-red-800/50">
            <span class="text-label text-red-400 dark:text-red-500 mb-0.5">频率</span>
            <span class="text-base leading-none">{{ question.frequency }}</span>
          </span>

          <!-- Category tag: primary color, single badge -->
          <Badge variant="outline" class="rounded-md bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">
            {{ question.cat1 || '未分类' }}
          </Badge>

          <!-- Tags: neutral, max 3 shown -->
          <Badge variant="outline" v-for="tag in parsedTags.slice(0, 3)" :key="tag" class="rounded-md bg-muted dark:bg-card/80 text-muted-foreground dark:text-muted-foreground text-label">
            {{ tag }}
          </Badge>
          <span v-if="parsedTags.length > 3" class="text-caption text-muted-foreground dark:text-muted-foreground">+{{ parsedTags.length - 3 }}</span>

          <!-- Position badge -->
          <Badge variant="outline" v-if="question.job_position" class="rounded-md text-label bg-muted dark:bg-card/80 text-muted-foreground dark:text-muted-foreground">
            {{ formatPosition(question.job_position) }}
          </Badge>

          <!-- Difficulty: semantic color (the only strong color on the row) -->
          <Badge variant="outline" class="ml-auto" :class="difficultyClass">
            {{ question.difficulty || '-' }}
          </Badge>

          <!-- Practice status: compact -->
          <Badge variant="outline" v-if="practiceInfo" class="text-label"
            :class="practiceInfo.best_score >= 80 ? 'bg-emerald-50 dark:bg-emerald-900/25 text-emerald-600 dark:text-emerald-400' : practiceInfo.best_score >= 60 ? 'bg-amber-50 dark:bg-amber-900/25 text-amber-600 dark:text-amber-400' : 'bg-red-50 dark:bg-red-900/25 text-red-500 dark:text-red-400'">
            {{ practiceInfo.best_score }}
          </Badge>
          <Badge variant="outline" v-else class="rounded-md text-label bg-muted dark:bg-card/80 text-muted-foreground dark:text-muted-foreground">New</Badge>
        </div>

        <!-- Actions row: hover-reveal for secondary actions -->
        <div class="mt-2 flex gap-1.5 opacity-100 transition-opacity duration-200 sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
          <Button variant="ghost" size="sm" v-if="isAdmin" @click.stop="$emit('retag', question)" :disabled="question._isRetagging"
            class="px-2 py-1 flex items-center gap-1">
            <svg v-if="question._isRetagging" class="animate-spin size-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            {{ question._isRetagging ? '分类中...' : '重新分类' }}
          </Button>
          <AppTooltip v-if="canDelete" text="删除">
            <Button variant="ghost" size="sm" @click.stop="$emit('delete', question)" class="px-2 py-1 text-destructive hover:bg-destructive/10 dark:hover:bg-destructive/15 transition-all duration-200">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
              </svg>
            </Button>
          </AppTooltip>
        </div>
      </div>

      <!-- Practice button (always visible, primary action) -->
      <AppTooltip text="做题">
        <Button variant="default" size="sm" @click.stop="$emit('practice', question)"
          class="shrink-0 text-xs px-2.5 py-1 font-semibold">
          <svg class="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"/></svg>
          做题
        </Button>
      </AppTooltip>

      <!-- Star (always visible, tertiary action) -->
      <AppTooltip :text="question.is_starred ? '取消收藏' : '收藏'">
        <button @click.stop="$emit('toggle-star', question)" class="star-btn flex min-h-9 shrink-0 items-center gap-1 rounded-md px-2 transition-colors duration-200 hover:bg-muted sm:min-h-0 sm:px-1">
          <svg class="size-4.5 transition-colors" :class="question.is_starred ? 'text-amber-400' : 'text-border dark:text-foreground hover:text-amber-300 dark:hover:text-amber-500'" :fill="question.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/>
          </svg>
          <span class="text-xs text-muted-foreground sm:hidden">{{ question.is_starred ? '取消收藏' : '收藏' }}</span>
        </button>
      </AppTooltip>

      <!-- Expand chevron -->
      <div class="text-muted-foreground dark:text-muted-foreground mt-0.5 shrink-0">
        <svg class="size-4 transform transition-transform duration-200" :class="question._showAnswer ? 'rotate-180 text-primary dark:text-primary' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
      </div>
    </div>

    <!-- Answer section: always rendered in contentOnly mode; v-if for toggle in normal mode -->
    <div v-if="contentOnly || question._showAnswer" :class="contentOnly ? '' : 'border-t border-border bg-muted/30 dark:bg-muted/15 relative group answer-section'">

      <div v-if="contentOnly" class="flex items-center gap-2 border-b border-border/70 bg-background/70 px-3 py-2">
        <Button size="sm" class="h-10 flex-1 gap-1.5 text-xs sm:h-8 sm:flex-none" @click="$emit('practice', question)">
          <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 20h9"/><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4Z"/></svg>
          开始练习这道题
        </Button>
        <Button variant="ghost" size="sm" class="h-10 gap-1.5 px-2 text-xs text-muted-foreground sm:h-8" @click="$emit('toggle-star', question)">
          <svg class="size-4" :class="question.is_starred ? 'fill-amber-400 text-amber-500' : ''" :fill="question.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/></svg>
          {{ question.is_starred ? '已收藏' : '收藏' }}
        </Button>
      </div>

      <!-- Ownership badge + share action (visible in all modes) -->
      <div v-if="showOwnership || canShare" class="flex items-center gap-2 px-3 pt-3 sm:px-4">
        <Badge v-if="showOwnership" variant="outline" class="text-label"
          :class="question.is_personal
            ? 'bg-violet-50 dark:bg-violet-900/25 text-violet-600 dark:text-violet-400'
            : 'bg-teal-50 dark:bg-teal-900/25 text-teal-600 dark:text-teal-400'">
          {{ showOwnership ? '私有' : '公共' }}
        </Badge>
        <Button v-if="canShare" variant="ghost" size="sm"
          class="h-7 px-2 text-xs text-muted-foreground hover:text-primary"
          aria-label="分享到公共题库"
          @click.stop="$emit('share', question)">
          分享到公共题库
        </Button>
      </div>

      <!-- Answer (primary content — shown first) -->
      <div class="pb-0" :class="contentOnly ? 'px-0 pt-0' : 'px-4 pt-3'">
        <!-- Edit answer mode -->
        <div v-if="question._isEditingAnswer" class="flex flex-col gap-3">
          <label class="font-bold text-foreground text-sm">编辑答案</label>
          <textarea v-model="localQuestion._editAnswer" rows="8" class="w-full max-w-3xl border border-input rounded-lg p-4 text-sm focus:outline-none focus:ring-1 focus:ring-ring font-mono bg-transparent text-foreground transition-all duration-200"></textarea>
          <div class="flex gap-2 justify-end mt-2">
            <Button variant="outline" size="sm" @click="localQuestion._isEditingAnswer = false" class="px-5">取消</Button>
            <Button variant="default" size="sm" @click="isAdmin ? $emit('save-field', { tableName: 'question_bank', recordId: question.id, dbColumn: 'ai_answer', newValue: localQuestion._editAnswer, rowObj: localQuestion, editStateKey: '_isEditingAnswer', frontendKey: 'ai_answer' }) : $emit('save-user-answer', { question: localQuestion, answer: localQuestion._editAnswer })" class="px-5">保存</Button>
          </div>
        </div>

        <!-- View answer mode -->
        <div v-else>
            <div v-if="displayAnswer && !isFailedAnswer(displayAnswer)" class="relative group/answer">
            <div v-if="isAdmin" class="absolute top-0 right-0 flex gap-1 z-10">
              <button @click="localQuestion._isEditingAnswer = true; localQuestion._editAnswer = displayAnswer" class="rounded-md bg-white/80 px-2.5 py-1 text-caption text-muted-foreground opacity-100 transition-all duration-200 hover:bg-muted sm:opacity-0 sm:group-hover/answer:opacity-100 sm:focus-visible:opacity-100 dark:bg-muted/60 dark:hover:bg-muted">
                编辑
              </button>
              <button @click.stop="$emit('generate-answer', question)" :disabled="question._isLoadingAnswer" class="rounded-md bg-white/80 px-2.5 py-1 text-caption text-muted-foreground opacity-100 transition-all duration-200 hover:bg-muted disabled:cursor-not-allowed disabled:opacity-30 sm:opacity-0 sm:group-hover/answer:opacity-100 sm:focus-visible:opacity-100 dark:bg-muted/60 dark:hover:bg-muted">
                重新生成
              </button>
            </div>
            <div class="answer-content prose prose-sm max-w-none rounded-md border border-border bg-card px-3 py-3 text-sm leading-7 text-foreground dark:prose-invert sm:px-4" v-html="cachedMarkdown"></div>

            <SourceList
              :sources="answerSources"
              :open="Boolean(question._showAnswerSources)"
              test-id="answer-sources"
              @update:open="localQuestion._showAnswerSources = $event"
            />
          </div>

          <div v-else-if="isLoadingDetail" class="flex flex-col items-center justify-center py-8 text-primary gap-3">
            <svg class="animate-spin h-6 w-6" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span class="font-medium text-sm">加载答案中...</span>
          </div>

          <div v-else-if="detailError" class="flex flex-col items-center justify-center py-6 text-amber-600 dark:text-amber-400 gap-2">
            <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            <span class="text-sm">答案加载失败</span>
            <button @click="detailError = false; fullAnswer = null; loadFullAnswer()" class="text-xs text-primary hover:underline mt-1">重试</button>
          </div>

          <div v-else-if="question._isLoadingAnswer" class="flex flex-col items-center justify-center py-8 text-primary gap-3">
            <svg class="animate-spin h-8 w-8" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            <span class="font-medium text-sm">AI 正在生成答案，请稍候...</span>
          </div>

          <div v-else class="text-center py-6">
            <p v-if="isFailedAnswer(displayAnswer)" class="text-destructive mb-3 text-sm flex items-center justify-center gap-1.5">
              <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              上次生成失败，请重试。
            </p>
            <p v-else class="text-muted-foreground mb-4 text-sm">该题目暂无答案</p>
            <div class="flex gap-2 justify-center flex-wrap">
              <Button v-if="isAdmin" variant="default" size="sm" @click.stop="$emit('generate-answer', question)" class="px-5 py-2">
                <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                AI 生成答案
              </Button>
              <Button v-if="isAdmin" variant="ghost" size="sm" @click="localQuestion._isEditingAnswer = true; localQuestion._editAnswer = ''" class="px-5 py-2">
                手动编写
              </Button>
              <p v-else class="text-caption text-muted-foreground">暂无参考答案，请等待管理员生成</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Sources & original questions (secondary — collapsible) -->
      <div v-if="hasSources" class="border-t border-border/50 mt-4">
        <button ref="sourceBtnRef" @click.stop="toggleSources"
          class="w-full px-4 py-2 flex items-center gap-2 text-caption font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 dark:hover:bg-muted/25 transition-colors">
          <svg class="size-3 transform transition-transform duration-200" :class="question._showSources ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          <span>来源详情</span>
          <span class="text-label text-muted-foreground ml-0.5">{{ sourceCount }}条</span>
        </button>

        <div ref="sourcesContentRef" :style="{ height: question._showSources ? 'auto' : '0px', overflow: question._showSources ? '' : 'hidden' }">
        <div class="px-4 pb-4 flex flex-col gap-1.5">
          <div v-for="(src, idx) in dedupedSources" :key="src.url || idx"
            class="bg-card border border-border rounded-md p-2.5 flex items-start gap-2.5">
            <span class="text-caption text-muted-foreground font-mono shrink-0 mt-0.5">{{ idx + 1 }}.</span>
            <div class="flex-1 min-w-0">
              <div v-if="src._origQuestion" class="text-xs text-muted-foreground mb-1 whitespace-pre-line">{{ src._origQuestion }}</div>
              <div class="flex flex-wrap items-center gap-1.5">
                <span @click="$emit('navigate-to-interview', src)"
                  class="text-caption bg-primary/10 dark:bg-primary/15 text-primary px-2 py-0.5 rounded-md inline-flex items-center cursor-pointer hover:bg-primary/15 dark:hover:bg-primary/20 transition-colors">
                  <svg class="size-3 mr-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                  {{ src.company === '未提供' ? '未知' : src.company }}
                  <span class="text-primary/40 dark:text-primary/50 mx-0.5">|</span>
                  {{ src.round === '未提供' ? '未知' : src.round }}
                  <span v-if="src._internal" class="ml-1 text-caption text-primary/60 dark:text-primary/50">内部面经</span>
                  <AppTooltip v-else-if="src.url && src.url !== '未提供链接'" text="查看原文">
                    <a @click.stop :href="safeUrl(src.url)" target="_blank" rel="noopener noreferrer" class="ml-1 text-primary hover:text-primary/80 dark:hover:text-primary/70 font-bold transition-colors duration-200">[原文]</a>
                  </AppTooltip>
                </span>
                <button v-if="isAdmin && dedupedSources.length > 1" @click.stop="$emit('split-question', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-muted-foreground hover:text-orange-500 dark:hover:text-orange-400 px-1.5 py-0.5 rounded transition-colors">
                  独立
                </button>
                <button v-if="isAdmin" @click.stop="$emit('start-merge', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-muted-foreground hover:text-violet-500 dark:hover:text-violet-400 px-1.5 py-0.5 rounded transition-colors">
                  合并到
                </button>
                <button v-if="canDelete" @click.stop="$emit('delete-original-question', { question, originalQuestion: src._origQuestion || question.question })"
                  class="text-caption text-muted-foreground hover:text-destructive dark:hover:text-destructive px-1.5 py-0.5 rounded transition-colors">
                  删除
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
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import AppTooltip from '@/components/common/AppTooltip.vue'
import SourceList from '@/components/common/SourceList.vue'

const sourceBtnRef = ref(null)
const sourcesContentRef = ref(null)
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { safeUrl } from '@/utils/validate.js'
import { get } from '@/services/http.js'

const answerSources = computed(() => {
  const raw = localQuestion.answer_sources
  return Array.isArray(raw) ? raw : []
})

// Lazy-loaded full answer detail (for compact mode)
const fullAnswer = ref(null)
const isLoadingDetail = ref(false)
const detailError = ref(false)
const answerDetailLoaded = ref(false)

async function loadFullAnswer() {
  if (answerDetailLoaded.value || isLoadingDetail.value) return
  const hasAnswer = Boolean(localQuestion.ai_answer)
  const hasAnswerSources = Array.isArray(localQuestion.answer_sources)
  if (hasAnswer && hasAnswerSources) {
    fullAnswer.value = localQuestion.ai_answer
    answerDetailLoaded.value = true
    return
  }
  // A full answer without answer_sources is an incomplete read model. Fetch
  // detail so the reference-source section is not silently omitted.
  if (hasAnswer) fullAnswer.value = localQuestion.ai_answer
  if (!localQuestion.has_reference_answer && !localQuestion.id) return
  isLoadingDetail.value = true
  try {
    const detail = await get(`/api/master-bank/${localQuestion.id}/detail`)
    fullAnswer.value = detail.ai_answer || ''
    if (Array.isArray(detail.answer_sources)) localQuestion.answer_sources = detail.answer_sources
    answerDetailLoaded.value = true
    // Emit to parent so it updates the question object too
    emit('update-answer', {
      id: localQuestion.id,
      ai_answer: detail.ai_answer,
      answer_sources: detail.answer_sources,
    })
  } catch (e) {
    console.warn('Failed to load answer detail:', e)
    detailError.value = true
    fullAnswer.value = ''
  } finally {
    isLoadingDetail.value = false
  }
}

const props = defineProps({
  question: { type: Object, required: true },
  isSelected: { type: Function, required: true },
  practiceInfo: { type: Object, default: null },
  bankFilter: { type: String, default: 'all' },
  isAdmin: { type: Boolean, default: false },
  currentUserId: { type: [Number, String], default: null },
  contentOnly: { type: Boolean, default: false },
})

// Keep transient UI state local to the card.  The question object is owned by
// the list, so editing it directly here creates hidden parent updates and
// violates Vue's one-way data flow.
const localQuestion = reactive({})
watch(() => props.question, (value) => {
  for (const key of Object.keys(localQuestion)) delete localQuestion[key]
  Object.assign(localQuestion, value)
}, { immediate: true, deep: true })

const emit = defineEmits(['toggle-answer', 'toggle-star', 'retag', 'generate-answer', 'save-field', 'toggle-item', 'practice', 'split-question', 'start-merge', 'navigate-to-interview', 'delete', 'edit-question', 'delete-original-question', 'update-answer'])

// Trigger detail load when answer section is shown
watch(() => localQuestion._showAnswer, (show) => {
  if (show) loadFullAnswer()
}, { immediate: true })

// In content-only mode (Accordion), always mark as showing so lazy load triggers
onMounted(() => {
  if (props.contentOnly) {
    localQuestion._showAnswer = true
  }
})

// Sync fullAnswer when parent updates question.ai_answer (e.g., admin generate)
watch(() => props.question.ai_answer, (val) => {
  if (val && val !== fullAnswer.value) {
    fullAnswer.value = val
  }
})

// 平滑展开/收起来源详情（JS 高度动画 + 锁定 scrollTop 防止虚拟滚动器跳动）
const toggleSources = () => {
  const q = localQuestion
  const el = sourcesContentRef.value
  if (!el || !q.sources?.length) return

  const scroller = document.querySelector('.vue-recycle-scroller')
  const btn = sourceBtnRef.value
  const savedScroll = scroller?.scrollTop
  const savedBtnOffset = btn ? btn.offsetTop : 0

  if (!q._showSources) {
    q._showSources = true
    el.style.overflow = 'hidden'
    const targetH = el.scrollHeight
    el.style.height = '0px'
    el.offsetHeight
    animateExpand(el, 0, targetH, scroller, btn, savedScroll, savedBtnOffset, () => {
      el.style.height = 'auto'
      el.style.overflow = ''
    })
  } else {
    const currentH = el.offsetHeight
    el.style.height = currentH + 'px'
    el.style.overflow = 'hidden'
    el.offsetHeight
    q._showSources = false
    animateExpand(el, currentH, 0, scroller, btn, savedScroll, savedBtnOffset, () => {
      el.style.height = '0px'
    })
  }
}

const animateExpand = (el, from, to, scroller, btn, savedScroll, savedBtnOffset, onDone) => {
  // Read duration from motion token (--motion-medium-2 = 300ms)
  const durationStr = getComputedStyle(document.documentElement).getPropertyValue('--motion-medium-2').trim()
  const duration = parseInt(durationStr) || 300
  const start = performance.now()
  // Standard easing: cubic-bezier(0.2, 0, 0, 1) approximation
  const ease = (t) => t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2

  const step = (now) => {
    const t = Math.min(1, (now - start) / duration)
    el.style.height = (from + (to - from) * ease(t)) + 'px'
    if (scroller && btn) {
      const drift = btn.offsetTop - savedBtnOffset
      if (Math.abs(drift) > 1) scroller.scrollTop = savedScroll + drift
    }
    if (t < 1) requestAnimationFrame(step)
    else onDone()
  }
  requestAnimationFrame(step)
}

const DIFFICULTY_CLASSES = {
  L3: 'bg-red-50 dark:bg-red-900/25 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-800/50',
  L2: 'bg-amber-50 dark:bg-amber-900/25 text-amber-600 dark:text-amber-400 border border-amber-100 dark:border-amber-800/50',
  default: 'bg-emerald-50 dark:bg-emerald-900/25 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-800/50',
}

const parsedTags = computed(() => {
  const tags = localQuestion.tags
  return tags ? tags.split(',') : []
})

const canShare = computed(() => {
  // 仅我的私有题可分享（公共题不可转私有）
  return localQuestion.owner_id != null && String(localQuestion.owner_id) === String(props.currentUserId)
})

const canDelete = computed(() => {
  if (props.isAdmin) return true
  if (localQuestion.owner_id != null && String(localQuestion.owner_id) === String(props.currentUserId)) return true
  return false
})

const canEdit = computed(() => {
  if (props.isAdmin) return true
  if (localQuestion.owner_id != null && String(localQuestion.owner_id) === String(props.currentUserId)) return true
  return false
})

const startEditQuestion = () => {
  localQuestion._isEditingQuestion = true
  localQuestion._editQuestion = localQuestion.question
}

const difficultyClass = computed(() => {
  const d = String(localQuestion.difficulty || '')
  if (d.includes('L3')) return DIFFICULTY_CLASSES.L3
  if (d.includes('L2')) return DIFFICULTY_CLASSES.L2
  return DIFFICULTY_CLASSES.default
})

const displayAnswer = computed(() => {
  // 公共参考答案（题解）是唯一答案展示源
  return fullAnswer.value || localQuestion.ai_answer || ''
})

const cachedMarkdown = computed(() => {
  return renderSafeMarkdown(displayAnswer.value)
})

const hasSources = computed(() => {
  const q = localQuestion
  return (q.original_questions && q.original_questions.length > 0) || (q.sources && q.sources.length > 0)
})

const sourceCount = computed(() => {
  const q = localQuestion
  if (q.sources && q.sources.length > 0) return q.sources.length
  return 0
})

const isFailedAnswer = (answer) => answer && answer.includes('生成失败')

const showOwnership = computed(() =>
  localQuestion.owner_id != null && String(localQuestion.owner_id) === String(props.currentUserId)
)

const formatPosition = (pos) => {
  if (!pos) return ''
  const first = pos.split('/')[0].trim()
  return first.charAt(0).toUpperCase() + first.slice(1)
}

// 按 URL 去重的来源列表，仅在展开时计算以节省性能
const dedupedSources = computed(() => {
  if (!localQuestion._showSources) return []
  const q = localQuestion
  const sources = q.sources || []

  // 优先用 original_question_sources（非 compact 模式）
  if (q.original_question_sources && q.original_question_sources.length) {
    const urlToOq = {}
    for (const item of q.original_question_sources) {
      for (const s of (item.sources || [])) {
        if (s.url) {
          if (!urlToOq[s.url]) urlToOq[s.url] = item.question
          else if (!urlToOq[s.url].includes(item.question)) urlToOq[s.url] += '\n' + item.question
        }
      }
    }
    return sources.map(s => ({ ...s, _origQuestion: urlToOq[s.url] || '', _internal: isInternalUrl(s.url) }))
  }

  // compact 模式回退：用 source_labels（url → 原题文本）
  const labels = q.source_labels || {}
  if (Object.keys(labels).length) {
    return sources.map(s => ({ ...s, _origQuestion: labels[s.url] || '', _internal: isInternalUrl(s.url) }))
  }

  return sources.map(s => ({ ...s, _internal: isInternalUrl(s.url) }))
})

// internal:// 来源（用户粘贴 App 内部分享链接或无链接面经）：不渲染为可点击链接
function isInternalUrl(url) {
  return !!url && url.startsWith('internal://')
}
</script>

<style scoped>
.star-btn:active svg { animation: star-pop 0.3s ease-out; }
@keyframes star-pop {
  0% { transform: scale(1); }
  50% { transform: scale(1.4); }
  100% { transform: scale(1); }
}

/* 暗黑模式：答案区域高对比度 */
.dark :deep(.answer-content) {
  color: var(--foreground);
}
.dark :deep(.answer-content p),
.dark :deep(.answer-content li),
.dark :deep(.answer-content span) {
  color: var(--foreground);
}
.dark :deep(.answer-content h1),
.dark :deep(.answer-content h2),
.dark :deep(.answer-content h3),
.dark :deep(.answer-content h4) {
  color: var(--foreground);
}
.dark :deep(.answer-content code) {
  background-color: oklch(0.32 0 0);
  color: var(--foreground);
  padding: 0.125rem 0.375rem;
  border-radius: var(--radius-sm);
}
.dark :deep(.answer-content pre) {
  background-color: oklch(0.19 0 0);
  color: var(--foreground);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 1rem;
}
.dark :deep(.answer-content pre code) {
  background-color: transparent;
  padding: 0;
}
.dark :deep(.answer-content a) {
  color: oklch(0.78 0.13 55);
}
.dark :deep(.answer-content strong) {
  color: var(--foreground);
}
.dark :deep(.answer-content blockquote) {
  border-left-color: var(--muted-foreground);
  color: oklch(0.82 0.01 89.876);
}
</style>
