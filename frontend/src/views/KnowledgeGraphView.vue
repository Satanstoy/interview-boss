<template>
  <div class="px-4 py-4 md:px-6 md:py-6 flex-1 min-h-0 flex flex-col gap-4 overflow-y-auto custom-scrollbar">
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
