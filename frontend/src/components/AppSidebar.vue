<script setup>
import { ref } from 'vue'
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
import { PanelLeft } from '@lucide/vue'
import UserMenu from '@/components/business/UserMenu.vue'

const props = defineProps({
  activeTab: { type: String, default: 'masterBank' },
  sidebarTabs: { type: Array, default: () => [] },
  popularTags: { type: Object, default: () => ({}) },
  selectedTag: { type: String, default: '全部' },
  masterBank: { type: Array, default: () => [] },
  displayUser: { type: Object, default: null },
  pendingReviewCount: { type: Number, default: 0 },
})

const emit = defineEmits([
  'update:active-tab',
  'select-tag',
  'go-to-question',
  'logout',
  'bank-mode-changed',
  'show-review',
  'show-profile',
  'update:collapsed',
])

const collapsed = ref(false)
const logoHovered = ref(false)

function toggleCollapsed() {
  collapsed.value = !collapsed.value
  emit('update:collapsed', collapsed.value)
}

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

function onTabChange(key) { emit('update:active-tab', key) }
function onSelectTag(tag) { emit('select-tag', tag) }
function onGoToQuestion(q) { emit('go-to-question', q) }
function handleLogout() { emit('logout') }
function handleBankModeChanged(val) { emit('bank-mode-changed', val) }
function handleShowReview() { emit('show-review') }
function handleShowProfile() { emit('show-profile') }
</script>

<template>
  <!-- Collapsed: logo + nav icons + avatar -->
  <div v-if="collapsed" class="flex flex-col h-full items-center py-3 px-2 gap-1">
    <!-- Logo → hover shows PanelLeft icon → click expands -->
    <button
      @mouseenter="logoHovered = true"
      @mouseleave="logoHovered = false"
      @click="toggleCollapsed"
      class="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300 mb-1 overflow-hidden"
      :class="logoHovered
        ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer'
        : 'bg-gradient-to-br from-primary to-primary-600 text-white shadow-lg shadow-primary/20'"
      :title="logoHovered ? '展开侧栏' : undefined"
    >
      <!-- IB logo -->
      <span
        class="text-sm font-bold transition-all duration-300 ease-out"
        :class="logoHovered ? 'opacity-0 scale-75' : 'opacity-100 scale-100'"
      >IB</span>
      <!-- PanelLeft icon -->
      <PanelLeft
        :size="18"
        class="absolute transition-all duration-300 ease-out"
        :class="logoHovered ? 'opacity-100 scale-100' : 'opacity-0 scale-75'"
      />
    </button>

    <!-- Navigation icons -->
    <button
      v-for="tab in sidebarTabs"
      :key="tab.key"
      @click="onTabChange(tab.key)"
      class="flex items-center justify-center w-10 h-10 rounded-lg transition-colors"
      :class="activeTab === tab.key
        ? 'bg-sidebar-accent text-sidebar-accent-foreground'
        : 'text-sidebar-foreground/50 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
      :title="tab.label"
    >
      <HugeiconsIcon
        v-if="iconMap[tab.key]"
        :icon="iconMap[tab.key]"
        :size="18"
        :class="activeTab === tab.key ? 'text-primary' : ''"
      />
    </button>

    <div class="flex-1"></div>

    <!-- User avatar -->
    <UserMenu
      v-if="displayUser"
      :user="displayUser"
      :pending-count="pendingReviewCount"
      placement="top"
      compact
      button-class="rounded-lg hover:bg-sidebar-accent transition-colors p-0"
      @logout="handleLogout"
      @bank-mode-changed="handleBankModeChanged"
      @show-review="handleShowReview"
      @show-profile="handleShowProfile"
    />
  </div>

  <!-- Expanded: full sidebar -->
  <div v-else class="flex flex-col h-full overflow-hidden">
    <!-- Header: logo + PanelLeft toggle -->
    <div class="flex items-center justify-between px-4 py-3 shrink-0">
      <a href="#" class="flex items-center gap-3 min-w-0">
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-primary-600 text-sm font-bold text-white shadow-lg shadow-primary/20 transition-transform hover:scale-105">
          IB
        </div>
        <div class="flex flex-col items-start leading-tight">
          <span class="text-base font-semibold tracking-tight text-sidebar-foreground whitespace-nowrap">InterviewBoss</span>
          <span class="text-[11px] text-sidebar-foreground/50 whitespace-nowrap">AI 面试准备工作台</span>
        </div>
      </a>
      <button
        @click="toggleCollapsed"
        class="p-1.5 rounded-lg text-sidebar-foreground/40 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
        title="收起侧栏"
      >
        <PanelLeft :size="18" />
      </button>
    </div>

    <!-- Navigation -->
    <div class="flex-1 min-h-0 flex flex-col overflow-y-auto custom-scrollbar py-1 px-2 gap-0.5">
      <button
        v-for="tab in sidebarTabs"
        :key="tab.key"
        @click="onTabChange(tab.key)"
        class="group relative flex items-center w-full rounded-lg transition-all duration-150 gap-3 px-3 py-2"
        :class="activeTab === tab.key
          ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
          : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
      >
        <HugeiconsIcon
          v-if="iconMap[tab.key]"
          :icon="iconMap[tab.key]"
          :size="18"
          class="transition-colors shrink-0"
          :class="activeTab === tab.key ? 'text-primary' : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'"
        />
        <span class="text-sm whitespace-nowrap">{{ tab.label }}</span>
        <span
          v-if="tab.count != null && tab.count !== 0"
          class="ml-auto text-[11px] font-medium text-sidebar-foreground/50 whitespace-nowrap"
        >
          {{ tab.count }}
        </span>
      </button>

      <!-- Category Directory -->
      <div class="mx-2 my-2 h-px bg-sidebar-border/50"></div>
      <div class="min-h-0 flex-1 overflow-y-auto custom-scrollbar">
        <div class="px-2 py-2">
          <h3 class="text-xs font-bold text-ink-500 dark:text-ink-400 mb-2 uppercase tracking-wider px-2">分类目录</h3>
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

    <!-- Footer: user menu -->
    <div class="shrink-0 p-3 border-t border-sidebar-border/50">
      <UserMenu
        v-if="displayUser"
        :user="displayUser"
        :pending-count="pendingReviewCount"
        placement="top"
        button-class="w-full justify-start rounded-lg hover:bg-sidebar-accent px-3 py-2 gap-3 transition-colors"
        @logout="handleLogout"
        @bank-mode-changed="handleBankModeChanged"
        @show-review="handleShowReview"
        @show-profile="handleShowProfile"
      />
    </div>
  </div>
</template>
