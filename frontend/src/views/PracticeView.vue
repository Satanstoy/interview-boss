<template>
  <div data-testid="practice-view" class="px-4 py-4 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
    <PracticeMode
      :questions="filteredMasterBank"
      :practiced-questions="practicedQuestions"
      class="w-full min-w-0"
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
