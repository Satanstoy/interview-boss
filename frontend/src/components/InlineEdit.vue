<template>
  <div class="group">
    <!-- Display mode -->
    <div v-if="!editing" class="flex items-center gap-2">
      <span v-if="type === 'select'" class="px-2 py-1 rounded text-xs" :class="(displayValue || '').includes('难') ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'">
        {{ displayValue || '-' }}
      </span>
      <span v-else :class="{ 'whitespace-pre-wrap break-words flex-1': type === 'textarea' }">{{ displayValue }}</span>
      <button @click="startEdit" class="text-gray-400 hover:text-blue-500 opacity-0 group-hover:opacity-100 transition shrink-0 text-xs" title="编辑">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
      </button>
    </div>

    <!-- Edit mode -->
    <div v-else class="flex flex-col gap-1 w-full">
      <div class="flex items-center gap-1">
        <input v-if="type === 'text'" v-model="editValue" class="border rounded px-2 py-1 w-full text-sm" @keyup.enter="save" />
        <textarea v-else-if="type === 'textarea'" v-model="editValue" :rows="rows || 3" class="border rounded px-2 py-1 w-full text-sm"></textarea>
        <select v-else-if="type === 'select'" v-model="editValue" class="border rounded px-2 py-1 text-sm">
          <option value="">未提供</option>
          <option v-for="opt in options" :key="opt" :value="opt">{{ opt }}</option>
        </select>
        <input v-else v-model="editValue" class="border rounded px-2 py-1 w-full text-sm" @keyup.enter="save" />
        <div class="flex gap-1 shrink-0">
          <button @click="save" class="text-green-500 hover:text-green-700 text-sm font-medium" title="保存">保存</button>
          <button @click="editing = false" class="text-red-400 hover:text-red-600 text-sm" title="取消">取消</button>
        </div>
      </div>
      <p v-if="validationError" class="text-red-500 text-xs mt-0.5">{{ validationError }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { validateTextField } from '../utils/validate.js'

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
const validationError = ref('')

const displayValue = ref(props.row[props.field])
const displayRef = displayValue

const startEdit = () => {
  editValue.value = props.row[props.field] || ''
  validationError.value = ''
  editing.value = true
}

const save = () => {
  const result = validateTextField(editValue.value, props.field)
  if (!result.valid) {
    validationError.value = result.error
    return
  }
  validationError.value = ''
  emit('save', props.tableName, props.row.id, props.dbColumn, result.value, props.row, '_editing_inline', props.field)
  editing.value = false
}
</script>
