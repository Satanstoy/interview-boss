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

    <AppEmpty 
      v-if="items.length === 0"
      title="题库空空如也"
      description="导入面经或 JD，AI 会自动为你生成高频题目"
    >
      <button @click="$emit('navigate-to-import')" class="btn-primary text-sm mt-4">
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"/></svg>
        开始导入
      </button>
    </AppEmpty>

    <!-- Virtual scroller: only renders visible cards in DOM -->
    <DynamicScroller
      v-if="items.length > 0"
      ref="scrollerRef"
      :key="items.map(i => i.id).join(',')"
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
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import AppEmpty from '@/components/common/AppEmpty.vue'
import BatchActionPanel from '@/components/common/BatchActionPanel.vue'
import QuestionCard from '@/components/business/QuestionCard.vue'

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

const emit = defineEmits(['toggle-select-all', 'invert-selection', 'toggle-star', 'retag', 'generate-answer', 'use-reference-answer', 'save-user-answer', 'save-field', 'toggle-item', 'expand-all', 'collapse-all', 'practice', 'split-question', 'start-merge', 'navigate-to-interview', 'delete', 'edit-question', 'delete-original-question', 'update-answer', 'scroller-visible'])

const containerRef = ref(null)
const scrollerRef = ref(null)
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

defineExpose({ scrollerRef })
</script>

<style scoped>
.virtual-scroller {
  overflow-y: auto;
}
</style>
