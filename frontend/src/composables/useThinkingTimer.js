import { ref } from 'vue'

export function useThinkingTimer() {
  const liveThinkingSeconds = ref(0)
  let thinkingTimer = null

  function startThinkingTimer() {
    stopThinkingTimer()
    liveThinkingSeconds.value = 0
    const startedAt = Date.now()
    thinkingTimer = window.setInterval(() => {
      liveThinkingSeconds.value = Math.max(1, Math.round((Date.now() - startedAt) / 1000))
    }, 250)
  }

  function stopThinkingTimer() {
    if (thinkingTimer) {
      window.clearInterval(thinkingTimer)
      thinkingTimer = null
    }
  }

  return { liveThinkingSeconds, startThinkingTimer, stopThinkingTimer }
}
