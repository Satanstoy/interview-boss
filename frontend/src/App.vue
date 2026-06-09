<template>
  <div class="min-h-screen bg-white dark:bg-surface-900">
    <!-- Top bar -->
    <nav v-if="!isAuthenticatedForUi" class="sticky top-0 z-50 bg-background/90 backdrop-blur-xl border-b border-border">
      <div class="max-w-[1920px] mx-auto px-3 sm:px-5 lg:px-6 h-14 flex items-center justify-between overflow-hidden">
        <div class="flex items-center gap-2 min-w-0">
          <span v-if="!isAuthenticatedForUi" class="grid h-8 w-8 place-items-center rounded-lg bg-primary text-xs font-bold text-primary-foreground">IB</span>
          <h1 class="text-sm lg:text-base font-semibold tracking-tight text-ink-900 dark:text-ink-100 truncate">
            {{ activeTabLabel }}
          </h1>
          <span v-if="isAuthenticatedForUi && activeSeason" class="hidden md:inline-flex items-center rounded-md bg-surface-100 dark:bg-ink-800 text-ink-500 dark:text-ink-400 border border-surface-200 dark:border-ink-700 px-2 py-1 text-xs">
            {{ activeSeason }}
          </span>
        </div>
        <div class="flex items-center gap-1.5 sm:gap-3 min-w-0 shrink-0">
          <a v-if="!isAuthenticatedForUi" href="?preview=1" class="hidden sm:inline-flex h-8 items-center rounded-md border border-surface-200 dark:border-ink-700 bg-white dark:bg-surface-900 px-3 text-xs font-medium text-ink-600 dark:text-ink-300 shadow-sm hover:bg-surface-50 dark:hover:bg-ink-800 transition">
            预览新版界面
          </a>
          <button v-if="isAuthenticatedForUi" type="button" class="hidden sm:inline-flex h-8 items-center rounded-md border border-surface-200 dark:border-ink-700 bg-white dark:bg-surface-900 px-3 text-xs font-medium text-ink-600 dark:text-ink-300 shadow-sm hover:bg-surface-50 dark:hover:bg-ink-800 transition">
            搜索 ⌘K
          </button>
          <!-- Dark mode toggle -->
          <button
            @click="toggleDark()"
            class="p-2 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-800 transition-all duration-200"
            :title="isDark ? '切换到亮色模式' : '切换到暗色模式'"
          >
            <svg v-if="isDark" class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
            <svg v-else class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          </button>
          <button
            v-if="isAuthenticatedForUi"
            @click="showSettings = true"
            class="p-2 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-800 transition-all duration-200"
            title="系统配置"
          >
            <svg class="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /></svg>
          </button>
        </div>
      </div>
    </nav>

    <!-- Settings modal -->
    <SettingsPanel
      :visible="showSettings"
      :active-season="activeSeason"
      :is-admin="displayUser?.is_admin"
      :is-building="isBuilding"
      @close="onSettingsClose"
      @update:active-season="activeSeason = $event"
      @settings-saved="onSettingsSaved"
      @position-changed="onPositionChanged"
      @build-master-bank="triggerBuildMasterBank"
    />

    <!-- Login gate -->
    <LoginPage v-if="!isAuthenticatedForUi" @login-success="handleLoginSuccess" />

    <!-- Simple two-column layout: sidebar left, content right -->
    <div v-else class="flex min-h-screen">
      <!-- Sidebar: dynamic width, collapsible -->
      <aside
        class="hidden md:flex shrink-0 flex-col border-r border-border bg-sidebar h-screen sticky top-0 transition-all duration-300"
        :class="sidebarCollapsed ? 'w-[60px]' : 'w-64'"
      >
        <AppSidebar
          :active-tab="activeTab"
          :sidebar-tabs="sidebarTabs"
          :popular-tags="popularTags"
          :selected-tag="selectedTag"
          :master-bank="masterBank"
          :display-user="displayUser"
          :pending-review-count="pendingReviewCount"
          @update:active-tab="onTabChange"
          @update:collapsed="sidebarCollapsed = $event"
          @select-tag="onSelectTag"
          @go-to-question="onGoToQuestion"
          @logout="handleLogout"
          @bank-mode-changed="handleBankModeChanged"
          @show-review="showReviewPanel = true"
          @show-profile="showProfile = true"
        />
      </aside>

      <!-- Main content: takes remaining space -->
      <main class="flex-1 min-w-0 flex flex-col">
        <SiteHeader
          :active-tab-label="activeTabLabel"
          :active-season="activeSeason"
          :is-dark="isDark"
          @toggle-dark="toggleDark()"
          @show-settings="showSettings = true"
        />

        <TabBar class="md:hidden" :active-tab="activeTab" @update:active-tab="onTabChange" />

        <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar" style="position: relative;">



          <!-- Error banner -->
          <div v-if="dataLoadError" class="mb-4 bg-red-50/80 dark:bg-red-900/20 border border-red-200/80 dark:border-red-800/50 text-red-700 dark:text-red-400 px-4 py-3 rounded-xl flex items-center justify-between">
            <span class="flex items-center gap-2 text-sm">
              <svg class="size-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              {{ dataLoadError }}
            </span>
            <button @click="fetchTableData" class="text-sm bg-red-100/80 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-800/40 px-3 py-1 rounded-lg transition font-medium">重试</button>
          </div>

          <!-- Loading skeleton -->
          <div v-if="isDataLoading && jdData.length === 0 && interviewData.length === 0 && masterBank.length === 0" class="py-10 flex flex-col gap-4">
            <div class="flex items-center gap-3 mb-6">
              <Skeleton class="h-10 w-10 rounded-xl" />
              <div class="flex-1 flex flex-col gap-2">
                <Skeleton class="h-5 w-48 rounded" />
                <Skeleton class="h-3 w-24 rounded" />
              </div>
            </div>
            <Card v-for="(w, i) in skeletonCards" :key="i" class="p-5 flex flex-col gap-3">
              <div class="flex gap-3">
                <Skeleton class="h-12 w-12 rounded-lg" />
                <div class="flex-1 flex flex-col gap-2">
                  <Skeleton class="h-4 rounded" :style="{ width: w.title }" />
                  <Skeleton class="h-3 rounded" :style="{ width: w.subtitle }" />
                </div>
                <Skeleton class="h-6 w-16 rounded-full" />
              </div>
              <div class="flex gap-2">
                <Skeleton class="h-5 w-20 rounded-full" />
                <Skeleton class="h-5 w-14 rounded-full" />
                <Skeleton class="h-5 w-24 rounded-full" />
              </div>
            </Card>
          </div>

          <!-- Tab content with crossfade transitions (no mode="out-in" to eliminate blank window) -->
          <Transition name="tab-fade" @after-enter="restoreScroll()">
            <div :key="activeTab" class="tab-content" data-motion="tab-transition">
              <!-- MasterBank Tab -->
              <div v-if="activeTab === 'MasterBank' && masterBankEverShown">
                <!-- SearchFilterBar -->
                <SearchFilterBar
                  :search-query="searchQuery"
                  :filter-difficulty="filterDifficulty"
                  @update:search-query="searchQuery = $event"
                  @update:filter-difficulty="filterDifficulty = $event"
                />
                <!-- Sub-tag filter chips -->
                <div v-if="selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-2">
                  <span class="text-xs text-ink-400 dark:text-ink-500 self-center mr-1 font-medium">子标签：</span>
                  <button
                    v-for="st in availableSubTags"
                    :key="st.tag"
                    @click="toggleSubTag(st.tag)"
                    class="text-xs px-2.5 py-1 rounded-lg border transition-all duration-200"
                    :class="selectedSubTags.includes(st.tag)
                      ? 'bg-sage-50 dark:bg-sage-700/20 text-sage-700 dark:text-sage-400 border-sage-200 dark:border-sage-700 font-semibold shadow-sm'
                      : 'bg-white dark:bg-surface-700 text-ink-500 dark:text-ink-400 border-surface-200 dark:border-ink-600 hover:bg-surface-50 dark:hover:bg-surface-600 hover:border-surface-300 dark:hover:border-ink-500'"
                  >
                    {{ st.tag }}
                    <span class="ml-1 opacity-50">{{ st.count }}</span>
                  </button>
                </div>

                <!-- Exam Distribution Chart -->
                <ExamDistribution :master-bank="masterBank" />

                <!-- MasterBankList -->
                <div class="flex flex-col flex-1 min-h-0">
                  <MasterBankList
                    ref="masterBankRef"
                    :items="filteredMasterBank"
                    :selected-count="masterSelection.selectedCount.value"
                    :is-selected="isMasterSelected"
                    :batch-actions="masterBatchActions"
                    :practiced-questions="practicedQuestions"
                    :bank-mode="displayUser?.bank_mode"
                    :is-admin="displayUser?.is_admin"
                    :current-user-id="displayUser?.id"
                    :is-loading-more="isLoadingMore"
                    :has-more="hasMore"
                    @toggle-select-all="masterSelection.toggleSelectAll()"
                    @invert-selection="masterSelection.invertSelection()"
                    @toggle-item="masterSelection.toggleItem($event)"
                    @toggle-star="toggleStar"
                    @retag="retagQuestion"
                    @generate-answer="generateAnswer"
                    @use-reference-answer="useReferenceAnswer"
                    @save-user-answer="saveUserAnswer"
                    @save-field="saveFieldFromEvent"
                    @practice="practiceQuestion = $event"
                    @split-question="splitQuestion"
                    @start-merge="startMerge"
                    @navigate-to-interview="onNavigateToInterview"
                    @delete="deleteQuestion"
                    @edit-question="editQuestion"
                    @delete-original-question="deleteOriginalQuestion"
                    @update-answer="onUpdateAnswer"
                    @load-more="loadMoreMasterBank"
                  >
                    <template #actions>
                      <div class="flex flex-wrap items-center gap-2 pt-1">
                        <Button v-if="displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildMasterBank" :disabled="isBuilding">
                          {{ isBuilding ? '重建中...' : '重建题库' }}
                        </Button>
                        <Button v-if="!displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildPersonalBank" :disabled="isBuilding">
                          {{ isBuilding ? '重建中...' : '重建题库' }}
                        </Button>
                        <Button v-if="filteredMasterBank.length > 0" variant="outline" size="sm" @click="enterPracticeMode">
                          刷题模式
                        </Button>
                        <Button v-if="!isDataLoading" variant="outline" size="sm" @click="fetchTableData" :disabled="isDataLoading">
                          刷新
                        </Button>
                      </div>
                    </template>
                  </MasterBankList>
                </div>
              </div>

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
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 transition-colors duration-200" title="打开链接">
                      <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button v-if="displayUser?.is_admin || row.owner_id === displayUser?.id" @click="deleteDataRow('jd', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1 transition-colors duration-200" title="删除">
                      <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="公司" db-column="company" table-name="jd" @save="saveField" />
                  <span v-else>{{ row['公司'] }}</span>
                </template>
                <template #cell-job_title="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="岗位名称" db-column="job_title" table-name="jd" @save="saveField" />
                  <span v-else>{{ row['岗位名称'] }}</span>
                </template>
                <template #cell-salary="{ row }">
                  <span class="text-red-600 dark:text-red-400 font-medium">{{ row['薪资范围'] }}</span>
                </template>
                <template #cell-tech_stack="{ row }">
                  <span class="whitespace-pre-wrap break-words min-w-[200px]">{{ row['核心技术要求'] }}</span>
                </template>
                <template #cell-bonus="{ row }">
                  <span class="text-gray-500 dark:text-gray-400 whitespace-pre-wrap break-words">{{ row['加分项'] }}</span>
                </template>
              </DataTable>

              <!-- Interview Tab -->
              <div v-if="activeTab === 'Interview'" class="flex items-center gap-2 mb-3 p-3 rounded-xl border border-border bg-card shadow-sm">
                <template v-if="interviewSeasons.length > 0">
                  <label class="text-xs text-ink-500 dark:text-ink-400">招聘季筛选：</label>
                  <Select v-model="filterSeason">
                    <SelectTrigger class="min-w-[100px] h-8 text-xs">
                      <SelectValue placeholder="全部" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="">全部</SelectItem>
                      <SelectItem v-for="s in interviewSeasons" :key="s" :value="s">{{ s }}</SelectItem>
                    </SelectContent>
                  </Select>
                  <span class="text-surface-300 dark:text-ink-600">|</span>
                </template>
                <button
                  @click="interviewSortOrder = interviewSortOrder === 'desc' ? 'asc' : 'desc'"
                  class="inline-flex items-center gap-1 border border-surface-300 dark:border-ink-600 rounded-lg px-3 py-1.5 text-xs bg-white dark:bg-surface-800 text-ink-700 dark:text-ink-200 hover:bg-surface-50 dark:hover:bg-surface-700 transition-colors"
                  :title="interviewSortOrder === 'desc' ? '当前：最新在前，点击切换' : '当前：最旧在前，点击切换'"
                >
                  <svg class="size-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path v-if="interviewSortOrder === 'desc'" stroke-linecap="round" stroke-linejoin="round" d="M3 4h13M3 8h9M3 12h5m4 0l4-4m0 0l4 4m-4-4v12" />
                    <path v-else stroke-linecap="round" stroke-linejoin="round" d="M3 4h13M3 8h9m-9 4h9m5-4v12m0 0l-4-4m4 4l4-4" />
                  </svg>
                  上传日期 {{ interviewSortOrder === 'desc' ? '↓' : '↑' }}
                </button>
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
                :highlight-id="highlightInterviewId"
                @toggle-select-all="interviewSelection.toggleSelectAll()"
                @invert-selection="interviewSelection.invertSelection()"
                @toggle-item="interviewSelection.toggleItem($event)"
                @update:current-page="interviewCurrentPage = $event"
                @update:page-size="interviewPageSize = $event"
              >
                <template #actions="{ row }">
                  <div class="flex items-center justify-center gap-1">
                    <div v-if="displayUser?.is_admin" class="relative flex flex-col items-center">
                      <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 disabled:opacity-50 transition-colors duration-200" title="重新提取并打标">
                        <svg v-if="reprocessingIds[row.id]" class="animate-spin size-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                        <svg v-else class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                        <span class="text-[10px] leading-tight">{{ reprocessingIds[row.id] ? (reprocessProgress[row.id]?.step === 'tag' ? '标注中' : reprocessProgress[row.id]?.step === 'match' ? '聚类中' : reprocessProgress[row.id]?.step === 'save' ? '保存中' : '分析中') : '分析' }}</span>
                      </button>
                    </div>
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 transition-colors duration-200" title="打开链接">
                      <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button v-if="displayUser?.is_admin || row.owner_id === displayUser?.id" @click="deleteDataRow('interview', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1 transition-colors duration-200" title="删除">
                      <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="公司" db-column="company" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['公司'] }}</span>
                </template>
                <template #cell-season="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="season" db-column="season" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['season'] }}</span>
                </template>
                <template #cell-round="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="面试轮次" db-column="round" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['面试轮次'] }}</span>
                </template>
                <template #cell-focus="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="考察重点" db-column="focus" table-name="interview" type="textarea" @save="saveField" />
                  <span v-else>{{ row['考察重点'] }}</span>
                </template>
                <template #cell-questions_list="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="具体题目清单" db-column="questions_list" table-name="interview" type="textarea" rows="6" @save="saveField" />
                  <span v-else>{{ row['具体题目清单'] }}</span>
                </template>
                <template #cell-difficulty="{ row }">
                  <InlineEdit v-if="displayUser?.is_admin" :row="row" field="难易程度" db-column="difficulty" table-name="interview" type="select" :options="['简单', '中等', '困难']" @save="saveField" />
                  <span v-else>{{ row['难易程度'] }}</span>
                </template>
                <template #cell-created_at="{ row }">
                  <span class="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap">{{ formatDate(row.created_at) }}</span>
                </template>
              </DataTable>

              <!-- Floating return button -->
              <button
                v-if="activeTab === 'Interview' && returnTab && highlightInterviewId"
                ref="floatingReturnBtn"
                @click="handleReturn"
                class="absolute z-50 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-600 rounded-lg shadow-lg hover:shadow-xl transition-all duration-200 whitespace-nowrap"
                :style="floatingBtnStyle"
              >
                <svg class="size-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18"/></svg>
                {{ returnToPracticeMode ? '返回刷题模式' : '返回题库' }}
              </button>

              <!-- MockInterview Tab -->
              <MockInterview
                v-if="activeTab === 'MockInterview'"
                ref="mockInterviewRef"
                :popular-tags="popularTags"
              />

              <!-- Chat Tab (模拟面试) -->
              <ChatView
                v-if="activeTab === 'Chat'"
              :jd-list="jdData"
              :preview="isPreviewMode"
              />

              <!-- KnowledgeGraph Tab -->
              <KnowledgeGraph
                v-if="activeTab === 'KnowledgeGraph'"
                @filter-by-tag="onGraphFilterTag"
                @filter-by-category="onGraphFilterCategory"
              />

              <!-- Import Tab -->
              <StagingPanel v-if="activeTab === 'Import'" :active-season="activeSeason" :available-seasons="availableSeasons" :is-admin="displayUser?.is_admin" @submitted="onSubmitted" />

              <!-- Coding Tab -->
              <CodingPractice v-if="activeTab === 'Coding'" />

            </div>
          </Transition>
        </div>
      </main>
    </div>

    <Toaster position="top-right" richColors closeButton />
    <ConfirmDialog />
    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
    <ProfilePanel
      :visible="showProfile"
      :user="currentUser"
      :practice-stats="practiceStats"
      :master-bank="masterBank"
      :recommend-seed="recommendSeed"
      @close="showProfile = false"
      @go-to-question="onGoToQuestion"
      @refresh-recommend="recommendSeed++"
    />
    <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
    <PracticePanel :visible="!!practiceQuestion" :question="practiceQuestion" @close="practiceQuestion = null" @answer-evaluated="handlePracticeEvaluated" @navigate-to-interview="onNavigateToInterview" />
    <PracticeMode
      v-if="showPracticeMode"
      :questions="filteredMasterBank"
      :start-index="practiceModeIndex"
      :bank-mode="displayUser?.bank_mode"
      :is-admin="displayUser?.is_admin"
      @close="handlePracticeModeClose"
      @answer-evaluated="handlePracticeModeEvaluated"
      @toggle-star="toggleStar"
      @navigate-to-interview="onNavigateToInterview"
    />

    <MergeQuestionDialog
      :visible="mergeDialogVisible"
      :source-question="mergeSourceOriginalQ"
      :search-query="mergeSearchQuery"
      :results="mergeSearchResults"
      :searching="mergeSearching"
      @close="mergeDialogVisible = false"
      @search="doMergeSearch"
      @confirm="confirmMerge"
      @split="splitAsNew"
      @update:search-query="mergeSearchQuery = $event"
    />

    <!-- Reprocessing toast -->
    <Transition name="tab-fade">
      <div v-if="Object.keys(activeReprocessing).length > 0"
           class="fixed bottom-4 right-4 z-50 bg-white dark:bg-surface-800 rounded-xl shadow-lg border border-surface-200 dark:border-ink-700 p-4 max-w-sm">
        <div class="flex items-center gap-3">
          <div class="animate-spin size-5 border-2 border-primary-600 border-t-transparent rounded-full flex-shrink-0"></div>
          <div>
            <p class="text-sm font-medium text-ink-900 dark:text-ink-100">正在分析面经...</p>
            <p v-for="(info, id) in activeReprocessing" :key="id"
               class="text-xs text-ink-500 dark:text-ink-400 mt-0.5">
              {{ info.message || '准备中...' }}
            </p>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { cancelAllRequests } from '@/services/http.js'
import { safeUrl } from '@/utils/validate.js'
import { useSelection } from '@/composables/useSelection.js'
import { useTheme } from '@/composables/useTheme.js'
import { useToast, useConfirm } from '@/composables/useNotification.js'
import AppSidebar from '@/components/AppSidebar.vue'
import SiteHeader from '@/components/SiteHeader.vue'
import { useHighlightNav } from '@/composables/useHighlightNav.js'
import { useQuestionOps } from '@/composables/useQuestionOps.js'
import { useMergeDialog } from '@/composables/useMergeDialog.js'
import { useBatchActions } from '@/composables/useBatchActions.js'
import { useTabScroll } from '@/composables/useTabScroll.js'
import { useAuth } from '@/composables/useAuth.js'
import { useMasterBankData } from '@/composables/useMasterBankData.js'
import { useBuildTrigger } from '@/composables/useBuildTrigger.js'

import { defineAsyncComponent } from 'vue'
import StagingPanel from '@/components/business/StagingPanel.vue'
import SettingsPanel from '@/components/business/SettingsPanel.vue'
import TabBar from '@/components/common/TabBar.vue'
import SearchFilterBar from '@/components/business/SearchFilterBar.vue'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import DataTable from '@/components/common/DataTable.vue'
import MasterBankList from '@/components/business/MasterBankList.vue'
import InlineEdit from '@/components/common/InlineEdit.vue'
import ExamDistribution from '@/components/business/ExamDistribution.vue'
import { Toaster } from 'vue-sonner'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import LoginModal from '@/components/business/LoginModal.vue'
import MergeQuestionDialog from '@/components/business/MergeQuestionDialog.vue'
import PracticePanel from '@/components/business/PracticePanel.vue'
import LoginPage from '@/components/business/LoginPage.vue'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

// 异步组件 loading/error 包装
const asyncOptions = {
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
}

const MockInterview = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/MockInterview.vue'),
})
const KnowledgeGraph = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/KnowledgeGraph.vue'),
})
const ChatView = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/ChatView.vue'),
})
const ProfilePanel = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/ProfilePanel.vue'),
})
const AdminReview = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/AdminReview.vue'),
})
const CodingPractice = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/CodingPractice.vue'),
})
const PracticeMode = defineAsyncComponent({
  ...asyncOptions,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

// ── Composables ──
const toast = useToast()
const { confirm: showConfirm } = useConfirm()
const { isDark, toggleDark } = useTheme()

const activeTab = ref('MasterBank')
const showPracticeMode = ref(false)
const isPreviewMode = new URLSearchParams(window.location.search).get('preview') === '1'
const sidebarTabs = computed(() => [
  { key: 'MasterBank', label: '高频题库', count: filteredMasterBank.value.length },
  { key: 'Chat', label: '模拟面试' },
  { key: 'JD', label: 'JD 筛选', count: jdData.value.length },
  { key: 'Interview', label: '面经库', count: interviewData.value.length },
  { key: 'MockInterview', label: '题目抽测' },
  { key: 'KnowledgeGraph', label: '知识图谱' },
  { key: 'Import', label: '导入' },
  { key: 'Coding', label: '手撕代码' },
])
const activeTabLabel = computed(() => isAuthenticatedForUi.value ? (sidebarTabs.value.find(tab => tab.key === activeTab.value)?.label || '工作台') : 'InterviewBoss')
const showWorkspaceOverview = computed(() => ['MasterBank', 'JD', 'Interview'].includes(activeTab.value))
const practiceProgressPercent = computed(() => {
  const total = practiceStats.value?.total_questions || masterBank.value.length || 0
  if (!total) return 0
  return Math.round(((practiceStats.value?.practiced_questions || 0) / total) * 100)
})

const { saveScroll, prepareRestore, restoreScroll } = useTabScroll()

const {
  highlightInterviewId, returnTab, returnToPracticeMode,
  floatingReturnBtn, floatingBtnStyle, masterBankEverShown,
  handleReturn, detachHighlightScroll, setSavedScrollTop,
} = useHighlightNav(activeTab, showPracticeMode)

// ── Data (题库数据 + 筛选 + 获取) ──
let afterFetchCleanup = () => {}
const {
  jdData, interviewData, masterBank,
  isDataLoading, dataLoadError,
  analytics, practiceStats, popularTags,
  activeSeason, availableSeasons,
  isLoadingMore, hasMore, loadMoreMasterBank,
  selectedTag, selectedSubTags, searchQuery,
  filterDifficulty, showStarredOnly,
  filterSeason, interviewSortOrder,
  filteredMasterBank, filteredInterviewData,
  availableSubTags, interviewSeasons, practicedQuestions,
  fetchTableData, fetchAnalytics, fetchPracticeStats,
  loadActiveSeason, loadAllData, formatDate,
} = useMasterBankData({ onAfterFetch: () => afterFetchCleanup() })

// ── Build（题库重建） ──
const {
  isBuilding, buildProgress, buildStepList,
  triggerBuildMasterBank, triggerBuildPersonalBank,
} = useBuildTrigger({ onRebuildDone: () => { fetchTableData(); fetchAnalytics() } })

// ── UI state ──
const sidebarCollapsed = ref(false)
const mockInterviewRef = ref(null)
const masterBankRef = ref(null)
const jdCurrentPage = ref(1)
const jdPageSize = ref(20)
const interviewCurrentPage = ref(1)
const interviewPageSize = ref(20)
const showSettings = ref(false)
const showProfile = ref(false)
const recommendSeed = ref(0)
const showReviewPanel = ref(false)
const practiceQuestion = ref(null)
const practiceModeIndex = ref(0)

// ── Selection ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)
const isMasterSelected = (id) => masterSelection.selectedIds.value.has(id)
afterFetchCleanup = () => { jdSelection.clearSelection(); interviewSelection.clearSelection() }

// ── Auth（认证状态） ──
const {
  currentUser, showLoginModal, pendingReviewCount,
  initAuth, handleLoginSuccess, handleLogout, handleBankModeChanged,
} = useAuth({
  onReady: loadAllData,
  onDataRefresh: () => { fetchTableData(); fetchPracticeStats() },
})

const previewUser = {
  id: 'preview-user',
  username: 'Preview',
  is_admin: true,
  bank_mode: 'mixed',
}
const displayUser = computed(() => currentUser.value || (isPreviewMode ? previewUser : null))
const isAuthenticatedForUi = computed(() => Boolean(displayUser.value))

const applyPreviewData = () => {
  activeSeason.value = '2026 春招'
  availableSeasons.value = ['2026 春招', '2025 秋招']
  popularTags.value = {
    前端框架: 318,
    项目复盘: 126,
    工程化: 94,
    浏览器原理: 76,
    系统设计: 42,
  }
  practiceStats.value = {
    total_questions: 1248,
    practiced_questions: 426,
    avg_score: 82,
    by_difficulty: {
      'L1-基础': { practiced: 168, total: 320, avg_score: 86 },
      'L2-中等': { practiced: 202, total: 654, avg_score: 80 },
      'L3-困难': { practiced: 56, total: 274, avg_score: 74 },
    },
  }
  analytics.value = {
    tech_trends: { Vue: 128, TypeScript: 96, Vite: 72, 性能优化: 64, 工程化: 58 },
  }
  masterBank.value = [
    {
      id: 9001,
      question: 'Vue 3 的响应式系统相比 Vue 2 有哪些关键变化？',
      frequency: 92,
      cat1: '前端框架',
      tags: 'Vue,响应式,Proxy',
      difficulty: 'L2-中等',
      job_position: 'frontend',
      is_personal: false,
      is_starred: true,
      has_reference_answer: true,
      ai_answer: 'Vue 3 使用 Proxy 代替 Object.defineProperty，覆盖新增、删除、数组索引等场景；依赖收集以 effect 为核心组织，配合 ref、reactive、computed 和 scheduler，让组合式 API 下的状态复用更自然。',
      sources: [{ company: '字节', round: '一面', url: 'https://example.com', _origQuestion: 'Vue3 响应式原理是什么？' }],
    },
    {
      id: 9002,
      question: '如何介绍你最近一个项目里的性能优化？',
      frequency: 81,
      cat1: '项目复盘',
      tags: '性能优化,项目经验,指标',
      difficulty: 'L2-中等',
      job_position: 'frontend',
      is_personal: true,
      is_starred: false,
      has_reference_answer: true,
      ai_answer: '建议按“问题背景、定位方法、优化动作、量化收益、复盘边界”组织回答，优先给出首屏、接口耗时、打包体积或交互延迟等可验证指标。',
      sources: [{ company: '美团', round: '二面', url: 'https://example.com', _origQuestion: '项目性能怎么优化？' }],
    },
    {
      id: 9003,
      question: '前端工程化中如何设计稳定的构建和发布流程？',
      frequency: 64,
      cat1: '工程化',
      tags: 'CI/CD,Vite,质量门禁',
      difficulty: 'L3-困难',
      job_position: 'frontend',
      is_personal: false,
      is_starred: false,
      has_reference_answer: false,
    },
  ]
  jdData.value = [
    { id: 8101, 公司: 'Moonshot AI', 岗位名称: '高级前端工程师', 薪资范围: '35k-55k', 核心技术要求: 'Vue 3 / TypeScript / 大模型应用工程化', 加分项: 'AI 产品经验、性能优化、组件库建设', season: '2026 春招', owner_id: 'preview-user', 来源链接: 'https://example.com' },
    { id: 8102, 公司: '字节跳动', 岗位名称: '前端基础架构', 薪资范围: '40k-65k', 核心技术要求: '构建系统 / 监控 / 微前端 / Node.js', 加分项: '复杂业务平台治理经验', season: '2026 春招', owner_id: 'preview-user', 来源链接: 'https://example.com' },
  ]
  interviewData.value = [
    { id: 8201, 公司: '腾讯', season: '2026 春招', 面试轮次: '一面', 考察重点: 'Vue 原理、项目复盘、性能优化', 具体题目清单: 'Vue3 响应式原理；项目里如何做性能指标采集；如何处理复杂表格渲染。', 难易程度: '中等', created_at: new Date().toISOString(), owner_id: 'preview-user', 来源链接: 'https://example.com' },
    { id: 8202, 公司: '美团', season: '2026 春招', 面试轮次: '二面', 考察重点: '工程化、系统设计、团队协作', 具体题目清单: '如何设计导入解析容错；如何回滚异常发布；如何拆分公共组件。', 难易程度: '困难', created_at: new Date(Date.now() - 3600000).toISOString(), owner_id: 'preview-user', 来源链接: 'https://example.com' },
  ]
  practicedQuestions.value = {
    9001: { best_score: 88 },
    9002: { best_score: 76 },
  }
  masterBankEverShown.value = true
  isDataLoading.value = false
  dataLoadError.value = ''
}

// ── Question operations ──
const {
  reprocessingIds, reprocessProgress, activeReprocessing,
  deleteDataRow, reprocessInterview, retagQuestion,
  saveField, saveFieldFromEvent, toggleStar,
  generateAnswer, useReferenceAnswer, saveUserAnswer,
  deleteQuestion, deleteOriginalQuestion, editQuestion, onUpdateAnswer, splitQuestion,
} = useQuestionOps(masterBank, currentUser, fetchTableData, fetchAnalytics)

// ── Merge dialog ──
const {
  mergeDialogVisible, mergeSourceOriginalQ, mergeSearchQuery,
  mergeSearchResults, mergeSearching, startMerge, doMergeSearch, confirmMerge, splitAsNew,
} = useMergeDialog(fetchTableData)

// ── Batch actions ──
const { jdBatchActions, interviewBatchActions, masterBatchActions } = useBatchActions({
  currentUser, jdSelection, interviewSelection, masterSelection, fetchTableData, fetchAnalytics,
})

// ── Static data ──
const skeletonCards = [
  { title: '75%', subtitle: '45%' },
  { title: '60%', subtitle: '55%' },
  { title: '85%', subtitle: '35%' },
  { title: '50%', subtitle: '65%' },
  { title: '70%', subtitle: '40%' },
]
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
  { key: 'focus', label: '考察重点', frontendKey: '考察重点', width: '14%', cellClass: 'whitespace-pre-wrap' },
  { key: 'questions_list', label: '具体题目清单', frontendKey: '具体题目清单', width: '32%', cellClass: 'whitespace-pre-wrap' },
  { key: 'difficulty', label: '难度', frontendKey: '难易程度', width: '8%' },
  { key: 'created_at', label: '上传日期', frontendKey: '上传日期', width: '10%' }
]

// ── Practice mode ──
const handlePracticeEvaluated = async ({ questionId, score }) => { await fetchPracticeStats() }
const enterPracticeMode = () => {
  if (filteredMasterBank.value.length === 0) { toast.warning('当前筛选条件下没有题目'); return }
  practiceModeIndex.value = 0
  showPracticeMode.value = true
}
const handlePracticeModeClose = () => { showPracticeMode.value = false; fetchPracticeStats() }
const handlePracticeModeEvaluated = async ({ questionId, score }) => { await fetchPracticeStats() }

watch(activeTab, (newTab, oldTab) => {
  if (oldTab === 'MockInterview' && newTab === 'MasterBank') { fetchPracticeStats() }
})

// ── Event handlers ──
const onSubmitted = () => { fetchTableData(); fetchAnalytics() }
let _tabChangeTimer = null
const onTabChange = async (tab) => {
  if (tab === activeTab.value) return
  // 防抖：防止快速点击导致 Transition 竞态
  if (_tabChangeTimer) return
  // 检查是否有未保存的内联编辑
  const editingInputs = document.querySelectorAll('.tab-content input:not([type="checkbox"]):not([type="hidden"]), .tab-content textarea')
  const hasActiveEdit = Array.from(editingInputs).some(el => {
    const parent = el.closest('.group')
    return parent && el.offsetParent !== null && el === document.activeElement
  })
  if (hasActiveEdit) {
    const confirmed = await showConfirm('有未保存的编辑内容，确定要离开吗？', { title: '未保存的修改', variant: 'warning' })
    if (!confirmed) return
  }
  // 保存当前 tab 的滚动位置，标记下一个 tab 需要恢复
  const scrollEl = document.querySelector('.overflow-y-auto.custom-scrollbar')
  if (scrollEl) saveScroll(activeTab.value, scrollEl.scrollTop)
  prepareRestore(tab)
  activeTab.value = tab
  returnTab.value = null
  returnToPracticeMode.value = false
  highlightInterviewId.value = null
  floatingBtnStyle.value = { display: 'none' }
  // 更新浏览器历史，支持后退/前进恢复 Tab
  history.pushState({ tab }, '', `#${tab}`)
  // 防抖重置
  _tabChangeTimer = setTimeout(() => { _tabChangeTimer = null }, 300)
}
const onSelectTag = (tag) => { selectedTag.value = tag; selectedSubTags.value = []; activeTab.value = 'MasterBank' }
const onGraphFilterTag = (tagName) => { selectedTag.value = '全部'; selectedSubTags.value = []; searchQuery.value = tagName; activeTab.value = 'MasterBank' }
const onGraphFilterCategory = (catName) => { selectedTag.value = catName; selectedSubTags.value = []; searchQuery.value = ''; activeTab.value = 'MasterBank' }
const onGoToQuestion = (question) => {
  activeTab.value = 'MasterBank'
  const q = question.question || ''
  searchQuery.value = q.length > 30 ? q.substring(0, 30) : q
  selectedTag.value = '全部'; selectedSubTags.value = []
}
const toggleSubTag = (tag) => {
  const idx = selectedSubTags.value.indexOf(tag)
  if (idx === -1) { selectedSubTags.value = [...selectedSubTags.value, tag] }
  else { selectedSubTags.value = selectedSubTags.value.filter(t => t !== tag) }
}

const onNavigateToInterview = (event) => {
  const source = event?.source || event
  const questionId = event?.questionId
  const targetUrl = source.url || ''
  if (!targetUrl) return

  const normalizeUrl = (u) => {
    try { return new URL(u).pathname.replace(/\/+$/, '') } catch { return u.split('?')[0].replace(/\/+$/, '') }
  }
  const targetPath = normalizeUrl(targetUrl)

  const match = interviewData.value.find(row => {
    const rowUrl = row['来源链接'] || row.url || ''
    return rowUrl === targetUrl || normalizeUrl(rowUrl) === targetPath
  })
  if (!match) { toast.warning('未找到该面经记录'); return }

  returnTab.value = activeTab.value
  const outerScroll = document.querySelector('.overflow-y-auto.custom-scrollbar')
  if (outerScroll) setSavedScrollTop(outerScroll.scrollTop)

  if (showPracticeMode.value) { returnToPracticeMode.value = true; showPracticeMode.value = false }
  activeTab.value = 'Interview'

  filterSeason.value = ''
  const sortedIdx = filteredInterviewData.value.indexOf(match)
  const idx = sortedIdx >= 0 ? sortedIdx : interviewData.value.indexOf(match)
  interviewCurrentPage.value = Math.floor(idx / interviewPageSize.value) + 1

  highlightInterviewId.value = match.id

  const scrollAndHighlight = (attempt = 0) => {
    const el = document.querySelector(`[data-row-id="${match.id}"]`)
    if (el) {
      const allScrollContainers = document.querySelectorAll('.custom-scrollbar')
      let mainScroll = null
      for (const c of allScrollContainers) {
        if (c.scrollHeight > c.clientHeight + 10 && c.classList.contains('overflow-y-auto')) { mainScroll = c; break }
      }
      if (mainScroll) {
        const containerRect = mainScroll.getBoundingClientRect()
        const rowRect = el.getBoundingClientRect()
        const delta = rowRect.top - containerRect.top - containerRect.height / 3
        mainScroll.scrollTo({ top: mainScroll.scrollTop + delta, behavior: 'smooth' })
      } else { el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
      const questionText = source._origQuestion || source.question || ''
      if (questionText) {
        setTimeout(() => {
          const cells = el.querySelectorAll('td')
          for (const cell of cells) {
            if (cell.textContent.includes(questionText.slice(0, 15))) {
              const escaped = questionText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
              cell.innerHTML = cell.innerHTML.replace(new RegExp(`(${escaped})`, 'g'), '<mark class="bg-yellow-200 dark:bg-yellow-700/60 rounded px-0.5 question-highlight">$1</mark>')
              setTimeout(() => { cell.querySelectorAll('.question-highlight').forEach(m => { m.replaceWith(m.textContent) }) }, 10000)
              break
            }
          }
        }, 300)
      }
    } else if (attempt < 40) { setTimeout(() => scrollAndHighlight(attempt + 1), 100) }
  }
  scrollAndHighlight()
}

// ── Settings callbacks ──
const onSettingsClose = () => { showSettings.value = false }
const onSettingsSaved = () => { loadAllData() }
const onPositionChanged = () => { loadAllData() }

// ── Lifecycle ──
onMounted(async () => {
  if (isPreviewMode) {
    currentUser.value = previewUser
    applyPreviewData()
  } else {
    await initAuth()
  }
  // 通知白屏检测器：Vue 应用已完成初始化
  window.__VUE_APP_READY__ = true
  // 从 URL hash 恢复 Tab
  const hashTab = location.hash.replace('#', '')
  const validTabs = ['MasterBank', 'JD', 'Interview', 'MockInterview', 'Chat', 'KnowledgeGraph', 'Import', 'Coding']
  if (hashTab && validTabs.includes(hashTab)) {
    activeTab.value = hashTab
  }
  // 监听浏览器后退/前进
  const onPopState = (e) => {
    const tab = e.state?.tab || location.hash.replace('#', '')
    if (tab && validTabs.includes(tab)) {
      activeTab.value = tab
    }
  }
  window.addEventListener('popstate', onPopState)
  onUnmounted(() => window.removeEventListener('popstate', onPopState))
})
onUnmounted(() => { cancelAllRequests(); detachHighlightScroll() })
</script>

<style scoped>
:deep(pre) { background-color: #2d2a27; color: #faf9f7; padding: 1rem; border-radius: var(--radius-xl); overflow-x: auto; margin-top: 0.5rem; margin-bottom: 1rem; }
:deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; }
:deep(p code) { @apply bg-surface-100 dark:bg-ink-800 text-red-600 dark:text-red-400; padding: 0.125rem 0.375rem; border-radius: var(--radius-md); font-size: 0.8125em; }
:deep(ul) { list-style-type: disc; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(ol) { list-style-type: decimal; padding-left: 1.5rem; margin-bottom: 1rem; }
:deep(strong) { font-weight: 700; @apply text-ink-900 dark:text-ink-100; }
:deep(h1), :deep(h2), :deep(h3) { font-weight: 700; @apply text-ink-900 dark:text-ink-100; margin-top: 1.5rem; margin-bottom: 0.5rem; }
:deep(h3) { font-size: 1.125rem; }

@keyframes indeterminate-slide {
  0% { margin-left: 0%; width: 15%; }
  50% { margin-left: 40%; width: 50%; }
  100% { margin-left: 85%; width: 15%; }
}
.indeterminate-bar { animation: indeterminate-slide 1.8s ease-in-out infinite; }
.tab-fade-enter-active { transition: opacity 0.25s cubic-bezier(0.25, 0.46, 0.45, 0.94); }
.tab-fade-leave-active { transition: opacity 0.15s ease-in; position: absolute; width: 100%; }
.tab-fade-enter-from { opacity: 0; }
.tab-fade-leave-to { opacity: 0; }
.fade-slide-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.fade-slide-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateX(-8px); }
.fade-slide-leave-to { opacity: 0; transform: translateX(-8px); }
.float-pop-enter-active { transition: opacity 0.3s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.float-pop-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.float-pop-enter-from { opacity: 0; transform: scale(0.8) translateX(-8px); }
.float-pop-leave-to { opacity: 0; transform: scale(0.8) translateX(-8px); }

:global(.scroll-restore-highlight) { animation: scroll-glow 2.2s ease-out forwards; }

@media (prefers-reduced-motion: reduce) {
  .tab-fade-enter-active, .tab-fade-leave-active { transition-duration: 0.01ms !important; }
  .fade-slide-enter-active, .fade-slide-leave-active { transition-duration: 0.01ms !important; }
  .float-pop-enter-active, .float-pop-leave-active { transition-duration: 0.01ms !important; }
}
</style>
