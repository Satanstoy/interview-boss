import { nextTick, ref } from 'vue'
import { useToast } from '@/composables/useNotification.js'
import { upload } from '@/services/http.js'

export function useChatAttachments({ inputText, autoResize }) {
  const attachmentInput = ref(null)
  const attachmentLoading = ref(false)
  const { success: toastSuccess, error: toastError } = useToast()

  async function handleAttachmentChange(event) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return

    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
    if (!isPdf) {
      toastError('目前仅支持 PDF 附件')
      return
    }

    attachmentLoading.value = true
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await upload('/api/chat/extract-pdf', formData)
      const extractedText = String(response?.text || '').trim()
      if (!extractedText) throw new Error('PDF 中没有可读取的文本')

      const prefix = inputText.value.trim()
      inputText.value = `${prefix ? `${prefix}\n\n` : ''}[附件：${file.name}]\n${extractedText}`
      toastSuccess(`已读取 ${file.name}，发送前可以继续编辑`)
      await nextTick()
      autoResize()
    } catch (error) {
      toastError(error?.message || '附件读取失败，请重试')
    } finally {
      attachmentLoading.value = false
    }
  }

  return { attachmentInput, attachmentLoading, handleAttachmentChange }
}
