/**
 * useAuth — 认证状态管理
 *
 * 职责：currentUser、登录/登出/刷新token、未授权拦截、待审核数量
 * 不负责：数据获取（由调用方通过回调注入）
 */
import { ref } from 'vue'
import { setAuthToken, refreshAuthToken, setUnauthorizedHandler, invalidateCache } from '@/services/http.js'
import * as api from '@/api/index.js'

export function useAuth({ onReady, onDataRefresh } = {}) {
  const currentUser = ref(null)
  const showLoginModal = ref(false)
  const pendingReviewCount = ref(0)

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
      onReady?.()
      loadPendingCount()
    }
  }

  // ── 登录成功 ──
  const handleLoginSuccess = (user) => {
    currentUser.value = user
    onReady?.()
    loadPendingCount()
  }

  // ── 登出 ──
  const handleLogout = () => {
    setAuthToken('')
    currentUser.value = null
    onDataRefresh?.()
    pendingReviewCount.value = 0
  }

  // ── 切换题库模式（公共/个人） ──
  const handleBankModeChanged = (user) => {
    currentUser.value = user
    invalidateCache('master-bank')
    onDataRefresh?.()
  }

  // ── 401 拦截：弹出登录框 ──
  setUnauthorizedHandler(() => { showLoginModal.value = true })

  return {
    currentUser,
    showLoginModal,
    pendingReviewCount,
    initAuth,
    handleLoginSuccess,
    handleLogout,
    handleBankModeChanged,
    loadPendingCount,
  }
}
