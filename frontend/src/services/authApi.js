import { get, post, put, del, fetchWithCredentials } from './http.js'

const API = '/api'

// ── Auth ──
export const authRegister = (username, password) => post(`${API}/auth/register`, { username, password })
export const authLogin = (username, password, remember_me = false) => post(`${API}/auth/login`, { username, password, remember_me })
export const authMe = () => get(`${API}/auth/me`)
export const authUpdateBankMode = (bank_mode) => put(`${API}/auth/bank-mode`, { bank_mode })
export const authRefresh = () => post(`${API}/auth/refresh`, null)
export const authLogout = async () => {
  try {
    await fetchWithCredentials(`${API}/auth/logout`, { method: 'POST' })
  } catch { /* 忽略网络错误，前端仍会清除本地状态 */ }
}

// ── Email Auth ──
export const sendVerifyCode = (email, purpose) => post(`${API}/auth/send-code`, { email, purpose })
export const authRegisterWithEmail = (email, code, username, password) => post(`${API}/auth/register-with-email`, { email, code, username, password })
export const authLoginWithEmail = (email, code) => post(`${API}/auth/login-with-email`, { email, code })

// ── Email Binding ──
export const getMyEmail = () => get(`${API}/profile/email`)
export const sendBindCode = (email) => post(`${API}/profile/send-bind-code`, { email })
export const bindEmail = (email, code) => post(`${API}/profile/bind-email`, { email, code })
