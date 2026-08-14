// 聊天流式/等待状态格式化（从 ChatView.vue 抽出）
// 接收调用方 refs，返回计算属性；不持自身状态。
import { computed } from 'vue'
import { waitingStepText } from '@/utils/chatFormat.js'

export function useChatFormat({ streamingContent, processingSteps, thinkingDuration, liveThinkingSeconds, renderSafeMarkdown }) {
  const renderStreamingContent = computed(() => {
    if (!streamingContent.value) return ''
    const cleaned = streamingContent.value
      .replace(/\[BASIS\][\s\S]*?\[\/BASIS\]/g, '')
      .replace(/\[BASIS\]\{[^}]*\}/g, '')
      .trim()
    return renderSafeMarkdown(cleaned || streamingContent.value)
  })

  const waitingText = computed(() => {
    if (processingSteps.value.length === 0) return '正在连接...'
    const lastStep = processingSteps.value[processingSteps.value.length - 1]
    if (!lastStep) return '正在思考...'
    return waitingStepText(lastStep.step) || lastStep.message || '思考中...'
  })

  const displayThinkingDuration = computed(() => {
    return thinkingDuration.value || liveThinkingSeconds.value
  })

  return { renderStreamingContent, waitingText, displayThinkingDuration }
}
