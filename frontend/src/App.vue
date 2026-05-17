<template>
  <div class="min-h-screen bg-surface-50 dark:bg-surface-900">
    <!-- Top bar -->
    <nav class="sticky top-0 z-50 bg-white/85 dark:bg-surface-900/85 backdrop-blur-xl border-b border-surface-200/60 dark:border-ink-700/40 supports-[backdrop-filter]:bg-white/60 dark:supports-[backdrop-filter]:bg-surface-900/60">
      <div class="max-w-[1920px] mx-auto px-5 lg:px-8 h-14 flex items-center justify-between">
        <h1 class="text-lg lg:text-xl font-serif font-normal tracking-tight text-ink-900 dark:text-ink-100">
          Interview<span class="text-primary-600 dark:text-primary-400">Boss</span>
        </h1>
        <div class="flex items-center gap-3">
          <span v-if="currentUser && activeSeason" class="badge bg-primary-50 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 border border-primary-200 dark:border-primary-800 px-3 py-1">
            {{ activeSeason }}
          </span>
          <UserMenu
            v-if="currentUser"
            :user="currentUser"
            :pending-count="pendingReviewCount"
            @logout="handleLogout"
            @bank-mode-changed="handleBankModeChanged"
            @show-review="showReviewPanel = true"
            @show-profile="showProfile = true"
          />
          <!-- Dark mode toggle -->
          <button
            @click="toggleDark()"
            class="p-2 rounded-xl text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-800 transition-all duration-200"
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
            class="p-2 rounded-xl text-ink-400 hover:text-ink-600 dark:hover:text-ink-300 hover:bg-surface-100 dark:hover:bg-ink-800 transition-all duration-200"
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
      :is-admin="currentUser?.is_admin"
      :is-building="isBuilding"
      @close="onSettingsClose"
      @update:active-season="activeSeason = $event"
      @settings-saved="onSettingsSaved"
      @position-changed="onPositionChanged"
      @build-master-bank="triggerBuildMasterBank"
    />

    <!-- Login gate: split layout -->
    <div v-if="!currentUser" class="relative min-h-[calc(100vh-56px)] overflow-hidden">
      <div class="absolute inset-0 overflow-hidden pointer-events-none">
        <div class="absolute -top-40 -right-40 w-[500px] h-[500px] bg-primary-200/20 dark:bg-primary-900/15 rounded-full blur-[100px] animate-pulse-slow"></div>
        <div class="absolute -bottom-40 -left-40 w-[500px] h-[500px] bg-accent-200/20 dark:bg-accent-900/15 rounded-full blur-[100px] animate-pulse-slow" style="animation-delay: 1.5s"></div>
        <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[300px] h-[300px] bg-primary-100/10 rounded-full blur-[80px] animate-float"></div>
      </div>

      <div class="relative flex flex-col lg:flex-row min-h-[calc(100vh-56px)]">
        <!-- Left: brand showcase -->
        <div class="flex-1 flex flex-col justify-center px-8 lg:px-16 py-12 lg:py-0 animate-fade-in">
          <div class="max-w-md mx-auto lg:mx-0">
            <div class="w-20 h-20 mb-8 rounded-2xl bg-gradient-brand flex items-center justify-center shadow-warm transform hover:scale-105 transition-transform duration-300">
              <svg class="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"/>
              </svg>
            </div>

            <h2 class="font-serif text-3xl lg:text-[2.5rem] text-ink-900 dark:text-ink-100 mb-3 leading-tight">
              欢迎使用 InterviewBoss
            </h2>
            <p class="text-ink-400 dark:text-ink-400 mb-10 leading-relaxed text-lg font-light">
              AI 驱动的面试准备平台
            </p>

            <div class="grid grid-cols-3 gap-4">
              <div v-for="feature in loginFeatures" :key="feature.label"
                class="flex flex-col items-center gap-2.5 p-4 rounded-2xl bg-white/70 dark:bg-surface-800/70 backdrop-blur-sm border border-surface-200/80 dark:border-ink-700/50 shadow-card hover:shadow-card-hover transition-all duration-300 hover:-translate-y-0.5">
                <div class="w-10 h-10 rounded-xl flex items-center justify-center" :class="feature.iconBg">
                  <span class="text-lg">{{ feature.icon }}</span>
                </div>
                <span class="text-xs font-semibold text-ink-600 dark:text-ink-400">{{ feature.label }}</span>
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

    <main v-else class="p-3 lg:p-5 max-w-[1920px] mx-auto">
      <div class="sidebar-layout flex gap-6 lg:gap-8">
      <!-- Sidebar + resize handle wrapper -->
      <div
        ref="sidebarWrapperRef"
        class="sidebar-wrapper hidden lg:block"
        :style="{ width: sidebarCollapsed ? '0px' : sidebarWidth + 'px', flexShrink: 0 }"
      >
        <AnalyticsSidebar
          v-show="!sidebarCollapsed"
          :sidebar-collapsed="sidebarCollapsed"
          :sidebar-width="sidebarWidth"
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
      </div>
      <!-- Resize handle: positioned via JS to track sidebar edge -->
      <div
        v-show="!sidebarCollapsed"
        ref="resizeHandleRef"
        class="resize-handle hidden lg:flex"
        :class="{ 'resize-handle--collapsed': sidebarCollapsed, 'resize-handle--dragging': isResizing }"
        :style="resizeHandleStyle"
        @pointerdown="onResizeStart"
      >
        <div class="resize-handle__grip">
          <span></span>
          <span></span>
          <span></span>
        </div>
        <!-- Collapse arrow: click to hide sidebar -->
        <button
          v-if="!sidebarCollapsed"
          class="resize-handle__collapse-btn"
          @pointerdown.stop
          @click.stop="sidebarCollapsed = true; localStorage.setItem('sidebar-collapsed', 'true')"
          title="收起侧栏"
        >
          <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <!-- Expand button: visible when sidebar is collapsed -->
      <Transition name="expand-btn-fade">
        <button
          v-if="sidebarCollapsed"
          ref="expandBtnRef"
          class="sidebar-expand-btn hidden lg:flex"
          @pointerdown="onExpandBtnDragStart"
          title="展开侧栏（可拖拽调整宽度）"
        >
          <svg class="w-4 h-4 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </Transition>

      <div class="relative min-w-0 flex-1 bg-white dark:bg-surface-800 rounded-2xl shadow-card dark:shadow-glass-dark border border-surface-200/80 dark:border-ink-700/50 overflow-hidden flex flex-col h-[calc(100vh-88px)]">
        <TabBar :active-tab="activeTab" @update:active-tab="onTabChange" />

        <div class="p-3 lg:p-4 flex-1 min-h-0 flex flex-col overflow-y-auto custom-scrollbar">
          <SearchFilterBar
            v-if="activeTab === 'MasterBank'"
            :search-query="searchQuery"
            :filter-difficulty="filterDifficulty"
            @update:search-query="searchQuery = $event"
            @update:filter-difficulty="filterDifficulty = $event"
          />

          <!-- Sub-tag filter chips -->
          <div v-if="activeTab === 'MasterBank' && selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-2">
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


          <!-- Error banner -->
          <div v-if="dataLoadError" class="mb-4 bg-red-50/80 dark:bg-red-900/20 border border-red-200/80 dark:border-red-800/50 text-red-700 dark:text-red-400 px-4 py-3 rounded-xl flex items-center justify-between">
            <span class="flex items-center gap-2 text-sm">
              <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              {{ dataLoadError }}
            </span>
            <button @click="fetchTableData" class="text-sm bg-red-100/80 dark:bg-red-900/40 hover:bg-red-200 dark:hover:bg-red-800/40 px-3 py-1 rounded-lg transition font-medium">重试</button>
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
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1" title="打开链接">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button v-if="currentUser?.is_admin || row.owner_id === currentUser?.id" @click="deleteDataRow('jd', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1" title="删除">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="公司" db-column="company" table-name="jd" @save="saveField" />
                  <span v-else>{{ row['公司'] }}</span>
                </template>
                <template #cell-job_title="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="岗位名称" db-column="job_title" table-name="jd" @save="saveField" />
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
              <div v-if="activeTab === 'Interview'" class="flex items-center gap-2 mb-4">
                <template v-if="interviewSeasons.length > 0">
                  <label class="text-xs text-ink-500 dark:text-ink-400">招聘季筛选：</label>
                  <RoundedSelect
                    v-model="filterSeason"
                    :options="[{ value: '', label: '全部' }, ...interviewSeasons.map(s => ({ value: s, label: s }))]"
                    size="sm"
                    trigger-class="min-w-[100px]"
                  />
                  <span class="text-surface-300 dark:text-ink-600">|</span>
                </template>
                <button
                  @click="interviewSortOrder = interviewSortOrder === 'desc' ? 'asc' : 'desc'"
                  class="inline-flex items-center gap-1 border border-surface-300 dark:border-ink-600 rounded-lg px-3 py-1.5 text-xs bg-white dark:bg-surface-800 text-ink-700 dark:text-ink-200 hover:bg-surface-50 dark:hover:bg-surface-700 transition-colors"
                  :title="interviewSortOrder === 'desc' ? '当前：最新在前，点击切换' : '当前：最旧在前，点击切换'"
                >
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
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
                    <div v-if="currentUser?.is_admin" class="relative flex flex-col items-center">
                      <button @click="reprocessInterview(row.id)" :disabled="reprocessingIds[row.id]" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1 disabled:opacity-50" title="重新提取并打标">
                        <svg v-if="reprocessingIds[row.id]" class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                        <svg v-else class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                        <span class="text-[10px] leading-tight">{{ reprocessingIds[row.id] ? (reprocessProgress[row.id]?.step === 'tag' ? '标注中' : reprocessProgress[row.id]?.step === 'match' ? '聚类中' : reprocessProgress[row.id]?.step === 'save' ? '保存中' : '分析中') : '分析' }}</span>
                      </button>
                    </div>
                    <a v-if="row['来源链接'] && row['来源链接'] !== '未提供链接'" :href="safeUrl(row['来源链接'])" target="_blank" rel="noopener noreferrer" class="flex flex-col items-center text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300 px-1" title="打开链接">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>
                      <span class="text-[10px] leading-tight">链接</span>
                    </a>
                    <button v-if="currentUser?.is_admin || row.owner_id === currentUser?.id" @click="deleteDataRow('interview', row.id)" class="flex flex-col items-center text-red-500 hover:text-red-700 dark:text-red-400 dark:hover:text-red-300 px-1" title="删除">
                      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                      <span class="text-[10px] leading-tight">删除</span>
                    </button>
                  </div>
                </template>
                <template #cell-company="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="公司" db-column="company" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['公司'] }}</span>
                </template>
                <template #cell-season="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="season" db-column="season" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['season'] }}</span>
                </template>
                <template #cell-round="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="面试轮次" db-column="round" table-name="interview" @save="saveField" />
                  <span v-else>{{ row['面试轮次'] }}</span>
                </template>
                <template #cell-focus="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="考察重点" db-column="focus" table-name="interview" type="textarea" @save="saveField" />
                  <span v-else>{{ row['考察重点'] }}</span>
                </template>
                <template #cell-questions_list="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="具体题目清单" db-column="questions_list" table-name="interview" type="textarea" rows="6" @save="saveField" />
                  <span v-else>{{ row['具体题目清单'] }}</span>
                </template>
                <template #cell-difficulty="{ row }">
                  <InlineEdit v-if="currentUser?.is_admin" :row="row" field="难易程度" db-column="difficulty" table-name="interview" type="select" :options="['简单', '中等', '困难']" @save="saveField" />
                  <span v-else>{{ row['难易程度'] }}</span>
                </template>
                <template #cell-created_at="{ row }">
                  <span class="text-xs text-ink-500 dark:text-ink-400 whitespace-nowrap">{{ formatDate(row.created_at) }}</span>
                </template>
              </DataTable>

              <!-- Floating return button (appears next to highlighted row) -->
              <Teleport to="body">
                <Transition name="float-pop">
                  <button
                    v-if="activeTab === 'Interview' && returnTab && highlightInterviewId"
                    ref="floatingReturnBtn"
                    @click="handleReturn"
                    class="fixed z-[200] flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-white bg-primary-600 hover:bg-primary-700 dark:bg-primary-500 dark:hover:bg-primary-600 rounded-lg shadow-lg hover:shadow-xl transition-all duration-200 whitespace-nowrap"
                    :style="floatingBtnStyle"
                  >
                    <svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18"/></svg>
                    {{ returnToPracticeMode ? '返回刷题模式' : '返回题库' }}
                    <svg class="w-3 h-3 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>
                  </button>
                </Transition>
              </Teleport>

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
              <StagingPanel v-if="activeTab === 'Import'" :active-season="activeSeason" :available-seasons="availableSeasons" :is-admin="currentUser?.is_admin" @submitted="onSubmitted" />

              <!-- MasterBank Tab -->
              <MasterBankList
                v-if="activeTab === 'MasterBank'"
                :items="filteredMasterBank"
                :selected-count="masterSelection.selectedCount.value"
                :is-selected="isMasterSelected"
                :batch-actions="masterBatchActions"
                :practiced-questions="practicedQuestions"
                :bank-mode="currentUser?.bank_mode"
                :is-admin="currentUser?.is_admin"
                :current-user-id="currentUser?.id"
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
              >
                <template #actions>
                  <div v-if="isBuilding" class="flex items-center gap-2">
                    <div class="flex items-center gap-1">
                      <template v-for="s in buildStepList" :key="s.key">
                        <span
                          class="inline-block w-1.5 h-1.5 rounded-full transition-colors duration-300"
                          :class="s.active ? 'bg-primary-500 animate-pulse-slow' : s.done ? 'bg-primary-300 dark:bg-primary-600' : 'bg-surface-300 dark:bg-ink-600'"
                          :title="s.label"
                        ></span>
                      </template>
                    </div>
                    <div class="w-24 h-1.5 bg-surface-200 dark:bg-ink-700 rounded-full overflow-hidden">
                      <div
                        class="h-full bg-primary-500 rounded-full"
                        :class="buildProgress.total > 0 ? 'transition-all duration-500 ease-out' : (buildProgress.message ? 'indeterminate-bar' : '')"
                        :style="buildProgress.total > 0 ? { width: Math.round((buildProgress.current / buildProgress.total) * 100) + '%' } : { width: buildProgress.message ? undefined : '15%' }"
                      ></div>
                    </div>
                    <span class="text-xs font-medium text-primary-600 dark:text-primary-400 whitespace-nowrap tabular-nums">
                      <template v-if="buildProgress.total > 0">{{ buildProgress.message }} ({{ Math.round((buildProgress.current / buildProgress.total) * 100) }}%)</template>
                      <template v-else-if="buildProgress.message">{{ buildProgress.message }}</template>
                      <template v-else>准备中...</template>
                    </span>
                  </div>
                  <button v-if="!currentUser?.is_admin" @click="triggerBuildPersonalBank" :disabled="isBuilding" class="btn-primary text-xs">
                    {{ isBuilding ? '重建中...' : '重建题库' }}
                  </button>
                  <button v-if="filteredMasterBank.length > 0" @click="enterPracticeMode" class="btn-secondary text-xs">
                    刷题模式
                  </button>
                  <button v-if="!isDataLoading" @click="fetchTableData" :disabled="isDataLoading" class="btn-secondary text-xs">
                    刷新
                  </button>
                </template>
              </MasterBankList>
            </div>
          </Transition>
        </div>
      </div>
    </div>
    </main>

    <Toaster position="top-right" richColors closeButton />
    <ConfirmDialog />
    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="handleLoginSuccess" />
    <ProfilePanel :visible="showProfile" :user="currentUser" @close="showProfile = false" />
    <AdminReview :visible="showReviewPanel" @close="showReviewPanel = false" @reviewed="fetchTableData" />
    <PracticePanel :visible="!!practiceQuestion" :question="practiceQuestion" @close="practiceQuestion = null" @answer-evaluated="handlePracticeEvaluated" @navigate-to-interview="onNavigateToInterview" />
    <PracticeMode
      v-if="showPracticeMode"
      :questions="filteredMasterBank"
      :start-index="practiceModeIndex"
      :bank-mode="currentUser?.bank_mode"
      :is-admin="currentUser?.is_admin"
      @close="handlePracticeModeClose"
      @answer-evaluated="handlePracticeModeEvaluated"
      @toggle-star="toggleStar"
      @navigate-to-interview="onNavigateToInterview"
    />

    <!-- Merge Question Dialog -->
    <Teleport to="body">
      <div v-if="mergeDialogVisible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="mergeDialogVisible = false">
        <div class="bg-white dark:bg-surface-800 rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col border border-surface-200 dark:border-ink-700">
          <div class="p-5 border-b border-surface-200 dark:border-ink-700">
            <h3 class="text-lg font-bold text-ink-800 dark:text-ink-100 font-serif">移动题目到目标聚类</h3>
            <p class="text-sm text-ink-400 dark:text-ink-400 mt-1">选择要移动到的目标题目，或独立为新聚类</p>
            <p class="text-xs text-ink-400 dark:text-ink-500 mt-2 bg-surface-50 dark:bg-surface-700 rounded-lg p-2 truncate">
              <span class="font-medium">当前题目：</span>{{ mergeSourceOriginalQ }}
            </p>
          </div>
          <div class="p-4 border-b border-surface-200 dark:border-ink-700">
            <button @click="splitAsNew" class="w-full text-left p-3 rounded-xl border-2 border-dashed border-primary-300 dark:border-primary-700 hover:bg-primary-50 dark:hover:bg-primary-900/20 hover:border-primary-400 dark:hover:border-primary-600 transition-all duration-200">
              <div class="flex items-center gap-2">
                <svg class="w-4 h-4 text-primary-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/></svg>
                <span class="text-sm font-medium text-primary-700 dark:text-primary-400">成为新的独立聚类</span>
              </div>
              <p class="text-xs text-ink-400 dark:text-ink-500 mt-1 ml-6">从当前聚类中拆出，作为独立题目</p>
            </button>
          </div>
          <div class="p-5 border-b border-surface-200 dark:border-ink-700">
            <div class="flex gap-2">
              <input v-model="mergeSearchQuery" @keyup.enter="doMergeSearch"
                class="flex-1 px-3 py-2 border border-surface-300 dark:border-ink-600 rounded-lg text-sm bg-white dark:bg-surface-900 text-ink-800 dark:text-ink-200 focus:ring-2 focus:ring-primary-400 focus:border-primary-400"
                placeholder="搜索目标题目..." />
              <button @click="doMergeSearch" :disabled="mergeSearching"
                class="btn-primary px-4 py-2 text-sm disabled:opacity-50">
                {{ mergeSearching ? '搜索中...' : '搜索' }}
              </button>
            </div>
          </div>
          <div class="flex-1 overflow-y-auto p-5 custom-scrollbar">
            <div v-if="mergeSearchResults.length === 0" class="text-center py-8 text-ink-400 dark:text-ink-500 text-sm">
              {{ mergeSearching ? '搜索中...' : '输入关键词搜索目标题目' }}
            </div>
            <div v-else class="space-y-2">
              <button v-for="item in mergeSearchResults" :key="item.id"
                @click="confirmMerge(item)"
                class="w-full text-left p-3 rounded-xl border border-surface-200 dark:border-ink-700 hover:bg-primary-50 dark:hover:bg-primary-900/20 hover:border-primary-300 dark:hover:border-primary-700 transition-all duration-200">
                <div class="text-sm font-medium text-ink-800 dark:text-ink-200 line-clamp-2">{{ item.question }}</div>
                <div class="text-xs text-ink-400 dark:text-ink-500 mt-1">频率: {{ item.frequency }} | {{ item.cat1 || '未分类' }} / {{ item.cat2 || '未分类' }}</div>
              </button>
            </div>
          </div>
          <div class="p-4 border-t border-surface-200 dark:border-ink-700 flex justify-end">
            <button @click="mergeDialogVisible = false" class="btn-secondary px-4 py-2 text-sm">取消</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 全局分析进度提示（切换 Tab 后仍可见） -->
    <Transition name="tab-fade">
      <div v-if="Object.keys(activeReprocessing).length > 0"
           class="fixed bottom-4 right-4 z-50 bg-white dark:bg-surface-800 rounded-xl shadow-lg border border-surface-200 dark:border-ink-700 p-4 max-w-sm">
        <div class="flex items-center gap-3">
          <div class="animate-spin w-5 h-5 border-2 border-primary-600 border-t-transparent rounded-full flex-shrink-0"></div>
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
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { cancelAllRequests, setUnauthorizedHandler, setAuthToken, refreshAuthToken, getFriendlyError } from './utils/http.js'
import { safeUrl } from './utils/validate.js'
import * as api from './api/index.js'
import { useSelection } from './composables/useSelection.js'
import { useTheme } from './composables/useTheme.js'

import { defineAsyncComponent } from 'vue'

import StagingPanel from './components/StagingPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import TabBar from './components/TabBar.vue'
import SearchFilterBar from './components/SearchFilterBar.vue'
import RoundedSelect from './components/RoundedSelect.vue'
import DataTable from './components/DataTable.vue'
import MasterBankList from './components/MasterBankList.vue'
import InlineEdit from './components/InlineEdit.vue'
import { Toaster } from 'vue-sonner'
import ConfirmDialog from './components/ConfirmDialog.vue'
import LoginModal from './components/LoginModal.vue'
import UserMenu from './components/UserMenu.vue'
import PracticePanel from './components/PracticePanel.vue'

// 低频组件异步懒加载，减少首屏 JS 体积
const MockInterview = defineAsyncComponent(() => import('./components/MockInterview.vue'))
const KnowledgeGraph = defineAsyncComponent(() => import('./components/KnowledgeGraph.vue'))
const ProfilePanel = defineAsyncComponent(() => import('./components/ProfilePanel.vue'))
const AdminReview = defineAsyncComponent(() => import('./components/AdminReview.vue'))
const PracticeMode = defineAsyncComponent(() => import('./components/PracticeMode.vue'))
const AnalyticsSidebar = defineAsyncComponent(() => import('./components/AnalyticsSidebar.vue'))
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
const buildProgress = ref({ step: '', current: 0, total: 0, message: '' })
const buildStepsDef = [
  { key: 'tag', label: 'LLM 标注' },
  { key: 'cluster', label: '聚类去重' },
  { key: 'merge', label: '统一问题' },
  { key: 'save', label: '写入题库' },
]
const buildStepList = computed(() => {
  const curIdx = buildStepsDef.findIndex(s => s.key === buildProgress.value.step)
  return buildStepsDef.map((s, i) => ({
    ...s,
    active: i === curIdx,
    done: curIdx >= 0 && i < curIdx,
  }))
})
const isDataLoading = ref(false)
const dataLoadError = ref(null)
const analytics = ref({ tech_trends: {} })
const popularTagsFromServer = ref([])
const selectedTag = ref('全部')
const selectedSubTags = ref([])
const searchQuery = ref('')
const filterDifficulty = ref('')
const showStarredOnly = ref(false)
const filterSeason = ref('')
const interviewSortOrder = ref('desc')  // desc = newest first, asc = oldest first
const reprocessingIds = ref({})
const reprocessProgress = ref({})  // { [id]: { step, message } }
const mockInterviewRef = ref(null)
const jdCurrentPage = ref(1)
const jdPageSize = ref(20)
const interviewCurrentPage = ref(1)
const interviewPageSize = ref(20)
const activeSeason = ref('')
const availableSeasons = ref([])
const showSettings = ref(false)
const showProfile = ref(false)
const practiceStats = ref({})
const recommendSeed = ref(0)
const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
const sidebarWidth = ref(Number(localStorage.getItem('sidebar-width')) || 320)
const isResizing = ref(false)
const resizeHandleRef = ref(null)
const expandBtnRef = ref(null)
const sidebarWrapperRef = ref(null)
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 480
const SIDEBAR_COLLAPSE_THRESHOLD = 120

const toggleSidebar = () => {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('sidebar-collapsed', sidebarCollapsed.value)
}

function onResizeStart(e) {
  if (e.button !== 0) return
  e.preventDefault()
  isResizing.value = true
  const startX = e.clientX
  const startWidth = sidebarWidth.value
  const wasCollapsed = sidebarCollapsed.value

  const handle = resizeHandleRef.value
  if (handle) handle.setPointerCapture(e.pointerId)

  const wrapperEl = sidebarWrapperRef.value
  let rafId = null
  let finalWidth = startWidth
  let finalCollapsed = wasCollapsed

  function onMove(ev) {
    const delta = ev.clientX - startX
    if (wasCollapsed) {
      if (delta > 10) {
        finalCollapsed = false
        finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, delta))
      } else {
        return
      }
    } else {
      const newWidth = startWidth + delta
      if (newWidth < SIDEBAR_COLLAPSE_THRESHOLD) {
        finalCollapsed = true
        finalWidth = 0
      } else {
        finalCollapsed = false
        finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, newWidth))
      }
    }
    if (!rafId) {
      rafId = requestAnimationFrame(() => {
        rafId = null
        if (wrapperEl) wrapperEl.style.width = finalWidth + 'px'
        if (handle) handle.style.left = (finalWidth - 6) + 'px'
      })
    }
  }

  function onUp(ev) {
    isResizing.value = false
    if (rafId) { cancelAnimationFrame(rafId); rafId = null }
    if (handle) handle.releasePointerCapture(ev.pointerId)
    handle?.removeEventListener('pointermove', onMove)
    handle?.removeEventListener('pointerup', onUp)
    handle?.removeEventListener('pointercancel', onUp)
    // Sync final state to reactive refs (one-time)
    sidebarCollapsed.value = finalCollapsed
    if (!finalCollapsed) {
      sidebarWidth.value = finalWidth
      localStorage.setItem('sidebar-width', finalWidth)
    }
    localStorage.setItem('sidebar-collapsed', finalCollapsed)
  }

  handle?.addEventListener('pointermove', onMove)
  handle?.addEventListener('pointerup', onUp)
  handle?.addEventListener('pointercancel', onUp)
}

// Drag-to-resize from the expand button when sidebar is collapsed
function onExpandBtnDragStart(e) {
  if (e.button !== 0) return
  e.preventDefault()
  e.stopPropagation()  // prevent the click handler from firing immediately
  isResizing.value = true  // disable CSS transition immediately
  const startX = e.clientX
  let dragged = false

  const btn = expandBtnRef.value
  if (btn) btn.setPointerCapture(e.pointerId)

  const wrapperEl = sidebarWrapperRef.value
  const handle = resizeHandleRef.value
  let rafId = null
  let finalWidth = 0

  function onMove(ev) {
    const delta = ev.clientX - startX
    if (delta > 10) {
      dragged = true
      finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, delta))
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          rafId = null
          if (wrapperEl) wrapperEl.style.width = finalWidth + 'px'
          if (handle) handle.style.left = (finalWidth - 6) + 'px'
        })
      }
    }
  }

  function onUp(ev) {
    isResizing.value = false
    if (rafId) { cancelAnimationFrame(rafId); rafId = null }
    if (btn) btn.releasePointerCapture(ev.pointerId)
    btn?.removeEventListener('pointermove', onMove)
    btn?.removeEventListener('pointerup', onUp)
    btn?.removeEventListener('pointercancel', onUp)
    if (!dragged) {
      // It was a click, not a drag — toggle sidebar
      toggleSidebar()
    } else {
      // Sync final state to reactive refs (one-time)
      sidebarCollapsed.value = false
      sidebarWidth.value = finalWidth
      localStorage.setItem('sidebar-width', finalWidth)
      localStorage.setItem('sidebar-collapsed', 'false')
    }
  }

  btn?.addEventListener('pointermove', onMove)
  btn?.addEventListener('pointerup', onUp)
  btn?.addEventListener('pointercancel', onUp)
}

const resizeHandleStyle = computed(() => {
  // Position the handle at the sidebar's right edge (centered on the edge)
  if (sidebarCollapsed.value) {
    return { left: '0px' }
  }
  return { left: (sidebarWidth.value - 6) + 'px' }
})

// ── Auth state ──
const currentUser = ref(null)
const showLoginModal = ref(false)
const showReviewPanel = ref(false)
const pendingReviewCount = ref(0)
const practiceQuestion = ref(null)
const showPracticeMode = ref(false)
const practiceModeIndex = ref(0)
const highlightInterviewId = ref(null)
const returnTab = ref(null)
const returnToPracticeMode = ref(false)
const floatingReturnBtn = ref(null)
const floatingBtnStyle = ref({ display: 'none' })

const positionFloatingBtn = () => {
  // 固定在页面左上角（面经模块区域上方）
  floatingBtnStyle.value = {
    position: 'fixed',
    top: '12px',
    left: '12px',
    display: 'flex'
  }
}

watch(highlightInterviewId, async (id) => {
  if (id) {
    await nextTick()
    await new Promise(r => setTimeout(r, 250))
    positionFloatingBtn()
    const onScroll = () => positionFloatingBtn()
    window.addEventListener('scroll', onScroll, true)
    setTimeout(() => {
      window.removeEventListener('scroll', onScroll, true)
      floatingBtnStyle.value = { display: 'none' }
    }, 30000)
  } else {
    floatingBtnStyle.value = { display: 'none' }
  }
})

const handleReturn = () => {
  floatingBtnStyle.value = { display: 'none' }
  const target = returnTab.value
  const practice = returnToPracticeMode.value
  returnTab.value = null
  returnToPracticeMode.value = false
  highlightInterviewId.value = null
  activeTab.value = target
  if (practice) showPracticeMode.value = true
}

// ── Selection composables ──
const jdSelection = useSelection(() => jdData.value)
const interviewSelection = useSelection(() => interviewData.value)
const masterSelection = useSelection(() => filteredMasterBank.value)
const isMasterSelected = (id) => masterSelection.selectedIds.value.has(id)

// ── Login features ──
const loginFeatures = [
  { icon: '📚', label: '智能题库', iconBg: 'bg-primary-100 dark:bg-primary-900/30' },
  { icon: '🤖', label: 'AI 刷题', iconBg: 'bg-sage-100 dark:bg-sage-700/30' },
  { icon: '🎯', label: '模拟面试', iconBg: 'bg-accent-100 dark:bg-accent-700/30' },
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
  { key: 'focus', label: '考察重点', frontendKey: '考察重点', width: '14%', cellClass: 'whitespace-pre-wrap' },
  { key: 'questions_list', label: '具体题目清单', frontendKey: '具体题目清单', width: '32%', cellClass: 'whitespace-pre-wrap' },
  { key: 'difficulty', label: '难度', frontendKey: '难易程度', width: '8%' },
  { key: 'created_at', label: '上传日期', frontendKey: '上传日期', width: '10%' }
]

// ── Computed ──
const popularTags = computed(() => {
  // Prefer server-side popular_tags when available
  if (popularTagsFromServer.value.length > 0) {
    const result = {}
    for (const t of popularTagsFromServer.value) {
      result[t.tag] = t.count
    }
    return result
  }
  // Fallback to client-side computation
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
    result = result.filter(q => {
      if ((q.question || '').toLowerCase().includes(query)) return true
      if ((q.cat1 || '').toLowerCase().includes(query)) return true
      if ((q.tags || '').toLowerCase().includes(query)) return true
      if (q.original_questions && Array.isArray(q.original_questions)) {
        return q.original_questions.some(oq => {
          const text = typeof oq === 'string' ? oq : (oq.question || '')
          return text.toLowerCase().includes(query)
        })
      }
      return false
    })
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
  let data = filterSeason.value
    ? interviewData.value.filter(d => d.season === filterSeason.value)
    : [...interviewData.value]
  data.sort((a, b) => {
    const da = a.created_at || ''
    const db = b.created_at || ''
    return interviewSortOrder.value === 'desc'
      ? db.localeCompare(da)
      : da.localeCompare(db)
  })
  return data
})

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  return dateStr.replace('T', ' ').slice(0, 16)
}

const practicedQuestions = computed(() => {
  const stats = practiceStats.value
  if (!stats?.practiced_details) return {}
  return stats.practiced_details
})

const handlePracticeEvaluated = async ({ questionId, score }) => {
  await fetchPracticeStats()
}

const enterPracticeMode = () => {
  if (filteredMasterBank.value.length === 0) {
    toast.warning('当前筛选条件下没有题目')
    return
  }
  practiceModeIndex.value = 0
  showPracticeMode.value = true
}

const handlePracticeModeClose = () => {
  showPracticeMode.value = false
  fetchPracticeStats()
}

const handlePracticeModeEvaluated = async ({ questionId, score }) => {
  await fetchPracticeStats()
}

watch(activeTab, (newTab, oldTab) => {
  if (oldTab === 'MockInterview' && newTab === 'MasterBank') {
    fetchPracticeStats()
  }
})

// ── Batch action definitions ──
const jdBatchActions = computed(() => {
  if (!currentUser.value?.is_admin) return []
  return [
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
  ]
})

const interviewBatchActions = computed(() => {
  if (!currentUser.value?.is_admin) return []
  return [
  {
    key: 'batch-reprocess',
    label: '批量重新分析',
    color: 'blue',
    handler: async (onProgress) => {
      const ids = [...interviewSelection.selectedIds.value]
      if (!await showConfirm(`确定要重新分析选中的 ${ids.length} 条面经？`)) return
      onProgress(0, ids.length)
      let ok = 0
      const failed = []  // { id, error }
      for (let i = 0; i < ids.length; i++) {
        try {
          await api.reprocessInterviewSSE(ids[i], (evt) => {
            if (evt.type === 'error') throw new Error(evt.message)
          })
          ok++
        } catch (e) {
          // 首次失败，重试一次
          try {
            await api.reprocessInterviewSSE(ids[i], (evt) => {
              if (evt.type === 'error') throw new Error(evt.message)
            })
            ok++
          } catch (e2) {
            failed.push({ id: ids[i], error: getFriendlyError(e2) })
          }
        }
        onProgress(i + 1, ids.length)
      }
      // 报告结果
      if (failed.length === 0) {
        toast.success(`全部 ${ok} 条面经分析完成！`)
      } else {
        toast.error(`完成 ${ok}/${ids.length} 条，${failed.length} 条失败（已重试一次）`)
        // 在控制台打印失败详情，方便排查
        console.warn('批量分析失败详情:', failed)
        // 弹窗展示失败详情
        const failList = failed.map(f => `ID ${f.id}: ${f.error}`).join('\n')
        await showConfirm(`${failed.length} 条面经分析失败（已重试一次）：\n\n${failList}\n\n请检查这些问题后重试。`, { title: '分析失败详情', variant: 'danger' })
      }
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
  ]
})

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

// ── Global reprocessing progress (visible across all tabs) ──
const activeReprocessing = computed(() => {
  const active = {}
  for (const [id, isProcessing] of Object.entries(reprocessingIds.value)) {
    if (isProcessing && reprocessProgress.value[id]) {
      active[id] = reprocessProgress.value[id]
    }
  }
  return active
})

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
    if (masterResp.popular_tags) {
      popularTagsFromServer.value = masterResp.popular_tags
    }
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
  try { analytics.value = await api.fetchAnalytics() } catch (e) { console.warn('获取分析数据失败', e) }
}

const fetchPracticeStats = async () => {
  try { practiceStats.value = await api.fetchPracticeStats() } catch (e) { console.warn('获取练习统计失败', e) }
}

// ── Actions ──
const onSubmitted = () => {
  // 保持在导入界面，让用户看到成功反馈（StagingPanel 的绿色提示）
  fetchTableData()
  fetchAnalytics()
}

const onTabChange = (tab) => {
  activeTab.value = tab
  returnTab.value = null
  returnToPracticeMode.value = false
  highlightInterviewId.value = null
  floatingBtnStyle.value = { display: 'none' }
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

const onNavigateToInterview = async (source) => {
  const targetUrl = source.url || ''
  if (!targetUrl) return

  // 在全量数据中查找（不受筛选条件限制）
  const match = interviewData.value.find(row => (row['来源链接'] || row.url) === targetUrl)
  if (!match) {
    toast.warning('未找到该面经记录')
    return
  }

  // 记录来源 tab 并切换到面经库
  returnTab.value = activeTab.value
  if (showPracticeMode.value) {
    returnToPracticeMode.value = true
    showPracticeMode.value = false
  }
  activeTab.value = 'Interview'

  // 计算目标行在全量数据中的页码（清除筛选确保可见）
  filterSeason.value = ''
  const idx = interviewData.value.indexOf(match)
  interviewCurrentPage.value = Math.floor(idx / interviewPageSize.value) + 1

  // 设置高亮
  highlightInterviewId.value = match.id

  // 等待 DOM 渲染完成后滚动
  await nextTick()
  await new Promise(r => setTimeout(r, 200))
  const el = document.querySelector(`[data-row-id="${match.id}"]`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  setTimeout(() => { highlightInterviewId.value = null; floatingBtnStyle.value = { display: 'none' } }, 30000)
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
  reprocessProgress.value[id] = { step: '', message: '准备中...' }
  try {
    await api.reprocessInterviewSSE(id, (evt) => {
      if (evt.type === 'progress' || evt.type === 'done') {
        reprocessProgress.value[id] = { step: evt.step, message: evt.message || '' }
      }
      if (evt.type === 'error') throw new Error(evt.message)
    })
    toast.success('重新解析完成')
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
  finally {
    reprocessingIds.value[id] = false
    reprocessProgress.value[id] = null
  }
}

const retagQuestion = async (question) => {
  // Find cluster siblings: entries sharing the same original question texts
  const origTexts = new Set()
  if (question.original_questions) {
    question.original_questions.forEach(oq => {
      const text = typeof oq === 'string' ? oq : (oq.question || '')
      if (text) origTexts.add(text)
    })
  }
  const siblings = origTexts.size > 0
    ? masterBank.value.filter(q => q.id !== question.id && q.original_questions?.some(oq => {
        const text = typeof oq === 'string' ? oq : (oq.question || '')
        return origTexts.has(text)
      }))
    : []

  const totalCount = 1 + siblings.length
  const msg = siblings.length > 0
    ? `确定要重新分类该题目及其 ${siblings.length} 个聚类关联题？共 ${totalCount} 题。`
    : '确定要重新分类该题目？'
  if (!await showConfirm(msg)) return

  question._isRetagging = true
  siblings.forEach(s => { s._isRetagging = true })
  try {
    const data = await api.retagQuestion(question.id)
    const newCat1 = data.data.cat1
    const newCat2 = data.data.cat2
    const newTags = data.data.tags
    const newDiff = data.data.difficulty

    // Apply to the target question
    question.cat1 = newCat1
    question.cat2 = newCat2
    question.tags = newTags
    question.difficulty = newDiff

    // Propagate to siblings
    if (siblings.length > 0) {
      await Promise.all(siblings.map(async (s) => {
        try {
          await api.retagQuestion(s.id)
          s.cat1 = newCat1
          s.cat2 = newCat2
          s.tags = newTags
          s.difficulty = newDiff
        } catch (e) { /* sibling fail non-fatal */ }
      }))
    }

    toast.success(siblings.length > 0 ? `已更新 ${totalCount} 个聚类关联题` : '分类成功')
    fetchAnalytics()
  } catch (e) { toast.error('失败：' + getFriendlyError(e)) }
  finally {
    question._isRetagging = false
    siblings.forEach(s => { s._isRetagging = false })
  }
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
    // 普通用户答案存入 user_answer，管理员存入 ai_answer
    if (currentUser.value?.is_admin) {
      question.ai_answer = data.answer
    } else {
      question.user_answer = data.answer
    }
    toast.success('答案生成成功')
  } catch (e) { toast.error('生成失败：' + getFriendlyError(e)) }
  finally { question._isLoadingAnswer = false }
}

const useReferenceAnswer = async (question) => {
  question._isLoadingAnswer = true
  try {
    const data = await api.useReferenceAnswer(question.id)
    question.user_answer = data.answer
    toast.success('已使用参考答案')
  } catch (e) { toast.error('操作失败：' + getFriendlyError(e)) }
  finally { question._isLoadingAnswer = false }
}

const saveUserAnswer = async ({ question, answer }) => {
  try {
    await api.saveUserAnswer(question.id, answer)
    question.user_answer = answer
    question._isEditingAnswer = false
    toast.success('保存成功')
  } catch (e) { toast.error('保存失败：' + getFriendlyError(e)) }
}

const deleteQuestion = async (question) => {
  const shortQ = question.question.length > 30 ? question.question.slice(0, 30) + '...' : question.question
  if (!await showConfirm(`确定要删除题目「${shortQ}」吗？此操作不可撤销。`, { title: '确认删除', variant: 'danger' })) return
  try {
    await api.deleteMasterQuestion(question.id)
    toast.success('题目已删除')
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('删除失败：' + getFriendlyError(e)) }
}

const deleteOriginalQuestion = async ({ question, originalQuestion }) => {
  const shortQ = originalQuestion.length > 30 ? originalQuestion.slice(0, 30) + '...' : originalQuestion
  if (!await showConfirm(`确定要从聚类中删除「${shortQ}」吗？此操作不可撤销。`, { title: '删除聚类题目', variant: 'danger' })) return
  try {
    await api.deleteOriginalQuestion(question.id, originalQuestion)
    toast.success('已从聚类中删除')
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('删除失败：' + getFriendlyError(e)) }
}

const editQuestion = async ({ question, newValue }) => {
  try {
    const data = await api.updateQuestion(question.id, { question: newValue })
    question.question = data.data.question
    question._isEditingQuestion = false
    question._editQuestion = ''
    toast.success('题目已更新')
  } catch (e) { toast.error('编辑失败：' + getFriendlyError(e)) }
}

const onUpdateAnswer = ({ id, ai_answer, user_answer }) => {
  const q = masterBank.value.find(item => item.id === id)
  if (q) {
    if (ai_answer !== undefined) q.ai_answer = ai_answer
    if (user_answer !== undefined) q.user_answer = user_answer
  }
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
const mergeSourceCat1 = ref('')
const mergeSourceCat2 = ref('')
const mergeSearchQuery = ref('')
const mergeSearchResults = ref([])
const mergeSearching = ref(false)

const startMerge = ({ question, originalQuestion }) => {
  mergeSourceQuestionId.value = question.id
  mergeSourceOriginalQ.value = originalQuestion
  mergeSourceCat1.value = question.cat1 || ''
  mergeSourceCat2.value = question.cat2 || ''
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

  let targetCat1 = ''
  let targetCat2 = ''

  // 跨类别合并时让用户选择类别
  const srcCat = `${mergeSourceCat1.value}/${mergeSourceCat2.value}`
  const tgtCat = `${target.cat1 || '未分类'}/${target.cat2 || '未分类'}`
  if (srcCat !== tgtCat && (mergeSourceCat1.value || target.cat1)) {
    const choice = await showConfirm(
      `源类别：${srcCat}\n目标类别：${tgtCat}\n\n是否将目标聚类的类别更新为源类别？\n（取消则保留目标类别）`,
      { title: '选择类别', confirmLabel: '更新为源类别', cancelLabel: '保留目标类别' }
    )
    if (choice) {
      targetCat1 = mergeSourceCat1.value
      targetCat2 = mergeSourceCat2.value
    }
  }

  if (!await showConfirm(`确定将「${shortQ}」合并到「${shortT}」吗？`, { title: '确认合并', variant: 'danger' })) return
  try {
    await api.mergeQuestion(mergeSourceQuestionId.value, mergeSourceOriginalQ.value, target.id, targetCat1, targetCat2)
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

const onSettingsClose = () => {
  showSettings.value = false
  loadAllData()
}

const onSettingsSaved = () => {
  loadAllData()
}

const onPositionChanged = () => {
  loadAllData()
}

const triggerBuildMasterBank = async () => {
  // 先检查是否有未分析的面经
  try {
    const status = await api.getAnalysisStatus()
    if (status.unanalyzed_count > 0) {
      const hasContent = status.unanalyzed.filter(u => u.has_content)
      const noContent = status.unanalyzed.filter(u => !u.has_content)
      let warnMsg = `当前有 ${status.unanalyzed_count} 条面经尚未分析：`
      if (hasContent.length > 0) {
        warnMsg += `\n\n有内容但未分析（${hasContent.length} 条）：`
        warnMsg += hasContent.slice(0, 5).map(u => `\n  · ${u.company} - ${u.round}`).join('')
        if (hasContent.length > 5) warnMsg += `\n  ...等共 ${hasContent.length} 条`
      }
      if (noContent.length > 0) {
        warnMsg += `\n\n无题目内容（${noContent.length} 条），将被跳过`
      }
      warnMsg += '\n\n未分析的面经不会被纳入题库。是否继续重建？'
      if (!await showConfirm(warnMsg, { title: '存在未分析的面经', variant: 'warning' })) return
    }
  } catch (e) {
    // 检查失败不阻塞重建，仅记录
    console.warn('检查分析状态失败，继续重建:', e)
  }

  if (!await showConfirm('将基于现有分类重新聚类（不会重新打标），确定继续？', { title: '重新聚类', variant: 'danger' })) return
  isBuilding.value = true
  buildProgress.value = { step: '', current: 0, total: 0, message: '' }
  try {
    const result = await api.buildMasterBankSSE((event) => {
      if (event.type === 'init') {
        buildProgress.value = { step: event.step, current: 0, total: event.total, message: event.message }
      } else if (event.type === 'progress') {
        buildProgress.value = { step: event.step, current: event.current, total: event.total, message: event.message }
      } else if (event.type === 'error') {
        throw new Error(event.message)
      }
    })
    if (!result) {
      toast.error('重建连接中断，请刷新页面检查结果')
    } else {
      toast.success(`重建完成，共 ${result.total_unique || 0} 道题目`)
    }
    fetchTableData()
    fetchAnalytics()
  } catch (e) { toast.error('重建失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false; buildProgress.value = { step: '', current: 0, total: 0, message: '' } }
}

const triggerBuildPersonalBank = async () => {
  if (!await showConfirm('将把你的个人题目与公共题库进行聚类合并，匹配到的题目会并入公共题库，确定继续？', { title: '重建个人题库' })) return
  isBuilding.value = true
  buildProgress.value = { step: '', current: 0, total: 0, message: '' }
  try {
    const result = await api.buildPersonalBankSSE((event) => {
      if (event.type === 'init') {
        buildProgress.value = { step: 'match', current: 0, total: event.total, message: event.message }
      } else if (event.type === 'progress') {
        buildProgress.value = { step: event.step, current: event.current, total: event.total, message: event.message }
      } else if (event.type === 'error') {
        throw new Error(event.message)
      }
    })
    toast.success(`个人题库重建完成，合并 ${result?.merged || 0} 题，保留 ${result?.kept || 0} 题`)
    fetchTableData()
  } catch (e) { toast.error('重建个人题库失败：' + getFriendlyError(e)) }
  finally { isBuilding.value = false; buildProgress.value = { step: '', current: 0, total: 0, message: '' } }
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
    const data = await api.fetchPublicProfile()
    activeSeason.value = data.settings?.active_season || ''
    availableSeasons.value = data.available_seasons || []
  } catch (e) { console.warn('加载招聘季失败', e) }
}

onMounted(async () => {
  await initAuth()
})
onUnmounted(() => cancelAllRequests())
</script>

<style scoped>
:deep(pre) { background-color: #2d2a27; color: #faf9f7; padding: 1rem; border-radius: 0.75rem; overflow-x: auto; margin-top: 0.5rem; margin-bottom: 1rem; }
:deep(code) { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 0.875em; }
:deep(p code) { @apply bg-surface-100 dark:bg-ink-800 text-red-600 dark:text-red-400; padding: 0.125rem 0.375rem; border-radius: 0.375rem; font-size: 0.8125em; }
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
.indeterminate-bar {
  animation: indeterminate-slide 1.8s ease-in-out infinite;
}

.tab-fade-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.tab-fade-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.tab-fade-enter-from { opacity: 0; transform: translateY(10px); }
.tab-fade-leave-to { opacity: 0; transform: translateY(-4px); }

.fade-slide-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.fade-slide-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.fade-slide-enter-from { opacity: 0; transform: translateX(-8px); }
.fade-slide-leave-to { opacity: 0; transform: translateX(-8px); }

.float-pop-enter-active { transition: opacity 0.3s ease, transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1); }
.float-pop-leave-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.float-pop-enter-from { opacity: 0; transform: scale(0.8) translateX(-8px); }
.float-pop-leave-to { opacity: 0; transform: scale(0.8) translateX(-8px); }

/* ── Sidebar resize handle ── */
.sidebar-layout {
  position: relative;
}
.sidebar-wrapper {
  transition: width 0.15s ease;
}
.sidebar-wrapper:has(~ .resize-handle--dragging) {
  transition: none;
}
.resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  z-index: 20;
  width: 12px;
  cursor: col-resize;
  align-items: center;
  justify-content: center;
  touch-action: none;
  user-select: none;
}
.resize-handle::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 1px;
  margin-left: -0.5px;
  background: var(--color-surface-200);
}
:global(.dark) .resize-handle::before {
  background: var(--color-ink-700);
}
.resize-handle::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 3px;
  margin-left: -1.5px;
  background: transparent;
  transition: background 0.15s ease;
  border-radius: 2px;
}
.resize-handle:hover::after,
.resize-handle--dragging::after {
  background: var(--color-primary-400);
  opacity: 0.5;
}
.resize-handle__grip {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px 3px;
  border-radius: 6px;
  background: var(--color-white);
  border: 1px solid var(--color-surface-200);
  box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  opacity: 0;
  transition: opacity 0.2s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
.resize-handle:hover .resize-handle__grip,
.resize-handle--dragging .resize-handle__grip {
  opacity: 1;
}
.resize-handle--collapsed .resize-handle__grip {
  opacity: 1;
}
.resize-handle--collapsed:hover .resize-handle__grip,
.resize-handle--collapsed.resize-handle--dragging .resize-handle__grip {
  box-shadow: 0 2px 8px rgba(0,0,0,0.12);
  transform: scale(1.05);
}
:global(.dark) .resize-handle__grip {
  background: var(--color-surface-800);
  border-color: var(--color-ink-600);
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}
.resize-handle__grip span {
  display: block;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--color-surface-400);
  transition: background 0.15s ease;
}
:global(.dark) .resize-handle__grip span {
  background: var(--color-ink-500);
}
.resize-handle:hover .resize-handle__grip span,
.resize-handle--dragging .resize-handle__grip span {
  background: var(--color-primary-500);
}

/* ── Sidebar expand button (visible when collapsed) ── */
.sidebar-expand-btn {
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 25;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  align-items: center;
  justify-content: center;
  background: var(--color-white);
  border: 1px solid var(--color-surface-200);
  box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  color: var(--color-surface-400);
  cursor: pointer;
  touch-action: none;
  user-select: none;
  transition: color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease, background 0.15s ease;
}
.sidebar-expand-btn:hover {
  color: var(--color-primary-500);
  box-shadow: 0 2px 12px rgba(0,0,0,0.15);
  transform: translateY(-50%) scale(1.1);
}
.sidebar-expand-btn:active {
  transform: translateY(-50%) scale(0.95);
}
:global(.dark) .sidebar-expand-btn {
  background: var(--color-surface-800);
  border-color: var(--color-ink-600);
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  color: var(--color-ink-400);
}
:global(.dark) .sidebar-expand-btn:hover {
  color: var(--color-primary-400);
}

/* expand button fade transition */
.expand-btn-fade-enter-active { transition: opacity 0.2s ease, transform 0.2s ease; }
.expand-btn-fade-leave-active { transition: opacity 0.15s ease, transform 0.15s ease; }
.expand-btn-fade-enter-from { opacity: 0; transform: translateY(-50%) scale(0.8); }
.expand-btn-fade-leave-to { opacity: 0; transform: translateY(-50%) scale(0.8); }

/* ── Sidebar collapse arrow button ── */
.resize-handle__collapse-btn {
  position: absolute;
  left: -16px;
  top: 50%;
  transform: translateY(-50%);
  z-index: 2;
  width: 20px;
  height: 36px;
  border-radius: 6px 0 0 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-white);
  border: 1px solid var(--color-surface-200);
  border-right: none;
  box-shadow: -1px 1px 4px rgba(0,0,0,0.06);
  color: var(--color-surface-400);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.2s ease, color 0.15s ease, background 0.15s ease;
  pointer-events: none;
}
.resize-handle:hover .resize-handle__collapse-btn {
  opacity: 0.7;
  pointer-events: auto;
}
.resize-handle__collapse-btn:hover {
  opacity: 1 !important;
  color: var(--color-primary-500);
  background: var(--color-primary-50);
}
:global(.dark) .resize-handle__collapse-btn {
  background: var(--color-surface-800);
  border-color: var(--color-ink-600);
  box-shadow: -1px 1px 4px rgba(0,0,0,0.2);
  color: var(--color-ink-400);
}
:global(.dark) .resize-handle__collapse-btn:hover {
  color: var(--color-primary-400);
  background: var(--color-primary-900/30);
}
</style>
