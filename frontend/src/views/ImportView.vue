<template>
  <div class="flex flex-1 min-h-0 flex-col gap-2 overflow-y-auto px-2 py-2 custom-scrollbar sm:gap-3 sm:px-4 sm:py-4 md:gap-4 md:px-6 md:py-6">
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
