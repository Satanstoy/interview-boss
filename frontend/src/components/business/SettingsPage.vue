<script setup>
import { ref, computed } from 'vue'
import { User, Target, Bot, Shield, Settings, Server } from '@lucide/vue'
import SettingsNav from './SettingsNav.vue'
import SettingsProfile from './SettingsProfile.vue'
import SettingsInterview from './SettingsInterview.vue'
import SettingsAIConfig from './SettingsAIConfig.vue'
import SettingsSecurity from './SettingsSecurity.vue'
import SettingsMCP from './SettingsMCP.vue'
import SettingsAdmin from './SettingsAdmin.vue'
import { Button } from '@/components/ui/button'

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
  'close', 'go-to-question', 'logout', 'share-default-changed',
  'profile-updated', 'build-master-bank', 'update:activeSeason',
  'sidebar-collapsed-changed',
])

const activeSection = ref('profile')

const sections = computed(() => {
  const items = [
    { id: 'profile', label: '个人信息', description: '账户、简历和题库模式', icon: User },
    { id: 'interview', label: '面试偏好', description: '岗位和分类偏好', icon: Target },
    { id: 'ai', label: 'AI 配置', description: '模型和接口参数', icon: Bot },
    { id: 'mcp', label: 'MCP 接入', description: '外部 agent 访问配置', icon: Server },
    { id: 'security', label: '账户安全', description: '密码和登录安全', icon: Shield },
  ]
  if (props.isAdmin) items.push({ id: 'admin', label: '管理员设置', description: '分类和题库操作', icon: Settings })
  return items
})
</script>

<template>
  <div class="flex h-full min-h-0 bg-background">
    <div
      class="flex w-64 shrink-0 flex-col overflow-hidden border-r border-border"
    >
      <div class="sidebar-content h-full">
        <SettingsNav
          :active-section="activeSection"
          :sections="sections"
          :is-admin="isAdmin"
          @update:active-section="activeSection = $event"
          @close="emit('close')"
        />
      </div>
    </div>

    <div class="flex min-w-0 flex-1 flex-col">
      <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
        <div class="mx-auto flex w-full max-w-4xl flex-col px-6 py-6">
          <div v-if="activeSection === 'profile'" class="animate-fade-in">
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

          <div v-else-if="activeSection === 'interview'" class="animate-fade-in">
            <SettingsInterview
              :master-bank="masterBank"
              @go-to-question="emit('go-to-question', $event)"
              @profile-updated="emit('profile-updated')"
            />
          </div>

          <div v-else-if="activeSection === 'ai'" class="animate-fade-in">
            <SettingsAIConfig />
          </div>

          <div v-else-if="activeSection === 'mcp'" class="animate-fade-in">
            <SettingsMCP />
          </div>

          <div v-else-if="activeSection === 'security'" class="animate-fade-in">
            <SettingsSecurity @logout="emit('logout')" />
          </div>

          <div v-else-if="activeSection === 'admin'" class="animate-fade-in">
            <SettingsAdmin
              :is-building="isBuilding"
              :is-admin="isAdmin"
              @build-master-bank="emit('build-master-bank')"
              @taxonomy-updated="emit('profile-updated')"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.animate-fade-in {
  animation: fadeIn var(--motion-short-3) var(--ease-decelerate);
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
