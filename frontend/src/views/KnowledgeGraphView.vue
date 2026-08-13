<template>
  <div class="flex flex-1 min-h-0 flex-col gap-2 overflow-y-auto px-2 py-2 custom-scrollbar sm:gap-4 sm:px-4 sm:py-4 md:px-6 md:py-6">
    <KnowledgeGraph
      @filter-by-tag="onGraphFilterTag"
      @filter-by-category="onGraphFilterCategory"
    />
  </div>
</template>

<script setup>
import { inject, defineAsyncComponent } from 'vue'
import { useRouter } from 'vue-router'
import AsyncLoading from '@/components/common/AsyncLoading.vue'

const KnowledgeGraph = defineAsyncComponent({
  delay: 100, timeout: 15000, suspensible: false,
  loadingComponent: AsyncLoading,
  loader: () => import('@/components/business/KnowledgeGraph.vue'),
})

const router = useRouter()
const { selectedTag, selectedSubTags, searchQuery } = inject('appData')

const onGraphFilterTag = (tagName) => {
  selectedTag.value = '全部'
  selectedSubTags.value = []
  searchQuery.value = tagName
  router.push('/master-bank')
}

const onGraphFilterCategory = (catName) => {
  selectedTag.value = catName
  selectedSubTags.value = []
  searchQuery.value = ''
  router.push('/master-bank')
}
</script>
