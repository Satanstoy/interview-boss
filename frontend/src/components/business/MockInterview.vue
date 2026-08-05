<template>
  <div class="flex flex-col gap-4">
    <!-- Config panel -->
    <div v-if="!quizStarted" class="bg-card rounded-xl border border-border shadow-sm overflow-hidden">

      <!-- Header -->
      <div class="border-b border-border px-4 py-3">
        <div class="flex items-center gap-3">
          <div class="size-9 rounded-xl bg-gradient-brand flex items-center justify-center shadow-sm">
            <svg class="size-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
          </div>
          <div>
            <h3 class="text-sm font-bold text-foreground">模拟面试</h3>
            <p class="text-caption text-muted-foreground">选择领域和难度，开始练习</p>
          </div>
        </div>
      </div>

      <div class="p-4 flex flex-col gap-4">
        <!-- Category selection -->
        <div>
          <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"/></svg>
            选择领域
          </label>
          <div class="flex flex-wrap gap-2">
            <button
              @click="selectedCat = ''"
              class="text-xs px-3 py-1.5 rounded-full border transition-colors"
              :class="selectedCat === '' ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
            >全部领域</button>
            <button
              v-for="(cnt, cat) in popularTags" :key="cat"
              @click="selectedCat = cat"
              class="text-xs px-3 py-1.5 rounded-full border transition-colors"
              :class="selectedCat === cat ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
            >{{ cat }} <span class="opacity-50 ml-0.5">{{ cnt }}</span></button>
          </div>
        </div>

        <!-- Difficulty + Count row -->
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <!-- Difficulty selection -->
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              难度
            </label>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="opt in difficultyOptions" :key="opt.value"
                @click="selectedDifficulty = opt.value"
                class="text-xs px-3 py-1.5 rounded-full border transition-colors"
                :class="selectedDifficulty === opt.value ? 'bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-300 dark:border-primary-700 font-semibold' : 'bg-card text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
              >{{ opt.label }}</button>
            </div>
          </div>

          <!-- Count -->
          <div>
            <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14"/></svg>
              题目数量
            </label>
            <div class="inline-flex items-center rounded-xl border border-border overflow-hidden bg-card">
              <button @click="questionCount = Math.max(1, questionCount - 1)" class="size-10 text-muted-foreground hover:bg-muted dark:hover:bg-muted flex items-center justify-center text-lg font-bold transition">-</button>
              <input v-model.number="questionCount" type="number" min="1" max="50" class="w-14 text-center border-x border-border py-2 text-sm bg-transparent text-foreground focus:ring-0 focus:border-primary-400 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none" />
              <button @click="questionCount = Math.min(50, questionCount + 1)" class="size-10 text-muted-foreground hover:bg-muted dark:hover:bg-muted flex items-center justify-center text-lg font-bold transition">+</button>
            </div>
          </div>
        </div>

        <!-- Model selection (optional override) -->
        <div>
          <label class="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
            <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            模型（留空使用全局默认）
          </label>
          <ModelSelectField
            v-model="selectedModel"
            placeholder="使用全局默认模型"
          />
        </div>

        <!-- Start button -->
        <Button variant="default" class="w-full py-3 text-base" @click="startQuiz">
          <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"/><path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          开始抽测
        </Button>
      </div>
    </div>

    <!-- Quiz mode -->
    <div v-else>
      <!-- Summary bar -->
      <div class="flex flex-wrap items-center justify-between gap-3 mb-4 bg-primary-50/60 dark:bg-primary-900/15 border border-border rounded-xl px-4 py-3">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <span class="text-muted-foreground">当前：</span>
          <Badge variant="outline" class="bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">{{ selectedCat || '全部领域' }}</Badge>
          <Badge variant="outline" class="bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label">{{ selectedDifficultyLabel }}</Badge>
          <span class="text-muted-foreground/50">|</span>
          <span class="text-muted-foreground">共 {{ mockQuestions.length }} 题</span>
          <template v-if="selectedModel">
            <span class="text-muted-foreground/50">|</span>
            <Badge variant="outline" class="bg-primary-50/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 text-label font-mono">{{ selectedModel }}</Badge>
          </template>
          <template v-if="quizSummary">
            <span class="text-muted-foreground">|</span>
            <span class="text-muted-foreground">已答 {{ quizSummary.answered }}/{{ quizSummary.total }}</span>
            <span class="font-bold" :class="scoreTextColor(quizSummary.avgScore)">均分 {{ quizSummary.avgScore }}</span>
          </template>
        </div>
        <div class="flex gap-2">
          <Button variant="default" size="sm" class="px-4 py-1.5" @click="loadQuestions">换一批</Button>
          <Button variant="outline" size="sm" class="px-4 py-1.5" @click="quizStarted = false">重新配置</Button>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="isLoading" class="text-center py-10 text-muted-foreground border-2 border-dashed border-border rounded-xl">
        <svg class="animate-spin h-8 w-8 text-primary-400 dark:text-primary-400 mx-auto mb-3" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
        <p class="text-lg">正在加载题目...</p>
      </div>

      <!-- Empty -->
      <div v-else-if="mockQuestions.length === 0" class="text-center py-10 text-muted-foreground border-2 border-dashed border-border rounded-xl">
        <p class="mb-2 text-lg">暂无符合条件的题目</p>
        <p class="text-sm">请调整筛选条件或录入更多面经数据。</p>
        <Button variant="outline" size="sm" class="mt-4 px-4 py-2" @click="quizStarted = false">返回配置</Button>
      </div>

      <!-- Questions -->
      <div v-for="(q, qIdx) in mockQuestions" :key="q.id" class="border border-border rounded-xl overflow-hidden bg-card shadow-sm">
        <div class="p-4 border-b border-border">
          <div class="flex items-start gap-3">
            <div class="flex flex-col items-center justify-center bg-primary-100/80 dark:bg-primary-900/25 text-primary-700 dark:text-primary-400 font-bold rounded-lg p-2 min-w-[44px]">
              <span class="text-caption text-primary-400 dark:text-primary-500">第</span>
              <span class="text-xl leading-none">{{ qIdx + 1 }}</span>
              <span class="text-caption text-primary-400 dark:text-primary-500">题</span>
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex gap-2 mb-2 items-center flex-wrap">
                <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded font-semibold">{{ q.cat1 || '未分类' }}</span>
                <span class="text-xs font-medium px-2 py-0.5 rounded" :class="String(q.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400' : String(q.difficulty).includes('L2') ? 'bg-yellow-50 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400' : 'bg-green-50 dark:bg-green-900/30 text-green-600 dark:text-green-400'">
                  {{ q.difficulty || '-' }}
                </span>
                <span v-if="q.attempt_count > 0" class="bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 text-xs px-2 py-0.5 rounded font-medium">已刷 {{ q.attempt_count }} 次</span>
                <span v-else class="bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 text-xs px-2 py-0.5 rounded font-medium">新题</span>
                <AppTooltip :text="q.is_starred ? '取消收藏' : '收藏'">
                  <button @click="handleToggleStar(q)" class="text-lg ml-1 transition-transform hover:scale-125">
                    {{ q.is_starred ? '★' : '☆' }}
                  </button>
                </AppTooltip>
                <span class="text-xs text-muted-foreground ml-auto">频率 {{ q.frequency }}</span>
              </div>
              <h3 class="text-base lg:text-lg font-bold text-foreground leading-snug">{{ q.question }}</h3>
            </div>
          </div>
        </div>

        <!-- User answer input -->
        <div class="px-4 py-3 border-t border-border bg-card">
          <label class="text-xs font-semibold text-muted-foreground mb-1.5 block">你的回答</label>
          <textarea
            v-model="q._userAnswer"
            placeholder="在这里输入你的回答，然后点击「提交评估」让 AI 对比参考答案评分..."
            rows="5"
            class="w-full border border-input rounded-lg p-3 text-sm leading-relaxed bg-transparent text-foreground focus:outline-none focus:ring-1 focus:ring-ring resize-y"
          ></textarea>
          <div class="flex gap-2 mt-2">
            <Button
              variant="default"
              size="sm"
              class="px-5 py-2 flex items-center gap-2"
              :disabled="q._isEvaluating"
              @click="handleEvaluate(q)"
            >
              <svg v-if="q._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
              {{ q._isEvaluating ? '评估中...' : '提交评估' }}
            </Button>
            <Button
              v-if="q._userAnswer"
              variant="ghost"
              size="sm"
              class="px-3 py-2"
              @click="q._userAnswer = ''; q._evaluation = null"
            >清空</Button>
          </div>
        </div>

        <!-- Evaluation result -->
        <div v-if="q._evaluation" class="px-5 py-4 border-t border-border bg-primary-50/40 dark:bg-primary-900/10">
          <h4 class="text-sm font-bold text-foreground mb-3">评估结果</h4>

          <!-- Overall score -->
          <div class="flex items-center gap-3 mb-4">
            <span class="text-3xl font-extrabold" :class="scoreTextColor(q._evaluation.overall_score)">{{ q._evaluation.overall_score }}</span>
            <div class="flex-1">
              <div class="bg-muted dark:bg-muted rounded-full h-3 overflow-hidden">
                <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(q._evaluation.overall_score)" :style="{ width: q._evaluation.overall_score + '%' }"></div>
              </div>
            </div>
            <span class="text-xs text-muted-foreground">/ 100</span>
          </div>

          <!-- Dimension scores -->
          <div class="flex flex-col gap-2 mb-4">
            <div v-for="(val, key) in q._evaluation.dimensions" :key="key" class="flex items-start gap-2">
              <span class="text-xs text-muted-foreground w-14 shrink-0 pt-0.5">{{ dimLabel[key] || key }}</span>
              <div class="flex-1">
                <div class="flex items-center gap-2">
                  <div class="bg-muted dark:bg-muted rounded-full h-2 flex-1 overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                  </div>
                  <span class="text-xs font-bold w-8 text-right" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                </div>
                <p v-if="val.comment" class="text-xs text-muted-foreground mt-0.5 leading-snug">{{ val.comment }}</p>
              </div>
            </div>
          </div>

          <!-- Strengths & Weaknesses -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
            <div v-if="q._evaluation.strengths?.length">
              <p class="text-xs font-semibold text-green-700 dark:text-green-400 mb-1">亮点</p>
              <ul class="flex flex-col gap-1">
                <li v-for="s in q._evaluation.strengths" :key="s" class="text-xs text-muted-foreground flex gap-1.5">
                  <span class="text-green-500 dark:text-green-400 shrink-0">+</span>{{ s }}
                </li>
              </ul>
            </div>
            <div v-if="q._evaluation.weaknesses?.length">
              <p class="text-xs font-semibold text-red-700 dark:text-red-400 mb-1">不足</p>
              <ul class="flex flex-col gap-1">
                <li v-for="w in q._evaluation.weaknesses" :key="w" class="text-xs text-muted-foreground flex gap-1.5">
                  <span class="text-red-500 dark:text-red-400 shrink-0">-</span>{{ w }}
                </li>
              </ul>
            </div>
          </div>

          <!-- Suggestions -->
          <div v-if="q._evaluation.suggestions">
            <p class="text-xs font-semibold text-foreground mb-1">改进建议</p>
            <div class="text-sm text-muted-foreground leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(q._evaluation.suggestions)"></div>
          </div>
        </div>

        <!-- Practice history toggle -->
        <div v-if="q.attempt_count > 0" class="border-t border-primary-100 dark:border-primary-800/50">
          <button
            @click="toggleHistory(q)"
            class="w-full py-2.5 text-xs font-medium text-muted-foreground hover:bg-muted dark:hover:bg-primary-900/20 transition flex items-center justify-center gap-2"
          >
            <svg class="size-3.5 transition-transform" :class="{ 'rotate-90': q._showHistory }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
            {{ q._showHistory ? '收起练习记录' : `查看练习记录 (${q.attempt_count}次)` }}
          </button>
          <div v-if="q._showHistory" class="px-5 py-4 bg-muted dark:bg-card border-t border-primary-100 dark:border-primary-800/50 flex flex-col gap-2 max-h-64 overflow-y-auto custom-scrollbar">
            <div v-if="q._historyLoading" class="text-center py-3 text-xs text-muted-foreground">加载中...</div>
            <div v-else-if="q._history && q._history.length > 0">
              <div v-for="(h, hIdx) in q._history" :key="h.id" class="border-b border-border last:border-b-0">
                <div class="flex items-center gap-3 py-2 cursor-pointer hover:bg-muted/50 dark:hover:bg-muted/50 px-1 rounded transition-colors duration-200" @click="h._expanded = !h._expanded">
                  <span class="text-xs text-muted-foreground w-5 text-right shrink-0">#{{ q._history.length - hIdx }}</span>
                  <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                      <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                      <span class="text-xs text-muted-foreground/50">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                    </div>
                    <p v-if="!h._expanded" class="text-xs text-muted-foreground truncate">{{ h.user_answer?.slice(0, 80) }}{{ h.user_answer?.length > 80 ? '...' : '' }}</p>
                  </div>
                  <div class="w-16 shrink-0">
                    <div class="bg-muted dark:bg-muted rounded-full h-1.5 overflow-hidden">
                      <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                    </div>
                  </div>
                  <svg class="size-3.5 text-muted-foreground transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                </div>
                <div v-if="h._expanded" class="pl-6 pr-2 pb-3 flex flex-col gap-2">
                  <div>
                    <p class="text-xs font-semibold text-muted-foreground mb-1">我的回答</p>
                    <p class="text-xs text-muted-foreground bg-card rounded p-2 border border-border whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                  </div>
                  <div v-if="h.evaluation_result">
                    <div class="flex items-center gap-3 mb-1">
                      <span class="text-xs font-semibold text-muted-foreground">维度评分：</span>
                      <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-xs text-muted-foreground">
                        {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                      </span>
                    </div>
                    <div v-if="h.evaluation_result.suggestions" class="text-xs text-muted-foreground">
                      <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 200) }}{{ h.evaluation_result.suggestions?.length > 200 ? '...' : '' }}
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-3 text-xs text-muted-foreground">暂无练习记录</div>
          </div>
        </div>

        <div class="border-t border-primary-100 dark:border-primary-800/50">
          <button
            @click="q._showAnswer = !q._showAnswer"
            class="w-full py-3 text-sm font-medium text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-900/30 transition flex items-center justify-center gap-2"
          >
            {{ q._showAnswer ? '收起答案' : '查看答案' }}
          </button>
          <div v-if="q._showAnswer" class="p-6 bg-slate-50 dark:bg-card border-t border-primary-100 dark:border-primary-800/50">
            <!-- Edit mode -->
            <div v-if="q._isEditingAnswer" class="flex flex-col gap-3">
              <label class="text-xs font-semibold text-muted-foreground">编辑参考答案</label>
              <textarea
                v-model="q._editAnswer"
                rows="10"
                class="w-full border border-blue-300 dark:border-blue-700 rounded-lg p-3 text-sm leading-relaxed bg-card text-foreground focus:ring-blue-500 focus:border-blue-500 dark:focus:ring-blue-400 dark:focus:border-blue-400 resize-y font-mono"
              ></textarea>
              <div class="flex gap-2 justify-end">
                <button @click="q._isEditingAnswer = false" class="px-4 py-1.5 text-sm text-muted-foreground border border-border rounded-lg hover:bg-muted dark:hover:bg-muted transition">取消</button>
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
                <div class="text-foreground text-sm leading-relaxed answer-content prose prose-sm dark:prose-invert max-w-none" v-html="renderMarkdown(q.ai_answer)"></div>
              </div>
              <div v-else class="text-center py-4">
                <p class="text-muted-foreground mb-3 text-sm">暂无 AI 答案。</p>
                <div class="flex gap-2 justify-center flex-wrap">
                  <button @click="handleGenerate(q)" :disabled="q._isLoadingAnswer" class="bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 font-bold px-5 py-2 rounded-lg hover:bg-blue-200 dark:hover:bg-blue-900/50 transition text-sm disabled:opacity-50">
                    {{ q._isLoadingAnswer ? '生成中...' : 'AI 生成答案' }}
                  </button>
                  <button @click="q._isEditingAnswer = true; q._editAnswer = ''" class="bg-muted dark:bg-muted text-muted-foreground font-bold px-5 py-2 rounded-lg hover:bg-muted dark:hover:bg-gray-600 transition text-sm">
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
import { ref, computed, watch } from 'vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { renderSafeMarkdown } from '@/utils/markdown.js'
import { fetchRandomQuestions, generateAnswer as apiGenerateAnswer, evaluateAnswer, fetchPracticeHistory, updateRecord, toggleStar as apiToggleStar } from '@/api/index.js'
import { sanitizeAgainstInjection, validateNumber } from '@/utils/validate.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import { useModelGuard } from '@/composables/useModelGuard.js'
import AppTooltip from '@/components/common/AppTooltip.vue'
import ModelSelectField from '@/components/business/ModelSelectField.vue'

const toast = useToast()
const { confirm: showConfirm } = useConfirm()
const { ensureModelReady } = useModelGuard()

const props = defineProps({
  popularTags: { type: Object, default: () => ({}) }
})

const difficultyOptions = [
  { value: '', label: '随机' },
  { value: 'L1', label: 'L1-基础' },
  { value: 'L2', label: 'L2-中等' },
  { value: 'L3', label: 'L3-困难' }
]

// Config state（持久化到 localStorage，刷新不丢）
const QUIZ_CONFIG_KEY = 'mock-interview-config'
const loadQuizConfig = () => {
  try {
    return JSON.parse(localStorage.getItem(QUIZ_CONFIG_KEY) || '{}')
  } catch {
    return {}
  }
}
const saveQuizConfig = () => {
  localStorage.setItem(QUIZ_CONFIG_KEY, JSON.stringify({
    selectedCat: selectedCat.value,
    selectedDifficulty: selectedDifficulty.value,
    questionCount: questionCount.value,
    selectedModel: selectedModel.value,
  }))
}

const savedConfig = loadQuizConfig()
const selectedCat = ref(savedConfig.selectedCat || '')
const selectedDifficulty = ref(savedConfig.selectedDifficulty || '')
const questionCount = ref(savedConfig.questionCount || 10)
const selectedModel = ref(savedConfig.selectedModel || '')

watch([selectedCat, selectedDifficulty, questionCount, selectedModel], saveQuizConfig)

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
    toast.error('获取题目失败：' + (e.message || '请检查网络'))
    mockQuestions.value = []
  } finally {
    isLoading.value = false
  }
}

const handleGenerate = async (q) => {
  if (!await ensureModelReady({ action: 'AI 生成答案' })) return
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
  if (!await ensureModelReady({ action: '自测评估' })) return
  q._isEvaluating = true
  q._evaluation = null
  try {
    const data = await evaluateAnswer({
      question_id: q.id,
      question_text: q.question,
      user_answer: q._userAnswer,
      reference_answer: q.ai_answer,
      model: selectedModel.value || undefined
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
