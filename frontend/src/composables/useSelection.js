import { ref, computed } from 'vue'

export function useSelection(getList, getFilteredList) {
  const selectedIds = ref(new Set())

  const selectedCount = computed(() => selectedIds.value.size)

  const allSelected = computed(() => {
    const list = getFilteredList ? getFilteredList() : getList()
    return list.length > 0 && list.every(item => selectedIds.value.has(item.id))
  })

  let _lastToggleTime = 0
  const toggleSelectAll = () => {
    // 防抖：300ms 内忽略重复点击
    const now = Date.now()
    if (now - _lastToggleTime < 300) return
    _lastToggleTime = now
    // 按当前筛选列表全选/取消，不影响筛选外的已选项
    const list = getFilteredList ? getFilteredList() : getList()
    if (allSelected.value) {
      // 取消当前筛选列表的选中
      const newSet = new Set(selectedIds.value)
      list.forEach(item => newSet.delete(item.id))
      selectedIds.value = newSet
    } else {
      // 选中当前筛选列表（保留已有的其他选中项）
      const newSet = new Set(selectedIds.value)
      list.forEach(item => newSet.add(item.id))
      selectedIds.value = newSet
    }
  }

  const invertSelection = () => {
    // 在当前筛选列表范围内反选
    const list = getFilteredList ? getFilteredList() : getList()
    const newSet = new Set(selectedIds.value)
    list.forEach(item => {
      if (newSet.has(item.id)) {
        newSet.delete(item.id)
      } else {
        newSet.add(item.id)
      }
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
