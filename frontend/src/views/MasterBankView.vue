<template>
  <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden px-2 py-2 sm:gap-3 sm:px-4 sm:py-4 md:px-6 md:py-6">
    <!-- Error banner -->
    <div v-if="dataLoadError" class="bg-red-50/80 dark:bg-red-900/20 border border-red-200/80 dark:border-red-800/50 text-red-700 dark:text-red-400 px-4 py-3 rounded-xl flex items-center justify-between shrink-0">
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
    <div v-if="masterBankEverShown" class="flex flex-col flex-1 min-h-0 gap-3">
      <!-- ══ 固定区域（不滚动） ══ -->
      <div class="flex shrink-0 flex-col gap-2 rounded-xl border border-border bg-card p-2 shadow-sm sm:gap-3 sm:p-3">
        <!-- SearchFilterBar -->
        <SearchFilterBar
          :search-query="searchQuery"
          :filter-difficulty="filterDifficulty"
          :framed="false"
          @update:search-query="searchQuery = $event"
          @update:filter-difficulty="filterDifficulty = $event"
        />

        <!-- 题库过滤 tabs（全部 / 公共 / 我的） -->
        <div class="flex shrink-0 items-center gap-1.5">
          <button
            v-for="tab in bankFilterTabs" :key="tab.value"
            @click="onSelectBankFilter(tab.value)"
            class="text-xs px-3 py-1.5 rounded-lg border transition-all duration-200 font-medium whitespace-nowrap"
            :class="bankFilter === tab.value
              ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 shadow-sm'
              : 'bg-background dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
          >
            {{ tab.label }}
          </button>
          <span class="ml-auto text-[11px] tabular-nums text-muted-foreground md:hidden">{{ filteredMasterBank.length }} 道匹配</span>
          <Button variant="ghost" size="sm" class="h-9 shrink-0 gap-1 px-2 text-xs md:hidden" :aria-expanded="mobileToolsOpen" @click="mobileToolsOpen = !mobileToolsOpen">
            <SlidersHorizontal class="size-3.5" />管理
            <ChevronDown class="size-3 transition-transform" :class="mobileToolsOpen ? 'rotate-180' : ''" />
          </Button>
        </div>

        <Button v-if="filteredMasterBank.length > 0" class="h-10 w-full gap-2 text-sm md:hidden" @click="enterPracticeMode">
          <BookOpenCheck class="size-4" />开始八股刷题
        </Button>

        <!-- BatchActionPanel (全选/反选 + 操作) -->
        <div :class="mobileToolsOpen ? 'block' : 'hidden md:block'">
          <BatchActionPanel
          :selected-count="masterSelection.selectedCount.value"
          :total-count="filteredMasterBank.length"
          :actions="masterBatchActions"
          :framed="false"
          @toggle-select-all="masterSelection.toggleSelectAll()"
          @invert-selection="masterSelection.invertSelection()"
        >
          <div class="w-px h-5 bg-muted mx-1"></div>
          <Button @click="masterBankRef?.expandAll()" variant="ghost" size="sm" class="text-xs">全部展开</Button>
          <Button @click="masterBankRef?.collapseAll()" variant="ghost" size="sm" class="text-xs">全部收起</Button>
          <template #right>
            <div class="flex flex-wrap items-center gap-2">
              <Button v-if="displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildMasterBank" :disabled="isBuilding">
                {{ isBuilding ? '重建中...' : '重建题库' }}
              </Button>
              <Button v-if="!displayUser?.is_admin" variant="default" size="sm" @click="triggerBuildPersonalBank" :disabled="isBuilding">
                {{ isBuilding ? '重建中...' : '重建题库' }}
              </Button>
              <Button v-if="filteredMasterBank.length > 0" variant="outline" size="sm" class="hidden md:inline-flex" @click="enterPracticeMode">
                八股刷题模式
              </Button>
              <Button v-if="!isDataLoading" variant="outline" size="sm" @click="fetchTableData" :disabled="isDataLoading">
                刷新
              </Button>
            </div>
          </template>
          </BatchActionPanel>
        </div>

        <!-- Category tags (horizontal scroll) -->
        <div class="flex gap-1.5 shrink-0 overflow-x-auto custom-scrollbar pb-1">
          <button
            @click="onSelectTag('全部')"
            class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 font-medium whitespace-nowrap shrink-0"
            :class="selectedTag === '全部'
              ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 shadow-sm'
              : 'bg-background dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted'"
          >
            全部
            <span class="ml-1 opacity-60 font-mono tabular-nums">{{ masterBankOverallTotal || masterBank.length }}</span>
          </button>
          <button
            v-for="(count, topic) in categoryCounts" :key="topic"
            @click="onSelectTag(topic)"
            class="text-xs px-2.5 py-1.5 rounded-lg border transition-all duration-200 group whitespace-nowrap shrink-0"
            :class="selectedTag === topic
              ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 font-semibold shadow-sm'
              : 'bg-background dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted hover:text-primary dark:hover:text-primary'"
          >
            {{ topic }}
            <span class="ml-1 opacity-60 font-mono tabular-nums">{{ count }}</span>
          </button>
        </div>
      </div>

      <div class="flex flex-col flex-1 min-h-0">
        <MasterBankList
          ref="masterBankRef"
          :items="filteredMasterBank"
          :selected-count="masterSelection.selectedCount.value"
          :is-selected="isMasterSelected"
          :practiced-questions="practicedQuestions"
          :bank-filter="bankFilter"
          :is-admin="displayUser?.is_admin"
          :current-user-id="displayUser?.id"
          :is-loading-more="isLoadingMore"
          :has-more="hasMore"
          @toggle-item="masterSelection.toggleItem($event)"
          @toggle-star="toggleStar"
          @retag="retagQuestion"
          @generate-answer="generateAnswer"
          @save-field="saveFieldFromEvent"
          @save-user-answer="saveUserAnswer"
          @practice="practiceQuestion = $event"
          @split-question="splitQuestion"
          @start-merge="startMerge"
          @navigate-to-interview="onNavigateToInterview"
          @delete="deleteQuestion"
          @edit-question="editQuestion"
          @delete-original-question="deleteOriginalQuestion"
          @update-answer="onUpdateAnswer"
          @share="handleShare"
          @load-more="loadMoreMasterBank"
        >
          <template #scroll-header>
            <div v-if="selectedTag !== '全部' && availableSubTags.length > 0" class="flex flex-wrap gap-2 mb-3 rounded-xl border border-border bg-card p-3 shadow-sm">
              <span class="text-xs text-muted-foreground self-center mr-1 font-medium">子标签：</span>
              <button
                v-for="st in availableSubTags"
                :key="st.tag"
                @click="toggleSubTag(st.tag)"
                class="text-xs px-2.5 py-1 rounded-lg border transition-all duration-200"
                :class="selectedSubTags.includes(st.tag)
                  ? 'bg-primary/10 dark:bg-primary/20 text-primary dark:text-primary border-primary/30 dark:border-primary/30 font-semibold shadow-sm'
                  : 'bg-background dark:bg-muted text-muted-foreground border-border hover:bg-muted dark:hover:bg-muted hover:border-border dark:hover:border-border'"
              >
                {{ st.tag }}
                <span class="ml-1 opacity-50">{{ st.count }}</span>
              </button>
            </div>
          </template>
        </MasterBankList>
      </div>
    </div>
  </div>
</template>

<script setup>
import { inject, ref } from 'vue'
import { BookOpenCheck, ChevronDown, SlidersHorizontal } from '@lucide/vue'
import { useToast } from '@/composables/useNotification.js'
import SearchFilterBar from '@/components/business/SearchFilterBar.vue'
import MasterBankList from '@/components/business/MasterBankList.vue'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'

const {
  masterBank, filteredMasterBank, bankFilter, isDataLoading, dataLoadError,
  jdData, interviewData,
  masterBankTotal, masterBankOverallTotal,
  categoryCounts, selectedTag, selectedSubTags, availableSubTags,
  searchQuery, filterDifficulty,
  masterSelection, isMasterSelected, masterBatchActions,
  practicedQuestions, displayUser,
  isLoadingMore, hasMore, loadMoreMasterBank,
  isBuilding, triggerBuildMasterBank, triggerBuildPersonalBank,
  fetchTableData, enterPracticeMode,
  toggleStar, retagQuestion, generateAnswer, saveUserAnswer,
  saveFieldFromEvent, deleteQuestion, deleteOriginalQuestion,
  editQuestion, onUpdateAnswer, splitQuestion, startMerge,
  onNavigateToInterview, masterBankEverShown,
  practiceQuestion,
  toggleSubTag,
} = inject('appData')

const toast = useToast()
const masterBankRef = ref(null)
const mobileToolsOpen = ref(false)

const skeletonCards = [
  { title: '75%', subtitle: '45%' },
  { title: '60%', subtitle: '55%' },
  { title: '85%', subtitle: '35%' },
  { title: '50%', subtitle: '65%' },
  { title: '70%', subtitle: '40%' },
]

const bankFilterTabs = [
  { value: 'all', label: '全部' },
  { value: 'public', label: '公共' },
  { value: 'mine', label: '我的' },
]

const onSelectBankFilter = (value) => {
  bankFilter.value = value
  fetchTableData()
}

const handleShare = async (question) => {
  if (!question || !question.id) return
  try {
    const { shareQuestionToBank } = await import('@/services/masterBankApi.js')
    const result = await shareQuestionToBank(question.id)
    if (result?.result === 'merged') {
      toast.success('已分享：与公共题库已有题目合并')
    } else {
      toast.success('已提交审核，通过后对所有人可见')
    }
    fetchTableData()
  } catch (e) {
    toast.error(`分享失败: ${e.message}`)
  }
}

const onSelectTag = (tag) => {
  selectedTag.value = tag
  selectedSubTags.value = []
}
</script>
