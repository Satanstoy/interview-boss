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
        <div class="w-px h-5 bg-surface-200 dark:bg-ink-700 mx-1"></div>
        <button @click="expandAll" class="btn-ghost text-xs">全部展开</button>
        <button @click="collapseAll" class="btn-ghost text-xs">全部收起</button>
      </template>
      <template #right>
        <slot name="actions" />
      </template>
    </BatchActionPanel>

    <div v-if="items.length === 0" class="text-center py-16 rounded-2xl border-2 border-dashed border-surface-200 dark:border-ink-700 bg-surface-50/50 dark:bg-surface-800/50">
      <svg class="w-14 h-14 text-ink-300 dark:text-ink-600 mx-auto mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
      </svg>
      <p class="text-ink-500 dark:text-ink-400 font-medium mb-1">暂无符合条件的题目</p>
      <p class="text-sm text-ink-400 dark:text-ink-500">点击左侧「全部」查看所有题目，或录入更多面经自动扩充。</p>
    </div>

    <!-- Virtual scroller: only renders visible cards in DOM -->
    <DynamicScroller
      v-if="items.length > 0"
      ref="scrollerRef"
      :items="items"
      :min-item-size="130"
      key-field="id"
      class="virtual-scroller custom-scrollbar"
    >
      <template #default="{ item, index, active }">
        <DynamicScrollerItem
          :item="item"
          :active="active"
          :size-dependencies="[item._showAnswer]"
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
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import BatchActionPanel from './BatchActionPanel.vue'
import QuestionCard from './QuestionCard.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] },
  practicedQuestions: { type: Object, default: () => ({}) },
  bankMode: { type: String, default: 'public' },
  isAdmin: { type: Boolean, default: false },
  currentUserId: { type: [Number, String], default: null },
})

const emit = defineEmits(['toggle-select-all', 'invert-selection', 'toggle-star', 'retag', 'generate-answer', 'use-reference-answer', 'save-user-answer', 'save-field', 'toggle-item', 'expand-all', 'collapse-all', 'practice', 'split-question', 'start-merge', 'navigate-to-interview', 'delete', 'edit-question', 'delete-original-question', 'update-answer'])

const containerRef = ref(null)
let resizeObserver = null
let lastHeight = 0

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

  // Navigate up: container → wrapper → panel (fixed height via CSS)
  const wrapper = container.parentElement
  const panel = wrapper?.parentElement
  if (!panel) return

  const panelH = panel.clientHeight
  const wrapperPad = parseFloat(getComputedStyle(wrapper).paddingTop) + parseFloat(getComputedStyle(wrapper).paddingBottom)
  const h = panelH - wrapperPad - aboveH - gapPx - 8

  if (Math.abs(h - lastHeight) > 2) {
    lastHeight = h
    scroller.style.height = Math.max(Math.round(h), 200) + 'px'
  }
}

onMounted(() => {
  nextTick(() => {
    updateScrollerHeight()
    setTimeout(updateScrollerHeight, 300)
  })

  // Observe panel for size changes (window resize, sidebar toggle)
  const container = containerRef.value
  const panel = container?.parentElement?.parentElement
  if (panel) {
    resizeObserver = new ResizeObserver(updateScrollerHeight)
    resizeObserver.observe(panel)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
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
</script>

<style scoped>
.virtual-scroller {
  overflow-y: auto;
}
</style>
