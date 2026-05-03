import { ref, computed } from 'vue'

export function useSelection(getList) {
  const selectedIds = ref(new Set())

  const selectedCount = computed(() => selectedIds.value.size)

  const allSelected = computed(() => {
    const list = getList()
    return list.length > 0 && list.every(item => selectedIds.value.has(item.id))
  })

  const toggleSelectAll = () => {
    const list = getList()
    if (allSelected.value) {
      selectedIds.value.clear()
    } else {
      selectedIds.value = new Set(list.map(item => item.id))
    }
  }

  const invertSelection = () => {
    const list = getList()
    const newSet = new Set()
    list.forEach(item => {
      if (!selectedIds.value.has(item.id)) newSet.add(item.id)
    })
    selectedIds.value = newSet
  }

  const toggleItem = (id) => {
    if (selectedIds.value.has(id)) {
      selectedIds.value.delete(id)
    } else {
      selectedIds.value.add(id)
    }
    // trigger reactivity
    selectedIds.value = new Set(selectedIds.value)
  }

  const clearSelection = () => {
    selectedIds.value = new Set()
  }

  return { selectedIds, selectedCount, allSelected, toggleSelectAll, invertSelection, toggleItem, clearSelection }
}
