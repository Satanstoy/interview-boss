<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <StagingPanel
      :active-season="activeSeason"
      :available-seasons="availableSeasons"
      :is-admin="displayUser?.is_admin"
      @submitted="onSubmitted"
    />
  </div>
</template>

<script setup>
import { inject } from 'vue'
import StagingPanel from '@/components/business/StagingPanel.vue'

const { activeSeason, availableSeasons, displayUser, fetchTableData, fetchAnalytics } = inject('appData')

const onSubmitted = () => {
  fetchTableData()
  fetchAnalytics()
}
</script>
