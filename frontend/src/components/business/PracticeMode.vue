<template>
  <div data-testid="practice-workspace" class="relative flex h-full min-h-0 w-full overflow-hidden bg-background">
    <!-- Mobile sidebar overlay -->
    <div v-if="mobileSidebarOpen" class="fixed inset-0 z-40 bg-black/40 md:hidden" @click="mobileSidebarOpen = false" />

    <aside
      v-if="viewMode === 'browse'"
      data-testid="practice-queue-sidebar"
      class="sidebar-container z-30 w-64 shrink-0 flex-col overflow-hidden border-r border-border bg-background md:flex md:z-auto"
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
          <Button variant="ghost" size="sm" class="h-10 shrink-0 gap-1.5 px-2 text-muted-foreground md:size-7 md:px-0" aria-label="收起题单侧栏" @click="queueCollapsed = true">
            <PanelLeftClose :size="14" />
            <span class="text-xs md:hidden">收起</span>
          </Button>
        </AppTooltip>
      </div>
      <div class="min-h-0 flex-1 overflow-y-auto px-2 py-2 custom-scrollbar sidebar-content" @scroll.passive="handleQueueScroll">
        <button
          v-for="(question, questionIndex) in sessionQuestions"
          :key="question.id"
          type="button"
          class="group mb-1 flex w-full items-start gap-2 rounded-md p-2 text-left transition-colors"
          :class="questionIndex === currentIndex ? 'bg-sidebar-accent text-sidebar-accent-foreground' : 'text-sidebar-foreground/65 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
          @click="selectFromSidebar(questionIndex)"
        >
          <span class="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded text-[10px] tabular-nums" :class="questionIndex === currentIndex ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'">{{ questionIndex + 1 }}</span>
          <span class="min-w-0 flex-1">
            <span class="line-clamp-2 text-xs leading-5">{{ question.question }}</span>
            <span v-if="question.has_been_practiced" class="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground"><Check class="size-3" />熟练度 {{ question.proficiency || 0 }}/5</span>
          </span>
        </button>
        <p v-if="!sessionQuestions.length" class="px-2 py-8 text-center text-xs leading-5 text-muted-foreground">这个题单还没有可复习的题</p>
        <button
          v-if="hasMoreQuestions"
          type="button"
          class="mt-1 flex w-full items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs text-primary transition hover:bg-primary/5 disabled:cursor-wait disabled:opacity-60"
          :disabled="loadingMoreQuestions"
          @click="requestMoreQuestions"
        >
          <Loader2 v-if="loadingMoreQuestions" class="size-3.5 animate-spin" />
          {{ loadingMoreQuestions ? '正在加载更多...' : '加载更多题目' }}
        </button>
        <p v-else-if="sessionQuestions.length" class="px-2 py-2 text-center text-[10px] text-muted-foreground">已加载全部 {{ sessionQuestions.length }} 道题</p>
      </div>
    </aside>

    <div v-if="viewMode === 'browse' && queueCollapsed" class="flex shrink-0 flex-col items-center gap-1 px-2 py-2 sidebar-expand-buttons">
      <AppTooltip text="展开题单侧栏" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="展开题单侧栏" @click="queueCollapsed = false">
          <PanelLeft :size="14" />
        </Button>
      </AppTooltip>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <main data-testid="practice-main" class="min-h-0 flex-1 overflow-hidden">
        <div class="mx-auto flex h-full min-h-0 w-full max-w-4xl flex-col gap-2 overflow-hidden px-2 py-2 sm:gap-3 sm:px-4 sm:py-4 md:px-6 md:py-5">

    <div v-if="isAlgorithmQueue && dailyPlanTotal" data-testid="practice-daily-progress" class="flex shrink-0 items-center gap-3 rounded-xl border border-border/80 bg-card px-3 py-2.5 shadow-sm sm:px-4">
      <div class="min-w-0 flex-1">
        <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs">
          <span class="flex items-center gap-1.5 font-semibold text-foreground">今日计划 <span data-testid="practice-study-streak" class="inline-flex items-center gap-1 rounded-full bg-orange-500/10 px-2 py-0.5 text-[10px] font-medium text-orange-600 dark:text-orange-400"><Flame class="size-3" />{{ streakLabel }}</span></span>
          <div class="flex flex-wrap items-center gap-2">
            <span class="tabular-nums text-muted-foreground">已过关 {{ completedToday }} / {{ dailyPlanTotal }} · 今日已练 {{ attemptedToday }} 题<template v-if="reviewAttemptsToday > attemptedToday">（回忆 {{ reviewAttemptsToday }} 次）</template> · 剩余 {{ remainingToday }}<template v-if="postponedQuestionIds.length"> · 稍后 {{ postponedQuestionIds.length }}</template><template v-if="relearningQueue.length"> · 本轮待巩固 {{ relearningQueue.length }}</template></span>
            <span data-testid="practice-capacity-control" class="inline-flex h-7 items-center rounded-full border border-border bg-background/80">
              <button
                type="button"
                data-testid="practice-capacity-decrease"
                class="flex size-7 items-center justify-center rounded-l-full text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="每日计划减少 5 题"
                :disabled="capacitySaving || deckLoading || reviewLoading || dailyCapacity <= 5"
                @click="adjustDailyCapacity(-5)"
              ><Minus class="size-3" /></button>
              <span class="min-w-20 border-x border-border px-2 text-center text-[10px] tabular-nums text-foreground" :aria-busy="capacitySaving">
                {{ capacitySaving ? '调整中…' : `每日上限 ${dailyCapacity}` }}
              </span>
              <button
                type="button"
                data-testid="practice-capacity-increase"
                class="flex size-7 items-center justify-center rounded-r-full text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                aria-label="每日计划增加 5 题"
                :disabled="capacitySaving || deckLoading || reviewLoading || dailyCapacity >= 200"
                @click="adjustDailyCapacity(5)"
              ><Plus class="size-3" /></button>
            </span>
          </div>
        </div>
        <p v-if="taskMixLabel" data-testid="practice-plan-mix" class="mt-1 text-[10px] text-muted-foreground">待完成 · {{ taskMixLabel }}</p>
        <div class="mt-2 h-1.5 overflow-hidden rounded-full bg-muted" role="progressbar" :aria-valuenow="dailyProgress" aria-valuemin="0" aria-valuemax="100">
          <div class="h-full rounded-full bg-primary transition-[width] duration-300" :style="{ width: `${dailyProgress}%` }"></div>
        </div>
        <div v-if="reviewForecast.length" data-testid="practice-review-forecast" class="mt-3 flex items-end gap-3 border-t border-border/60 pt-2" role="img" :aria-label="`未来 7 天预计复习 ${forecastTotal} 题`">
          <div class="shrink-0 pb-3 text-[10px] leading-4 text-muted-foreground"><span class="block font-medium text-foreground">未来 7 天</span>预计 {{ forecastTotal }} 题</div>
          <div class="grid min-w-0 flex-1 grid-cols-7 gap-1.5">
            <div v-for="day in reviewForecast" :key="day.date" data-testid="practice-forecast-day" class="flex min-w-0 flex-col items-center gap-1" :title="`${day.date} · ${day.count} 题`">
              <span class="text-[9px] tabular-nums text-muted-foreground">{{ day.count }}</span>
              <span class="flex h-6 w-full items-end justify-center"><span class="w-full max-w-5 rounded-sm transition-[height]" :class="day.count ? 'bg-primary/75' : 'bg-muted'" :style="{ height: forecastBarHeight(day.count) }"></span></span>
              <span class="text-[9px] text-muted-foreground">{{ forecastDayLabel(day.date) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <Card v-if="currentQ" data-testid="practice-card" class="practice-card mx-auto flex min-h-0 w-full flex-1 flex-col overflow-hidden rounded-2xl p-0 shadow-sm">
      <div data-testid="practice-focus-card" class="contents">
      <div class="flex shrink-0 flex-col gap-2 border-b border-border px-3 py-2.5 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between sm:gap-3 sm:px-4 sm:py-3 md:px-6">
        <div class="flex min-w-0 flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <Button v-if="currentQ && isAlgorithmQueue" data-testid="practice-switch-browse" variant="ghost" size="sm" class="h-10 shrink-0 gap-1.5 px-2 text-xs text-muted-foreground sm:h-8" @click="switchToBrowse"><List class="size-3.5" />看题模式</Button>
          <Button v-else-if="currentQ && viewMode === 'browse'" data-testid="practice-switch-quiz" variant="ghost" size="sm" class="h-10 shrink-0 gap-1.5 px-2 text-xs text-muted-foreground sm:h-8" @click="switchToQuiz"><Zap class="size-3.5" />切回八股刷题</Button>
          <Button variant="ghost" size="sm" class="h-11 min-h-11 gap-1.5 px-2 md:hidden" aria-label="展开题目列表" @click="mobileSidebarOpen = true">
            <PanelLeft :size="14" />
            <span>题目列表</span>
          </Button>
          <span class="font-semibold text-foreground">第 {{ currentIndex + 1 }} 题</span>
          <span>·</span>
          <span>高频 {{ currentQ.frequency || 0 }} 次</span>
          <span v-if="questionAttemptCount(currentQ)" class="hidden items-center gap-1 sm:inline-flex"><History class="size-3.5" />已练习 {{ questionAttemptCount(currentQ) }} 次</span>
          <span v-if="currentQ.has_been_practiced" class="hidden items-center gap-1 sm:inline-flex"><Target class="size-3.5" />熟练度 {{ currentQ.proficiency || 0 }}/5</span>
        </div>
        <div class="flex min-w-0 flex-wrap items-center gap-1.5 sm:justify-end">
          <Button v-if="currentQ" data-testid="practice-add-to-deck" variant="ghost" size="sm" class="h-10 gap-1.5 px-2 text-xs text-muted-foreground sm:h-8" @click="openDeckPicker"><Plus class="size-3.5" />加入题单</Button>
          <Button data-testid="practice-practiced" variant="ghost" size="sm" class="h-10 gap-1.5 px-2 text-xs text-muted-foreground sm:h-8" @click="togglePracticed"><History class="size-3.5" />已刷过的题</Button>
          <AppTooltip v-if="currentQ" :text="currentQ.is_starred ? '取消收藏' : '收藏题目'">
            <Button variant="ghost" size="sm" class="h-11 min-h-11 gap-1.5 px-2 text-muted-foreground hover:text-amber-500 sm:size-9 sm:min-h-0 sm:px-0" :aria-label="currentQ.is_starred ? '取消收藏' : '收藏题目'" @click="toggleStar"><Star :size="17" :fill="currentQ.is_starred ? 'currentColor' : 'none'" /><span class="text-xs sm:sr-only">{{ currentQ.is_starred ? '取消收藏' : '收藏' }}</span></Button>
          </AppTooltip>
          <Badge v-if="currentQ.difficulty" variant="outline" class="text-[10px]" :class="difficultyClass(currentQ.difficulty)">{{ currentQ.difficulty }}</Badge>
          <Badge variant="outline" class="max-w-32 truncate text-[10px]">{{ currentQ.cat1 || '未分类' }}</Badge>
        </div>
      </div>

      <div data-testid="practice-card-content" :key="currentQ.id" class="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-5 custom-scrollbar question-content-enter sm:px-6 md:px-12 md:py-7">
        <div class="flex flex-wrap items-center gap-1.5">
          <Badge v-for="tag in questionTags(currentQ).slice(0, 4)" :key="tag" variant="secondary" class="text-[10px]">{{ tag }}</Badge>
        </div>

        <div class="mx-auto flex min-h-0 w-full max-w-3xl flex-none flex-col py-5 text-center sm:py-6 md:flex-1 md:py-8" :class="answerRevealed ? 'justify-start' : 'justify-start md:justify-center'">
          <div v-if="currentQ.is_checkin" class="mb-3 flex justify-center">
            <Badge variant="outline" class="text-[10px] text-muted-foreground" data-testid="checkin-badge">保持手感 · 已掌握题每 30 天复查一次</Badge>
          </div>
          <h2 class="practice-question font-semibold leading-relaxed tracking-tight text-foreground">{{ currentQ.question }}</h2>

          <div v-if="!answerRevealed" class="mt-10 flex flex-col items-center gap-3">
            <template v-if="isAlgorithmQueue">
              <template v-if="recallCover">
                <p class="text-sm text-muted-foreground">答案已盖住，先在脑中完整复述一遍</p>
                <Button data-testid="practice-reveal-again" size="lg" class="gap-2 px-6" @click="answerRevealed = true"><Eye class="size-4" />再次对照答案</Button>
                <span class="text-[11px] text-muted-foreground">这次只练回忆，不会重复记录自评<span class="hidden sm:inline"> · Enter 再次查看</span></span>
              </template>
              <template v-else>
                <p class="text-sm text-muted-foreground">先判断一下，能答出来吗？</p>
                <div class="flex w-full max-w-md flex-col gap-2.5 sm:w-auto sm:flex-row">
                  <Button data-testid="practice-self-assess-again" variant="outline" size="lg" class="w-full gap-2 sm:w-36" @click="handleSelfAssess('again')"><kbd class="hidden text-[10px] opacity-60 sm:inline">1</kbd><X class="size-4" />不会</Button>
                  <Button data-testid="practice-self-assess-hard" variant="outline" size="lg" class="w-full gap-2 sm:w-36" @click="handleSelfAssess('hard')"><kbd class="hidden text-[10px] opacity-60 sm:inline">2</kbd><Target class="size-4" />有点印象</Button>
                  <Button data-testid="practice-self-assess-good" size="lg" class="w-full gap-2 sm:w-36" @click="handleSelfAssess('good')"><kbd class="hidden text-[10px] opacity-70 sm:inline">3</kbd><Check class="size-4" />能答出</Button>
                </div>
                <span class="text-[11px] text-muted-foreground">先自评，再看答案<span class="hidden sm:inline"> · 按 1 / 2 / 3 快速选择</span></span>
                <Button data-testid="practice-postpone" variant="ghost" size="sm" class="gap-1.5 text-muted-foreground" @click="postponeCurrentQuestion"><Clock3 class="size-3.5" />稍后再答 <kbd class="hidden text-[10px] opacity-60 sm:inline">S</kbd></Button>
              </template>
            </template>
            <template v-else>
              <Button data-testid="practice-show-answer" size="lg" class="gap-2 px-6" @click="answerRevealed = true"><Eye :size="17" />查看参考答案</Button>
              <span class="text-[11px] text-muted-foreground"><span class="sm:hidden">点击按钮查看答案</span><span class="hidden sm:inline">Enter 查看答案 · ← → 切换题目</span></span>
            </template>
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
            <div v-else-if="currentQ.ai_answer && !isFailedAnswer(currentQ.ai_answer)" class="flashcard-answer answer-content rounded-xl border border-border/80 bg-muted/30 p-4 text-sm leading-7 text-foreground md:p-6" v-html="renderMarkdown(currentQ.ai_answer)"></div>
            <div v-else class="rounded-xl border border-dashed border-border bg-muted/30 p-8 text-center">
              <p v-if="isAdmin" class="text-sm text-muted-foreground">这道题还没有参考答案</p>
              <p v-else class="text-sm text-muted-foreground">这道题还没有参考答案，请等待管理员生成</p>
              <Button v-if="isAdmin" size="sm" class="mt-4 gap-1.5" :disabled="qState._isLoadingAnswer" @click="handleGenerate"><Sparkles class="size-4" />AI 生成答案</Button>
            </div>
            <SourceList
              :sources="referenceAnswerSources"
              :open="qState._showAnswerSources"
              test-id="reference-answer-sources"
              @update:open="qState._showAnswerSources = $event"
            />
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
              <div v-else-if="qState._recitation">
                <div class="recitation-content answer-content text-sm leading-7 text-foreground" v-html="renderMarkdown(qState._recitation)"></div>
                <SourceList
                  :sources="qState._recitationSources"
                  :open="qState._showRecitationSources"
                  test-id="recitation-sources"
                  @update:open="qState._showRecitationSources = $event"
                />
              </div>
              <div v-else-if="qState._isGeneratingRecitation" class="flex flex-col items-center gap-2 py-4 text-primary">
                <Loader2 class="size-5 animate-spin" />
                <span class="text-xs">正在结合你的岗位/简历定制背诵稿...</span>
              </div>
              <Button v-else size="sm" class="gap-1.5" :disabled="qState._isGeneratingRecitation" @click="handleGenerateRecitation"><Sparkles class="size-4" />AI 定制我的背诵稿</Button>
            </div>
          </div>
        </div>

        <div v-if="answerRevealed" data-testid="practice-review-actions" class="mt-6 border-t border-border pt-5">
          <div v-if="isAlgorithmQueue" class="flex flex-col gap-3">
            <div class="flex items-center justify-between gap-3">
              <div>
              <p class="text-sm font-semibold text-foreground">{{ reviewStatusLabel }}</p>
              <p class="mt-1 text-[11px] text-muted-foreground">{{ reviewStatusHint }}</p>
              </div>
              <Button
                v-if="reviewStatus === 'error'"
                data-testid="practice-retry-review"
                variant="outline"
                size="sm"
                class="gap-1.5"
                @click="retrySelfAssessment"
              ><RotateCcw class="size-3.5" />重试保存</Button>
              <Button
                v-else
                data-testid="practice-next-question"
                size="sm"
                class="gap-1.5"
                :disabled="reviewStatus !== 'saved' || correctionLoading"
                @click="nextWithRating"
              ><Loader2 v-if="reviewStatus === 'saving' || correctionLoading" class="size-3.5 animate-spin" /><ArrowRight v-else class="size-3.5" />下一题 <kbd v-if="reviewStatus === 'saved' && !correctionLoading" class="hidden text-[10px] opacity-60 sm:inline">Enter</kbd></Button>
            </div>
            <div v-if="reviewStatus === 'saved' && savedReview?.can_correct" data-testid="practice-correct-rating" class="flex flex-wrap items-center gap-1.5 rounded-lg bg-muted/40 px-2.5 py-2 text-[11px] text-muted-foreground">
              <span class="mr-auto">对照答案后判断有偏差？可直接修正</span>
              <Button v-for="rating in correctionRatings" :key="rating" variant="ghost" size="sm" class="h-8 px-2 text-xs" :class="selfRating === rating ? 'bg-background font-semibold text-foreground shadow-sm' : ''" :disabled="correctionLoading || selfRating === rating" :data-testid="`practice-correct-${rating}`" @click="correctSelfAssessment(rating)">{{ ratingLabels[rating] }}</Button>
            </div>
          </div>
          <div v-else class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
            <Button data-testid="practice-recall-again" variant="ghost" size="sm" class="ml-auto gap-1.5 text-muted-foreground" @click="coverAnswerForRecall"><RotateCcw class="size-3.5" />再想一遍</Button>
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

        <div v-if="currentQ.sources?.length" data-testid="practice-question-sources" class="mt-5 flex flex-col gap-2 border-t border-border/60 pt-4 text-[11px] text-muted-foreground sm:flex-row sm:flex-wrap sm:items-center sm:gap-1.5 sm:border-t-0 sm:pt-0">
          <div class="flex items-center gap-1.5"><Link2 class="size-3.5 shrink-0" /><span>出处：</span></div>
          <div class="grid w-full gap-2 sm:flex sm:w-auto sm:flex-wrap sm:gap-1.5">
            <button v-for="(source, sourceIndex) in currentQ.sources" :key="sourceIndex" type="button" class="flex min-h-10 w-full min-w-0 items-center justify-start break-words rounded-md border border-border bg-card px-3 py-2 text-left leading-5 transition hover:border-border hover:bg-accent hover:text-foreground sm:w-auto sm:justify-center" @click="emit('navigate-to-interview', { source, questionId: currentQ.id })">{{ source.company || '未知公司' }} · {{ source.round || '未知轮次' }}</button>
          </div>
        </div>
      </div>
      </div>
    </Card>

    <div v-else class="mx-auto flex min-h-0 w-full max-w-xl flex-1 flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card px-6 py-12 text-center">
      <div class="flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground"><List :size="26" /></div>
      <h2 class="mt-5 text-lg font-semibold text-foreground">{{ sessionKey === 'due' ? '今日复习已经完成' : '这个题单还没有题目' }}</h2>
      <p class="mt-2 text-sm leading-relaxed text-muted-foreground">{{ sessionKey === 'due' ? completionMessage : '先收藏几道题，或者切换到全部题开始刷题。' }}</p>
      <div v-if="sessionKey === 'due' && sessionReviewCount" data-testid="practice-session-summary" class="mt-5 w-full max-w-md rounded-xl border border-border/80 bg-muted/30 p-4">
        <p class="text-sm font-semibold text-foreground">本轮完成 {{ sessionReviewCount }} 次主动回忆</p>
        <div class="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div class="rounded-lg bg-background px-2 py-2"><span class="block font-semibold text-emerald-600 dark:text-emerald-400">{{ sessionRatings.good + sessionRatings.easy }}</span><span class="text-muted-foreground">能答出</span></div>
          <div class="rounded-lg bg-background px-2 py-2"><span class="block font-semibold text-amber-600 dark:text-amber-400">{{ sessionRatings.hard }}</span><span class="text-muted-foreground">有点模糊</span></div>
          <div class="rounded-lg bg-background px-2 py-2"><span class="block font-semibold text-rose-600 dark:text-rose-400">{{ sessionRatings.again }}</span><span class="text-muted-foreground">不会</span></div>
        </div>
        <p v-if="sessionWeakQuestions.length" class="mt-3 text-xs text-muted-foreground">本轮有 {{ sessionWeakQuestions.length }} 道题需要继续巩固。</p>
      </div>
      <div class="mt-5 flex flex-wrap justify-center gap-2">
        <Button v-if="sessionKey === 'due' && sessionWeakQuestions.length" data-testid="practice-retry-weak" class="gap-1.5" @click="restartWeakSession"><RotateCcw class="size-3.5" />重刷 {{ sessionWeakQuestions.length }} 道薄弱题</Button>
        <Button
          v-if="sessionKey === 'due' && canExtendDailyPlan"
          data-testid="practice-continue-five"
          :variant="sessionWeakQuestions.length ? 'outline' : 'default'"
          class="gap-1.5"
          :disabled="capacitySaving || deckLoading"
          @click="adjustDailyCapacity(5)"
        ><Loader2 v-if="capacitySaving" class="size-3.5 animate-spin" /><Plus v-else class="size-3.5" />{{ capacitySaving ? '正在安排…' : '再学 5 题' }}</Button>
        <Button variant="outline" @click="selectSession('all')">切换到全部题</Button>
      </div>
    </div>

    <div v-if="currentQ" class="mx-auto flex w-full shrink-0 flex-wrap items-center justify-between gap-2 px-1 pb-[env(safe-area-inset-bottom)] sm:gap-3">
      <template v-if="isAlgorithmQueue">
        <span data-testid="practice-question-total" class="ml-auto text-xs tabular-nums text-muted-foreground">题库共 {{ questionBankTotal }} 题</span>
      </template>
      <template v-else>
        <Button variant="outline" class="min-w-28 flex-1 gap-2 sm:flex-none" :disabled="currentIndex === 0" @click="goPrev"><ChevronLeft class="size-4" />上一题</Button>
        <div class="flex flex-1 items-center justify-end gap-2 sm:ml-auto sm:gap-3">
          <span data-testid="practice-question-total" class="text-xs tabular-nums text-muted-foreground">题库共 {{ questionBankTotal }} 题</span>
          <Button variant="outline" class="min-w-28 flex-1 gap-2 sm:flex-none" @click="goNext">{{ isLastQuestion ? '完成一轮' : '下一题' }}<ChevronRight class="size-4" /></Button>
        </div>
      </template>
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

  <AppDialog
    :open="showPracticed"
    title="已刷过的题"
    :max-width="'32rem'"
    @update:open="showPracticed = $event"
  >
    <template #default>
      <div class="max-h-[60vh] overflow-y-auto custom-scrollbar">
        <p v-if="practicedLoading" class="py-8 text-center text-sm text-muted-foreground">加载中...</p>
        <div v-else-if="practicedList.length" class="flex flex-col gap-1.5">
          <div
            v-for="item in practicedList"
            :key="item.id"
            class="flex items-center gap-2.5 rounded-lg border border-border bg-card p-2.5"
          >
            <span class="flex size-7 shrink-0 items-center justify-center rounded-md text-xs font-semibold" :class="scoreTextColor(item.proficiency * 20)">{{ item.proficiency }}/5</span>
            <div class="min-w-0 flex-1">
              <p class="truncate text-sm text-foreground">{{ item.question }}</p>
              <p class="mt-0.5 text-[11px] text-muted-foreground">
                刷过 {{ item.review_count }} 次
                <span v-if="item.next_review_at"> · 下次复习 {{ formatNextReview(item.next_review_at) }}</span>
                <span v-if="item.last_rating"> · {{ { again: '不会', hard: '有点模糊', good: '记得了', easy: '很熟' }[item.last_rating] || item.last_rating }}</span>
              </p>
            </div>
          </div>
        </div>
        <p v-else class="py-8 text-center text-sm text-muted-foreground">还没有刷过的题，先去刷几道吧。</p>
      </div>
    </template>
  </AppDialog>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import {
  ArrowRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Eye,
  Flame,
  History,
  Layers,
  Link2,
  List,
  Loader2,
  Minus,
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
  X,
  Zap,
} from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import AppDialog from '@/components/common/AppDialog.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'
import SourceList from '@/components/common/SourceList.vue'
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
  selectedDeck: { type: Object, default: null },
  reviewLoading: { type: Boolean, default: false },
  deckLoading: { type: Boolean, default: false },
  hasMoreQuestions: { type: Boolean, default: false },
  questionTotal: { type: Number, default: 0 },
  loadingMoreQuestions: { type: Boolean, default: false },
  dailyCapacity: { type: Number, default: 30 },
  capacitySaving: { type: Boolean, default: false },
  startIndex: { type: Number, default: 0 },
  isAdmin: { type: Boolean, default: false },
  practicedQuestions: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['close', 'answer-evaluated', 'toggle-star', 'navigate-to-interview', 'select-deck', 'load-more', 'review', 'correct-review', 'update-daily-capacity', 'add-to-deck', 'manage-decks'])
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
const pendingReviewedId = ref(null)
const showDeckPicker = ref(false)
const addDeckKey = ref('')
// 已刷过的题（右上角入口）
const showPracticed = ref(false)
const practicedList = ref([])
const practicedLoading = ref(false)
// 模式：quiz=算法队列刷题（无侧栏，先自评再看答案）；browse=列表浏览（侧栏可自由切题）
const viewMode = ref(props.selectedDeckKey === 'due' ? 'quiz' : 'browse')
const isAlgorithmQueue = computed(() => viewMode.value === 'quiz')
const selfRating = ref(null)
const reviewStatus = ref('idle')
const retainedReviewedId = ref(null)
const savedReview = ref(null)
const correctionLoading = ref(false)
const recallCover = ref(false)
const RELEARNING_GAP = 3
const relearningQueue = ref([])
const postponedQuestionIds = ref([])
const sessionRatings = reactive({ again: 0, hard: 0, good: 0, easy: 0 })
const sessionWeakQuestions = ref([])
const qState = reactive({ _userAnswer: '', _evaluation: null, _isEvaluating: false, _isLoadingAnswer: false, _history: null, _historyLoading: false, _isEditingAnswer: false, _editAnswer: '', _isSavingAnswer: false, _recitation: '', _recitationSources: [], _showRecitationSources: false, _showAnswerSources: false, _isGeneratingRecitation: false, _isEditingRecitation: false, _editRecitation: '', _isSavingRecitation: false })

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
  if (serverDeckMode.value) {
    if (props.deckLoading) return []
    if (props.selectedDeckKey !== 'due') return props.questions
    const postponedIds = new Set(postponedQuestionIds.value)
    const relearningIds = new Set(relearningQueue.value.map(entry => entry.question.id))
    const dueQuestions = props.questions.filter(question => (
      (question.id === retainedReviewedId.value || question.is_daily_relearning || isDueNow(question.next_review_at))
      && !postponedIds.has(question.id)
      && (question.id === retainedReviewedId.value || !relearningIds.has(question.id))
    ))
    const dueIds = new Set(dueQuestions.map(question => question.id))
    const relearningQuestions = relearningQueue.value
      .filter(entry => entry.remaining <= 0 && !dueIds.has(entry.question.id))
      .map(entry => entry.question)
    const queuedIds = new Set([...dueIds, ...relearningQuestions.map(question => question.id)])
    const postponedQuestions = postponedQuestionIds.value
      .map(id => props.questions.find(question => question.id === id))
      .filter(question => question
        && (question.id === retainedReviewedId.value || question.is_daily_relearning || isDueNow(question.next_review_at))
        && !queuedIds.has(question.id))
    return [...dueQuestions, ...relearningQuestions, ...postponedQuestions]
  }
  if (sessionKey.value === 'starred') return starredQuestions.value
  return props.questions
})
const sessionQuestions = computed(() => {
  const query = deckQuery.value.trim().toLowerCase()
  if (!query) return sessionSource.value
  return sessionSource.value.filter(question => [question.question, question.cat1, question.cat2, question.tags].some(value => String(value || '').toLowerCase().includes(query)))
})
const questionBankTotal = computed(() => {
  if (serverDeckMode.value) return Number(props.questionTotal) || sessionSource.value.length
  if (sessionKey.value === 'starred') return starredQuestions.value.length
  return props.questions.length
})
const currentQ = computed(() => sessionQuestions.value[currentIndex.value] || null)
const referenceAnswerSources = computed(() => (
  Array.isArray(currentQ.value?.answer_sources) ? currentQ.value.answer_sources : []
))
const isLastQuestion = computed(() => currentIndex.value >= sessionQuestions.value.length - 1)
const completedToday = computed(() => Number(props.selectedDeck?.completed_today || 0))
const attemptedToday = computed(() => Number(props.selectedDeck?.attempted_today || 0))
const reviewAttemptsToday = computed(() => Number(props.selectedDeck?.review_attempts_today || 0))
const remainingToday = computed(() => Number(props.selectedDeck?.remaining_today ?? sessionSource.value.length))
const dailyPlanTotal = computed(() => Number(props.selectedDeck?.planned_today || (completedToday.value + remainingToday.value)))
const dailyProgress = computed(() => dailyPlanTotal.value
  ? Math.round(completedToday.value / dailyPlanTotal.value * 100)
  : 0)
const canExtendDailyPlan = computed(() => props.dailyCapacity < 200 && props.questionTotal > 0)
const sessionReviewCount = computed(() => Object.values(sessionRatings).reduce((sum, count) => sum + count, 0))
const studyStreak = computed(() => Number(props.selectedDeck?.study_streak || 0))
const streakLabel = computed(() => {
  if (props.selectedDeck?.studied_today) return `连续 ${studyStreak.value} 天`
  if (studyStreak.value) return `再刷 1 题延续 ${studyStreak.value} 天`
  return '今天开始第 1 天'
})
const taskMixLabel = computed(() => [
  ['到期复习', props.selectedDeck?.due_review_count],
  ['待巩固', props.selectedDeck?.relearning_count],
  ['保持手感', props.selectedDeck?.checkin_count],
  ['新学', props.selectedDeck?.new_question_count],
].filter(([, count]) => Number(count || 0) > 0).map(([label, count]) => `${label} ${count}`).join(' · '))
const reviewForecast = computed(() => Array.isArray(props.selectedDeck?.review_forecast)
  ? props.selectedDeck.review_forecast
  : [])
const forecastTotal = computed(() => reviewForecast.value.reduce((sum, day) => sum + Number(day.count || 0), 0))
const forecastMaximum = computed(() => Math.max(1, ...reviewForecast.value.map(day => Number(day.count || 0))))
const completionMessage = computed(() => props.selectedDeck?.next_due_at
  ? `下一轮复习将在${formatNextReview(props.selectedDeck.next_due_at)}到期，也可以切换到全部题继续刷。`
  : '今天的计划已完成，明天再来复习，或者切换到全部题继续刷。')
const reviewStatusLabel = computed(() => ({
  saving: '正在保存自评…',
  saved: '自评已保存',
  error: '自评保存失败',
})[reviewStatus.value] || '等待自评')
const ratingLabels = { again: '不会', hard: '有点印象', good: '能答出', easy: '很熟' }
const correctionRatings = ['again', 'hard', 'good']
const reviewStatusHint = computed(() => {
  if (reviewStatus.value === 'error') return '记录尚未成功，请重试后再进入下一题'
  if (reviewStatus.value !== 'saved' || !savedReview.value) return '对照答案查漏补缺，保存完成后进入下一题'
  const pieces = [ratingLabels[selfRating.value] || '已自评']
  if (selfRating.value === 'again') pieces.push('本轮稍后再考')
  if (savedReview.value.next_review_at) {
    pieces.push(`${selfRating.value === 'again' ? '后续' : '预计'} ${formatNextReview(savedReview.value.next_review_at)}复习`)
  }
  if (savedReview.value.proficiency != null) pieces.push(`熟练度 ${savedReview.value.proficiency}/5`)
  return pieces.join(' · ')
})

function adjustDailyCapacity(delta) {
  emit('update-daily-capacity', Math.min(200, Math.max(5, props.dailyCapacity + delta)))
}

function isDueNow(nextReviewAt) {
  if (!nextReviewAt) return true
  const value = String(nextReviewAt)
  const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value)
    ? value
    : `${value.replace(' ', 'T')}Z`)
  return Number.isNaN(parsed.getTime()) || parsed.getTime() <= Date.now()
}

function forecastBarHeight(count) {
  const value = Number(count || 0)
  return value ? `${Math.max(4, Math.round(value / forecastMaximum.value * 24))}px` : '2px'
}
function forecastDayLabel(date) {
  const parsed = new Date(`${date}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return ''
  return ['日', '一', '二', '三', '四', '五', '六'][parsed.getUTCDay()]
}

const difficultyClass = (difficulty) => {
  const value = String(difficulty || '')
  if (value.includes('L3')) return 'border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-800 dark:bg-rose-900/20 dark:text-rose-400'
  if (value.includes('L2')) return 'border-amber-200 bg-amber-50 text-amber-600 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-400'
  return 'border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-400'
}

function resetState() { resetQState(qState); qState._recitation = currentQ.value?.user_answer || ''; answerRevealed.value = false; showSelfCheck.value = false; showHistory.value = false; selfRating.value = null; reviewStatus.value = 'idle'; savedReview.value = null; correctionLoading.value = false; recallCover.value = false }
function selectSession(key) {
  const option = sessionOptions.value.find(item => item.key === key)
  if (!option?.count) { toast.warning('这个题单还没有题目'); return }
  sessionKey.value = key
  currentIndex.value = 0
  deckQuery.value = ''
  pendingReviewedId.value = null
  resetState()
  if (serverDeckMode.value) emit('select-deck', key)
}
// 墨墨模式：due 队列未完成自评前禁止切换题目
function queueSwitchBlocked() {
  if (reviewStatus.value === 'saving' || correctionLoading.value) {
    toast.warning('正在保存这道题的自评，请稍候')
    return true
  }
  if (isAlgorithmQueue.value && !answerRevealed.value) {
    toast.warning('先自评这道题（不会 / 有点印象 / 能答出），再看答案切换')
    return true
  }
  return false
}
function selectFromSidebar(questionIndex) {
  if (queueSwitchBlocked()) return
  currentIndex.value = questionIndex
  resetState()
  mobileSidebarOpen.value = false
}
function requestMoreQuestions() {
  if (props.hasMoreQuestions && !props.loadingMoreQuestions) emit('load-more')
}
function handleQueueScroll(event) {
  const target = event.currentTarget
  if (target.scrollTop + target.clientHeight >= target.scrollHeight - 120) requestMoreQuestions()
}
// 模式切换：quiz（算法刷题）↔ browse（列表看题，默认全部题）
function switchToBrowse() {
  if (reviewStatus.value === 'saving' || correctionLoading.value) { toast.warning('正在保存这道题的自评，请稍候'); return }
  viewMode.value = 'browse'
  if (props.selectedDeckKey === 'due') emit('select-deck', 'all')
}
function switchToQuiz() {
  viewMode.value = 'quiz'
  if (props.selectedDeckKey !== 'due') emit('select-deck', 'due')
}
function goPrev() { if (queueSwitchBlocked()) return; if (currentIndex.value > 0) { currentIndex.value -= 1; pendingReviewedId.value = null; resetState() } }
function goNext() {
  if (queueSwitchBlocked()) return
  if (!sessionQuestions.value.length) return
  if (isLastQuestion.value) {
    if (props.hasMoreQuestions) {
      requestMoreQuestions()
      return
    }
    currentIndex.value = 0; resetState(); toast.info('这一轮完成了，已回到第 1 题'); return
  }
  currentIndex.value += 1
  resetState()
}
function markAndNext(rating) {
  if (!currentQ.value?.id) return
  if (rating === 'good' || rating === 'easy') rememberedIds.value = new Set([...rememberedIds.value, currentQ.value.id])
  pendingReviewedId.value = currentQ.value.id
  if (serverDeckMode.value) emit('review', { questionId: currentQ.value.id, rating })
  goNext()
}
function saveSelfAssessment() {
  if (!currentQ.value?.id || !selfRating.value || reviewStatus.value === 'saving') return
  const questionId = currentQ.value.id
  const reviewedQuestion = currentQ.value
  const rating = selfRating.value
  reviewStatus.value = 'saving'
  emit('review', {
    questionId,
    rating,
    onComplete: (response) => {
      if (retainedReviewedId.value !== questionId) return
      savedReview.value = response?.review || null
      reviewStatus.value = response ? 'saved' : 'error'
      if (response) {
        sessionRatings[rating] += 1
        if (
          (rating === 'again' || rating === 'hard')
          && !sessionWeakQuestions.value.some(question => question.id === questionId)
        ) {
          sessionWeakQuestions.value = [...sessionWeakQuestions.value, reviewedQuestion]
        }
      }
    },
  })
}
// 墨墨式主流程：三选一即落库，同时保留当前卡供用户对照答案。
function handleSelfAssess(rating) {
  if (!currentQ.value?.id || answerRevealed.value || recallCover.value || reviewStatus.value !== 'idle') return
  selfRating.value = rating
  retainedReviewedId.value = currentQ.value.id
  answerRevealed.value = true
  saveSelfAssessment()
}
function postponeCurrentQuestion() {
  if (!isAlgorithmQueue.value || answerRevealed.value || recallCover.value || reviewStatus.value !== 'idle' || !currentQ.value) return
  if (sessionQuestions.value.length <= 1) {
    toast.info('本轮只剩这一题，先试着回忆一下吧')
    return
  }
  const questionId = currentQ.value.id
  const nextQuestionId = sessionQuestions.value[currentIndex.value + 1]?.id
    ?? sessionQuestions.value.find(question => question.id !== questionId)?.id
  postponedQuestionIds.value = [
    ...postponedQuestionIds.value.filter(id => id !== questionId),
    questionId,
  ]
  currentIndex.value = Math.max(0, sessionQuestions.value.findIndex(question => question.id === nextQuestionId))
  resetState()
  toast.info('已放到本轮稍后，不计入完成进度')
}
function coverAnswerForRecall() {
  if (isAlgorithmQueue.value && reviewStatus.value !== 'saved') return
  answerRevealed.value = false
  recallCover.value = isAlgorithmQueue.value
  showSelfCheck.value = false
  showHistory.value = false
}
function retrySelfAssessment() { saveSelfAssessment() }
function correctSelfAssessment(rating) {
  if (!currentQ.value?.id || !savedReview.value?.event_id || correctionLoading.value || rating === selfRating.value) return
  const previousRating = selfRating.value
  const questionId = currentQ.value.id
  correctionLoading.value = true
  emit('correct-review', {
    eventId: savedReview.value.event_id,
    questionId,
    rating,
    previousRating,
    onComplete: (response) => {
      correctionLoading.value = false
      if (!response || retainedReviewedId.value !== questionId) return
      savedReview.value = response.review
      selfRating.value = rating
      sessionRatings[previousRating] = Math.max(0, sessionRatings[previousRating] - 1)
      sessionRatings[rating] += 1
      const needsRelearning = rating === 'again' || rating === 'hard'
      const withoutQuestion = sessionWeakQuestions.value.filter(question => question.id !== questionId)
      sessionWeakQuestions.value = needsRelearning
        ? [...withoutQuestion, currentQ.value]
        : withoutQuestion
      toast.success(`已修正为“${ratingLabels[rating]}”`)
    },
  })
}
function nextWithRating() {
  if (reviewStatus.value !== 'saved' || correctionLoading.value || !currentQ.value) return
  const reviewedQuestion = currentQ.value
  const reviewedId = reviewedQuestion.id
  const rating = selfRating.value
  const nextQuestionId = sessionQuestions.value[currentIndex.value + 1]?.id
  postponedQuestionIds.value = postponedQuestionIds.value.filter(id => id !== reviewedId)

  // 未达到过关条件的卡会继续留在本轮；不会更快回流，模糊稍后再验一次。
  const agedQueue = relearningQueue.value
    .filter(entry => entry.question.id !== reviewedId)
    .map(entry => ({ ...entry, remaining: Math.max(0, entry.remaining - 1) }))
  if (rating === 'again' || rating === 'hard') {
    agedQueue.push({ question: reviewedQuestion, remaining: rating === 'again' ? RELEARNING_GAP : RELEARNING_GAP + 2 })
  }
  relearningQueue.value = agedQueue
  retainedReviewedId.value = null

  // 本轮没有其他卡时不让用户误入完成态，立即把最早的不会卡提到队尾。
  if (!sessionQuestions.value.length && relearningQueue.value.length) {
    const minimum = Math.min(...relearningQueue.value.map(entry => entry.remaining))
    relearningQueue.value = relearningQueue.value.map(entry => (
      entry.remaining === minimum ? { ...entry, remaining: 0 } : entry
    ))
  }
  const nextIndex = nextQuestionId == null
    ? Math.min(currentIndex.value, Math.max(0, sessionQuestions.value.length - 1))
    : sessionQuestions.value.findIndex(question => question.id === nextQuestionId)
  currentIndex.value = Math.max(0, nextIndex)
  resetState()
}
function restartWeakSession() {
  if (!sessionWeakQuestions.value.length) return
  relearningQueue.value = sessionWeakQuestions.value.map(question => ({ question, remaining: 0 }))
  retainedReviewedId.value = null
  currentIndex.value = 0
  resetState()
  toast.info(`开始巩固 ${sessionWeakQuestions.value.length} 道本轮薄弱题`)
}
function resetSessionSummary() {
  for (const rating of Object.keys(sessionRatings)) sessionRatings[rating] = 0
  sessionWeakQuestions.value = []
}
function toggleStar() { if (currentQ.value) emit('toggle-star', currentQ.value) }
async function togglePracticed() {
  showPracticed.value = !showPracticed.value
  if (showPracticed.value && !practicedList.value.length) {
    practicedLoading.value = true
    try {
      const { fetchPracticedQuestions } = await import('@/services/practiceApi.js')
      const data = await fetchPracticedQuestions()
      practicedList.value = data.items || []
    } catch (e) {
      toast.error('加载已刷题列表失败')
    } finally {
      practicedLoading.value = false
    }
  }
}
function formatNextReview(date) {
  if (!date) return ''
  const value = String(date)
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value.replace(' ', 'T')}Z`)
  if (Number.isNaN(d.getTime())) return String(date).slice(0, 10)
  const now = Date.now()
  const diff = d.getTime() - now
  if (diff < 0) return '已到期'
  const hours = Math.max(1, Math.ceil(diff / 3600000))
  if (hours < 24) return `${hours} 小时后`
  return `${Math.ceil(hours / 24)} 天后`
}
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
  if (isAlgorithmQueue.value) {
    if (!answerRevealed.value) {
      if (recallCover.value && ['Enter', ' '].includes(event.key)) {
        event.preventDefault()
        answerRevealed.value = true
        return
      }
      const rating = { '1': 'again', '2': 'hard', '3': 'good' }[event.key]
      if (rating) { event.preventDefault(); handleSelfAssess(rating) }
      else if (event.key.toLowerCase() === 's') { event.preventDefault(); postponeCurrentQuestion() }
      return
    }
    if (['Enter', 'ArrowRight', ' '].includes(event.key)) {
      event.preventDefault()
      if (reviewStatus.value === 'saved') nextWithRating()
      else if (reviewStatus.value === 'error') retrySelfAssessment()
    }
    return
  }
  if (event.key === 'ArrowLeft') { event.preventDefault(); goPrev() }
  else if (event.key === 'ArrowRight') { event.preventDefault(); goNext() }
  else if (event.key === 'Enter' && currentQ.value && !answerRevealed.value && !isAlgorithmQueue.value) { event.preventDefault(); answerRevealed.value = true }
}

watch(sessionQuestions, (questions) => {
  const reviewedId = pendingReviewedId.value
  if (reviewedId && !questions.some(q => q.id === reviewedId)) {
    // 复习的卡已被移出队列（排到未来）：goNext 已 +1，这里补偿回来，避免跳过下一张
    pendingReviewedId.value = null
    if (currentIndex.value > 0) {
      currentIndex.value = Math.min(currentIndex.value - 1, questions.length - 1)
      return
    }
  }
  if (currentIndex.value >= questions.length) currentIndex.value = Math.max(0, questions.length - 1)
})
watch(() => props.startIndex, (index) => { currentIndex.value = Math.min(Math.max(0, index), Math.max(0, sessionQuestions.value.length - 1)) })
watch(() => props.selectedDeckKey, (key) => {
  if (key) {
    sessionKey.value = key
    currentIndex.value = 0
    pendingReviewedId.value = null
    retainedReviewedId.value = null
    relearningQueue.value = []
    postponedQuestionIds.value = []
    resetSessionSummary()
    resetState()
    // due 队列 = 算法刷题模式；其他题单 = 浏览模式
    viewMode.value = key === 'due' ? 'quiz' : 'browse'
  }
})
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
