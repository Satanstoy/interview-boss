<template>
  <div class="min-h-screen bg-slate-50 dark:bg-surface-900">
    <!-- Top bar -->
    <nav class="sticky top-0 z-50 bg-white/80 dark:bg-surface-900/80 backdrop-blur-xl border-b border-gray-100/80 dark:border-gray-800/80 supports-[backdrop-filter]:bg-white/60 dark:supports-[backdrop-filter]:bg-surface-900/60">
      <div class="max-w-[1440px] mx-auto px-5 lg:px-8 h-14 flex items-center justify-between">
        <h1 class="text-lg lg:text-xl font-extrabold bg-gradient-to-r from-primary-600 via-accent-600 to-primary-500 bg-clip-text text-transparent tracking-tight">InterviewBoss</h1>
        <div class="flex items-center gap-3">
          <span v-if="currentUser && activeSeason" class="badge bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border border-primary-100 dark:border-primary-800 px-3 py-1">
            {{ activeSeason }}
          </span>
          <UserMenu
            v-if="currentUser"
            :user="currentUser"
            :pending-count="pendingReviewCount"
            @logout="handleLogout"
            @bank-mode-changed="handleBankModeChanged"
            @show-review="showReviewPanel = true"
          />
          <!-- Dark mode toggle -->
          <button
            @click="toggleDark()"
            class="p-2 rounded-xl text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200"
            :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
          >
            <svg v-if="isDark" class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
            <svg v-else class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          </button>
          <button
            v-if="currentUser"
            @click="showSettings = true"
            class="p-2 rounded-xl text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-all duration-200"
            title="系统配置"
          >
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          </button>
        </div>
      </div>
    </nav>

    <!-- Settings modal -->
    <SettingsPanel
      :visible="showSettings"
      :active-season="activeSeason"
      @close="showSettings = false"
      @update:active-season="activeSeason = $event"
    />

    <!-- Login gate: split layout -->
    <div v-if="!currentUser" class="relative min-h-[calc(100vh-56px)] overflow-hidden">
      <div class="absolute inset-0 overflow-hidden pointer-events-none">
        <div class="absolute -top-40 -right-40 w-96 h-96 bg-primary-200/30 dark:bg-primary-900/20 rounded-full blur-3xl animate-pulse-slow"></div>
        <div class="absolute -bottom-40 -left-40 w-96 h-96 bg-accent-200/30 dark:bg-accent-900/20 rounded-full blur-3xl animate-pulse-slow" style="animation-delay: 1.5s"></div>
      </div>

      <div class="relative flex flex-col lg:flex-row min-h-[calc(100vh-56px)]">
        <!-- Left: brand showcase -->
        <div class="flex-1 flex flex-col justify-center px-8 lg:px-16 py-12 lg:py-0 animate-fade-in">
          <div class="max-w-md mx-auto lg:mx-0">
            <div class="w-20 h-20 mb-8 rounded-3xl bg-gradient-brand flex items-center justify-center shadow-glow transform hover:scale-105 transition-transform duration-300">
              <svg class="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/>
              </svg>
            </div>

            <h2 class="text-3xl lg:text-4xl font-extrabold bg-gradient-to-r from-gray-800 to-gray-600 dark:from-gray-100 dark:to-gray-300 bg-clip-text text-transparent mb-3">
              欢迎使用 InterviewBoss
            </h2>
            <p class="text-gray-500 dark:text-gray-400 mb-10 leading-relaxed text-lg">
              AI 驱动的面试准备平台
            </p>

            <div class="grid grid-cols-3 gap-4">
              <div v-for="feature in loginFeatures" :key="feature.label"
                class="flex flex-col items-center gap-2 p-4 rounded-2xl bg-white/60 dark:bg-surface-800/60 backdrop-blur-sm border border-gray-100 dark:border-gray-700/50 shadow-card hover:shadow-card-hover transition-all duration-300 hover:-translate-y-0.5">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center" :class="feature.iconBg">
                  <span class="text-lg">{{ feature.icon }}</span>
                </div>
                <span class="text-xs font-semibold text-gray-600 dark:text-gray-400">{{ feature.label }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Right: login form -->
        <div class="flex items-center justify-center px-8 lg:px-16 py-12 lg:py-0 lg:w-[440px] xl:w-[480px]">
          <div class="w-full max-w-sm animate-fade-in">
            <LoginModal embedded @login-success="handleLoginSuccess" />
          </div>
        </div>
      </div>
    </div>

    <main v-else class="p-5 lg:p-8 max-w-[1440px] mx-auto">
      <div class="grid grid-cols-1 lg:grid-cols-4 gap-6 lg:gap-8">
      <AnalyticsSidebar
        :analytics="analytics"
        :master-bank="masterBank"
        :popular-tags="popularTags"
        :selected-tag="selectedTag"
        :practice-stats="practiceStats"
        :recommend-seed="recommendSeed"
        @refresh="fetchAnalytics"
        @select-tag="onSelectTag($event)"
        @go-to-question="onGoToQuestion"
        @refresh-recommend="recommendSeed++"
      />

      <div class="lg:col-span-3 bg-white dark:bg-surface-800 rounded-2xl shadow-card dark:shadow-glass-dark border border-gray-100/80 dark:border-gray-700/50 overflow-hidden">
        <TabBar :active-tab="activeTab" @update:active-tab="onTabChange" />

        <div class="p-4 lg:p-6">
          <SearchFilterBar
            v-if="activeTab === 'MasterBank'"
            :search-query="searchQuery"
            :filter-difficulty="filterDifficulty"
            :show-starred-only="showStarredOnly"
            :show-starred-toggle="activeTab === 'MasterBank'"
            @update:search-query="searchQuery = $event"
            @update:filter-difficulty="filterDifficulty = $event"
            @update:show-starred-only="showStarredOnly = $event"
          />

          <!-- Sub-tag filter chips -->
          <div v-if="activeTab === 'MasterBank' && selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-4">
            <span class="text-xs text-gray-400 dark:text-gray-500 self-center mr-1 font-medium">子标签：</span>
            <button
              v-for="st in availableSubTags"
              :key="st.tag"
              @click="toggleSubTag(st.tag)"
              class="text-xs px-2.5 py-1 rounded-lg border transition-all duration-200"
              :class="selectedSubTags.includes(st.tag)
                ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-300 dark:border-emerald-700 font-semibold shadow-sm'
                : 'bg-white dark:bg-surface-700 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-surface-600 hover:border-gray-300 dark:hover:border-gray-500'"
            >
              {{ st.tag }}
              <span class="ml-1 opacity-50">{{ st.count }}</span>
            </button>
          </div>

          <!-- Action bar -->
          <div class="flex flex-wrap justify-between items-center mb-5 gap-3">
            <h2 class="text-lg lg:text-xl font-bold text-gray-800 dark:text-gray-100 flex items-center gap-2">
              {{ activeTab === 'JD' ? 'JD 筛选' : activeTab === 'Interview' ? '面经记录' : activeTab === 'MockInterview' ? '题目抽测' : activeTab === 'Import' ? '导入数据' : activeTab === 'KnowledgeGraph' ? '知识图谱' : '高频题库' }}
              <span v-if="activeTab === 'MasterBank' && selectedTag !== '全部'" class="badge bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 text-xs px-3 py-1">
                筛选: {{ selectedTag }}
              </span>
            </h2>
            <div class="flex flex-wrap gap-2">
              <button v-if="activeTab === 'MasterBank'" @click="triggerBuildMasterBank" class="btn-primary text-sm bg-gradient-to-r from-accent-600 to-primary-600">
                {{ isBuilding ? '重建中...' : '重建题库' }}
              </button>
              <button v-if="!isDataLoading && activeTab !== 'Import'" @click="fetchTableData" :disabled="isDataLoading" class="btn-secondary text-sm">
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                {{ isDataLoading ? '加载中...' : '刷新数据' }}
              </button>
            </div>
          </div>

          <!-- Error banner -->
          <div v-if="dataLoadError" class="mb-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 px-4 py-3 rounded-xl flex items-center justify-between">
            <span class="flex items-center gap-2 text-sm">
              <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              {{ dataLoadError }}
            </span>
            <button @click="fetchTableData" class="text-sm bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-800/50 px-3 py-1 rounded-lg transition font-medium">重试</button>
          </div>

          <!-- Loading skeleton -->
          <div v-if="isDataLoading && jdData.length === 0 && interviewData.length === 0 && masterBank.length === 0" class="py-10 space-y-4">
            <div class="flex items-center gap-3 mb-6">
              <div class="skeleton h-10 w-10 rounded-xl"></div>
              <div class="flex-1 space-y-2">
                <div class="skeleton h-5 w-48 rounded"></div>
                <div class="skeleton h-3 w-24 rounded"></div>
              </div>
            </div>
            <div v-for="(w, i) in skeletonCards" :key="i" class="card-smooth p-5 space-y-3">
              <div class="flex gap-3">
                <div class="skeleton h-12 w-12 rounded-lg"></div>
                <div class="flex-1 space-y-2">
                  <div class="skeleton h-4 rounded" :style="{ width: w.title }"></div>
                  <div class="skeleton h-3 rounded" :style="{ width: w.subtitle }"></div>
                </div>
                <div class="skeleton h-6 w-16 rounded-full"></div>
              </div>
              <div class="flex gap-2">
                <div class="skeleton h-5 w-20 rounded-full"></div>
                <div class="skeleton h-5 w-14 rounded-full"></div>
                <div class="skeleton h-5 w-24 rounded-full"></div>
              </div>
            </div>
          </div>

          <!-- Tab content with transitions -->
          <Transition name="tab-fade" mode="out-in">
            <div :key="activeTab">
              <!-- JD Tab -->
              <DataTable
                v-if="activeTab === 'JD'"
                :columns="jdColumns"
                :rows="jdData"
                :selected-count="jdSelection.selectedCount.value"
                :is-selected="(id) => jdSelection.selectedIds.value.has(id)"
                :batch-actions="jdBatchActions"
                :current-page="jdCurrentPage"
                :page-size="jdPageSize"
                @toggle-select-all="jdSelection.toggleSelectAll()"
                @invert-selection="jdSelection.invertSelection()"
                @toggle-item="jdSelection.toggleItem($event)"
                @update:current-page="jdCurrentPage = $event"
                @update:page-size="jdPageSize = $event"
              >
                <template #actions="{ row }">
                  <div class="flex items-center justify-center gap-1">
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="flex flex-col items-center text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 px-1" title="打开链接">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button @click="deleteDataRow('jd', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1" title="删除">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit :row="row" field="公司" db-column="company" table-name="jd" @save="saveField" />
                </template>
                <template #cell-job_title="{ row }">
                  <InlineEdit :row="row" field="岗位名称" db-column="job_title" table-name="jd" @save="saveField" />
                </template>
                <template #cell-salary="{ row }">
                  <span class="text-red-600 dark:text-red-400">{{ row['薪资范围'] }}</span>
                </template>
                <template #cell-tech_stack="{ row }">
                  <span class="whitespace-pre-wrap break-words min-w-[200px]">{{ row['核心技术要求'] }}</span>
                </template>
                <template #cell-bonus="{ row }">
                  <span class="text-gray-500 dark:text-gray-400 whitespace-pre-wrap break-words">{{ row['加分项'] }}</span>
                </template>
              </DataTable>

              <!-- Interview Tab -->
              <div v-if="activeTab === 'Interview' && interviewSeasons.length > 0" class="flex items-center gap-2 mb-4">
                <label class="text-xs text-gray-500 dark:text-gray-400">招聘季筛选：</label>
                <select v-model="filterSeason" class="border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-1.5 text-xs bg-white dark:bg-surface-800 text-gray-800 dark:text-gray-200 focus:ring-blue-500 focus:border-blue-500">
                  <option value="">全部</option>
                  <option v-for="s in interviewSeasons" :key="s" :value="s">{{ s }}</option>
                </select>
              </div>
              <DataTable
                v-if="activeTab === 'Interview'"
                :columns="interviewColumns"
                :rows="filteredInterviewData"
                :selected-count="interviewSelection.selectedCount.value"
                :is-selected="(id) => interviewSelection.selectedIds.value.has(id)"
                :batch-actions="interviewBatchActions"
                :current-page="interviewCurrentPage"
                :page-size="interviewPageSize"
                @toggle-select-all="interviewSelection.toggleSelectAll()"
                @invert-selection="interviewSelection.invertSelection()"
                @toggle-item="interviewSelection.toggleItem($event)"
                @update:current-page="interviewCurrentPage = $event"
                @update:page-size="interviewPageSize = $event"
              >
                <template #actions="{ row }">
                  <div class="flex items-center justify-center gap-1">
                    <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="flex flex-col items-center text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 px-1 disabled:opacity-50" title="重新提取并打标">
                      <svg v-if="reprocessingIds[row.id]" class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                      <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                      <span class="text-[10px] leading-tight">分析</span>
                    </button>
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="row['来源链接']" target="_blank" class="flex flex-col items-center text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 px-1" title="打开链接">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button @click="deleteDataRow('interview', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1" title="删除">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit :row="row" field="公司" db-column="company" table-name="interview" @save="saveField" />
                </template>
                <template #cell-season="{ row }">
                  <InlineEdit :row="row" field="season" db-column="season" table-name="interview" @save="saveField" />
                </template>
                <template #cell-round="{ row }">
                  <InlineEdit :row="row" field="面试轮次" db-column="round" table-name="interview" @save="saveField" />
                </template>
                <template #cell-focus="{ row }">
                  <InlineEdit :row="row" field="考察重点" db-column="focus" table-name="interview" type="textarea" @save="saveField" />
                </template>
                <template #cell-questions_list="{ row }">
                  <InlineEdit :row="row" field="具体题目清单" db-column="questions_list" table-name="interview" type="textarea" rows="6" @save="saveField" />
                </template>
                <template #cell-difficulty="{ row }">
                  <InlineEdit :row="row" field="难易程度" db-column="difficulty" table-name="interview" type="select" :options="['简单', '中等', '困难']" @save="saveField" />
                </template>
              </DataTable>

              <!-- MockInterview Tab -->
              <MockInterview
                v-if="activeTab === 'MockInterview'"
                ref="mockInterviewRef"
                :popular-tags="popularTags"
              />

              <!-- KnowledgeGraph Tab -->
              <KnowledgeGraph
                v-if="activeTab === 'KnowledgeGraph'"
                @filter-by-tag="onGraphFilterTag"
                @filter-by-category="onGraphFilterCategory"
              />

              <!-- Import Tab -->
              <StagingPanel v-if="activeTab === 'Import'" :active-season="activeSeason" @submitted="onSubmitted" />

              <!-- MasterBank Tab -->
              <MasterBankList
                v-if="activeTab === 'MasterBank'"
                :items="filteredMasterBank"
                :selected-count="masterSelection.selectedCount.value"
                :is-selected="isMasterSelected"
                :batch-actions="masterBatchActions"
                :practiced-questions="practicedQuestions"
                :bank-mode="currentUser?.bank_mode"
                @toggle-select-all="masterSelection.toggleSelectAll()"
                @invert-selection="masterSelection.invertSelection()"
                @toggle-item="masterSelection.toggleItem($event)"
                @toggle-star="toggleStar"
                @retag="retagQuestion"
                @generate-answer="generateAnswer"
                @save-field="saveFieldFromEvent"
                @expand-all=""
                @collapse-all=""
                @practice="practiceQuestion = $event"
                @split-question="splitQuestion"
                @start-merge="startMerge"
              />
            </div>
          </Transition>
        </div>
      </div>
    </div>
    </main>

    <Toaster position="top-right" richColors closeButton />
    <ConfirmDialog />
    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
    <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
    <PracticePanel :visible="!!practiceQuestion" :question="practiceQuestion" @close="practiceQuestion = null" @answer-evaluated="handlePracticeEvaluated" />

    <!-- Merge Question Dialog -->
    <Teleport to="body">
      <div v-if="mergeDialogVisible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="mergeDialogVisible = false">
        <div class="bg-white dark:bg-surface-800 rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
          <div class="p-5 border-b border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-bold text-gray-800 dark:text-gray-100">移动题目到目标聚类</h3>
            <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">选择要移动到的目标题目，或独立为新聚类</p>
            <p class="text-xs text-gray-400 dark:text-gray-500 mt-2 bg-gray-50 dark:bg-surface-700 rounded-lg p-2 truncate">
              <span class="font-medium">当前题目：</span>{{ mergeSourceOriginalQ }}
            </p>
          </div>
          <div class="p-4 border-b border-gray-200 dark:border-gray-700">
            <button @click="splitAsNew" class="w-full text-left p-3 rounded-xl border-2 border-dashed border-orange-300 dark:border-orange-700 hover:bg-orange-50 dark:hover:bg-orange-900/20 hover:border-orange-400 dark:hover:border-orange-600 transition-all duration-200">
              <div class="flex items-center gap-2">
                <svg class="w-4 h-4 text-orange-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/></svg>
                <span class="text-sm font-medium text-orange-700 dark:text-orange-400">成为新的独立聚类</span>
              </div>
              <p class="text-xs text-gray-400 dark:text-gray-500 mt-1 ml-6">从当前聚类中拆出，作为独立题目</p>
            </button>
          </div>
          <div class="p-5 border-b border-gray-200 dark:border-gray-700">
            <div class="flex gap-2">
              <input v-model="mergeSearchQuery" @keyup.enter="doMergeSearch"
                class="flex-1 px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg text-sm bg-white dark:bg-surface-900 text-gray-800 dark:text-gray-200 focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
                placeholder="搜索目标题目..." />
              <button @click="doMergeSearch" :disabled="mergeSearching"
                class="btn-primary px-4 py-2 text-sm disabled:opacity-50">
                {{ mergeSearching ? '搜索中...' : '搜索' }}
              </button>
            </div>
          </div>
          <div class="flex-1 overflow-y-auto p-5 custom-scrollbar">
            <div v-if="mergeSearchResults.length === 0" class="text-center py-8 text-gray-400 dark:text-gray-500 text-sm">
              {{ mergeSearching ? '搜索中...' : '输入关键词搜索目标题目' }}
            </div>
            <div v-else class="space-y-2">
              <button v-for="item in mergeSearchResults" :key="item.id"
                @click="confirmMerge(item)"
                class="w-full text-left p-3 rounded-xl border border-gray-200 dark:border-gray-700 hover:bg-primary-50 dark:hover:bg-primary-900/20 hover:border-primary-300 dark:hover:border-primary-700 transition-all duration-200">
                <div class="text-sm font-medium text-gray-800 dark:text-gray-200 line-clamp-2">{{ item.question }}</div>
                <div class="text-xs text-gray-400 dark:text-gray-500 mt-1">频率: {{ item.frequency }} | ID: {{ item.id }}</div>
              </button>
            </div>
          </div>
          <div class="p-4 border-t border-gray-200 dark:border-gray-700 flex justify-end">
            <button @click="mergeDialogVisible = false" class="btn-secondary px-4 py-2 text-sm">取消</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { cancelAllRequests, setUnauthorizedHandler, setAuthToken, refreshAuthToken, getFriendlyError } from './utils/http.js'
import * as api from './api/index.js'
import { useSelection } from './composables/useSelection.js'
import { useTheme } from './composables/useTheme.js'

import StagingPanel from './components/StagingPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import AnalyticsSidebar from './components/AnalyticsSidebar.vue'
import TabBar from './components/TabBar.vue'
import SearchFilterBar from './components/SearchFilterBar.vue'
import DataTable from './components/DataTable.vue'
import MasterBankList from './components/MasterBankList.vue'
import MockInterview from './components/MockInterview.vue'
import KnowledgeGraph from './components/KnowledgeGraph.vue'
import InlineEdit from './components/InlineEdit.vue'
import { Toaster } from 'vue-sonner'
import ConfirmDialog from './components/ConfirmDialog.vue'
import LoginModal from './components/LoginModal.vue'
import UserMenu from './components/UserMenu.vue'
import AdminReview from './components/AdminReview.vue'
import PracticePanel from './components/PracticePanel.vue'
import { useToast, useConfirm } from './composables/useNotification.js'

const toast = useToast()
const { confirm: showConfirm } = useConfirm()
const { isDark, toggleDark } = useTheme()

// ── State ──
const activeTab = ref('MasterBank')
const jdData = ref([])
const interviewData = ref([])
const masterBank = ref([])
const isBuilding = ref(false)
const isDataLoading = ref(false)
const dataLoadError = ref(null)
const analytics = ref({ tech_trends: {} })
const selectedTag = ref('全部')
const selectedSubTags = ref([])
const searchQuery = ref('')
const filterDifficulty = ref('')
const showStarredOnly = ref(false)
const filterSeason = ref('')
const reprocessingIds = ref({})
const mockInterviewRef = ref(null)
const jdCurrentPage = ref(1)
const jdPageSize = ref(20)
const interviewCurrentPage = ref(1)
const interviewPageSize = ref(20)
const activeSeason = ref('')
const showSettings = ref(false)
const practiceStats = ref({})
const recommendSeed = ref(0)

// ── Auth state ──
const currentUser = ref(null)
const showLoginModal = ref(false)
const showReviewPanel = ref(false)
const pendingReviewCount = ref(0)
const practiceQuestion = ref(null)

// ── Selection composables ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)
const isMasterSelected = (id) => masterSelection.selectedIds.value.has(id)

// ── Login features ──
const loginFeatures = [
  { icon: '📚', label: '智能题库', iconBg: 'bg-blue-100 dark:bg-blue-900/30' },
  { icon: '🤖', label: 'AI 刷题', iconBg: 'bg-violet-100 dark:bg-violet-900/30' },
  { icon: '🎯', label: '模拟面试', iconBg: 'bg-orange-100 dark:bg-orange-900/30' },
]

// ── Skeleton data ──
const skeletonCards = [
  { title: '75%', subtitle: '45%' },
  { title: '60%', subtitle: '55%' },
  { title: '85%', subtitle: '35%' },
  { title: '50%', subtitle: '65%' },
  { title: '70%', subtitle: '40%' },
]

// ── Column definitions ──
const jdColumns = [
  { key: 'company', label: '公司', frontendKey: '公司', width: '12%' },
  { key: 'job_title', label: '岗位名称', frontendKey: '岗位名称', width: '15%' },
  { key: 'salary', label: '薪资范围', frontendKey: '薪资范围', width: '10%' },
  { key: 'tech_stack', label: '核心技术', frontendKey: '核心技术要求', width: '28%', cellClass: 'whitespace-pre-wrap' },
  { key: 'bonus', label: '加分项', frontendKey: '加分项', width: '22%' },
  { key: 'season', label: '招聘季', frontendKey: 'season', width: '8%' }
]

const interviewColumns = [
  { key: 'company', label: '公司', frontendKey: '公司', width: '10%' },
  { key: 'season', label: '招聘季', frontendKey: 'season', width: '8%' },
  { key: 'round', label: '面试轮次', frontendKey: '面试轮次', width: '8%' },
  { key: 'focus', label: '考察重点', frontendKey: '考察重点', width: '18%', cellClass: 'whitespace-pre-wrap' },
  { key: 'questions_list', label: '具体题目清单', frontendKey: '具体题目清单', width: '40%', cellClass: 'whitespace-pre-wrap' },
  { key: 'difficulty', label: '难度', frontendKey: '难易程度', width: '11%' }
]

// ── Computed ──
const popularTags = computed(() => {
  const counts = {}
  masterBank.value.forEach(q => {
    const cats = (q.cat1 || '未分类').split(',').map(c => c.trim()).filter(c => c)
    if (cats.length === 0) counts['未分类'] = (counts['未分类'] || 0) + 1
    else cats.forEach(cat => counts[cat] = (counts[cat] || 0) + 1)
  })
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).reduce((acc, [k, v]) => { acc[k] = v; return acc }, {})
})

const availableSubTags = computed(() => {
  if (selectedTag.value === '全部') return []
  const catItems = masterBank.value.filter(q =>
    (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value)
  )
  const counts = {}
  catItems.forEach(q => {
    const tags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
    tags.forEach(tag => { counts[tag] = (counts[tag] || 0) + 1 })
  })
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([tag, count]) => ({ tag, count }))
})

const filteredMasterBank = computed(() => {
  let result = masterBank.value
  if (selectedTag.value !== '全部') {
    result = result.filter(q => (q.cat1 || '未分类').split(',').map(c => c.trim()).includes(selectedTag.value))
  }
  if (selectedSubTags.value.length > 0) {
    result = result.filter(q => {
      const itemTags = (q.tags || '').split(',').map(t => t.trim()).filter(t => t)
      return selectedSubTags.value.some(st => itemTags.includes(st))
    })
  }
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.trim().toLowerCase()
    result = result.filter(q => (q.question || '').toLowerCase().includes(query) || (q.cat1 || '').toLowerCase().includes(query) || (q.tags || '').toLowerCase().includes(query))
  }
  if (filterDifficulty.value) result = result.filter(q => (q.difficulty || '').includes(filterDifficulty.value))
  if (showStarredOnly.value) result = result.filter(q => q.is_starred)
  return result
})

const interviewSeasons = computed(() => {
  const seasons = [...new Set(interviewData.value.map(d => d.season).filter(Boolean))]
  return seasons.sort()
})

const filteredInterviewData = computed(() => {
  if (!filterSeason.value) return interviewData.value
  return interviewData.value.filter(d => d.season === filterSeason.value)
})

const practicedQuestions = computed(() => {
  const stats = practiceStats.value
  if (!stats?.practiced_details) return {}
  return stats.practiced_details
})

const handlePracticeEvaluated = async ({ questionId, score }) => {
  await fetchPracticeStats()
}

watch(activeTab, (newTab, oldTab) => {
  if (oldTab === 'MockInterview' && newTab === 'MasterBank') {
    fetchPracticeStats()
  }
})

// ── Batch action definitions ──
const jdBatchActions = computed(() => [
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...jdSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`, { title: '确认删除', variant: 'danger' })) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteData('jd', ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 条记录！`)
      } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      jdSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  }
])

const interviewBatchActions = computed(() => [
  {
    key: 'batch-reprocess',
    label: '批量重新分析',
    color: 'blue',
    handler: async (onProgress) => {
      const ids = [...interviewSelection.selectedIds.value]
      if (!await showConfirm(`确定要重新分析选中的 ${ids.length} 条面经？`)) return
      onProgress(0, ids.length)
      let ok = 0
      for (let i = 0; i < ids.length; i++) {
        try { await api.reprocessInterview(ids[i]); ok++ } catch (e) { console.error(e) }
        onProgress(i + 1, ids.length)
      }
      toast.success(`批量重新分析完成，成功解析 ${ok} 条记录！`)
      interviewSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  },
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...interviewSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 条记录？`, { title: '确认删除', variant: 'danger' })) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteData('interview', ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 条记录！`)
      } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      interviewSelection.clearSelection()
      fetchTableData()
      fetchAnalytics()
    }
  }
])

const masterBatchActions = computed(() => [
  {
    key: 'batch-generate',
    label: '批量生成答案',
    color: 'blue',
    handler: async (onProgress) => {
      const ids = [...masterSelection.selectedIds.value]
      if (!await showConfirm(`确定要为选中的 ${ids.length} 道题目生成答案？`)) return
      try {
        const result = await api.batchGenerateAnswers(ids, (event) => {
          if (event.type === 'init') {
            if (event.total === 0) {
              toast.info(`所有 ${event.skipped} 道题目已有答案，无需生成`)
            } else {
              onProgress(0, event.total)
            }
          } else if (event.type === 'progress') {
            onProgress(event.current, event.total)
          }
        })
        if (result) {
          const parts = []
          if (result.generated) parts.push(`成功 ${result.generated} 题`)
          if (result.failed) parts.push(`失败 ${result.failed} 题`)
          if (result.skipped) parts.push(`跳过 ${result.skipped} 题`)
          toast.success(parts.length ? `生成完成：${parts.join('，')}` : '生成完成')
        }
      } catch (e) { toast.error('批量生成答案失败：' + getFriendlyError(e)) }
      fetchTableData()
    }
  },
  {
    key: 'batch-delete',
    label: '批量删除',
    color: 'red',
    handler: async (onProgress) => {
      const ids = [...masterSelection.selectedIds.value]
      if (!await showConfirm(`确定要删除选中的 ${ids.length} 道题目？`, { title: '确认删除', variant: 'danger' })) return
      onProgress(0, ids.length)
      try {
        const result = await api.batchDeleteMasterBank(ids)
        onProgress(result.deleted, ids.length)
        toast.success(`已成功删除 ${result.deleted} 道题目！`)
      } catch (e) { toast.error('批量删除失败：' + getFriendlyError(e)) }
      fetchTableData()
    }
  }
])

// ── Data fetching ──
const fetchTableData = async () => {
  isDataLoading.value = true
  dataLoadError.value = null
  try {
    const [jdResp, intResp, masterResp] = await Promise.all([
      api.fetchJdData(),
      api.fetchInterviewData(),
      api.fetchMasterBank()
    ])
    jdData.value = (jdResp.items || jdResp).map(item => ({ ...item }))
    interviewData.value = (intResp.items || intResp).map(item => ({ ...item }))
    masterBank.value = (masterResp.items || masterResp).map(q => ({ ...q, _showAnswer: false, _isLoadingAnswer: false, _isRetagging: false, _isEditingAnswer: false, _editAnswer: '' }))
    selectedSubTags.value = []
    jdSelection.clearSelection()
    interviewSelection.clearSelection()
  } catch (e) {
    dataLoadError.value = getFriendlyError(e, '数据加载失败，请刷新重试')
  } finally {
    isDataLoading.value = false
  }
}

const fetchAnalytics = async () => {
  try { analytics.value = await api.fetchAnalytics() } catch (e) { console.error('获取分析数据失败', e) }
}

const fetchPracticeStats = async () => {
  try { practiceStats.value = await api.fetchPracticeStats() } catch (e) { console.error('获取练习统计失败', e) }
}

// ── Actions ──
const onSubmitted = () => {
  activeTab.value = 'MasterBank'
  fetchTableData()
  fetchAnalytics()
}

const onTabChange = (tab) => {
  activeTab.value = tab
}

const onSelectTag = (tag) => {
  selectedTag.value = tag
  selectedSubTags.value = []
  activeTab.value = 'MasterBank'
}

const onGraphFilterTag = (tagName) => {
  selectedTag.value = '全部'
  selectedSubTags.value = []
  searchQuery.value = tagName
  activeTab.value = 'MasterBank'
}

const onGraphFilterCategory = (catName) => {
  selectedTag.value = catName
  selectedSubTags.value = []
  searchQuery.value = ''
  activeTab.value = 'MasterBank'
}

const onGoToQuestion = (question) => {
  activeTab.value = 'MasterBank'
  const q = question.question || ''
  searchQuery.value = q.length > 30 ? q.substring(0, 30) : q
  selectedTag.value = '全部'
  selectedSubTags.value = []
}

const toggleSubTag = (tag) => {
  const idx = selectedSubTags.value.indexOf(tag)
  if (idx === -1) {
    selectedSubTags.value = [...selectedSubTags.value, tag]
  } else {
    selectedSubTags.value = selectedSubTags.value.filter(t => t !== tag)
  }
}

const deleteDataRow = async (type, recordId) => {
  if (!await showConfirm('确定要删除该记录？', { title: '确认删除', variant: 'danger' })) return
  try {
    await api.deleteRecord(type, recordId)
    toast.success('删除成功')
    fetchTableData()
    fetchAnalytics()
  } catch (err) { toast.error('删除失败：' + getFriendlyError(err)) }
}

const reprocessInterview = async (id) => {
  if (!await showConfirm('确定要重新解析该面经？')) return
  reprocessingIds.value[id] = true
  try {
    const data = await api.reprocessInterview(id)
    toast.success('重新解析完成')
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
  finally { reprocessingIds.value[id] = false }
}

const retagQuestion = async (question) => {
  if (!await showConfirm('确定要重新分类该题目？')) return
  question._isRetagging = true
  try {
    const data = await api.retagQuestion(question.id)
    question.cat1 = data.data.cat1
    question.cat2 = data.data.cat2
    question.tags = data.data.tags
    question.difficulty = data.data.difficulty
    toast.success('分类成功')
    fetchAnalytics()
  } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
  finally { question._isRetagging = false }
}

const saveField = async (tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey) => {
  try {
    await api.updateRecord({ table_name: tableName, record_id: recordId, update_data: { [dbColumn]: newValue } })
    rowObj[frontendKey] = newValue
    rowObj[editStateKey] = false
    toast.success('保存成功')
  } catch (err) { toast.error('保存失败：' + getFriendlyError(err)) }
}

const saveFieldFromEvent = ({ tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey }) => {
  saveField(tableName, recordId, dbColumn, newValue, rowObj, editStateKey, frontendKey)
}

const toggleStar = async (question) => {
  try {
    const data = await api.toggleStar(question.id)
    question.is_starred = data.is_starred
  } catch (e) { toast.error('操作失败：' + getFriendlyError(e)) }
}

const generateAnswer = async (question) => {
  question._isLoadingAnswer = true
  try {
    const data = await api.generateAnswer(question.id)
    question.ai_answer = data.answer
    toast.success('答案生成成功')
  } catch (e) { toast.error('生成失败：' + getFriendlyError(e)) }
  finally { question._isLoadingAnswer = false }
}

// ── Cluster editing (per original question) ──
const splitQuestion = async ({ question, originalQuestion }) => {
  const shortQ = originalQuestion.length > 30 ? originalQuestion.slice(0, 30) + '...' : originalQuestion
  if (!await showConfirm(`确定要将「${shortQ}」从当前聚类中拆出为独立题目吗？`, { title: '拆分为独立题目' })) return
  try {
    await api.splitQuestion(question.id, originalQuestion)
    toast.success('题目已拆分为独立题目')
    fetchTableData()
  } catch (e) { toast.error('拆分失败：' + getFriendlyError(e)) }
}

const mergeDialogVisible = ref(false)
const mergeSourceQuestionId = ref(null)
const mergeSourceOriginalQ = ref('')
const mergeSearchQuery = ref('')
const mergeSearchResults = ref([])
const mergeSearching = ref(false)

const startMerge = ({ question, originalQuestion }) => {
  mergeSourceQuestionId.value = question.id
  mergeSourceOriginalQ.value = originalQuestion
  mergeSearchQuery.value = ''
  mergeSearchResults.value = []
  mergeDialogVisible.value = true
}

const doMergeSearch = async () => {
  mergeSearching.value = true
  try {
    const data = await api.searchMasterBank(mergeSearchQuery.value, mergeSourceQuestionId.value)
    mergeSearchResults.value = data.items || []
  } catch (e) { toast.error('搜索失败：' + getFriendlyError(e)) }
  finally { mergeSearching.value = false }
}

const confirmMerge = async (target) => {
  const shortQ = mergeSourceOriginalQ.value.length > 20 ? mergeSourceOriginalQ.value.slice(0, 20) + '...' : mergeSourceOriginalQ.value
  const shortT = target.question.length > 20 ? target.question.slice(0, 20) + '...' : target.question
  if (!await showConfirm(`确定将「${shortQ}」合并到「${shortT}」吗？`, { title: '确认合并', variant: 'danger' })) return
  try {
    await api.mergeQuestion(mergeSourceQuestionId.value, mergeSourceOriginalQ.value, target.id)
    toast.success('题目已合并到目标聚类')
    mergeDialogVisible.value = false
    fetchTableData()
  } catch (e) { toast.error('合并失败：' + getFriendlyError(e)) }
}

const splitAsNew = async () => {
  const shortQ = mergeSourceOriginalQ.value.length > 30 ? mergeSourceOriginalQ.value.slice(0, 30) + '...' : mergeSourceOriginalQ.value
  if (!await showConfirm(`确定要将「${shortQ}」从当前聚类中拆出为独立题目吗？`, { title: '拆分为独立题目' })) return
  try {
    await api.splitQuestion(mergeSourceQuestionId.value, mergeSourceOriginalQ.value)
    toast.success('题目已拆分为独立题目')
    mergeDialogVisible.value = false
    fetchTableData()
  } catch (e) { toast.error('拆分失败：' + getFriendlyError(e)) }
}

const triggerBuildMasterBank = async () => {
  if (!await showConfirm('将重新整理全部题目，确定继续？', { title: '重建题库', variant: 'danger' })) return
  isBuilding.value = true
  try {
    const data = await api.buildMasterBank()
    toast.success(`重建完成，共 ${data.total_unique} 道题目`)
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false }
}

// ── Lifecycle ──
const initAuth = async () => {
  const refreshResult = await refreshAuthToken()
  if (refreshResult?.token && refreshResult?.user) {
    setAuthToken(refreshResult.token)
    currentUser.value = refreshResult.user
    loadAllData()
    loadPendingCount()
  }
}

const handleLoginSuccess = (user) => {
  currentUser.value = user
  loadAllData()
  loadPendingCount()
}

const handleLogout = () => {
  setAuthToken('')
  currentUser.value = null
  fetchTableData()
  fetchPracticeStats()
  pendingReviewCount.value = 0
}

const handleBankModeChanged = (user) => {
  currentUser.value = user
  fetchTableData()
  fetchPracticeStats()
}

const loadPendingCount = async () => {
  if (!currentUser.value?.is_admin) { pendingReviewCount.value = 0; return }
  try {
    const data = await api.fetchPendingQuestions()
    pendingReviewCount.value = data.total || 0
  } catch { pendingReviewCount.value = 0 }
}

setUnauthorizedHandler(() => {
  showLoginModal.value = true
})

const loadAllData = () => {
  fetchTableData()
  fetchAnalytics()
  fetchPracticeStats()
  loadActiveSeason()
}

const loadActiveSeason = async () => {
  try {
    const data = await api.fetchProfile()
    activeSeason.value = data.settings?.active_season || ''
  } catch { /* ignore */ }
}

onMounted(async () => {
  await initAuth()
})
onUnmounted(() => cancelAllRequests())
</script>

<style scoped>
:deep(pre) { background-color: #1e293b; color: #f8fafc; padding: 1rem; border-radius: 0.75rem; overflow-x: auto; margin-top: 0.5rem; margin-bottom: 1rem; }
:deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; }
:deep(p code) { @apply bg-gray-100 dark:bg-gray-800 text-red-600 dark:text-red-400; padding: 0.125rem 0.375rem; border-radius: 0.375rem; font-size: 0.8125em; }
:deep(ul) { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(ol) { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(strong) { font-weight: 700; @apply text-gray-900 dark:text-gray-100; }
:deep(h1), :deep(h2), :deep(h3) { font-weight: 700; @apply text-gray-900 dark:text-gray-100; margin-top: 1.5rem; margin-bottom: 0.5rem; }
:deep(h3) { font-size: 1.125rem; }

.tab-fade-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.tab-fade-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.tab-fade-enter-from { opacity: 0; transform: translateY(8px); }
.tab-fade-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
