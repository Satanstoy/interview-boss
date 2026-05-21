import { ref, watch, nextTick } from 'vue'

export function useHighlightNav(activeTab, showPracticeMode) {
  const highlightInterviewId = ref(null)
  const returnTab = ref(null)
  const returnToPracticeMode = ref(false)
  const floatingReturnBtn = ref(null)
  const floatingBtnStyle = ref({ display: 'none' })
  const masterBankEverShown = ref(false)

  let highlightScrollHandler = null
  let highlightAnimFrame = null
  let highlightRetryId = null
  let savedScrollTop = null

  watch(activeTab, (tab) => { if (tab === 'MasterBank') masterBankEverShown.value = true }, { immediate: true })

  const restoreOuterScroll = () => {
    if (savedScrollTop == null) return
    const container = document.querySelector('.overflow-y-auto.custom-scrollbar')
    if (container) {
      container.scrollTop = savedScrollTop
      savedScrollTop = null
    }
  }

  const findScrollContainer = (el) => {
    let cur = el?.parentElement
    while (cur) {
      if (cur.classList.contains('custom-scrollbar') && cur.scrollHeight > cur.clientHeight + 10) return cur
      cur = cur.parentElement
    }
    return null
  }

  const getOffsetTopRelativeTo = (el, ancestor) => {
    let top = 0
    let cur = el
    while (cur && cur !== ancestor) {
      top += cur.offsetTop
      cur = cur.offsetParent
    }
    return top
  }

  const positionFloatingBtn = () => {
    const id = highlightInterviewId.value
    if (!id) return false
    const row = document.querySelector(`[data-row-id="${id}"]`)
    if (!row) return false
    const container = findScrollContainer(row)
    if (!container) return false
    const rowRect = row.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    floatingBtnStyle.value = {
      top: Math.max(4, rowRect.top - containerRect.top + container.scrollTop - 4) + 'px',
      left: Math.max(8, rowRect.left - containerRect.left + 8) + 'px',
    }
    return true
  }

  const attachHighlightScroll = () => {
    detachHighlightScroll()
    const id = highlightInterviewId.value
    if (!id) return
    const row = document.querySelector(`[data-row-id="${id}"]`)
    const container = findScrollContainer(row)
    if (!container) return
    highlightScrollHandler = () => {
      if (highlightAnimFrame) return
      highlightAnimFrame = requestAnimationFrame(() => {
        highlightAnimFrame = null
        positionFloatingBtn()
      })
    }
    container.addEventListener('scroll', highlightScrollHandler, { passive: true })
  }

  const detachHighlightScroll = () => {
    if (highlightAnimFrame) { cancelAnimationFrame(highlightAnimFrame); highlightAnimFrame = null }
    if (highlightRetryId) { clearTimeout(highlightRetryId); highlightRetryId = null }
    if (highlightScrollHandler) {
      document.querySelectorAll('.custom-scrollbar').forEach(el => el.removeEventListener('scroll', highlightScrollHandler))
      highlightScrollHandler = null
    }
  }

  const waitForHighlightRow = (attempt = 0) => {
    if (!highlightInterviewId.value) return
    if (positionFloatingBtn()) {
      attachHighlightScroll()
      return
    }
    if (attempt >= 40) {
      floatingBtnStyle.value = { top: '4px', left: '8px' }
      return
    }
    highlightRetryId = setTimeout(() => waitForHighlightRow(attempt + 1), 100)
  }

  watch(highlightInterviewId, async (id) => {
    if (id) {
      await nextTick()
      waitForHighlightRow()
      setTimeout(() => {
        detachHighlightScroll()
        highlightInterviewId.value = null
        floatingBtnStyle.value = { display: 'none' }
      }, 300000)
    } else {
      detachHighlightScroll()
      floatingBtnStyle.value = { display: 'none' }
    }
  })

  const handleReturn = async () => {
    floatingBtnStyle.value = { display: 'none' }
    const target = returnTab.value
    const practice = returnToPracticeMode.value
    returnTab.value = null
    returnToPracticeMode.value = false
    highlightInterviewId.value = null

    activeTab.value = target
    if (practice) showPracticeMode.value = true

    await nextTick()
    restoreOuterScroll()
  }

  return {
    highlightInterviewId,
    returnTab,
    returnToPracticeMode,
    floatingReturnBtn,
    floatingBtnStyle,
    masterBankEverShown,
    handleReturn,
    detachHighlightScroll,
    // Expose savedScrollTop setter for onNavigateToInterview
    setSavedScrollTop: (val) => { savedScrollTop = val },
  }
}
