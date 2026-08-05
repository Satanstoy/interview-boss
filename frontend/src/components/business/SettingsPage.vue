<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { User, Target, Bot, Shield, Settings, Server, Search, PanelLeft } from '@lucide/vue'
import SettingsNav from './SettingsNav.vue'
import SettingsProfile from './SettingsProfile.vue'
import SettingsInterview from './SettingsInterview.vue'
import SettingsAIConfig from './SettingsAIConfig.vue'
import SettingsSearchConfig from './SettingsSearchConfig.vue'
import SettingsSecurity from './SettingsSecurity.vue'
import SettingsMCP from './SettingsMCP.vue'
import SettingsAdmin from './SettingsAdmin.vue'
import { Button } from '@/components/ui/button'
import AppTooltip from '@/components/common/AppTooltip.vue'

const props = defineProps({
  displayUser: { type: Object, default: null },
  practiceStats: { type: Object, default: () => ({}) },
  masterBank: { type: Array, default: () => [] },
  isAdmin: { type: Boolean, default: false },
  activeSeason: { type: String, default: '' },
  availableSeasons: { type: Array, default: () => [] },
  isBuilding: { type: Boolean, default: false },
})

const emit = defineEmits([
  'go-to-question', 'logout', 'share-default-changed',
  'profile-updated', 'build-master-bank', 'update:activeSeason',
  'sidebar-collapsed-changed',
])

const route = useRoute()
const activeSection = ref('profile')
const isMobileViewport = () => window.matchMedia('(max-width: 767px)').matches
const navCollapsed = ref(isMobileViewport())

const sections = computed(() => {
  const items = [
    { id: 'profile', label: '个人信息', description: '账户、简历和题库模式', icon: User },
    { id: 'interview', label: '面试偏好', description: '岗位和分类偏好', icon: Target },
    { id: 'ai', label: 'AI 配置', description: '模型和接口参数', icon: Bot },
    { id: 'search', label: '联网搜索', description: '用外部资料增强答案', icon: Search },
    { id: 'mcp', label: 'MCP 接入', description: '外部 agent 访问配置', icon: Server },
    { id: 'security', label: '账户安全', description: '密码和登录安全', icon: Shield },
  ]
  if (props.isAdmin) items.push({ id: 'admin', label: '管理员设置', description: '分类和题库操作', icon: Settings })
  return items
})

// 支持 /settings?section=ai 直达对应配置区（模型守卫引导入口）
const sectionFromQuery = (value) => {
  const known = ['profile', 'interview', 'ai', 'search', 'mcp', 'security', 'admin']
  return known.includes(value) ? value : 'profile'
}
watch(() => route.query.section, (value) => {
  if (value) activeSection.value = sectionFromQuery(value)
}, { immediate: true })

const currentSectionLabel = computed(
  () => sections.value.find(s => s.id === activeSection.value)?.label || '设置',
)
</script>

<template>
  <div class="relative flex h-full min-h-0 overflow-hidden bg-background">
    <!-- Mobile overlay -->
    <div
      v-if="!navCollapsed"
      class="fixed inset-0 z-20 bg-background/70 backdrop-blur-sm md:hidden"
      @click="navCollapsed = true"
    />

    <!-- Settings sidebar -->
    <div
      class="settings-sidebar z-30 border-r border-border bg-background flex flex-col shrink-0 overflow-hidden md:z-auto"
      :class="{ 'settings-sidebar-collapsed': navCollapsed }"
      :style="{ width: navCollapsed ? '0px' : '16rem' }"
    >
      <div class="sidebar-content h-full">
        <SettingsNav
          :active-section="activeSection"
          :sections="sections"
          :is-admin="isAdmin"
          @update:active-section="activeSection = $event"
          @collapse="navCollapsed = true"
        />
      </div>
    </div>

    <!-- Sidebar collapsed: show expand button (desktop) -->
    <div v-if="navCollapsed" class="hidden flex-col items-center py-2 px-2 gap-1 shrink-0 sidebar-expand-buttons md:flex">
      <AppTooltip text="展开设置菜单" side="right">
        <Button variant="ghost" size="icon" class="size-7" aria-label="展开设置菜单" @click="navCollapsed = false">
          <PanelLeft :size="14" />
        </Button>
      </AppTooltip>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <!-- Mobile header: toggle settings menu -->
      <div class="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2 md:hidden">
        <Button
          variant="outline"
          size="sm"
          class="h-8 shrink-0 gap-1.5 rounded-lg text-xs"
          aria-label="切换设置菜单"
          @click="navCollapsed = false"
        >
          <PanelLeft :size="14" />
          <span>设置菜单</span>
        </Button>
        <span class="min-w-0 flex-1 truncate text-xs text-muted-foreground">
          {{ currentSectionLabel }}
        </span>
      </div>

      <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        <div class="mx-auto flex w-full max-w-4xl flex-col px-6 py-6">
          <Transition name="settings-section" mode="out-in">
          <div v-if="activeSection === 'profile'" key="profile" class="settings-section">
            <SettingsProfile
              :display-user="displayUser"
              :practice-stats="practiceStats"
              :share-default="displayUser?.share_default || 'private'"
              :active-season="activeSeason"
              :available-seasons="availableSeasons"
              @share-default-changed="emit('share-default-changed', $event)"
              @profile-updated="emit('profile-updated')"
              @sidebar-collapsed-changed="emit('sidebar-collapsed-changed', $event)"
              @update:active-season="emit('update:activeSeason', $event)"
            />
          </div>

          <div v-else-if="activeSection === 'interview'" key="interview" class="settings-section">
            <SettingsInterview
              :master-bank="masterBank"
              @go-to-question="emit('go-to-question', $event)"
              @profile-updated="emit('profile-updated')"
            />
          </div>

          <div v-else-if="activeSection === 'ai'" key="ai" class="settings-section">
            <SettingsAIConfig />
          </div>

          <div v-else-if="activeSection === 'search'" key="search" class="settings-section">
            <SettingsSearchConfig />
          </div>

          <div v-else-if="activeSection === 'mcp'" key="mcp" class="settings-section">
            <SettingsMCP />
          </div>

          <div v-else-if="activeSection === 'security'" key="security" class="settings-section">
            <SettingsSecurity @logout="emit('logout')" />
          </div>

          <div v-else-if="activeSection === 'admin'" key="admin" class="settings-section">
            <SettingsAdmin
              :is-building="isBuilding"
              :is-admin="isAdmin"
              @build-master-bank="emit('build-master-bank')"
              @taxonomy-updated="emit('profile-updated')"
            />
          </div>
          </Transition>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings-sidebar {
  transition: width 380ms cubic-bezier(0.4, 0, 0.2, 1);
}

@media (max-width: 767px) {
  .settings-sidebar {
    position: absolute;
    inset: 0 auto 0 0;
    width: min(82vw, 256px) !important;
    max-width: calc(100vw - 24px);
    box-shadow: 18px 0 40px rgba(0, 0, 0, 0.12);
    transform: translateX(0);
    transition: transform 220ms ease-out;
  }

  .settings-sidebar.settings-sidebar-collapsed {
    transform: translateX(-100%);
    pointer-events: none;
  }
}

.sidebar-content {
  transition: opacity 200ms ease-out;
}

.settings-sidebar-collapsed .sidebar-content {
  opacity: 0;
  pointer-events: none;
}

.settings-sidebar.settings-sidebar-collapsed {
  border-right-width: 0;
}

.sidebar-expand-buttons {
  animation: sidebarExpandButtons 280ms cubic-bezier(0, 0, 0.2, 1) 100ms both;
}

@keyframes sidebarExpandButtons {
  from { opacity: 0; transform: translateX(-4px); }
  to   { opacity: 1; transform: translateX(0); }
}

.animate-fade-in {
  animation: fadeIn var(--motion-short-3) var(--ease-decelerate);
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
