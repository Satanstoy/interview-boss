<template>
  <div class="overflow-x-auto w-full">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="rows.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <div class="rounded-xl border border-gray-100 dark:border-gray-700 overflow-hidden">
      <table class="w-full text-left border-collapse min-w-full">
        <thead>
          <tr class="bg-gradient-to-b from-gray-50 to-gray-50/50 dark:from-surface-700 dark:to-surface-700/50 text-gray-500 dark:text-gray-400 text-xs uppercase tracking-wider">
            <th class="p-3.5 border-b border-gray-100 dark:border-gray-700 whitespace-nowrap w-10 text-center">选择</th>
            <th class="p-3.5 border-b border-gray-100 dark:border-gray-700 whitespace-nowrap min-w-[160px]">操作</th>
            <th v-for="col in columns" :key="col.key" class="p-3.5 border-b border-gray-100 dark:border-gray-700 whitespace-nowrap font-semibold" :class="col.class || ''">
              {{ col.label }}
            </th>
          </tr>
        </thead>
        <tbody v-auto-animate>
          <tr v-for="(row, idx) in rows" :key="row.id"
            class="border-b border-gray-50 dark:border-gray-700/50 text-sm transition-colors duration-150 animate-fade-in"
            :class="isSelected(row.id) ? 'bg-primary-50/60 dark:bg-primary-900/20' : idx % 2 === 0 ? 'bg-white dark:bg-surface-800' : 'bg-gray-50/30 dark:bg-surface-900/30'"
            :style="{ animationDelay: Math.min(idx * 30, 300) + 'ms' }"
          >
            <td class="p-3.5 whitespace-nowrap text-center">
              <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)"
                class="w-4 h-4 text-primary-600 rounded-md border-gray-300 dark:border-gray-600 focus:ring-primary-500 cursor-pointer transition">
            </td>
            <td class="p-3.5 whitespace-nowrap">
              <slot name="actions" :row="row" />
            </td>
            <td v-for="col in columns" :key="col.key" class="p-3.5" :class="col.cellClass || 'whitespace-nowrap'">
              <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
                {{ row[col.frontendKey || col.key] }}
              </slot>
            </td>
          </tr>
          <tr v-if="rows.length === 0">
            <td :colspan="columns.length + 2" class="p-16 text-center">
              <div class="flex flex-col items-center">
                <div class="w-16 h-16 rounded-2xl bg-gray-100 dark:bg-gray-800 flex items-center justify-center mb-4">
                  <svg class="w-8 h-8 text-gray-300 dark:text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4"/>
                  </svg>
                </div>
                <p class="text-gray-500 dark:text-gray-400 font-medium mb-1">暂无数据</p>
                <p class="text-sm text-gray-400 dark:text-gray-500">试试切换筛选条件或录入更多内容</p>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import BatchActionPanel from './BatchActionPanel.vue'

defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false },
  batchActions: { type: Array, default: () => [] }
})
defineEmits(['toggle-select-all', 'invert-selection', 'toggle-item'])
</script>
