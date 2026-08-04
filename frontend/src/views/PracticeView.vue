<template>
  <div class="flex h-full min-h-0 px-4 py-4 md:px-6 md:py-6">
    <PracticeMode
      :questions="filteredMasterBank"
      :practiced-questions="practicedQuestions"
      class="h-full min-h-0 w-full overflow-hidden rounded-xl border border-border bg-card shadow-sm"
      @close="closePractice"
    />
  </div>
</template>

<script setup>
import { defineAsyncComponent, inject } from 'vue'
import { useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const PracticeMode = defineAsyncComponent({
  delay: 100,
  timeout: 15000,
  suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/PracticeMode.vue'),
})

const router = useRouter()
const { filteredMasterBank, practicedQuestions } = inject('appData')
const closePractice = () => router.push('/master-bank')
</script>
