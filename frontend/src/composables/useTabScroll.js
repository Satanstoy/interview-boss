import { ref } from 'vue'

/**
 * 管理各 tab 的滚动位置，切换 tab 时保存/恢复 scrollTop。
 * singleton 模式 — 状态在组件间共享。
 */
const scrollPositions = ref(new Map())
let pendingRestore = null

export function useTabScroll() {
  const saveScroll = (tabKey, scrollTop) => {
    scrollPositions.value.set(tabKey, scrollTop)
    pendingRestore = tabKey
  }

  const restoreScroll = () => {
    if (!pendingRestore) return
    const saved = scrollPositions.value.get(pendingRestore)
    pendingRestore = null
    if (saved == null) return
    requestAnimationFrame(() => {
      const container = document.querySelector('.overflow-y-auto.custom-scrollbar')
      if (container) container.scrollTop = saved
    })
  }

  return { scrollPositions, saveScroll, restoreScroll }
}
