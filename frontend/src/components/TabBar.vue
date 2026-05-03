<template>
  <div class="flex flex-wrap border-b bg-gray-50">
    <button
      v-for="tab in tabs" :key="tab.key"
      @click="$emit('update:activeTab', tab.key)"
      class="flex-1 min-w-0 py-3 lg:py-4 text-sm lg:text-lg font-medium transition-colors"
      :class="activeTab === tab.key ? tab.activeClass + ' bg-white border-b-2' : 'text-gray-500 hover:text-gray-700'"
    >
      {{ tab.label }}
    </button>
  </div>
</template>

<script setup>
defineProps({ activeTab: { type: String, default: 'MasterBank' } })
defineEmits(['update:activeTab'])

const tabs = [
  { key: 'JD', label: 'JD', activeClass: 'text-blue-600 border-blue-600' },
  { key: 'Interview', label: '面经', activeClass: 'text-gray-600 border-gray-600' },
  { key: 'MasterBank', label: '题库', activeClass: 'text-red-600 border-red-600 font-bold' },
  { key: 'MockInterview', label: '模拟', activeClass: 'text-orange-600 border-orange-600 font-bold' }
]
</script>
