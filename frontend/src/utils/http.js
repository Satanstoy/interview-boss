/**
 * 统一 HTTP 请求封装
 * - 超时控制（默认 10s，文件上传 60s）
 * - 自动重试（网络错误重试 2 次，间隔 1s/3s）
 * - 请求取消（组件卸载自动取消）
 * - 统一错误拦截（401/403/500/502/503/504）
 * - JWT 认证（自动附加 Authorization header）
 * - Token 自动刷新（401 时尝试用 refresh token 续期）
 */

const DEFAULT_TIMEOUT = 10_000
const UPLOAD_TIMEOUT = 60_000
const MAX_RETRIES = 2
const RETRY_DELAYS = [1000, 3000]

// 全局 AbortController 管理，用于组件卸载时批量取消
const pendingControllers = new Set()

// ── Access Token 内存存储（比 localStorage 更安全，XSS 无法直接读取）──
let _accessToken = ''

/**
 * 设置 access token（登录成功后由前端调用）
 */
export function setAuthToken(token) {
  _accessToken = token || ''
}

/**
 * 获取当前 access token
 */
export function getAuthToken() {
  return _accessToken
}

/**
 * 手动触发 token 刷新（供 App.vue 初始化时调用）
 * @returns {Promise<{token, user} | null>}
 */
export const refreshAuthToken = tryRefreshToken

// 401 回调（由 App.vue 注册，用于弹出登录框）
let onUnauthorized = null
export function setUnauthorizedHandler(fn) { onUnauthorized = fn }

// ── Token 自动刷新逻辑 ──
let _refreshPromise = null

async function tryRefreshToken() {
  // 合并并发的 refresh 请求
  if (_refreshPromise) return _refreshPromise

  _refreshPromise = (async () => {
    try {
      // 使用原生 fetch 避免递归调用 request()
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include', // 关键：发送 HttpOnly refresh cookie
      })
      if (!res.ok) return null
      const data = await res.json()
      if (data.token) {
        _accessToken = data.token
        return data // 返回 { token, user }
      }
      return null
    } catch {
      return null
    }
  })()

  const result = await _refreshPromise
  _refreshPromise = null
  return result
}

/**
 * 创建带超时的 AbortController
 */
function createTimeoutController(timeout) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  pendingControllers.add(controller)
  return { controller, timer }
}

function cleanup(controller, timer) {
  clearTimeout(timer)
  pendingControllers.delete(controller)
}

/**
 * 判断是否为可重试的网络错误
 */
function isRetryableError(err) {
  if (err.name === 'AbortError') return false
  return err instanceof TypeError || err.message?.includes('Failed to fetch')
}

/**
 * 判断 HTTP 状态码是否可重试（5xx 服务端错误）
 */
function isRetryableStatus(status) {
  return [500, 502, 503, 504].includes(status)
}

/**
 * 统一错误消息映射
 */
function getStatusMessage(status) {
  const map = {
    401: '未授权，请重新登录',
    403: '权限不足',
    404: '请求的资源不存在',
    409: '数据冲突（可能重复录入）',
    422: '请求参数有误',
    429: '请求过于频繁，请稍后重试',
    500: '服务器内部错误',
    502: '服务暂时不可用',
    503: '服务维护中，请稍后重试',
    504: '服务响应超时',
  }
  return map[status] || `请求失败 (${status})`
}

/**
 * 核心请求函数
 * @param {string} url - 请求地址
 * @param {object} options - fetch 选项 + 自定义选项
 * @param {number} options.timeout - 超时时间（ms）
 * @param {number} options.retries - 重试次数
 * @param {boolean} options.noRetry - 禁用重试
 * @param {boolean} options._isRetry - 内部标记：这是一次 401 重试
 * @returns {Promise<any>} - 解析后的 JSON 数据
 */
async function request(url, options = {}) {
  const {
    timeout = DEFAULT_TIMEOUT,
    retries = MAX_RETRIES,
    noRetry = false,
    _isRetry = false,
    ...fetchOptions
  } = options

  let lastError = null

  for (let attempt = 0; attempt <= (noRetry ? 0 : retries); attempt++) {
    const { controller, timer } = createTimeoutController(timeout)

    try {
      // 自动附加 Authorization header
      const authHeaders = {}
      const token = getAuthToken()
      if (token) authHeaders['Authorization'] = `Bearer ${token}`

      const mergedHeaders = { ...authHeaders, ...(fetchOptions.headers || {}) }

      const res = await fetch(url, {
        ...fetchOptions,
        headers: mergedHeaders,
        signal: controller.signal,
        credentials: 'same-origin',
      })

      cleanup(controller, timer)

      // 401 → 尝试自动刷新 token（只尝试一次，避免无限循环）
      if (res.status === 401 && !_isRetry && url !== '/api/auth/refresh' && url !== '/api/auth/login' && url !== '/api/auth/register') {
        const refreshResult = await tryRefreshToken()
        if (refreshResult) {
          // 刷新成功，用新 token 重试原始请求（仅一次）
          return request(url, { ...options, _isRetry: true })
        }
        // 刷新失败 → 触发登录弹窗
        if (onUnauthorized) onUnauthorized()
      }

      // 解析响应
      let data
      const contentType = res.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        data = await res.json()
      } else {
        const text = await res.text()
        try {
          data = JSON.parse(text)
        } catch {
          data = text
        }
      }

      // HTTP 状态码错误处理
      if (!res.ok) {
        const message = (typeof data === 'object' && data?.detail)
          ? (typeof data.detail === 'object' ? JSON.stringify(data.detail) : data.detail)
          : getStatusMessage(res.status)

        // 5xx 可重试
        if (isRetryableStatus(res.status) && attempt < retries) {
          lastError = new Error(message)
          lastError.status = res.status
          await delay(RETRY_DELAYS[attempt] || RETRY_DELAYS[RETRY_DELAYS.length - 1])
          continue
        }

        const err = new Error(message)
        err.status = res.status
        err.data = data
        throw err
      }

      return data
    } catch (err) {
      cleanup(controller, timer)

      // 超时错误
      if (err.name === 'AbortError') {
        if (attempt < retries && !noRetry) {
          lastError = new Error('请求超时')
          await delay(RETRY_DELAYS[attempt] || RETRY_DELAYS[RETRY_DELAYS.length - 1])
          continue
        }
        throw new Error('请求超时，请检查网络连接')
      }

      // 已处理的 HTTP 错误直接抛出
      if (err.status) throw err

      // 网络错误可重试
      if (isRetryableError(err) && attempt < retries) {
        lastError = err
        await delay(RETRY_DELAYS[attempt] || RETRY_DELAYS[RETRY_DELAYS.length - 1])
        continue
      }

      throw new Error(err.message || '网络请求失败')
    }
  }

  throw lastError || new Error('请求失败')
}

function delay(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 取消所有进行中的请求（组件卸载时调用）
 */
export function cancelAllRequests() {
  pendingControllers.forEach(controller => {
    try { controller.abort() } catch { /* ignore */ }
  })
  pendingControllers.clear()
}

/**
 * GET 请求
 */
export function get(url, options = {}) {
  return request(url, { ...options, method: 'GET' })
}

/**
 * POST 请求（JSON body）
 */
export function post(url, body, options = {}) {
  return request(url, {
    ...options,
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(body),
  })
}

/**
 * PUT 请求（JSON body）
 */
export function put(url, body, options = {}) {
  return request(url, {
    ...options,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(body),
  })
}

/**
 * DELETE 请求
 */
export function del(url, options = {}) {
  return request(url, { ...options, method: 'DELETE' })
}

/**
 * 文件上传（FormData，60s 超时，不自动重试）
 */
export function upload(url, formData, options = {}) {
  return request(url, {
    ...options,
    method: 'POST',
    body: formData,
    timeout: options.timeout || UPLOAD_TIMEOUT,
    noRetry: true,
  })
}

/**
 * POST 请求，返回 SSE 流式响应
 */
export async function postSSE(url, body, onEvent) {
  const controller = new AbortController()
  pendingControllers.add(controller)

  try {
    const authHeaders = {}
    const token = getAuthToken()
    if (token) authHeaders['Authorization'] = `Bearer ${token}`

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(body),
      signal: controller.signal,
      credentials: 'same-origin',
    })

    if (!res.ok) {
      const text = await res.text()
      throw new Error(`HTTP ${res.status}: ${text}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let finalResult = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop()

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data: ')) continue
        try {
          const data = JSON.parse(trimmed.slice(6))
          if (onEvent) onEvent(data)
          if (data.type === 'done') finalResult = data
        } catch { /* 忽略解析错误 */ }
      }
    }

    if (buffer.trim().startsWith('data: ')) {
      try {
        const data = JSON.parse(buffer.trim().slice(6))
        if (onEvent) onEvent(data)
        if (data.type === 'done') finalResult = data
      } catch { /* ignore */ }
    }

    return finalResult
  } finally {
    pendingControllers.delete(controller)
  }
}

/**
 * 带 cookie 的 fetch（用于 logout 等需要 HttpOnly cookie 的操作）
 */
export async function fetchWithCredentials(url, options = {}) {
  const token = getAuthToken()
  const authHeaders = {}
  if (token) authHeaders['Authorization'] = `Bearer ${token}`
  return fetch(url, {
    ...options,
    credentials: 'include',
    headers: { ...authHeaders, ...(options.headers || {}) },
  })
}

export default { get, post, put, del, upload, cancelAllRequests }
