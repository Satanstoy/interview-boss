import { ref, computed } from 'vue'

const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 480
const SIDEBAR_COLLAPSE_THRESHOLD = 120

export function useSidebar() {
  const sidebarCollapsed = ref(localStorage.getItem('sidebar-collapsed') === 'true')
  const sidebarWidth = ref(Number(localStorage.getItem('sidebar-width')) || 320)
  const isResizing = ref(false)
  const resizeHandleRef = ref(null)
  const expandBtnRef = ref(null)
  const sidebarWrapperRef = ref(null)

  const toggleSidebar = () => {
    sidebarCollapsed.value = !sidebarCollapsed.value
    localStorage.setItem('sidebar-collapsed', sidebarCollapsed.value)
  }

  function onResizeStart(e) {
    if (e.button !== 0) return
    e.preventDefault()
    isResizing.value = true
    const startX = e.clientX
    const startWidth = sidebarWidth.value
    const wasCollapsed = sidebarCollapsed.value

    const handle = resizeHandleRef.value
    if (handle) handle.setPointerCapture(e.pointerId)

    const wrapperEl = sidebarWrapperRef.value
    let rafId = null
    let finalWidth = startWidth
    let finalCollapsed = wasCollapsed

    function onMove(ev) {
      const delta = ev.clientX - startX
      if (wasCollapsed) {
        if (delta > 10) {
          finalCollapsed = false
          finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, delta))
        } else {
          return
        }
      } else {
        const newWidth = startWidth + delta
        if (newWidth < SIDEBAR_COLLAPSE_THRESHOLD) {
          finalCollapsed = true
          finalWidth = 0
        } else {
          finalCollapsed = false
          finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, newWidth))
        }
      }
      if (!rafId) {
        rafId = requestAnimationFrame(() => {
          rafId = null
          if (wrapperEl) wrapperEl.style.width = finalWidth + 'px'
          if (handle) handle.style.left = (finalWidth - 6) + 'px'
        })
      }
    }

    function onUp(ev) {
      isResizing.value = false
      if (rafId) { cancelAnimationFrame(rafId); rafId = null }
      if (handle) handle.releasePointerCapture(ev.pointerId)
      handle?.removeEventListener('pointermove', onMove)
      handle?.removeEventListener('pointerup', onUp)
      handle?.removeEventListener('pointercancel', onUp)
      sidebarCollapsed.value = finalCollapsed
      if (!finalCollapsed) {
        sidebarWidth.value = finalWidth
        localStorage.setItem('sidebar-width', finalWidth)
      }
      localStorage.setItem('sidebar-collapsed', finalCollapsed)
    }

    handle?.addEventListener('pointermove', onMove)
    handle?.addEventListener('pointerup', onUp)
    handle?.addEventListener('pointercancel', onUp)
  }

  function onExpandBtnDragStart(e) {
    if (e.button !== 0) return
    e.preventDefault()
    e.stopPropagation()
    isResizing.value = true
    const startX = e.clientX
    let dragged = false

    const btn = expandBtnRef.value
    if (btn) btn.setPointerCapture(e.pointerId)

    const wrapperEl = sidebarWrapperRef.value
    const handle = resizeHandleRef.value
    let rafId = null
    let finalWidth = 0

    function onMove(ev) {
      const delta = ev.clientX - startX
      if (delta > 10) {
        dragged = true
        finalWidth = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, delta))
        if (!rafId) {
          rafId = requestAnimationFrame(() => {
            rafId = null
            if (wrapperEl) wrapperEl.style.width = finalWidth + 'px'
            if (handle) handle.style.left = (finalWidth - 6) + 'px'
          })
        }
      }
    }

    function onUp(ev) {
      isResizing.value = false
      if (rafId) { cancelAnimationFrame(rafId); rafId = null }
      if (btn) btn.releasePointerCapture(ev.pointerId)
      btn?.removeEventListener('pointermove', onMove)
      btn?.removeEventListener('pointerup', onUp)
      btn?.removeEventListener('pointercancel', onUp)
      if (!dragged) {
        toggleSidebar()
      } else {
        sidebarCollapsed.value = false
        sidebarWidth.value = finalWidth
        localStorage.setItem('sidebar-width', finalWidth)
        localStorage.setItem('sidebar-collapsed', 'false')
      }
    }

    btn?.addEventListener('pointermove', onMove)
    btn?.addEventListener('pointerup', onUp)
    btn?.addEventListener('pointercancel', onUp)
  }

  const resizeHandleStyle = computed(() => {
    if (sidebarCollapsed.value) {
      return { left: '0px' }
    }
    return { left: (sidebarWidth.value - 6) + 'px' }
  })

  return {
    sidebarCollapsed,
    sidebarWidth,
    isResizing,
    resizeHandleRef,
    expandBtnRef,
    sidebarWrapperRef,
    resizeHandleStyle,
    toggleSidebar,
    onResizeStart,
    onExpandBtnDragStart,
  }
}
