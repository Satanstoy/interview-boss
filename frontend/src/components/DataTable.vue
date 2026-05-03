<template>
  <div class="overflow-x-auto w-full">
    <!-- Batch action bar -->
    <div class="mb-4 flex gap-2 flex-wrap items-center">
      <button @click="$emit('toggle-select-all')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">全选/取消全选</button>
      <button @click="$emit('invert-selection')" class="text-sm bg-gray-100 text-gray-700 px-3 py-1.5 rounded hover:bg-gray-200 transition">反选</button>
      <div class="w-px h-5 bg-gray-300 mx-1 self-center"></div>
      <slot name="batch-actions" />
      <button @click="$emit('batch-delete')" :disabled="selectedCount === 0" class="text-sm bg-red-100 text-red-700 px-3 py-1.5 rounded hover:bg-red-200 transition font-medium disabled:opacity-50 disabled:cursor-not-allowed">
        批量删除 ({{ selectedCount }})
      </button>
    </div>

    <table class="w-full text-left border-collapse min-w-full">
      <thead>
        <tr class="bg-gray-50 text-gray-600 text-sm">
          <th class="p-3 border-b whitespace-nowrap w-10">选择</th>
          <th class="p-3 border-b whitespace-nowrap">操作</th>
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
defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, default: () => [] },
  selectedCount: { type: Number, default: 0 },
  isSelected: { type: Function, default: () => false }
})
defineEmits(['toggle-select-all', 'invert-selection', 'batch-delete', 'toggle-item'])
</script>
