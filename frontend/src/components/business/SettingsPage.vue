<script setup>
import { ref, computed } from 'vue'
import { ArrowLeft, User, Target, Bot, Shield, Settings } from '@lucide/vue'
import SettingsNav from './SettingsNav.vue'
import SettingsProfile from './SettingsProfile.vue'
import SettingsInterview from './SettingsInterview.vue'
import SettingsAIConfig from './SettingsAIConfig.vue'
import SettingsSecurity from './SettingsSecurity.vue'
import SettingsAdmin from './SettingsAdmin.vue'

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
  'close', 'go-to-question', 'logout', 'bank-mode-changed',
  'profile-updated', 'build-master-bank', 'update:activeSeason',
  'sidebar-collapsed-changed',
])

const activeSection = ref('profile')

const sections = computed(() => {
  const items = [
    { id: 'profile', label: '个人信息', icon: User },
    { id: 'interview', label: '面试偏好', icon: Target },
    { id: 'ai', label: 'AI 配置', icon: Bot },
    { id: 'security', label: '账户安全', icon: Shield },
  ]
  if (props.isAdmin) items.push({ id: 'admin', label: '管理员设置', icon: Settings })
  return items
})
</script>

<template>
  <div class="flex flex-col bg-background" style="height: 100vh; height: 100dvh;">
    <!-- Top bar -->
    <div class="shrink-0 flex items-center gap-3 px-6 py-3 border-b border-border bg-background">
      <button
        @click="emit('close')"
        class="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft :size="16" />
        <span>返回工作台</span>
      </button>
      <div class="h-4 w-px bg-border" />
      <h1 class="text-base font-semibold text-foreground">设置</h1>
    </div>

    <!-- Body: nav + content — nav stays fixed, only content scrolls -->
    <div class="flex flex-1 min-h-0 overflow-hidden">
      <SettingsNav
        :active-section="activeSection"
        :sections="sections"
        :is-admin="isAdmin"
        @update:active-section="activeSection = $event"
      />

      <div class="flex-1 overflow-y-auto custom-scrollbar px-8 py-8">

          <div v-if="activeSection === 'profile'" class="animate-fade-in">
            <SettingsProfile
              :display-user="displayUser"
              :practice-stats="practiceStats"
              :bank-mode="displayUser?.bank_mode"
              :active-season="activeSeason"
              :available-seasons="availableSeasons"
              @bank-mode-changed="emit('bank-mode-changed', $event)"
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
</template>

<style scoped>
.animate-fade-in {
  animation: fadeIn 200ms ease-out;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}
</style>
