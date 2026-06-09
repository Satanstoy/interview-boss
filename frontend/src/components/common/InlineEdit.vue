<template>
  <div class="group">
    <!-- Display mode -->
    <div v-if="!editing" class="flex items-center gap-2">
      <span v-if="type === 'select'" class="px-2 py-1 rounded text-xs" :class="(displayValue || '').includes('难') ? 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400' : 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400'">
        {{ displayValue || '-' }}
      </span>
      <span v-else :class="{ 'whitespace-pre-wrap break-words flex-1': type === 'textarea' }">{{ displayValue }}</span>
      <Button variant="ghost" size="icon-xs" @click="startEdit" class="text-ink-400 hover:text-blue-500 dark:hover:text-blue-400 opacity-0 group-hover:opacity-100 transition shrink-0" title="编辑">
        <Pencil class="size-3.5" />
      </Button>
    </div>

    <!-- Edit mode -->
    <div v-else class="flex flex-col gap-1 w-full">
      <div class="flex items-center gap-1">
        <Input v-if="type === 'text'" v-model="editValue" @keyup.enter="save" />
        <Textarea v-else-if="type === 'textarea'" v-model="editValue" :rows="rows || 3" />
        <Select
          v-else-if="type === 'select'"
          :model-value="editValue"
          @update:model-value="editValue = $event"
        >
          <SelectTrigger class="flex-1 h-8 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="">未提供</SelectItem>
            <SelectItem v-for="opt in options" :key="opt" :value="opt">{{ opt }}</SelectItem>
          </SelectContent>
        </Select>
        <Input v-else v-model="editValue" @keyup.enter="save" />
        <div class="flex gap-1 shrink-0">
          <Button variant="ghost" size="sm" @click="save" class="text-green-500 hover:text-green-700 dark:text-green-400 dark:hover:text-green-300 transition-colors duration-200" title="保存">保存</Button>
          <Button variant="ghost" size="sm" @click="editing = false" class="text-red-400 hover:text-red-600 dark:text-red-400 dark:hover:text-red-300 transition-colors duration-200" title="取消">取消</Button>
        </div>
      </div>
      <p v-if="validationError" class="text-red-500 dark:text-red-400 text-xs mt-0.5">{{ validationError }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Pencil } from '@lucide/vue'
import { validateTextField } from '@/utils/validate.js'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

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

const displayValue = computed(() => props.row[props.field])

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
