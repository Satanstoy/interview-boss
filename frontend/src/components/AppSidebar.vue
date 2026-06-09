<script setup>
import { HugeiconsIcon } from '@hugeicons/vue'
import {
  Book02Icon,
  AiChat01Icon,
  FilterIcon,
  BookBookmark01Icon,
  TestTube01Icon,
  AiNetworkIcon,
  BookUploadIcon,
  BracesIcon,
} from '@hugeicons/core-free-icons'
import AnalyticsSidebar from '@/components/business/AnalyticsSidebar.vue'
import UserMenu from '@/components/business/UserMenu.vue'

const props = defineProps({
  activeTab: { type: String, default: 'masterBank' },
  sidebarTabs: { type: Array, default: () => [] },
  analytics: { type: Object, default: () => ({ tech_trends: {} }) },
  practiceStats: { type: Object, default: () => ({}) },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' },
  recommendSeed: { type: Number, default: 0 },
  masterBank: { type: Array, default: () => [] },
  filteredMasterBank: { type: Array, default: () => [] },
  displayUser: { type: Object, default: null },
  pendingReviewCount: { type: Number, default: 0 },
})

const emit = defineEmits([
  'update:active-tab',
  'select-tag',
  'go-to-question',
  'refresh-recommend',
  'logout',
  'bank-mode-changed',
  'show-review',
  'show-profile',
  'refresh',
])

const iconMap = {
  MasterBank: Book02Icon,
  Chat: AiChat01Icon,
  JD: FilterIcon,
  Interview: BookBookmark01Icon,
  MockInterview: TestTube01Icon,
  KnowledgeGraph: AiNetworkIcon,
  Import: BookUploadIcon,
  Coding: BracesIcon,
}

function onTabChange(key) {
  emit('update:active-tab', key)
}

function onSelectTag(tag) {
  emit('select-tag', tag)
}

function onGoToQuestion(q) {
  emit('go-to-question', q)
}

function onRefreshRecommend() {
  emit('refresh-recommend')
}

function onRefreshAnalytics() {
  emit('refresh')
}

function handleLogout() {
  emit('logout')
}

function handleBankModeChanged(val) {
  emit('bank-mode-changed', val)
}

function handleShowReview() {
  emit('show-review')
}

function handleShowProfile() {
  emit('show-profile')
}
</script>

<template>
  <!-- Plain div layout — no shadcn Sidebar wrapper (avoids fixed positioning) -->
  <div class="flex flex-col h-full overflow-hidden">
    <!-- Header: Logo -->
    <div class="p-4 pb-2 shrink-0">
      <a href="#" class="flex items-center gap-3">
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 text-sm font-bold text-white shadow-lg shadow-primary/20 transition-transform hover:scale-105">
          IB
        </div>
        <div class="flex flex-col items-start leading-tight">
          <span class="text-base font-semibold tracking-tight text-sidebar-foreground">InterviewBoss</span>
          <span class="text-[11px] text-sidebar-foreground/50">AI 面试准备工作台</span>
        </div>
      </a>
    </div>

    <!-- Navigation tabs -->
    <div class="flex-1 min-h-0 flex flex-col gap-1 py-2 overflow-y-auto custom-scrollbar">
      <div class="px-2 space-y-0.5">
        <button
          v-for="tab in sidebarTabs"
          :key="tab.key"
          @click="onTabChange(tab.key)"
          class="group relative flex items-center gap-3 w-full rounded-lg px-3 py-2 text-sm transition-all duration-150"
          :class="[
            activeTab === tab.key
              ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
              : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'
          ]"
        >
          <HugeiconsIcon
            v-if="iconMap[tab.key]"
            :icon="iconMap[tab.key]"
            :size="18"
            class="transition-colors shrink-0"
            :class="activeTab === tab.key ? 'text-primary' : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'"
          />
          <span class="text-sm">{{ tab.label }}</span>
          <span
            v-if="tab.count != null && tab.count !== 0"
            class="ml-auto text-[11px] font-medium text-sidebar-foreground/50"
          >
            {{ tab.count }}
          </span>
        </button>
      </div>

      <div class="mx-4 my-2 h-px bg-sidebar-border/50"></div>

      <!-- Category Directory (simplified) -->
      <div class="min-h-0 flex-1 overflow-y-auto px-2 custom-scrollbar">
        <div class="p-4">
          <h3 class="text-sm font-bold text-ink-800 dark:text-ink-100 mb-2 flex items-center gap-1.5">
            <div class="w-5 h-5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
              <svg class="w-3 h-3 text-emerald-600 dark:text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" /></svg>
            </div>
            分类目录
          </h3>
          <ul class="space-y-0.5">
            <li
              @click="onSelectTag('全部')"
              class="flex justify-between items-center text-xs cursor-pointer px-2.5 py-2 rounded-lg transition-all duration-200 border border-transparent"
              :class="selectedTag === '全部' ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-semibold border-emerald-200 dark:border-emerald-800' : 'hover:bg-surface-50 dark:hover:bg-ink-800 text-ink-600 dark:text-ink-400'"
            >
              <span>全部</span>
              <span class="text-ink-400 dark:text-ink-500 font-mono text-[11px] tabular-nums">{{ masterBank.length }}</span>
            </li>
            <li
              v-for="(count, topic) in popularTags" :key="topic"
              @click="onSelectTag(topic)"
              class="flex justify-between items-center text-xs cursor-pointer px-2.5 py-2 rounded-lg transition-all duration-200 border border-transparent group"
              :class="selectedTag === topic ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 font-semibold border-emerald-200 dark:border-emerald-800' : 'hover:bg-surface-50 dark:hover:bg-ink-800 text-ink-600 dark:text-ink-400'"
            >
              <span class="break-all mr-2 group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition-colors">{{ topic }}</span>
              <span class="text-ink-400 dark:text-ink-500 font-mono text-[11px] whitespace-nowrap tabular-nums group-hover:text-emerald-500 dark:group-hover:text-emerald-400">{{ count }}</span>
            </li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Footer: User menu -->
    <div class="p-4 pt-2 border-t border-sidebar-border/50 shrink-0">
      <div class="rounded-xl border border-sidebar-border/50 bg-sidebar-accent/30 p-3">
        <UserMenu
          v-if="displayUser"
          :user="displayUser"
          :pending-count="pendingReviewCount"
          placement="top"
          button-class="w-full justify-start rounded-lg hover:bg-sidebar-accent px-3 py-2.5 transition-colors"
          @logout="handleLogout"
          @bank-mode-changed="handleBankModeChanged"
          @show-review="handleShowReview"
          @show-profile="handleShowProfile"
        />
      </div>
    </div>
  </div>
</template>
