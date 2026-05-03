<template>
  <div class="overflow-x-auto w-full">
    <BatchActionPanel
      :selected-count="selectedCount"
      :total-count="rows.length"
      :actions="batchActions"
      @toggle-select-all="$emit('toggle-select-all')"
      @invert-selection="$emit('invert-selection')"
    />

    <table class="w-full text-left border-collapse min-w-full">
      <thead>
        <tr class="bg-gray-50 text-gray-600 text-sm">
          <th class="p-3 border-b whitespace-nowrap w-10">选择</th>
          <th class="p-3 border-b whitespace-nowrap min-w-[160px]">操作</th>
          <th v-for="col in columns" :key="col.key" class="p-3 border-b whitespace-nowrap" :class="col.class || ''">
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="row.id" class="border-b hover:bg-gray-50 text-sm" :class="isSelected(row.id) ? 'bg-blue-50' : ''">
          <td class="p-3 whitespace-nowrap text-center">
            <input type="checkbox" :checked="isSelected(row.id)" @change="$emit('toggle-item', row.id)" class="w-4 h-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer">
          </td>
          <td class="p-3 whitespace-nowrap">
            <slot name="actions" :row="row" />
          </td>
          <td v-for="col in columns" :key="col.key" class="p-3" :class="col.cellClass || 'whitespace-nowrap'">
            <slot :name="'cell-' + col.key" :row="row" :value="row[col.frontendKey || col.key]">
              {{ row[col.frontendKey || col.key] }}
            </slot>
          </td>
        </tr>
        <tr v-if="rows.length === 0">
          <td :colspan="columns.length + 2" class="p-6 text-center text-gray-400">暂无数据</td>
        </tr>
      </tbody>
    </table>
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
