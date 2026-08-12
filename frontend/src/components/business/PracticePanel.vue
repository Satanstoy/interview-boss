<template>
  <AppDialog
    :open="visible && !!question"
    @update:open="(val) => !val && emit('close')"
    size="full"
    :show-close-button="false"
    :close-on-backdrop="true"
  >
    <template #header>
      <div class="flex items-center justify-between -mt-2">
        <div class="flex items-center gap-3 min-w-0">
          <h2 class="text-sm font-bold text-foreground truncate max-w-md">{{ question?.question }}</h2>
          <Badge variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-100 dark:border-primary-800 text-[10px] shrink-0">{{ question?.cat1 || '未分类' }}</Badge>
          <Badge variant="outline" class="text-[10px] shrink-0"
            :class="String(question?.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border-red-100 dark:border-red-800' : String(question?.difficulty).includes('L2') ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border-amber-100 dark:border-amber-800' : 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-800'">
            {{ question?.difficulty || '-' }}
          </Badge>
        </div>
        <button @click="emit('close')" class="p-1.5 rounded-lg text-muted-foreground hover:text-muted-foreground dark:hover:text-muted-foreground/50 hover:bg-muted dark:hover:bg-muted transition shrink-0">
          <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>
    </template>

    <!-- Main content: left + right panels -->
    <div class="flex-1 flex flex-col lg:flex-row overflow-hidden -mx-6 -my-5 min-h-[70vh]">
      <!-- LEFT PANEL -->
      <div class="w-full lg:w-[45%] flex flex-col border-r border-border">
        <!-- Tabs -->
        <Tabs default-value="description" v-model:value="leftTab">
          <TabsList class="w-full flex shrink-0 bg-muted dark:bg-background">
            <TabsTrigger v-for="tab in leftTabs" :key="tab.key" :value="tab.key">
              {{ tab.label }}
              <span v-if="tab.key === 'answer' && !question.ai_answer" class="ml-1 inline-block size-1.5 rounded-full bg-red-400 dark:bg-red-400"></span>
              <span v-if="tab.key === 'history' && question.attempt_count" class="ml-1 text-[10px] text-muted-foreground">({{ question.attempt_count }})</span>
            </TabsTrigger>
          </TabsList>

          <!-- Tab content -->
          <div class="flex-1 overflow-y-auto custom-scrollbar">
            <!-- Description tab -->
            <TabsContent value="description" class="p-5 flex flex-col gap-4">
              <div class="flex gap-1.5 flex-wrap">
                <Badge v-for="tag in (question.tags ? question.tags.split(',') : [])" :key="tag" variant="outline" class="bg-muted dark:bg-card text-muted-foreground border-border/80 text-[10px]">{{ tag }}</Badge>
              </div>
              <div class="text-sm text-foreground leading-relaxed font-medium">{{ question.question }}</div>

              <!-- Sources -->
              <div v-if="question.sources && question.sources.length > 0" class="bg-primary-50/40 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800 rounded-xl p-4">
                <h4 class="text-xs font-bold text-primary-800 dark:text-primary-400 mb-2 flex items-center gap-1.5">
                  <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                  出处追溯 ({{ question.sources.length }} 次出现)
                </h4>
                <div class="flex flex-wrap gap-1.5 text-[11px]">
                  <span v-for="(src, idx) in question.sources" :key="idx"
                    @click="emit('navigate-to-interview', { source: src, questionId: question.id })"
                    class="bg-card border border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400 px-2 py-1 rounded-lg inline-flex items-center cursor-pointer hover:bg-primary-50 dark:hover:bg-primary-900/30 transition-colors">
                    {{ src.company === '未提供' ? '未知' : src.company }}
                    <span class="text-primary-300 dark:text-primary-600 mx-1">|</span>
                    {{ src.round === '未提供' ? '未知轮次' : src.round }}
                    <a v-if="src.url && src.url !== '未提供链接'" @click.stop :href="src.url" target="_blank" rel="noopener noreferrer" class="ml-1.5 text-primary-500 dark:text-primary-400 hover:text-primary-700 dark:hover:text-primary-300 font-bold transition-colors duration-200">[原文]</a>
                  </span>
                </div>
              </div>
            </TabsContent>

            <!-- Answer/Solution tab -->
            <TabsContent value="answer" class="p-5">
              <div v-if="qState._isEditingAnswer" class="flex flex-col gap-3">
                <textarea v-model="qState._editAnswer" rows="12" class="w-full border border-input rounded-lg p-3 text-sm bg-transparent text-foreground focus:outline-none focus:ring-1 focus:ring-ring font-mono resize-y"></textarea>
                <div class="flex gap-2 justify-end">
                  <Button @click="qState._isEditingAnswer = false" variant="outline" size="sm">取消</Button>
                  <Button @click="handleSaveAnswer" :disabled="qState._isSavingAnswer" size="sm">
                    {{ qState._isSavingAnswer ? '保存中...' : '保存' }}
                  </Button>
                </div>
              </div>

              <div v-else-if="question.ai_answer && !isFailedAnswer(question.ai_answer)">
                <div class="flex items-center justify-between mb-3">
                  <span class="text-xs font-semibold text-muted-foreground">AI 参考答案</span>
                  <div class="flex gap-1.5">
                    <Button v-if="isAdmin" @click="qState._isEditingAnswer = true; qState._editAnswer = question.ai_answer" variant="ghost" size="sm" class="text-[10px] h-auto px-2 py-0.5">编辑</Button>
                    <Button v-if="isAdmin" @click="handleGenerate" :disabled="qState._isLoadingAnswer" variant="ghost" size="sm" class="text-[10px] h-auto px-2 py-0.5">重新生成</Button>
                  </div>
                </div>
                <div class="text-sm text-foreground leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(question.ai_answer)"></div>
                <SourceList
                  :sources="answerSources"
                  :open="qState._showAnswerSources"
                  test-id="practice-panel-answer-sources"
                  @update:open="qState._showAnswerSources = $event"
                />
              </div>

              <div v-else-if="qState._isLoadingAnswer" class="flex flex-col items-center justify-center py-12 text-primary-600 dark:text-primary-400 gap-3">
                <AppLoading type="spinner" text="正在生成参考答案..." />
              </div>

              <div v-else class="text-center py-12">
                <p v-if="isFailedAnswer(question.ai_answer)" class="text-red-500 dark:text-red-400 mb-3 text-sm">上次生成失败，请重试</p>
                <p v-else class="text-muted-foreground mb-4 text-sm">{{ isAdmin ? '暂无参考答案' : '暂无参考答案，请等待管理员生成' }}</p>
                <Button v-if="isAdmin" @click="handleGenerate" size="sm">
                  <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                  AI 生成答案
                </Button>
              </div>
            </TabsContent>

            <!-- History tab -->
            <TabsContent value="history" class="p-5">
              <div v-if="qState._historyLoading" class="text-center py-8 text-xs text-muted-foreground">加载中...</div>
              <div v-else-if="qState._history && qState._history.length > 0" class="flex flex-col gap-2">
                <div v-for="(h, hIdx) in qState._history" :key="h.id" class="border border-border rounded-xl overflow-hidden">
                  <div class="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-muted dark:hover:bg-muted transition" @click="h._expanded = !h._expanded">
                    <span class="text-[10px] text-muted-foreground w-6 text-right shrink-0">#{{ qState._history.length - hIdx }}</span>
                    <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                    <span class="text-[10px] text-muted-foreground ml-auto">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                    <div class="w-16 shrink-0">
                      <div class="bg-muted dark:bg-muted rounded-full h-1.5 overflow-hidden">
                        <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                      </div>
                    </div>
                    <svg class="size-3 text-muted-foreground transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                  </div>
                  <div v-if="h._expanded" class="px-3 pb-3 flex flex-col gap-2 border-t border-border pt-2">
                    <div>
                      <p class="text-[10px] font-semibold text-muted-foreground mb-1">我的回答</p>
                      <p class="text-xs text-muted-foreground bg-muted dark:bg-card rounded-lg p-2 whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                    </div>
                    <div v-if="h.evaluation_result">
                      <div class="flex items-center gap-2 flex-wrap mb-1">
                        <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-[10px] text-muted-foreground">
                          {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                        </span>
                      </div>
                      <p v-if="h.evaluation_result.suggestions" class="text-[10px] text-muted-foreground">
                        <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 150) }}{{ h.evaluation_result.suggestions?.length > 150 ? '...' : '' }}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="text-center py-12 text-muted-foreground text-sm">
                <svg class="size-10 mx-auto mb-2 text-muted-foreground/50" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                暂无练习记录
              </div>
            </TabsContent>
          </div>
        </Tabs>
      </div>

      <!-- RIGHT PANEL -->
      <div class="w-full lg:w-[55%] flex flex-col">
        <!-- Answer input area -->
        <div class="flex-1 flex flex-col overflow-hidden">
          <div class="px-5 pt-4 pb-2 shrink-0">
            <h3 class="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
              我的回答
            </h3>
          </div>
          <div class="flex-1 px-5 pb-3 overflow-hidden">
            <textarea
              v-model="qState._userAnswer"
              class="w-full h-full border border-input rounded-lg p-3.5 text-sm leading-relaxed focus:outline-none focus:ring-1 focus:ring-ring resize-none transition-all duration-200 bg-transparent text-foreground"
              placeholder="在此输入你的回答，完成后点击下方「提交评估」..."
            ></textarea>
          </div>
          <div class="px-5 pb-3 flex gap-2 items-center shrink-0">
            <Button
              @click="handleEvaluate"
              :disabled="qState._isEvaluating || !qState._userAnswer.trim()"
              class="flex items-center gap-2"
            >
              <svg v-if="qState._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              {{ qState._isEvaluating ? '评估中...' : '提交评估' }}
            </Button>
            <Button v-if="qState._userAnswer" @click="qState._userAnswer = ''; qState._evaluation = null" variant="ghost" size="sm">清空</Button>
            <span v-if="question.attempt_count" class="text-[10px] text-muted-foreground ml-auto">已练习 {{ question.attempt_count }} 次</span>
          </div>
        </div>

        <!-- Evaluation result -->
        <div v-if="qState._evaluation" class="border-t border-border bg-gradient-to-b from-primary-50/30 to-background dark:from-primary-900/20 overflow-y-auto custom-scrollbar" style="max-height: 55%;">
          <div class="p-5 flex flex-col gap-4">
            <!-- Overall score -->
            <div class="flex items-center gap-4">
              <span class="text-4xl font-extrabold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span>
              <div class="flex-1">
                <div class="bg-muted dark:bg-muted rounded-full h-3 overflow-hidden">
                  <div class="h-full rounded-full transition-all duration-700" :class="scoreColor(qState._evaluation.overall_score)" :style="{ width: qState._evaluation.overall_score + '%' }"></div>
                </div>
                <p class="text-[10px] text-muted-foreground mt-1">加权总分（准确性 35%、完整性 30%、深度 20%、逻辑性 15%）</p>
              </div>
            </div>

            <!-- Dimension scores -->
            <div class="grid grid-cols-2 gap-2.5">
              <div v-for="(val, key) in qState._evaluation.dimensions" :key="key" class="bg-card rounded-xl p-2.5 border border-border">
                <div class="flex items-center justify-between mb-1">
                  <span class="text-[10px] font-semibold text-muted-foreground">{{ dimLabel[key] || key }}</span>
                  <span class="text-sm font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                </div>
                <div class="bg-muted dark:bg-muted rounded-full h-1.5 overflow-hidden mb-1">
                  <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                </div>
                <p v-if="val.comment" class="text-[10px] text-muted-foreground leading-snug">{{ val.comment }}</p>
              </div>
            </div>

            <!-- Strengths & Weaknesses -->
            <div class="grid grid-cols-2 gap-3">
              <div v-if="qState._evaluation.strengths?.length" class="bg-card rounded-xl p-2.5 border border-green-100 dark:border-green-800">
                <p class="text-[10px] font-semibold text-green-700 dark:text-green-400 mb-1.5">亮点</p>
                <ul class="flex flex-col gap-0.5">
                  <li v-for="s in qState._evaluation.strengths" :key="s" class="text-[11px] text-muted-foreground flex gap-1">
                    <span class="text-green-500 dark:text-green-400 shrink-0">+</span>{{ s }}
                  </li>
                </ul>
              </div>
              <div v-if="qState._evaluation.weaknesses?.length" class="bg-card rounded-xl p-2.5 border border-red-100 dark:border-red-800">
                <p class="text-[10px] font-semibold text-red-700 dark:text-red-400 mb-1.5">不足</p>
                <ul class="flex flex-col gap-0.5">
                  <li v-for="w in qState._evaluation.weaknesses" :key="w" class="text-[11px] text-muted-foreground flex gap-1">
                    <span class="text-red-500 dark:text-red-400 shrink-0">-</span>{{ w }}
                  </li>
                </ul>
              </div>
            </div>

            <!-- Suggestions -->
            <div v-if="qState._evaluation.suggestions" class="bg-card rounded-xl p-3 border border-border">
              <p class="text-[10px] font-semibold text-foreground mb-1">改进建议</p>
              <div class="text-xs text-muted-foreground leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(qState._evaluation.suggestions)"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppDialog>
</template>

<script setup>
import { computed, ref, reactive, watch } from 'vue'
import {
  leftTabs, dimLabel, isFailedAnswer, renderMarkdown,
  scoreColor, scoreTextColor, resetQState,
  generateAnswerForQuestion, saveAnswerForQuestion,
  evaluateAnswerForQuestion, loadHistory
} from '@/composables/usePractice.js'
import AppDialog from '@/components/common/AppDialog.vue'
import AppLoading from '@/components/common/AppLoading.vue'
import SourceList from '@/components/common/SourceList.vue'
import Button from '@/components/ui/button/Button.vue'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'

const props = defineProps({
  visible: { type: Boolean, default: false },
  question: { type: Object, default: null },
  isAdmin: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'answer-evaluated', 'navigate-to-interview'])

const leftTab = ref('description')

const qState = reactive({
  _userAnswer: '',
  _evaluation: null,
  _isEvaluating: false,
  _isLoadingAnswer: false,
  _history: null,
  _historyLoading: false,
  _isEditingAnswer: false,
  _editAnswer: '',
  _isSavingAnswer: false,
  _showAnswerSources: false
})

const answerSources = computed(() => (
  Array.isArray(props.question?.answer_sources) ? props.question.answer_sources : []
))

watch(() => props.question, (q) => {
  if (q) {
    leftTab.value = 'description'
    resetQState(qState)
  }
})

const handleGenerate = () => generateAnswerForQuestion(props.question, qState)
const handleSaveAnswer = () => saveAnswerForQuestion(props.question, qState)

const handleEvaluate = async () => {
  const data = await evaluateAnswerForQuestion(props.question, qState)
  if (data) {
    leftTab.value = 'answer'
    emit('answer-evaluated', { questionId: props.question.id, score: data.overall_score })
  }
}

// Load history when switching to history tab
watch(leftTab, (tab) => {
  if (tab === 'history' && !qState._history && props.question) {
    loadHistory(props.question.id, qState)
  }
})
</script>
