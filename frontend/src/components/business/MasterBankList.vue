<template>
  <div ref="containerRef" class="flex flex-col flex-1 min-h-0">
    <!-- Empty state -->
    <Empty v-if="items.length === 0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Inbox />
        </EmptyMedia>
        <EmptyTitle>题库空空如也</EmptyTitle>
        <EmptyDescription>导入面经或 JD，AI 会自动为你生成高频题目</EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button @click="$emit('navigate-to-import')" variant="default" size="sm">
          <Upload class="size-4 mr-1.5" />
          开始导入
        </Button>
      </EmptyContent>
    </Empty>

    <template v-else>
      <!-- Scrollable: sub-tags + accordion -->
      <div class="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
      <!-- Sub-tag filter (scrolls with content) -->
      <slot name="scroll-header" />

      <Accordion
        type="multiple"
        :model-value="openItems"
        @update:model-value="onOpenChange"
        class="flex flex-col gap-2 pb-4"
      >
        <AccordionItem
          v-for="q in items"
          :key="q.id"
          :value="String(q.id)"
          class="border border-border rounded-xl overflow-hidden bg-card shadow-sm data-[state=open]:border-primary/30"
        >
          <AccordionTrigger class="px-4 py-3 hover:no-underline">
            <div class="flex items-center gap-3 flex-1 min-w-0 text-left pr-2">
              <!-- Checkbox -->
              <input
                type="checkbox"
                :checked="isSelected(q.id)"
                @click.stop="$emit('toggle-item', q.id)"
                class="size-4 text-primary-600 rounded-md border-border cursor-pointer shrink-0"
              />
              <!-- Content -->
              <div class="flex-1 min-w-0">
                <span class="text-sm font-medium text-foreground truncate block">{{ q.question }}</span>
                <div class="flex gap-1.5 mt-1 flex-wrap items-center">
                  <span v-if="q.frequency > 1" class="text-xs px-1.5 py-0.5 rounded-md bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 font-bold">{{ q.frequency }}x</span>
                  <span class="bg-indigo-100 dark:bg-indigo-900/30 text-indigo-700 dark:text-indigo-400 text-xs px-2 py-0.5 rounded-md font-semibold">{{ q.cat1 || '未分类' }}</span>
                  <span
                    v-for="tag in (q.tags || '').split(',').filter(Boolean).slice(0, 3)"
                    :key="tag"
                    class="text-xs px-1.5 py-0.5 rounded-md bg-muted text-muted-foreground"
                  >{{ tag.trim() }}</span>
                  <span class="text-xs font-medium px-2 py-0.5 rounded-md ml-auto"
                    :class="difficultyClass(q.difficulty)">
                    {{ q.difficulty || '-' }}
                  </span>
                </div>
              </div>
            </div>
          </AccordionTrigger>
          <AccordionContent class="px-0 pb-0">
            <QuestionCard
              :question="q"
              :is-selected="isSelected"
              :practice-info="practicedQuestions[q.id] || null"
              :bank-mode="bankMode"
              :is-admin="isAdmin"
              :current-user-id="currentUserId"
              :content-only="true"
              @toggle-star="$emit('toggle-star', $event)"
              @retag="$emit('retag', $event)"
              @generate-answer="$emit('generate-answer', $event)"
              @use-reference-answer="$emit('use-reference-answer', $event)"
              @save-user-answer="$emit('save-user-answer', $event)"
              @save-field="$emit('save-field', $event)"
              @toggle-item="$emit('toggle-item', $event)"
              @practice="$emit('practice', $event)"
              @split-question="$emit('split-question', $event)"
              @start-merge="$emit('start-merge', $event)"
              @navigate-to-interview="$emit('navigate-to-interview', $event)"
              @delete="$emit('delete', $event)"
              @edit-question="$emit('edit-question', $event)"
              @delete-original-question="$emit('delete-original-question', $event)"
              @update-answer="$emit('update-answer', $event)"
            />
          </AccordionContent>
        </AccordionItem>
      </Accordion>

      <!-- Load more trigger (IntersectionObserver) -->
      <div ref="loadMoreRef" v-if="hasMore" class="flex items-center justify-center py-4 gap-2 text-muted-foreground">
        <Loader2 v-if="isLoadingMore" class="size-4 animate-spin" />
        <span class="text-xs">{{ isLoadingMore ? '加载更多题目...' : '滚动加载更多' }}</span>
      </div>
      <div v-else-if="items.length > 0" class="text-center py-3 text-xs text-muted-foreground/50">
        — 已加载全部 {{ items.length }} 道题目 —
      </div>
      </div> <!-- /scroll container -->
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { Inbox, Upload, Loader2 } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import QuestionCard from '@/components/business/QuestionCard.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  practicedQuestions: { type: Object, default: () => ({}) },
  bankMode: { type: String, default: 'public' },
  isAdmin: { type: Boolean, default: false },
  currentUserId: { type: [Number, String], default: null },
  isLoadingMore: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
})

const emit = defineEmits([
  'toggle-star', 'retag',
  'generate-answer', 'use-reference-answer', 'save-user-answer', 'save-field',
  'toggle-item', 'practice', 'split-question',
  'start-merge', 'navigate-to-interview', 'delete', 'edit-question',
  'delete-original-question', 'update-answer', 'load-more',
])

const containerRef = ref(null)
const loadMoreRef = ref(null)
const openItems = ref([])
let observer = null

// Sync _showAnswer with accordion state
const onOpenChange = (newVal) => {
  openItems.value = newVal
  props.items.forEach(q => {
    q._showAnswer = newVal.includes(String(q.id))
  })
}

const expandAll = () => {
  openItems.value = props.items.map(q => String(q.id))
  props.items.forEach(q => { q._showAnswer = true })
}

const collapseAll = () => {
  openItems.value = []
  props.items.forEach(q => { q._showAnswer = false })
}

defineExpose({ expandAll, collapseAll })

// Difficulty badge classes
const difficultyClass = (d) => {
  if (!d) return 'bg-muted text-muted-foreground'
  if (String(d).includes('L3')) return 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400'
  if (String(d).includes('L2')) return 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400'
  return 'bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400'
}

// Infinite scroll via IntersectionObserver
onMounted(() => {
  if (!loadMoreRef.value) return
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && props.hasMore && !props.isLoadingMore) {
        emit('load-more')
      }
    },
    { rootMargin: '200px' }
  )
  observer.observe(loadMoreRef.value)
})

onUnmounted(() => {
  observer?.disconnect()
})

// Re-observe when loadMoreRef changes (e.g. after items load)
watch(() => loadMoreRef.value, (el) => {
  if (observer && el) {
    observer.disconnect()
    observer.observe(el)
  }
})
</script>
