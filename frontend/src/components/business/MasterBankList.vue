<template>
  <div ref="containerRef" class="flex flex-col flex-1 min-h-0 gap-2">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="items.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    >
      <template v-if="items.length > 0" #default>
        <div class="w-px h-5 bg-muted dark:bg-muted mx-1"></div>
        <Button @click="expandAll" variant="ghost" size="sm" class="text-xs">全部展开</Button>
        <Button @click="collapseAll" variant="ghost" size="sm" class="text-xs">全部收起</Button>
      </template>
      <template #right>
        <slot name="actions" />
      </template>
    </BatchActionPanel>

    <AppEmpty 
      v-if="items.length === 0"
      title="题库空空如也"
      description="导入面经或 JD，AI 会自动为你生成高频题目"
    >
      <Button @click="$emit('navigate-to-import')" variant="default" size="sm" class="text-sm mt-4">
        <svg class="size-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
        开始导入
      </Button>
    </AppEmpty>

    <!-- Virtual scroller: only renders visible cards in DOM -->
    <DynamicScroller
      v-if="items.length > 0"
      ref="scrollerRef"
      :items="items"
      :min-item-size="130"
      key-field="id"
      class="virtual-scroller custom-scrollbar"
      @visible="emit('scroller-visible')"
    >
      <template #default="{ item, index, active }">
        <DynamicScrollerItem
          :item="item"
          :active="active"
          :size-dependencies="[item._showAnswer, item._showSources]"
          :data-index="index"
          class="mb-4"
        >
          <QuestionCard
            :question="item"
            :is-selected="isSelected"
            :practice-info="practicedQuestions[item.id] || null"
            :bank-mode="bankMode"
            :is-admin="isAdmin"
            :current-user-id="currentUserId"
            @toggle-answer="toggleAnswer"
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
        </DynamicScrollerItem>
      </template>
    </DynamicScroller>

    <!-- 加载更多指示器 -->
    <div v-if="isLoadingMore" class="flex items-center justify-center py-4 gap-2 text-muted-foreground">
      <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
      <span class="text-xs">加载更多题目...</span>
    </div>
    <div v-else-if="!hasMore && items.length > 0" class="text-center py-3 text-xs text-muted-foreground/50">
      — 已加载全部 {{ items.length }} 道题目 —
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import AppEmpty from '@/components/common/AppEmpty.vue'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'
import QuestionCard from '@/components/business/QuestionCard.vue'
import { Button } from '@/components/ui/button'

const props = defineProps({
  items: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] },
  practicedQuestions: { type: Object, default: () => ({}) },
  bankMode: { type: String, default: 'public' },
  isAdmin: { type: Boolean, default: false },
  currentUserId: { type: [Number, String], default: null },
  isLoadingMore: { type: Boolean, default: false },
  hasMore: { type: Boolean, default: false },
})

const emit = defineEmits(['toggle-select-all', 'invert-selection', 'toggle-star', 'retag', 'generate-answer', 'use-reference-answer', 'save-user-answer', 'save-field', 'toggle-item', 'expand-all', 'collapse-all', 'practice', 'split-question', 'start-merge', 'navigate-to-interview', 'delete', 'edit-question', 'delete-original-question', 'update-answer', 'scroller-visible', 'load-more'])

const containerRef = ref(null)
const scrollerRef = ref(null)
let resizeObserver = null
let lastHeight = 0
let scrollCheckTimer = null
let outerScrollContainer = null
let scrollerScrollEl = null

const checkScrollForLoadMore = () => {
  if (!props.hasMore || props.isLoadingMore) return
  const scrollEl = scrollerScrollEl || containerRef.value?.querySelector('.vue-recycle-scroller')
  if (!scrollEl) return
  const { scrollTop, scrollHeight, clientHeight } = scrollEl
  if (scrollHeight - scrollTop - clientHeight < 600) {
    emit('load-more')
  }
}

const onScroll = () => {
  if (scrollCheckTimer) return
  scrollCheckTimer = setTimeout(() => {
    scrollCheckTimer = null
    checkScrollForLoadMore()
  }, 150)
}

const bindScrollerScroll = () => {
  const nextEl = containerRef.value?.querySelector('.vue-recycle-scroller')
  if (!nextEl || nextEl === scrollerScrollEl) return
  if (scrollerScrollEl) scrollerScrollEl.removeEventListener('scroll', onScroll)
  scrollerScrollEl = nextEl
  scrollerScrollEl.addEventListener('scroll', onScroll, { passive: true })
  checkScrollForLoadMore()
}

const updateScrollerHeight = () => {
  const container = containerRef.value
  if (!container) return
  const scroller = container.querySelector('.vue-recycle-scroller')
  if (!scroller) return

  // Sum heights of siblings above the scroller (these are stable)
  let aboveH = 0
  for (const child of container.children) {
    if (child === scroller) break
    aboveH += child.offsetHeight
  }

  // Container gap (gap-2 = 8px between each pair of children above scroller)
  const idx = Array.from(container.children).indexOf(scroller)
  const gapPx = idx > 0 ? idx * 8 : 0

  // Navigate up to find the ACTUAL scroll container (overflow-y-auto)
  // container → wrapper (App.vue line 200) → v-if div → tab-content → Transition → scroll container
  const scrollContainer = container.closest('.overflow-y-auto')
  if (!scrollContainer) return

  const scrollH = scrollContainer.clientHeight
  const scrollPad = parseFloat(getComputedStyle(scrollContainer).paddingTop) + parseFloat(getComputedStyle(scrollContainer).paddingBottom)

  // Calculate height of elements above the scroll container's content
  const wrapper = container.parentElement
  const wrapperPad = parseFloat(getComputedStyle(wrapper).paddingTop) + parseFloat(getComputedStyle(wrapper).paddingBottom)

  const h = scrollH - scrollPad - wrapperPad - aboveH - gapPx - 8

  if (Math.abs(h - lastHeight) > 2) {
    lastHeight = h
    scroller.style.height = Math.max(Math.round(h), 200) + 'px'
  }
}

onMounted(() => {
  nextTick(() => {
    updateScrollerHeight()
    bindScrollerScroll()
    setTimeout(updateScrollerHeight, 300)
    setTimeout(bindScrollerScroll, 300)
  })

  const container = containerRef.value
  outerScrollContainer = container?.closest('.overflow-y-auto')
  if (outerScrollContainer) {
    resizeObserver = new ResizeObserver(updateScrollerHeight)
    resizeObserver.observe(outerScrollContainer)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  if (scrollCheckTimer) clearTimeout(scrollCheckTimer)
  if (scrollerScrollEl) scrollerScrollEl.removeEventListener('scroll', onScroll)
})

watch(() => [props.items.length, props.isLoadingMore, props.hasMore], () => {
  nextTick(() => {
    updateScrollerHeight()
    bindScrollerScroll()
    checkScrollForLoadMore()
  })
})

const toggleAnswer = (question) => {
  question._showAnswer = !question._showAnswer
}

const expandAll = () => {
  props.items.forEach(q => { q._showAnswer = true })
}

const collapseAll = () => {
  props.items.forEach(q => { q._showAnswer = false })
}

defineExpose({ scrollerRef })
</script>

<style scoped>
.virtual-scroller {
  overflow-y: auto;
}
</style>
