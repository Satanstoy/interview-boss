<template>
  <div class="fixed inset-0 z-[90] bg-white dark:bg-surface-900 flex flex-col">
    <!-- TOP BAR -->
    <div class="h-12 flex items-center justify-between px-4 border-b border-surface-200 dark:border-ink-700 bg-surface-50 dark:bg-surface-900 shrink-0">
      <div class="flex items-center gap-2 min-w-0 flex-1 mr-3">
        <button @click="showDirectory = !showDirectory" class="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-200 dark:hover:bg-ink-700 transition shrink-0" title="题目目录">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16"/></svg>
        </button>
        <span class="text-xs font-bold tabular-nums text-primary-600 dark:text-primary-400 shrink-0">{{ currentIndex + 1 }}/{{ questions.length }}</span>
        <h2 class="text-sm font-bold text-ink-800 dark:text-ink-100 truncate">{{ currentQ.question }}</h2>
        <Badge variant="outline" class="text-[10px] shrink-0"
          :class="String(currentQ.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400 border-red-100 dark:border-red-800' : String(currentQ.difficulty).includes('L2') ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 border-amber-100 dark:border-amber-800' : 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 border-emerald-100 dark:border-emerald-800'">
          {{ currentQ.difficulty || '-' }}
        </Badge>
        <Badge variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-100 dark:border-primary-800 text-[10px] shrink-0 hidden sm:inline">{{ currentQ.cat1 || '未分类' }}</Badge>
        <span v-if="currentQ.cat2" class="text-[10px] text-ink-400 dark:text-ink-500 shrink-0 hidden md:inline">{{ currentQ.cat2 }}</span>
      </div>
      <div class="flex items-center gap-1.5 shrink-0">
        <button @click="toggleStar" class="p-1.5 rounded-lg transition" :class="currentQ.is_starred ? 'text-amber-500' : 'text-ink-300 dark:text-ink-600 hover:text-amber-400'">
          <svg class="size-4" :fill="currentQ.is_starred ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11.049 2.927c.3-.921 1.603-.921 1.902 0l1.519 4.674a1 1 0 00.95.69h4.915c.969 0 1.371 1.24.588 1.81l-3.976 2.888a1 1 0 00-.363 1.118l1.518 4.674c.3.922-.755 1.688-1.538 1.118l-3.976-2.888a1 1 0 00-1.176 0l-3.976 2.888c-.783.57-1.838-.197-1.538-1.118l1.518-4.674a1 1 0 00-.363-1.118l-3.976-2.888c-.784-.57-.38-1.81.588-1.81h4.914a1 1 0 00.951-.69l1.519-4.674z"/></svg>
        </button>
        <div class="w-px h-5 bg-surface-200 dark:bg-ink-700 mx-1"></div>
        <button @click="goRandom" class="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-200 dark:hover:bg-ink-700 transition" title="随机跳题">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
        </button>
        <button @click="goPrev" :disabled="currentIndex === 0" class="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-200 dark:hover:bg-ink-700 transition disabled:opacity-30 disabled:cursor-not-allowed" title="上一题 (Alt+←)">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/></svg>
        </button>
        <button @click="goNext" :disabled="currentIndex >= questions.length - 1" class="p-1.5 rounded-lg text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-200 dark:hover:bg-ink-700 transition disabled:opacity-30 disabled:cursor-not-allowed" title="下一题 (Alt+→)">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/></svg>
        </button>
        <div class="w-px h-5 bg-surface-200 dark:bg-ink-700 mx-1"></div>
        <button @click="emit('close')" class="p-1.5 rounded-lg text-ink-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition" title="退出刷题 (Esc)">
          <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>
    </div>

    <!-- DIRECTORY PANEL -->
    <Transition name="directory-slide">
      <div v-if="showDirectory" class="absolute inset-y-12 left-0 z-10 w-80 bg-white dark:bg-surface-800 border-r border-surface-200 dark:border-ink-700 shadow-xl flex flex-col">
        <div class="p-3 border-b border-surface-200 dark:border-ink-700 flex items-center gap-2">
          <svg class="size-4 text-ink-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
          <input v-model="directorySearch" type="text" class="flex-1 text-sm bg-transparent outline-none text-ink-800 dark:text-ink-200 placeholder-ink-400" placeholder="搜索题目..." />
          <button @click="showDirectory = false; directorySearch = ''" class="p-1 rounded text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 transition">
            <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>
        <div ref="directoryRef" class="flex-1 overflow-y-auto custom-scrollbar">
          <button
            v-for="(item, idx) in filteredQuestions" :key="item.id"
            @click="goToDirectoryItem(item)"
            class="w-full text-left px-3 py-2.5 border-b border-surface-100 dark:border-ink-700/50 hover:bg-surface-50 dark:hover:bg-surface-700 transition-colors"
            :class="item.id === currentQ.id ? 'bg-primary-50 dark:bg-primary-900/20 border-l-2 border-l-primary-500' : ''"
          >
            <div class="flex items-center gap-2 mb-1">
              <span class="text-[10px] font-bold tabular-nums w-5 text-center" :class="item.id === currentQ.id ? 'text-primary-600 dark:text-primary-400' : 'text-ink-400'">{{ questions.indexOf(item) + 1 }}</span>
              <Badge variant="outline" class="text-[9px] shrink-0"
                :class="String(item.difficulty).includes('L3') ? 'bg-red-50 dark:bg-red-900/30 text-red-600 dark:text-red-400' : String(item.difficulty).includes('L2') ? 'bg-amber-50 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400' : 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400'">
                {{ item.difficulty || '-' }}
              </Badge>
              <Badge variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 text-[9px] shrink-0">{{ item.cat1 || '未分类' }}</Badge>
              <span class="text-[10px] text-ink-400 dark:text-ink-500 ml-auto tabular-nums">{{ item.frequency }}</span>
            </div>
            <p class="text-xs text-ink-700 dark:text-ink-300 leading-snug line-clamp-2 ml-7">{{ item.question }}</p>
          </button>
        </div>
      </div>
    </Transition>

    <!-- MAIN CONTENT -->
    <div ref="mainRef" class="relative flex-1 overflow-hidden"
      :class="isMobile ? 'flex flex-col' : 'grid'"
      :style="isMobile ? {} : { gridTemplateColumns: leftWidth + '% 4px 1fr', gridTemplateRows: '1fr' }">
      <!-- LEFT PANEL -->
      <div class="flex flex-col overflow-hidden border-b lg:border-b-0 lg:border-r border-surface-200 dark:border-ink-700 min-w-0">
        <!-- Tabs -->
        <Tabs default-value="description" v-model:value="leftTab">
          <TabsList class="flex border-b border-surface-200 dark:border-ink-600 shrink-0 bg-white dark:bg-surface-800 rounded-none">
            <TabsTrigger value="description">题目</TabsTrigger>
            <TabsTrigger value="answer">
              参考答案
              <span v-if="!currentQ.ai_answer" class="ml-1 inline-block size-1.5 rounded-full bg-red-400"></span>
            </TabsTrigger>
            <TabsTrigger value="history">
              练习记录
              <span v-if="currentQ.attempt_count" class="ml-1 text-[10px] text-ink-400 dark:text-ink-500">({{ currentQ.attempt_count }})</span>
            </TabsTrigger>
          </TabsList>

        <!-- Tab content -->
        <div class="flex-1 overflow-y-auto custom-scrollbar">
        <div :key="currentIndex" class="question-content-enter">
          <!-- Description tab -->
          <TabsContent value="description">
            <!-- Category badges -->
            <div class="flex gap-1.5 flex-wrap items-center">
              <Badge variant="outline" class="bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border-primary-100 dark:border-primary-800 text-[10px]">{{ currentQ.cat1 || '未分类' }}</Badge>
              <Badge v-if="currentQ.cat2" variant="outline" class="bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400 border-surface-200 dark:border-ink-700 text-[10px]">{{ currentQ.cat2 }}</Badge>
              <Badge v-for="tag in (currentQ.tags ? currentQ.tags.split(',') : [])" :key="tag" variant="outline" class="bg-surface-50 dark:bg-surface-900 text-ink-400 dark:text-ink-500 border-surface-200/60 dark:border-ink-700/60 text-[10px]">{{ tag }}</Badge>
            </div>
            <!-- Question text -->
            <div class="text-sm text-ink-800 dark:text-ink-100 leading-relaxed font-medium">{{ currentQ.question }}</div>
            <!-- Original question content -->
            <div v-if="currentQ.original_questions && currentQ.original_questions.length > 0" class="bg-surface-50 dark:bg-surface-900 border border-surface-200 dark:border-ink-700 rounded-xl p-4">
              <h4 class="text-xs font-bold text-ink-600 dark:text-ink-400 mb-2 flex items-center gap-1.5">
                <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                原始面经题目
              </h4>
              <div v-for="(oq, oidx) in currentQ.original_questions" :key="oidx" class="mb-2 last:mb-0">
                <p class="text-xs text-ink-700 dark:text-ink-300 leading-relaxed">{{ oq.question || oq }}</p>
                <div v-if="oq.sources && oq.sources.length" class="flex flex-wrap gap-1 mt-1">
                  <span v-for="(src, sidx) in oq.sources" :key="sidx" @click="emit('navigate-to-interview', { source: src, questionId: currentQ.id })"
                    class="text-[10px] bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400 px-1.5 py-0.5 rounded cursor-pointer hover:bg-primary-100 dark:hover:bg-primary-900/40 transition-colors">
                    {{ src.company || '未知' }} | {{ src.round || '未知' }}
                  </span>
                </div>
              </div>
            </div>
            <!-- Sources -->
            <div v-if="currentQ.sources && currentQ.sources.length > 0" class="bg-primary-50/40 dark:bg-primary-900/20 border border-primary-100 dark:border-primary-800 rounded-xl p-4">
              <h4 class="text-xs font-bold text-primary-800 dark:text-primary-400 mb-2 flex items-center gap-1.5">
                <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
                出处追溯 ({{ currentQ.sources.length }} 次出现)
              </h4>
              <div class="flex flex-wrap gap-1.5 text-[11px]">
                <span v-for="(src, idx) in currentQ.sources" :key="idx" class="bg-white dark:bg-ink-800 border border-primary-200 dark:border-primary-800 text-primary-700 dark:text-primary-400 px-2 py-1 rounded-lg inline-flex items-center gap-1">
                  <span @click="emit('navigate-to-interview', { source: src, questionId: currentQ.id })" class="cursor-pointer hover:underline">
                    {{ src.company === '未提供' ? '未知' : src.company }}
                    <span class="text-primary-300 dark:text-primary-600 mx-0.5">|</span>
                    {{ src.round === '未提供' ? '未知轮次' : src.round }}
                  </span>
                  <a v-if="src.url" :href="src.url" target="_blank" rel="noopener noreferrer" class="text-primary-400 hover:text-primary-600 dark:hover:text-primary-300" title="在新窗口打开">
                    <svg class="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                  </a>
                </span>
              </div>
            </div>
          </TabsContent>

          <!-- Answer tab -->
          <TabsContent value="answer">
            <div v-if="qState._isEditingAnswer" class="flex flex-col gap-3">
              <textarea v-model="qState._editAnswer" rows="12" class="w-full border border-primary-200 dark:border-primary-800 rounded-xl p-3 text-sm bg-white dark:bg-ink-800 text-ink-800 dark:text-ink-100 focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 font-mono resize-y"></textarea>
              <div class="flex gap-2 justify-end">
                <Button variant="outline" size="sm" @click="qState._isEditingAnswer = false">取消</Button>
                <Button size="sm" @click="handleSaveAnswer" :disabled="qState._isSavingAnswer">
                  {{ qState._isSavingAnswer ? '保存中...' : '保存' }}
                </Button>
              </div>
            </div>
            <div v-else-if="currentQ.ai_answer && !isFailedAnswer(currentQ.ai_answer)">
              <div class="flex items-center justify-between mb-3">
                <span class="text-xs font-semibold text-ink-500 dark:text-ink-400">AI 参考答案</span>
                <div class="flex gap-1.5">
                  <Button variant="ghost" size="sm" class="text-[10px] h-auto px-2 py-0.5" @click="qState._isEditingAnswer = true; qState._editAnswer = currentQ.ai_answer">编辑</Button>
                  <Button variant="ghost" size="sm" class="text-[10px] h-auto px-2 py-0.5" @click="handleGenerate" :disabled="qState._isLoadingAnswer">重新生成</Button>
                </div>
              </div>
              <div class="text-sm text-ink-700 dark:text-ink-300 leading-relaxed answer-content" v-html="renderMarkdown(currentQ.ai_answer)"></div>
            </div>
            <div v-else-if="qState._isLoadingAnswer" class="flex flex-col items-center justify-center py-12 text-primary-600 dark:text-primary-400 gap-3">
              <svg class="animate-spin h-7 w-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              <span class="text-sm">正在生成参考答案...</span>
            </div>
            <div v-else class="text-center py-12">
              <p v-if="isFailedAnswer(currentQ.ai_answer)" class="text-red-500 dark:text-red-400 mb-3 text-sm">上次生成失败，请重试</p>
              <p v-else class="text-ink-400 dark:text-ink-500 mb-4 text-sm">暂无参考答案</p>
              <Button size="sm" @click="handleGenerate">
                <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                AI 生成答案
              </Button>
            </div>
          </TabsContent>

          <!-- History tab -->
          <TabsContent value="history">
            <div v-if="qState._historyLoading" class="text-center py-8 text-xs text-ink-400 dark:text-ink-500">加载中...</div>
            <div v-else-if="qState._history && qState._history.length > 0" class="flex flex-col gap-2">
              <div v-for="(h, hIdx) in qState._history" :key="h.id" v-auto-animate class="border border-surface-200 dark:border-ink-600 rounded-xl overflow-hidden">
                <div class="flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-surface-50 dark:hover:bg-ink-800 transition" @click="h._expanded = !h._expanded">
                  <span class="text-[10px] text-ink-400 dark:text-ink-500 w-6 text-right shrink-0">#{{ qState._history.length - hIdx }}</span>
                  <span class="text-xs font-bold" :class="scoreTextColor(h.score)">{{ h.score }}分</span>
                  <span class="text-[10px] text-ink-400 dark:text-ink-500 ml-auto">{{ h.created_at?.slice(0, 16)?.replace('T', ' ') }}</span>
                  <div class="w-16 shrink-0">
                    <div class="bg-surface-200 dark:bg-ink-700 rounded-full h-1.5 overflow-hidden">
                      <div class="h-full rounded-full" :class="scoreColor(h.score)" :style="{ width: h.score + '%' }"></div>
                    </div>
                  </div>
                  <svg class="size-3 text-ink-400 dark:text-ink-500 transition-transform shrink-0" :class="{ 'rotate-90': h._expanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
                </div>
                <div v-if="h._expanded" class="px-3 pb-3 flex flex-col gap-2 border-t border-surface-100 dark:border-ink-700 pt-2">
                  <div>
                    <p class="text-[10px] font-semibold text-ink-500 dark:text-ink-400 mb-1">我的回答</p>
                    <p class="text-xs text-ink-600 dark:text-ink-400 bg-surface-50 dark:bg-ink-800 rounded-lg p-2 whitespace-pre-wrap leading-relaxed">{{ h.user_answer }}</p>
                  </div>
                  <div v-if="h.evaluation_result">
                    <div class="flex items-center gap-2 flex-wrap mb-1">
                      <span v-for="(val, key) in h.evaluation_result.dimensions" :key="key" class="text-[10px] text-ink-500 dark:text-ink-400">
                        {{ dimLabel[key] || key }} <span class="font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                      </span>
                    </div>
                    <p v-if="h.evaluation_result.suggestions" class="text-[10px] text-ink-500 dark:text-ink-400">
                      <span class="font-semibold">建议：</span>{{ h.evaluation_result.suggestions?.slice(0, 150) }}{{ h.evaluation_result.suggestions?.length > 150 ? '...' : '' }}
                    </p>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="text-center py-12 text-ink-400 dark:text-ink-500 text-sm">
              <svg class="size-10 mx-auto mb-2 text-ink-300 dark:text-ink-600" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              暂无练习记录
            </div>
          </TabsContent>
        </div>
      </div>
      </Tabs>
      </div>

      <!-- DRAGGABLE DIVIDER (desktop only) -->
      <div v-if="!isMobile" class="bg-surface-200 dark:bg-ink-700 hover:bg-primary-400 dark:hover:bg-primary-500 cursor-col-resize transition-colors relative group" @mousedown="onDividerMouseDown">
        <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-1 h-8 rounded-full bg-surface-400 dark:bg-ink-500 group-hover:bg-primary-500 transition-colors"></div>
      </div>

      <!-- RIGHT PANEL -->
      <div class="flex flex-col overflow-hidden min-h-0 min-w-0">
        <!-- Answer input area -->
        <div class="flex-1 flex flex-col overflow-hidden min-h-0" :style="qState._evaluation && consoleExpanded ? {} : { flex: 1 }">
          <div class="px-5 pt-4 pb-2 shrink-0">
            <h3 class="text-xs font-bold text-ink-500 dark:text-ink-400 uppercase tracking-wider flex items-center gap-1.5">
              <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
              我的回答
            </h3>
          </div>
          <div class="flex-1 px-5 pb-3 overflow-hidden min-h-0">
            <textarea
              ref="textareaRef"
              v-model="qState._userAnswer"
              @keydown="onTextareaKeydown"
              class="w-full h-full border border-surface-200 dark:border-ink-600 rounded-xl p-3.5 text-sm leading-relaxed focus:ring-2 focus:ring-primary-200 dark:focus:ring-primary-800 focus:border-primary-400 resize-none transition-all duration-200 bg-surface-50 dark:bg-surface-900 text-ink-800 dark:text-ink-100 focus:bg-white dark:focus:bg-surface-800"
              placeholder="在此输入你的回答，完成后点击 Ctrl+Enter 提交评估..."
            ></textarea>
          </div>
          <div class="px-5 pb-3 flex gap-2 items-center shrink-0">
            <button @click="handleEvaluate" :disabled="qState._isEvaluating || !qState._userAnswer.trim()"
              class="flex items-center gap-2 bg-gradient-to-r from-primary-600 to-indigo-600 dark:from-primary-600 dark:to-indigo-600 text-white font-medium px-5 py-2 rounded-xl hover:from-primary-700 hover:to-indigo-700 dark:hover:from-primary-700 dark:hover:to-indigo-700 transition-all duration-200 text-sm disabled:opacity-50 disabled:cursor-not-allowed">
              <svg v-if="qState._isEvaluating" class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
              {{ qState._isEvaluating ? '评估中...' : '提交评估' }}
            </button>
            <span class="text-[10px] text-ink-400 dark:text-ink-500 hidden sm:inline">Ctrl+Enter</span>
            <button v-if="qState._userAnswer" @click="qState._userAnswer = ''; qState._evaluation = null"
              class="text-sm text-ink-500 dark:text-ink-400 px-3 py-2 rounded-lg border border-surface-200 dark:border-ink-600 hover:bg-surface-50 dark:hover:bg-ink-700 transition">清空</button>
          </div>
        </div>

        <!-- Console panel (evaluation results) -->
        <div v-if="qState._evaluation" v-auto-animate class="border-t border-surface-200 dark:border-ink-600 shrink-0 flex flex-col" :style="consoleExpanded ? { maxHeight: '45%' } : {}">
          <!-- Console header -->
          <button @click="consoleExpanded = !consoleExpanded" class="flex items-center justify-between px-5 py-2.5 bg-surface-50 dark:bg-surface-900 hover:bg-surface-100 dark:hover:bg-ink-800 transition shrink-0">
            <div class="flex items-center gap-3">
              <span class="text-xs font-bold text-ink-600 dark:text-ink-400">评估结果</span>
              <span class="text-lg font-extrabold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span>
            </div>
            <svg class="size-4 text-ink-400 transition-transform" :class="{ 'rotate-180': consoleExpanded }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7"/></svg>
          </button>

          <!-- Console content -->
          <div v-if="consoleExpanded" class="flex-1 overflow-y-auto custom-scrollbar bg-gradient-to-b from-primary-50/30 to-white dark:from-primary-900/20 dark:to-surface-800">
            <div class="p-5 flex flex-col gap-4">
              <!-- Overall score -->
              <div class="flex items-center gap-4">
                <span class="text-4xl font-extrabold" :class="scoreTextColor(qState._evaluation.overall_score)">{{ qState._evaluation.overall_score }}</span>
                <div class="flex-1">
                  <div class="bg-surface-200 dark:bg-ink-700 rounded-full h-3 overflow-hidden">
                    <div class="h-full rounded-full transition-all duration-700" :class="scoreColor(qState._evaluation.overall_score)" :style="{ width: qState._evaluation.overall_score + '%' }"></div>
                  </div>
                  <p class="text-[10px] text-ink-400 dark:text-ink-500 mt-1">加权总分（准确性 35%、完整性 30%、深度 20%、逻辑性 15%）</p>
                </div>
              </div>

              <!-- Dimension scores -->
              <div class="grid grid-cols-2 gap-2.5">
                <div v-for="(val, key) in qState._evaluation.dimensions" :key="key" class="bg-white dark:bg-ink-800 rounded-xl p-2.5 border border-surface-100 dark:border-ink-700">
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-[10px] font-semibold text-ink-600 dark:text-ink-400">{{ dimLabel[key] || key }}</span>
                    <span class="text-sm font-bold" :class="scoreTextColor(val.score)">{{ val.score }}</span>
                  </div>
                  <div class="bg-surface-100 dark:bg-ink-700 rounded-full h-1.5 overflow-hidden mb-1">
                    <div class="h-full rounded-full transition-all duration-500" :class="scoreColor(val.score)" :style="{ width: val.score + '%' }"></div>
                  </div>
                  <p v-if="val.comment" class="text-[10px] text-ink-400 dark:text-ink-500 leading-snug">{{ val.comment }}</p>
                </div>
              </div>

              <!-- Strengths & Weaknesses -->
              <div class="grid grid-cols-2 gap-3">
                <div v-if="qState._evaluation.strengths?.length" class="bg-white dark:bg-ink-800 rounded-xl p-2.5 border border-green-100 dark:border-green-800">
                  <p class="text-[10px] font-semibold text-green-700 dark:text-green-400 mb-1.5">亮点</p>
                  <ul class="flex flex-col gap-0.5">
                    <li v-for="s in qState._evaluation.strengths" :key="s" class="text-[11px] text-ink-600 dark:text-ink-400 flex gap-1">
                      <span class="text-green-500 dark:text-green-400 shrink-0">+</span>{{ s }}
                    </li>
                  </ul>
                </div>
                <div v-if="qState._evaluation.weaknesses?.length" class="bg-white dark:bg-ink-800 rounded-xl p-2.5 border border-red-100 dark:border-red-800">
                  <p class="text-[10px] font-semibold text-red-700 dark:text-red-400 mb-1.5">不足</p>
                  <ul class="flex flex-col gap-0.5">
                    <li v-for="w in qState._evaluation.weaknesses" :key="w" class="text-[11px] text-ink-600 dark:text-ink-400 flex gap-1">
                      <span class="text-red-500 dark:text-red-400 shrink-0">-</span>{{ w }}
                    </li>
                  </ul>
                </div>
              </div>

              <!-- Suggestions -->
              <div v-if="qState._evaluation.suggestions" class="bg-white dark:bg-ink-800 rounded-xl p-3 border border-surface-100 dark:border-ink-700">
                <p class="text-[10px] font-semibold text-ink-700 dark:text-ink-300 mb-1">改进建议</p>
                <div class="text-xs text-ink-600 dark:text-ink-400 leading-relaxed answer-content" v-html="renderMarkdown(qState._evaluation.suggestions)"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue'
import { useEventListener } from '@vueuse/core'
import { dimLabel, isFailedAnswer, renderMarkdown, scoreColor, scoreTextColor, resetQState, generateAnswerForQuestion, saveAnswerForQuestion, evaluateAnswerForQuestion, loadHistory } from '@/composables/usePractice.js'
import { useToast } from '@/composables/useNotification.js'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import Button from '@/components/ui/button/Button.vue'
import { Badge } from '@/components/ui/badge'

const toast = useToast()

const props = defineProps({
  questions: { type: Array, default: () => [] },
  startIndex: { type: Number, default: 0 },
  bankMode: { type: String, default: 'public' },
  isAdmin: { type: Boolean, default: false }
})

const emit = defineEmits(['close', 'answer-evaluated', 'toggle-star', 'navigate-to-interview'])

// ── Navigation ──
const currentIndex = ref(props.startIndex)
const currentQ = computed(() => props.questions[currentIndex.value])

function resetState() {
  resetQState(qState)
  leftTab.value = 'description'
  consoleExpanded.value = true
}

function goPrev() {
  if (currentIndex.value > 0) {
    currentIndex.value--
    resetState()
  }
}

function goNext() {
  if (currentIndex.value < props.questions.length - 1) {
    currentIndex.value++
    resetState()
  }
}

function goRandom() {
  if (props.questions.length <= 1) return
  let idx
  do { idx = Math.floor(Math.random() * props.questions.length) } while (idx === currentIndex.value)
  currentIndex.value = idx
  resetState()
}

function toggleStar() {
  emit('toggle-star', currentQ.value)
}

// ── Keyboard shortcuts ──
const textareaRef = ref(null)

function onTextareaKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    handleEvaluate()
  }
}

function onGlobalKeydown(e) {
  if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); goPrev() }
  if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); goNext() }
  if (e.key === 'Escape') { emit('close') }
}

onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))

// ── Directory ──
const showDirectory = ref(false)
const directorySearch = ref('')
const directoryRef = ref(null)
const filteredQuestions = computed(() => {
  const q = directorySearch.value.toLowerCase().trim()
  if (!q) return props.questions
  return props.questions.filter(item =>
    (item.question || '').toLowerCase().includes(q) ||
    (item.cat1 || '').toLowerCase().includes(q) ||
    (item.cat2 || '').toLowerCase().includes(q)
  )
})

function goToDirectoryItem(item) {
  const idx = props.questions.indexOf(item)
  if (idx >= 0) {
    currentIndex.value = idx
    resetState()
  }
  showDirectory.value = false
  directorySearch.value = ''
}

// ── Left panel ──
const leftTab = ref('description')
const consoleExpanded = ref(true)

const qState = reactive({
  _userAnswer: '',
  _evaluation: null,
  _isEvaluating: false,
  _isLoadingAnswer: false,
  _history: null,
  _historyLoading: false,
  _isEditingAnswer: false,
  _editAnswer: '',
  _isSavingAnswer: false
})

watch(leftTab, async (tab) => {
  if (tab === 'history' && !qState._history && currentQ.value) {
    await loadHistory(currentQ.value.id, qState)
  }
})

// ── Draggable divider ──
const mainRef = ref(null)
const leftWidth = ref(50)
const isDragging = ref(false)
const isMobile = ref(false)

function checkMobile() { isMobile.value = window.innerWidth < 1024 }
onMounted(() => { checkMobile(); window.addEventListener('resize', checkMobile) })
onUnmounted(() => window.removeEventListener('resize', checkMobile))

function onDividerMouseDown(e) {
  e.preventDefault()
  isDragging.value = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

function onMouseMove(e) {
  if (!isDragging.value || !mainRef.value) return
  const rect = mainRef.value.getBoundingClientRect()
  const pct = ((e.clientX - rect.left) / rect.width) * 100
  leftWidth.value = Math.min(75, Math.max(25, pct))
}

function onMouseUp() {
  isDragging.value = false
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

useEventListener('mousemove', onMouseMove)
useEventListener('mouseup', onMouseUp)

// ── Actions ──
async function handleGenerate() {
  await generateAnswerForQuestion(currentQ.value, qState)
}

async function handleSaveAnswer() {
  await saveAnswerForQuestion(currentQ.value, qState)
}

async function handleEvaluate() {
  const result = await evaluateAnswerForQuestion(currentQ.value, qState)
  if (result) {
    consoleExpanded.value = true
    emit('answer-evaluated', { questionId: currentQ.value.id, score: result.overall_score })
  }
}
</script>

<style scoped>
/* Directory panel slide-in animation */
.directory-slide-enter-active {
  transition: opacity 0.25s ease, transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}
.directory-slide-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.directory-slide-enter-from {
  opacity: 0;
  transform: translateX(-100%);
}
.directory-slide-leave-to {
  opacity: 0;
  transform: translateX(-100%);
}

/* Question switching fade animation */
.question-content-enter {
  animation: question-enter 0.25s ease both;
}
@keyframes question-enter {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
