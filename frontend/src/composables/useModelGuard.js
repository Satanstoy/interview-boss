/**
 * useModelGuard — AI 模型可用性预检守卫（模块级单例）
 *
 * 职责：所有需要 LLM 模型的入口在点击后、请求前先校验模型是否就绪；
 * 未配置 / 未接通时弹全局 Dialog 提醒并引导到设置页 AI 配置区。
 * 不负责：模型配置的保存（SettingsAIConfig）
 */
import { ref } from 'vue'
import router from '@/router/index.js'
import { fetchLLMStatus } from '@/services/profileApi.js'

const CACHE_TTL = 60_000

const statusCache = ref(null) // { configured, connected, error, model, fetchedAt }
const testing = ref(false)

let dialogResolve = null
const dialogState = ref({ show: false, title: '', message: '' })

function isPreviewRoute() {
  return router.currentRoute.value.query.preview === '1'
}

async function loadStatus({ force = false } = {}) {
  const now = Date.now()
  if (!force && statusCache.value && now - statusCache.value.fetchedAt < CACHE_TTL) {
    return statusCache.value
  }
  try {
    const data = await fetchLLMStatus({ probe: force })
    statusCache.value = { ...data, fetchedAt: Date.now() }
  } catch (e) {
    statusCache.value = {
      configured: true,
      connected: false,
      error: `无法获取模型状态：${e.message}`,
      model: null,
      fetchedAt: Date.now(),
    }
  }
  return statusCache.value
}

function openDialog(title, message) {
  dialogState.value = { show: true, title, message }
  return new Promise((resolve) => {
    dialogResolve = resolve
  })
}

export function useModelGuard() {
  /**
   * 确保模型可用。返回 true 表示可继续执行；false 表示用户已被引导去配置，应中止操作。
   */
  const ensureModelReady = async ({ action = '' } = {}) => {
    if (isPreviewRoute()) return true
    const status = await loadStatus()
    if (status.configured && status.connected) return true

    const prefix = action ? `「${action}」` : '当前操作'
    if (status.configured) {
      await openDialog(
        '模型服务未接通',
        `${prefix}需要使用 AI 模型，但当前配置的模型暂时无法连接：\n${status.error || '未知错误'}\n\n请检查模型配置后重试。`,
      )
    } else {
      await openDialog(
        '尚未配置 AI 模型',
        `${prefix}需要使用 AI 模型，请先配置模型参数（API Key / Base URL / 模型名称）。`,
      )
    }
    return false
  }

  /** 设置页保存/清除模型配置后调用，使缓存立即失效 */
  const invalidateModelStatus = () => {
    statusCache.value = null
  }

  /** 设置页「测试连接」：强制重新探测 */
  const testModelConnection = async () => {
    testing.value = true
    try {
      return await loadStatus({ force: true })
    } finally {
      testing.value = false
    }
  }

  const handleDialogClose = () => {
    dialogState.value.show = false
    if (dialogResolve) {
      dialogResolve(false)
      dialogResolve = null
    }
  }

  const handleGoSettings = () => {
    dialogState.value.show = false
    if (dialogResolve) {
      dialogResolve(false)
      dialogResolve = null
    }
    router.push({ name: 'settings', query: { section: 'ai' } })
  }

  return {
    dialogState,
    testing,
    ensureModelReady,
    invalidateModelStatus,
    testModelConnection,
    handleDialogClose,
    handleGoSettings,
  }
}
