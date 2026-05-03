import { ref } from 'vue'

const toasts = ref([])
let toastId = 0

let confirmResolve = null
const confirmState = ref({ show: false, message: '', title: '' })

export function useToast() {
  const addToast = (message, type = 'info', duration = 3000) => {
    const id = ++toastId
    toasts.value.push({ id, message, type })
    while (toasts.value.length > 5) toasts.value.shift()
    if (duration > 0) {
      setTimeout(() => removeToast(id), duration)
    }
    return id
  }

  const removeToast = (id) => {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) toasts.value.splice(idx, 1)
  }

  const success = (msg, duration) => addToast(msg, 'success', duration)
  const error = (msg, duration) => addToast(msg, 'error', duration || 8000)
  const info = (msg, duration) => addToast(msg, 'info', duration)
  const warning = (msg, duration) => addToast(msg, 'warning', duration || 4000)

  return { toasts, addToast, removeToast, success, error, info, warning }
}

export function useConfirm() {
  const confirm = (message, title = '确认操作') => {
    return new Promise((resolve) => {
      confirmResolve = resolve
      confirmState.value = { show: true, message, title }
    })
  }

  const handleConfirm = () => {
    confirmState.value.show = false
    if (confirmResolve) { confirmResolve(true); confirmResolve = null }
  }

  const handleCancel = () => {
    confirmState.value.show = false
    if (confirmResolve) { confirmResolve(false); confirmResolve = null }
  }

  return { confirmState, confirm, handleConfirm, handleCancel }
}
