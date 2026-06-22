/**
 * useAuth — 认证状态管理（单例模式）
 *
 * 职责：currentUser、登录/登出/刷新token、未授权拦截、待审核数量
 * 不负责：数据获取（由调用方通过回调注入）
 *
 * 单例：模块级 ref 保证 router guard 和组件拿到同一个 currentUser
 */
import { ref } from 'vue'
import { setAuthToken, refreshAuthToken, setUnauthorizedHandler, invalidateCache } from '@/services/http.js'
import * as api from '@/api/index.js'
import { authLogout } from '@/api/index.js'

// ── 模块级状态（单例） ──
export const currentUser = ref(null)
export const authCompleted = ref(false)
const showLoginModal = ref(false)
const pendingReviewCount = ref(0)

// ── 回调占位（由 initAuthSingleton 注入） ──
let _onReady = null
let _onDataRefresh = null

// ── 内部：加载待审核数量（仅 admin） ──
const loadPendingCount = async () => {
  if (!currentUser.value?.is_admin) { pendingReviewCount.value = 0; return }
  try { const data = await api.fetchPendingQuestions(); pendingReviewCount.value = data.total || 0 }
  catch { pendingReviewCount.value = 0 }
}

// ── Token 刷新 / 自动登录 ──
const initAuth = async () => {
  const refreshResult = await refreshAuthToken()
  if (refreshResult?.token && refreshResult?.user) {
    setAuthToken(refreshResult.token)
    currentUser.value = refreshResult.user
    loadPendingCount()
  }
  // 标记认证流程完成（无论成功与否）
  authCompleted.value = true
}

// ── 登录成功 ──
const handleLoginSuccess = (user) => {
  currentUser.value = user
  _onReady?.()
  loadPendingCount()
}

// ── 登出 ──
const handleLogout = async () => {
  try {
    await authLogout()
  } finally {
    showLoginModal.value = false
    setAuthToken('')
    currentUser.value = null
    _onDataRefresh?.()
    pendingReviewCount.value = 0
  }
}

// ── 切换题库模式（公共/个人） ──
const handleBankModeChanged = (user) => {
  currentUser.value = user
  invalidateCache('master-bank')
  _onDataRefresh?.()
}

// ── 401 拦截：弹出登录框 ──
setUnauthorizedHandler(() => { showLoginModal.value = true })

/**
 * 初始化单例回调（在 layout 中调用一次）
 * 路由守卫直接 import { currentUser } 即可
 */
export function initAuthSingleton({ onReady, onDataRefresh } = {}) {
  _onReady = onReady || null
  _onDataRefresh = onDataRefresh || null
}

export function useAuth() {
  return {
    currentUser,
    authCompleted,
    showLoginModal,
    pendingReviewCount,
    initAuth,
    handleLoginSuccess,
    handleLogout,
    handleBankModeChanged,
    loadPendingCount,
  }
}
