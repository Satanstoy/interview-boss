import { toast } from 'vue-sonner'
import { ref } from 'vue'

export function useToast() {
  const success = (msg, options) => toast.success(msg, options)
  const error = (msg, options) => toast.error(msg, { duration: 5000, ...options })
  const info = (msg, options) => toast.info(msg, options)
  const warning = (msg, options) => toast.warning(msg, { duration: 4000, ...options })
  return { success, error, info, warning }
}

let confirmResolve = null
let confirmHandled = false
const confirmState = ref({ show: false, message: '', title: '', variant: 'warning', confirmLabel: '确定', cancelLabel: '取消' })

export function useConfirm() {
  const confirm = (message, titleOrOptions = '确认操作') => {
    const opts = typeof titleOrOptions === 'string'
      ? { title: titleOrOptions }
      : titleOrOptions
    return new Promise((resolve) => {
      confirmResolve = resolve
      confirmHandled = false
      confirmState.value = {
        show: true,
        message,
        title: opts.title || '确认操作',
        variant: opts.variant || 'warning',
        confirmLabel: opts.confirmLabel || '确定',
        cancelLabel: opts.cancelLabel || '取消',
      }
    })
  }

  const handleConfirm = () => {
    confirmHandled = true
    confirmState.value.show = false
    if (confirmResolve) { confirmResolve(true); confirmResolve = null }
  }

  const handleCancel = () => {
    confirmState.value.show = false
    if (!confirmHandled && confirmResolve) { confirmResolve(false); confirmResolve = null }
  }

  return { confirmState, confirm, handleConfirm, handleCancel }
}
