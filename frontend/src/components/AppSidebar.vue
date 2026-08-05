<script setup>
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  BookOpen,
  BotMessageSquare,
  Code2,
  FileText,
  FileUp,
  Filter,
  History,
  Layers,
  Library,
  LayoutDashboard,
  Network,
  PanelLeft,
  Target,
} from '@lucide/vue'
import UserMenu from '@/components/business/UserMenu.vue'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  collapsed: { type: Boolean, default: false },
  activeTab: { type: String, default: '' },
  sidebarTabs: { type: Array, default: () => [] },
  sidebarGroups: { type: Array, default: () => [] },
  displayUser: { type: Object, default: null },
  pendingReviewCount: { type: Number, default: 0 },
})

const emit = defineEmits([
  'go-to-question',
  'logout',
  'share-default-changed',
  'show-review',
  'show-settings',
  'update:collapsed',
])

const router = useRouter()
const route = useRoute()

const logoHovered = ref(false)

const groupedTabs = computed(() => (
  props.sidebarGroups?.length
    ? props.sidebarGroups
    : [{ label: null, tabs: props.sidebarTabs }]
))

const flatTabs = computed(() => groupedTabs.value.flatMap(group => group.tabs))

function toggleCollapsed() {
  logoHovered.value = false
  emit('update:collapsed', !props.collapsed)
}

const iconMap = {
  MasterBank: BookOpen,
  Chat: BotMessageSquare,
  JD: Filter,
  Interview: Library,
  Resume: FileText,
  Practice: Layers,
  KnowledgeGraph: Network,
  InsightsOverview: LayoutDashboard,
  InsightsReadiness: Target,
  InsightsReviews: History,
  Import: FileUp,
  Coding: Code2,
}

function isActive(tabRoute) {
  return route.path === tabRoute || route.path.startsWith(tabRoute + '/')
}

function routeTarget(path) {
  return route.query.preview === '1' ? { path, query: { preview: '1' } } : path
}

async function onTabChange(tab) {
  try {
    await router.push(routeTarget(tab.route))
  } catch (err) {
    console.warn('[AppSidebar] 导航失败:', tab.route, err)
  }
}

async function goHome() {
  try {
    await router.push(routeTarget('/master-bank'))
  } catch (err) {
    console.warn('[AppSidebar] 回到高频题库失败:', err)
  }
}

function onGoToQuestion(q) { emit('go-to-question', q) }
function handleLogout() { emit('logout') }
function handleShareDefaultChanged(val) { emit('share-default-changed', val) }
function handleShowReview() { emit('show-review') }
function handleShowSettings() { emit('show-settings') }
</script>

<template>
  <!-- Collapsed: logo + nav icons + avatar -->
  <div v-if="props.collapsed" class="flex flex-col h-full items-center py-3 px-2 gap-1 animate-sidebar-collapse">
    <!-- Logo → hover shows PanelLeft icon → click expands -->
    <AppTooltip text="展开侧栏" side="right">
      <button
        @mouseenter="logoHovered = true"
        @mouseleave="logoHovered = false"
        @click="toggleCollapsed"
        class="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-all duration-300 mb-1 overflow-hidden"
        :class="logoHovered
          ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer'
          : 'bg-transparent text-sidebar-foreground'"
      >
        <!-- App logo -->
        <img
          src="/favicon-b.png"
          alt="InterviewBoss"
          class="h-7 w-7 object-contain transition-all duration-300 ease-out"
          :class="logoHovered ? 'opacity-0 scale-75' : 'opacity-100 scale-100'"
        />
        <!-- PanelLeft icon -->
        <PanelLeft
          :size="18"
          class="absolute transition-all duration-300 ease-out"
          :class="logoHovered ? 'opacity-100 scale-100' : 'opacity-0 scale-75'"
        />
      </button>
    </AppTooltip>

    <!-- Navigation icons -->
    <AppTooltip
      v-for="tab in flatTabs"
      :key="tab.key"
      :text="tab.label"
      side="right"
    >
      <button
        @click="onTabChange(tab)"
        :aria-label="tab.label"
        class="flex items-center justify-center w-10 h-10 rounded-lg transition-all duration-300"
        :class="isActive(tab.route)
          ? 'bg-sidebar-accent text-sidebar-accent-foreground'
          : 'text-sidebar-foreground/50 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
      >
        <component
          v-if="iconMap[tab.key]"
          :is="iconMap[tab.key]"
          :size="18"
          :class="isActive(tab.route) ? 'text-primary' : ''"
        />
      </button>
    </AppTooltip>

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
      @share-default-changed="handleShareDefaultChanged"
      @show-review="handleShowReview"
      @show-settings="handleShowSettings"
    />
  </div>

  <!-- Expanded: full sidebar -->
  <div v-else class="flex flex-col h-full overflow-hidden animate-sidebar-expand">
    <!-- Header: logo + PanelLeft toggle -->
    <div class="flex items-center justify-between px-4 py-3 shrink-0">
      <a
        :href="route.query.preview === '1' ? '/master-bank?preview=1' : '/master-bank'"
        class="flex min-w-0 items-center gap-3 rounded-lg text-left transition-colors hover:bg-sidebar-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        @click.prevent="goHome"
      >
        <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl transition-transform hover:scale-105 overflow-hidden">
          <img src="/favicon-b.png" alt="InterviewBoss" class="h-8 w-8 object-contain" />
        </div>
        <div class="flex flex-col items-start leading-tight">
          <span class="text-base font-semibold tracking-tight text-sidebar-foreground whitespace-nowrap">InterviewBoss</span>
          <span class="text-[11px] text-sidebar-foreground/50 whitespace-nowrap">AI 面试准备工作台</span>
        </div>
      </a>
      <AppTooltip text="收起侧栏">
        <button
          @click="toggleCollapsed"
          aria-label="收起侧栏"
          class="p-1.5 rounded-lg text-sidebar-foreground/40 hover:text-sidebar-foreground hover:bg-sidebar-accent transition-colors"
        >
          <PanelLeft :size="18" />
        </button>
      </AppTooltip>
    </div>

    <!-- Navigation -->
    <div class="flex-1 min-h-0 flex flex-col overflow-y-auto custom-scrollbar py-1 px-2 gap-0.5">
      <div
        v-for="group in groupedTabs"
        :key="group.label || 'primary'"
        class="mb-2 last:mb-0"
      >
        <div
          v-if="group.label"
          data-sidebar-section
          class="px-3 pb-1.5 pt-2 text-[11px] font-medium text-sidebar-foreground/40"
        >
          {{ group.label }}
        </div>
        <button
          v-for="tab in group.tabs"
          :key="tab.key"
          data-sidebar-route
          @click="onTabChange(tab)"
          class="group relative flex items-center w-full rounded-lg transition-all duration-200 gap-3 px-3 py-2"
          :class="isActive(tab.route)
            ? 'bg-sidebar-accent text-sidebar-accent-foreground font-medium'
            : 'text-sidebar-foreground/60 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'"
        >
          <component
            v-if="iconMap[tab.key]"
            :is="iconMap[tab.key]"
            :size="18"
            class="transition-colors shrink-0"
            :class="isActive(tab.route) ? 'text-primary' : 'text-sidebar-foreground/40 group-hover:text-sidebar-foreground/70'"
          />
          <span class="text-sm whitespace-nowrap">{{ tab.label }}</span>
          <span
          v-if="tab.count != null && tab.count !== 0"
          class="ml-auto text-[11px] font-medium text-sidebar-foreground/50 whitespace-nowrap"
        >
            {{ ` ${tab.count}` }}
          </span>
        </button>
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
        @share-default-changed="handleShareDefaultChanged"
        @show-review="handleShowReview"
        @show-settings="handleShowSettings"
      />
    </div>
  </div>
</template>

<style scoped>
/*
  Sidebar animation strategy:
  - Content entrance/exit: unified medium-2 (300ms) + standard easing
  - Motion tokens defined in variables.css (--motion-medium-2, --ease-standard)
*/
.animate-sidebar-expand {
  animation: sidebarExpand var(--motion-medium-2) var(--ease-standard) both;
}
.animate-sidebar-collapse {
  animation: sidebarCollapse var(--motion-medium-2) var(--ease-standard) both;
}

@keyframes sidebarExpand {
  from { opacity: 0; transform: translateX(-8px); }
  to   { opacity: 1; transform: translateX(0); }
}
@keyframes sidebarCollapse {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}
</style>
