import { get, post, put, del, fetchWithCredentials } from './http.js'

const API = '/api'

// ── Auth ──
export const authRegister = (username, password, email) => post(`${API}/auth/register`, { username, password, email })
export const authLogin = (username, password, remember_me = false) => post(`${API}/auth/login`, { username, password, remember_me })
export const authMe = () => get(`${API}/auth/me`)
export const authUpdateBankMode = (bank_mode) => put(`${API}/auth/bank-mode`, { bank_mode })
export const authRefresh = () => post(`${API}/auth/refresh`, null)
export const authLogout = async () => {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetchWithCredentials(`${API}/auth/logout`, {
      method: 'POST',
      signal: controller.signal,
    })
    return response.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

export const resetPassword = (email, code, newPassword) => post(`${API}/auth/reset-password`, { email, code, new_password: newPassword })
export const changePassword = (currentPassword, newPassword) => post(`${API}/auth/change-password`, { current_password: currentPassword, new_password: newPassword })

// ── Email Auth ──
export const sendVerifyCode = (email, purpose) => post(`${API}/auth/send-code`, { email, purpose })
export const authRegisterWithEmail = (email, code, username, password) => post(`${API}/auth/register-with-email`, { email, code, username, password })
export const authLoginWithEmail = (email, code) => post(`${API}/auth/login-with-email`, { email, code })

// ── Email Binding ──
export const getMyEmail = () => get(`${API}/profile/email`)
export const sendBindCode = (email) => post(`${API}/profile/send-bind-code`, { email })
export const bindEmail = (email, code) => post(`${API}/profile/bind-email`, { email, code })
export const bindEmailWithToken = (email, code, tempToken) => post(`${API}/auth/bind-email-with-token`, { email, code }, { headers: { Authorization: `Bearer ${tempToken}` } })
