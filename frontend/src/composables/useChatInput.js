// 聊天输入框行为（从 ChatView.vue 抽出）
import { nextTick } from 'vue'

export function useChatInput({ inputRef, onSend } = {}) {
  function autoResize() {
    const el = inputRef?.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }

  function resetInputHeight() {
    nextTick(() => {
      if (inputRef?.value) inputRef.value.style.height = '32px'
    })
  }

  function onInputKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend?.()
    }
  }

  return { autoResize, resetInputHeight, onInputKeydown }
}
