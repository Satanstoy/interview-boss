<script setup>
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import {
  BookOpen,
  BotMessageSquare,
  ClipboardList,
  Code2,
  FileUp,
  Filter,
  Library,
  Network,
  PanelLeft,
} from '@lucide/vue'
import {
  SidebarHeader,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarMenuBadge,
  SidebarFooter,
  useSidebar,
} from '@/components/ui/sidebar'
import UserMenu from '@/components/business/UserMenu.vue'

const props = defineProps({
  activeTab: { type: String, default: '' },
  sidebarTabs: { type: Array, default: () => [] },
  sidebarGroups: { type: Array, default: () => [] },
  displayUser: { type: Object, default: null },
  pendingReviewCount: { type: Number, default: 0 },
})

const emit = defineEmits([
  'go-to-question',
  'logout',
  'bank-mode-changed',
  'show-review',
  'show-settings',
])

const router = useRouter()
const route = useRoute()
const { state, toggleSidebar } = useSidebar()

const collapsed = computed(() => state.value === 'collapsed')
const logoHovered = ref(false)

const groupedTabs = computed(() => (
  props.sidebarGroups?.length
    ? props.sidebarGroups
    : [{ label: null, tabs: props.sidebarTabs }]
))

const flatTabs = computed(() => groupedTabs.value.flatMap(group => group.tabs))

const iconMap = {
  MasterBank: BookOpen,
  Chat: BotMessageSquare,
  JD: Filter,
  Interview: Library,
  MockInterview: ClipboardList,
  KnowledgeGraph: Network,
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
function handleBankModeChanged(val) { emit('bank-mode-changed', val) }
function handleShowReview() { emit('show-review') }
function handleShowSettings() { emit('show-settings') }
</script>

<template>
  <!-- Header: logo hover (collapsed) or brand (expanded) -->
  <SidebarHeader>
    <!-- Collapsed: logo + hover PanelLeft interaction -->
    <div v-if="collapsed" class="flex justify-center">
      <button
        @mouseenter="logoHovered = true"
        @mouseleave="logoHovered = false"
        @click="toggleSidebar"
        class="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-all duration-300 overflow-hidden"
        :class="logoHovered
          ? 'bg-sidebar-accent text-sidebar-foreground cursor-pointer'
          : 'bg-transparent text-sidebar-foreground'"
      >
        <img
          src="/favicon-b.png"
          alt="InterviewBoss"
          class="h-7 w-7 object-contain transition-all duration-300 ease-out"
          :class="logoHovered ? 'opacity-0 scale-75' : 'opacity-100 scale-100'"
        />
        <PanelLeft
          :size="18"
          class="absolute transition-all duration-300 ease-out"
          :class="logoHovered ? 'opacity-100 scale-100' : 'opacity-0 scale-75'"
        />
      </button>
    </div>

    <!-- Expanded: brand header -->
    <a
      v-else
      :href="route.query.preview === '1' ? '/master-bank?preview=1' : '/master-bank'"
      class="flex min-w-0 items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-sidebar-accent/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
  </SidebarHeader>

  <!-- Navigation -->
  <SidebarContent>
    <SidebarGroup v-for="group in groupedTabs" :key="group.label || 'primary'">
      <SidebarGroupLabel v-if="group.label">{{ group.label }}</SidebarGroupLabel>
      <SidebarGroupContent>
        <SidebarMenu>
          <SidebarMenuItem v-for="tab in group.tabs" :key="tab.key">
            <SidebarMenuButton
              :tooltip="tab.label"
              :is-active="isActive(tab.route)"
              @click="onTabChange(tab)"
            >
              <component
                v-if="iconMap[tab.key]"
                :is="iconMap[tab.key]"
                :class="isActive(tab.route) ? 'text-primary' : ''"
              />
              <span>{{ tab.label }}</span>
            </SidebarMenuButton>
            <SidebarMenuBadge v-if="tab.count != null && tab.count !== 0">
              {{ tab.count }}
            </SidebarMenuBadge>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  </SidebarContent>

  <!-- Footer: user menu -->
  <SidebarFooter>
    <UserMenu
      v-if="displayUser"
      :user="displayUser"
      :pending-count="pendingReviewCount"
      placement="top"
      button-class="w-full justify-start rounded-lg hover:bg-sidebar-accent px-2 py-2 gap-2 transition-colors"
      @logout="handleLogout"
      @bank-mode-changed="handleBankModeChanged"
      @show-review="handleShowReview"
      @show-settings="handleShowSettings"
    />
  </SidebarFooter>
</template>
