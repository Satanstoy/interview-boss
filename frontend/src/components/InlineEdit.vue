<template>
  <div class="group">
    <!-- Display mode -->
    <div v-if="!editing" class="flex items-center gap-2">
      <span v-if="type === 'select'" class="px-2 py-1 rounded text-xs" :class="(displayValue || '').includes('难') ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'">
        {{ displayValue || '-' }}
      </span>
      <span v-else :class="{ 'whitespace-pre-wrap break-words flex-1': type === 'textarea' }">{{ displayValue }}</span>
      <button @click="startEdit" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition shrink-0" title="编辑">edit</button>
    </div>

    <!-- Edit mode -->
    <div v-else class="flex items-center gap-1">
      <input v-if="type === 'text'" v-model="editValue" class="border rounded px-2 py-1 w-full text-sm" @keyup.enter="save" />
      <textarea v-else-if="type === 'textarea'" v-model="editValue" :rows="rows || 3" class="border rounded px-2 py-1 w-full text-sm"></textarea>
      <select v-else-if="type === 'select'" v-model="editValue" class="border rounded px-2 py-1 text-sm">
        <option value="">未提供</option>
        <option v-for="opt in options" :key="opt" :value="opt">{{ opt }}</option>
      </select>
      <input v-else v-model="editValue" class="border rounded px-2 py-1 w-full text-sm" @keyup.enter="save" />
      <div class="flex gap-1 shrink-0">
        <button @click="save" class="text-green-500 hover:text-green-700 text-sm" title="保存">save</button>
        <button @click="editing = false" class="text-red-400 hover:text-red-600 text-sm" title="取消">cancel</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  row: { type: Object, required: true },
  field: { type: String, required: true },
  dbColumn: { type: String, required: true },
  tableName: { type: String, required: true },
  type: { type: String, default: 'text' },
  rows: { type: Number, default: 3 },
  options: { type: Array, default: () => [] }
})

const emit = defineEmits(['save'])

const editing = ref(false)
const editValue = ref('')

const displayValue = ref(props.row[props.field])
const displayRef = displayValue

const startEdit = () => {
  editValue.value = props.row[props.field] || ''
  editing.value = true
}

const save = () => {
  emit('save', props.tableName, props.row.id, props.dbColumn, editValue.value, props.row, '_editing_inline', props.field)
  // Update local display
  displayValue.value = editValue.value
  editing.value = false
}
</script>
