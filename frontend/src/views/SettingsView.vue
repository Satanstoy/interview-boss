<template>
  <div class="flex-1 min-h-0">
    <SettingsPage
      :display-user="displayUser"
      :practice-stats="practiceStats"
      :master-bank="masterBank"
      :is-admin="displayUser?.is_admin"
      :active-season="activeSeason"
      :available-seasons="availableSeasons"
      :is-building="isBuilding"
      @go-to-question="onGoToQuestion"
      @logout="handleLogout"
      @share-default-changed="handleShareDefaultChanged"
      @profile-updated="handleProfileUpdated"
      @build-master-bank="triggerBuildMasterBank"
      @update:active-season="activeSeason = $event"
      @sidebar-collapsed-changed="sidebarCollapsed = $event"
    />
  </div>
</template>

<script setup>
import { inject } from 'vue'
import SettingsPage from '@/components/business/SettingsPage.vue'

const {
  displayUser, practiceStats, masterBank,
  activeSeason, availableSeasons,
  isBuilding, sidebarCollapsed,
  handleLogout, handleShareDefaultChanged,
  loadAllData, triggerBuildMasterBank,
  onGoToQuestion,
} = inject('appData')

const handleProfileUpdated = () => {
  loadAllData()
}
</script>
