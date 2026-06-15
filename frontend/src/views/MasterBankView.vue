<template>
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

    <!-- MasterBank content -->
    <div v-if="masterBankEverShown">
      <!-- SearchFilterBar — 吸顶，始终可见 -->
      <div class="sticky top-0 z-10 bg-background pb-2 pt-1 -mx-4 px-4 md:-mx-6 md:px-6" style="margin-top: -0.5rem;">
        <SearchFilterBar
          :search-query="searchQuery"
          :filter-difficulty="filterDifficulty"
          @update:search-query="searchQuery = $event"
          @update:filter-difficulty="filterDifficulty = $event"
        />
      </div>

      <!-- Category tags (migrated from sidebar) -->
      <div class="flex flex-wrap gap-1.5 mb-2">
        <button
          @click="onSelectTag('全部')"
          class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 font-medium"
          :class="selectedTag === '全部'
            ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 shadow-sm'
            : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
        >
          全部
          <span class="ml-1 opacity-60 font-mono tabular-nums">{{ masterBankOverallTotal || masterBank.length }}</span>
        </button>
        <button
          v-for="(count, topic) in categoryCounts" :key="topic"
          @click="onSelectTag(topic)"
          class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 group"
          :class="selectedTag === topic
            ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 font-semibold shadow-sm'
            : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted hover:text-primary dark:hover:text-primary'"
        >
          {{ topic }}
          <span class="ml-1 opacity-60 font-mono tabular-nums">{{ count }}</span>
        </button>
      </div>

      <!-- Sub-tag filter chips -->
      <div v-if="selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-2">
        <span class="text-xs text-muted-foreground self-center mr-1 font-medium">子标签：</span>
        <button
          v-for="st in availableSubTags"
          :key="st.tag"
          @click="toggleSubTag(st.tag)"
          class="text-xs px-2.5 py-1 rounded-lg border transition-all duration-200"
          :class="selectedSubTags.includes(st.tag)
            ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 font-semibold shadow-sm'
            : 'bg-white dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted hover:border-border dark:hover:border-border'"
        >
          {{ st.tag }}
          <span class="ml-1 opacity-50">{{ st.count }}</span>
        </button>
      </div>

      <!-- Exam Distribution Chart (collapsible) -->
      <ExamDistribution :master-bank="masterBank" :default-collapsed="true" />

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
  </div>
</template>

<script setup>
import { inject, ref } from 'vue'
import SearchFilterBar from '@/components/business/SearchFilterBar.vue'
import ExamDistribution from '@/components/business/ExamDistribution.vue'
import MasterBankList from '@/components/business/MasterBankList.vue'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

const {
  // Data
  masterBank, filteredMasterBank, isDataLoading, dataLoadError,
  jdData, interviewData,
  masterBankTotal, masterBankOverallTotal,
  categoryCounts, selectedTag, selectedSubTags, availableSubTags,
  searchQuery, filterDifficulty,
  masterSelection, isMasterSelected, masterBatchActions,
  practicedQuestions, displayUser,
  isLoadingMore, hasMore, loadMoreMasterBank,
  isBuilding, triggerBuildMasterBank, triggerBuildPersonalBank,
  fetchTableData, enterPracticeMode,
  toggleStar, retagQuestion, generateAnswer, useReferenceAnswer,
  saveUserAnswer, saveFieldFromEvent, deleteQuestion, deleteOriginalQuestion,
  editQuestion, onUpdateAnswer, splitQuestion, startMerge,
  onNavigateToInterview, masterBankEverShown,
  practiceQuestion,
  // Sub-tag helper
  toggleSubTag,
} = inject('appData')

const masterBankRef = ref(null)

const skeletonCards = [
  { title: '75%', subtitle: '45%' },
  { title: '60%', subtitle: '55%' },
  { title: '85%', subtitle: '35%' },
  { title: '50%', subtitle: '65%' },
  { title: '70%', subtitle: '40%' },
]

const onSelectTag = (tag) => {
  selectedTag.value = tag
  selectedSubTags.value = []
}
</script>
