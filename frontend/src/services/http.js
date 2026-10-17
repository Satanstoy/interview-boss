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

// Simple TTL cache for GET requests
const _cache = new Map()
const DEFAULT_CACHE_TTL = 30000 // 30 seconds

function getCached(key, ttl = DEFAULT_CACHE_TTL) {
  const entry = _cache.get(key)
  if (entry && Date.now() - entry.ts < ttl) return entry.data
  return null
}

function setCache(key, data) {
  _cache.set(key, { data, ts: Date.now() })
  // Limit cache size
  if (_cache.size > 100) {
    const oldest = _cache.keys().next().value
    _cache.delete(oldest)
  }
}

export function invalidateCache(pattern) {
  if (!pattern) { _cache.clear(); return }
  for (const key of _cache.keys()) {
    if (key.includes(pattern)) _cache.delete(key)
  }
}

// ── Access Token 内存存储（比 localStorage 更安全，XSS 无法直接读取）──
let _accessToken = ''
let _authGeneration = 0

/**
 * 设置 access token（登录成功后由前端调用）
 */
export function setAuthToken(token) {
  const nextToken = token || ''
  if (nextToken === _accessToken) return
  _accessToken = nextToken
  _authGeneration++
  invalidateCache()
}

export function getAuthGeneration() {
  return _authGeneration
}

export function assertAuthGeneration(generation) {
  if (generation === _authGeneration) return
  const error = new Error('登录身份已变化，请重新请求')
  error.code = 'AUTH_CONTEXT_CHANGED'
  throw error
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
  const generation = _authGeneration
  if (_refreshPromise?.generation === generation) return _refreshPromise.promise

  const promise = (async () => {
    try {
      // 使用原生 fetch 避免递归调用 request()
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        credentials: 'include', // 关键：发送 HttpOnly refresh cookie
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
      if (!res.ok) return null
      const data = await res.json()
      if (generation !== _authGeneration) return null
      if (data.token) {
        // Refresh renews the token within the guarded login context.
        _accessToken = data.token
        invalidateCache()
        return data // 返回 { token, user }
      }
      return null
    } catch {
      return null
    }
  })()
  const refresh = { generation, promise }
  _refreshPromise = refresh
  try {
    return await promise
  } finally {
    if (_refreshPromise === refresh) _refreshPromise = null
  }
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
    400: '请求格式有误，请检查输入',
    401: '未授权，请重新登录',
    403: '权限不足',
    404: '请求的资源不存在',
    408: '请求超时，请稍后重试',
    409: '数据冲突（可能重复录入）',
    413: '上传内容过大，请压缩后重试',
    415: '不支持的文件格式',
    422: '请求参数有误',
    423: '账号已锁定，请稍后重试或联系管理员',
    429: '请求过于频繁，请稍后重试',
    500: '服务器内部错误',
    502: '服务暂时不可用',
    503: '服务维护中，请稍后重试',
    504: '服务响应超时',
  }
  return map[status] || '操作失败，请稍后重试'
}

/**
 * 友好错误消息提取
 */
export function getFriendlyError(err, fallback = '操作失败，请稍后重试') {
  if (!err) return fallback
  if (err.status && !err.message) return getStatusMessage(err.status)
  if (err.message?.includes('Failed to fetch')) return '网络连接失败，请检查网络'
  if (err.message?.includes('超时') || err.message?.includes('timeout')) return '请求超时，请稍后重试'
  return err.message || fallback
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
  const generation = _authGeneration
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
      assertAuthGeneration(generation)
      // 自动附加 Authorization header
      const authHeaders = { 'X-Requested-With': 'XMLHttpRequest' }
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
      assertAuthGeneration(generation)

      // 401 → 尝试自动刷新 token（只尝试一次，避免无限循环）
      if (res.status === 401 && !_isRetry && url !== '/api/auth/refresh' && url !== '/api/auth/login' && url !== '/api/auth/register') {
        const refreshResult = await tryRefreshToken()
        assertAuthGeneration(generation)
        if (refreshResult) {
          // 刷新成功，用新 token 重试原始请求（仅一次）
          return request(url, { ...options, _isRetry: true })
        }
        assertAuthGeneration(generation)
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

      assertAuthGeneration(generation)

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
      if (err.status || err.code === 'AUTH_CONTEXT_CHANGED') throw err

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
export async function get(url, options = {}) {
  const { ttl, noCache, ...fetchOptions } = options
  const generation = _authGeneration
  const cacheKey = `${generation}:${url}`

  // Check cache unless bypassed
  if (!noCache && ttl !== 0) {
    const cached = getCached(cacheKey, ttl)
    if (cached) return cached
  }

  const data = await request(url, { ...fetchOptions, method: 'GET' })

  // Cache successful response
  if (ttl !== 0 && generation === _authGeneration) setCache(cacheKey, data)
  return data
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
 * 文件上传（FormData，60s 超时，不自动重试，支持进度回调）
 */
export function upload(url, formData, options = {}) {
  const { onProgress, ...restOptions } = options
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', url)

    const token = getAuthToken()
    const headers = {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-Requested-With': 'XMLHttpRequest',
      ...(restOptions.headers || {}),
    }
    for (const [name, value] of Object.entries(headers)) {
      if (value != null) xhr.setRequestHeader(name, String(value))
    }

    xhr.timeout = restOptions.timeout || UPLOAD_TIMEOUT

    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          onProgress({ loaded: e.loaded, total: e.total, percent: Math.round(e.loaded / e.total * 100) })
        }
      }
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)) } catch { resolve(xhr.responseText) }
      } else {
        try {
          const data = JSON.parse(xhr.responseText)
          const detail = data.detail
          const error = new Error(typeof detail === 'object'
            ? (detail.message || detail.code || getStatusMessage(xhr.status))
            : (detail || getStatusMessage(xhr.status)))
          error.status = xhr.status
          error.code = typeof detail === 'object' ? detail.code : undefined
          error.data = data
          reject(error)
        } catch {
          const error = new Error(getStatusMessage(xhr.status))
          error.status = xhr.status
          reject(error)
        }
      }
    }

    xhr.onerror = () => reject(new Error('网络请求失败'))
    xhr.ontimeout = () => reject(new Error('请求超时'))
    xhr.send(formData)
  })
}

/**
 * 共享 SSE 流读取函数（消除 postSSE/uploadSSE/getSSE 中的重复代码）
 */
async function _consumeSSEStream(reader, onEvent, yieldForRender = false) {
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
        if (data.type === 'error') {
          const error = new Error(data.message || data.detail || '操作失败')
          error.code = data.code
          throw error
        }
        if (yieldForRender) await new Promise(r => setTimeout(r, 0))
      } catch (e) {
        if (e.message && !e.message.includes('JSON')) throw e
      }
    }
  }

  if (buffer.trim().startsWith('data: ')) {
    try {
      const data = JSON.parse(buffer.trim().slice(6))
      if (onEvent) onEvent(data)
      if (data.type === 'done') finalResult = data
      if (data.type === 'error') {
        const error = new Error(data.message || data.detail || '操作失败')
        error.code = data.code
        throw error
      }
    } catch (e) {
      if (e.message && !e.message.includes('JSON')) throw e
    }
  }

  return finalResult
}

/**
 * POST 请求，返回 SSE 流式响应
 */
export async function postSSE(url, body, onEvent, _isRetry = false, options = {}) {
  // Keep the old four-argument form while allowing the fourth argument to be
  // an options object for callers that need controller ownership.
  if (typeof _isRetry === 'object') {
    options = _isRetry || {}
    _isRetry = false
  }

  const controller = new AbortController()
  pendingControllers.add(controller)
  options.onController?.(controller)

  try {
    const authHeaders = {}
    const token = getAuthToken()
    if (token) authHeaders['Authorization'] = `Bearer ${token}`

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest', ...authHeaders },
      body: JSON.stringify(body),
      signal: controller.signal,
      credentials: 'same-origin',
    })

    // 401 → 尝试刷新 token 并重试一次
    if (res.status === 401 && !_isRetry) {
      const refreshResult = await tryRefreshToken()
      if (refreshResult) return postSSE(url, body, onEvent, true, options)
      if (onUnauthorized) onUnauthorized()
      throw new Error(getStatusMessage(401))
    }

    if (!res.ok) {
      const text = await res.text()
      let data
      try { data = JSON.parse(text) } catch { data = text }
      const detail = typeof data === 'object' ? data?.detail : data
      const code = typeof detail === 'object' ? detail?.code : null
      const message = typeof detail === 'object'
        ? (detail?.message || code || getStatusMessage(res.status))
        : (detail || getStatusMessage(res.status))
      const error = new Error(message)
      error.status = res.status
      error.code = code || (typeof detail === 'string' ? detail : undefined)
      error.data = data
      throw error
    }

    return await _consumeSSEStream(res.body.getReader(), onEvent)
  } finally {
    pendingControllers.delete(controller)
  }
}

/**
 * 上传 FormData，返回 SSE 流式响应
 */
export async function uploadSSE(url, formData, onEvent, _isRetry = false) {
  const controller = new AbortController()
  pendingControllers.add(controller)

  try {
    const authHeaders = {}
    const token = getAuthToken()
    if (token) authHeaders['Authorization'] = `Bearer ${token}`

    const res = await fetch(url, {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest', ...authHeaders },
      body: formData,
      signal: controller.signal,
      credentials: 'same-origin',
    })

    // 401 → 尝试刷新 token 并重试一次
    if (res.status === 401 && !_isRetry) {
      const refreshResult = await tryRefreshToken()
      if (refreshResult) return uploadSSE(url, formData, onEvent, true)
      if (onUnauthorized) onUnauthorized()
      throw new Error(getStatusMessage(401))
    }

    if (!res.ok) {
      const text = await res.text()
      let detail
      try { detail = JSON.parse(text).detail } catch { detail = text }
      throw new Error(detail || getStatusMessage(res.status))
    }

    return await _consumeSSEStream(res.body.getReader(), onEvent, true)
  } finally {
    pendingControllers.delete(controller)
  }
}

/**
 * GET 请求，返回 SSE 流式响应
 * @param {string} url
 * @param {Function} onEvent - 回调 (data, eventType)
 * @param {object} options - 可选配置
 * @param {AbortSignal} options.signal - 外部 AbortSignal，用于取消 SSE
 * @param {object} options.headers - 额外请求头（例如 Last-Event-ID）
 * @param {boolean} _isRetry - 内部标记
 */
// SSE 非终态 EOF 重连退避：1/3/10 秒，上限 30 秒 + 抖动（AC-010）
const _SSE_BACKOFF_MS = [1000, 3000, 10000, 30000]

function _sseReconnectDelay(attempt) {
  const base = _SSE_BACKOFF_MS[Math.min(attempt, _SSE_BACKOFF_MS.length - 1)]
  return base + Math.floor(Math.random() * 250)
}

function _sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function _retrySSEConnection(url, onEvent, options, isRetry, error, lastStatus) {
  if (options.signal?.aborted) return
  if (typeof options.isTerminal !== 'function') throw error
  if (lastStatus != null && options.isTerminal(lastStatus)) throw error
  const attempt = options.reconnectAttempt || 0
  if (options.maxReconnects != null && attempt >= options.maxReconnects) throw error
  await _sleep(_sseReconnectDelay(attempt))
  if (options.signal?.aborted) return
  options.onReconnect?.(attempt + 1)
  return getSSE(
    url,
    onEvent,
    { ...options, reconnectAttempt: attempt + 1 },
    isRetry,
  )
}

export async function getSSE(url, onEvent, options = {}, _isRetry = false) {
  // 支持旧的 3 参数调用: getSSE(url, onEvent, true)
  if (options === true) {
    options = {}
    _isRetry = true
  }

  // 如果外部 signal 已经 aborted，直接退出
  if (options.signal?.aborted) return

  const controller = new AbortController()
  pendingControllers.add(controller)

  // 如果传了外部 signal，外部 abort 时也 abort 内部 controller
  let onExternalAbort
  if (options.signal) {
    onExternalAbort = () => controller.abort()
    options.signal.addEventListener('abort', onExternalAbort, { once: true })
  }

  try {
    const authHeaders = {}
    const token = getAuthToken()
    if (token) authHeaders['Authorization'] = `Bearer ${token}`

    let res
    try {
      res = await fetch(url, {
        method: 'GET',
        headers: { 'X-Requested-With': 'XMLHttpRequest', ...authHeaders, ...(options.headers || {}) },
        signal: controller.signal,
        credentials: 'same-origin',
      })
    } catch (err) {
      if (controller.signal.aborted || err?.name === 'AbortError') return
      return _retrySSEConnection(url, onEvent, options, _isRetry, err)
    }

    // 401 → 尝试刷新 token 并重试一次
    if (res.status === 401 && !_isRetry) {
      const refreshResult = await tryRefreshToken()
      if (refreshResult) return getSSE(url, onEvent, options, true)
      if (onUnauthorized) onUnauthorized()
      throw new Error(getStatusMessage(401))
    }

    if (!res.ok) {
      const text = await res.text()
      let detail
      try { detail = JSON.parse(text).detail } catch { detail = text }
      const error = new Error(detail || getStatusMessage(res.status))
      error.status = res.status
      if (res.status >= 500 || res.status === 408 || res.status === 429) {
        return _retrySSEConnection(url, onEvent, options, _isRetry, error)
      }
      throw error
    }

    let lastStatus
    const _track = (event) => {
      if (event && typeof event === 'object' && 'status' in event) lastStatus = event.status
      return onEvent(event)
    }
    let result
    try {
      result = await _consumeSSEStream(res.body.getReader(), _track)
    } catch (err) {
      if (controller.signal.aborted || err?.name === 'AbortError') return
      return _retrySSEConnection(url, onEvent, options, _isRetry, err, lastStatus)
    }

    // AC-010：正常 EOF 但业务未终态 → 退避重连；终态/被 abort 不再重连
    if (typeof options.isTerminal === 'function' && !options.signal?.aborted) {
      const status = lastStatus ?? result?.status
      if (!options.isTerminal(status)) {
        return _retrySSEConnection(url, onEvent, options, _isRetry, new Error('SSE stream ended'), status)
      }
    }
    return result
  } finally {
    // finally 释放 controller（正常关闭读取也必须释放）
    if (options.signal && onExternalAbort) {
      options.signal.removeEventListener('abort', onExternalAbort)
    }
    pendingControllers.delete(controller)
  }
}

/**
 * 带 cookie 的 fetch（用于 logout 等需要 HttpOnly cookie 的操作）
 */
export async function fetchWithCredentials(url, options = {}) {
  const token = getAuthToken()
  const authHeaders = { 'X-Requested-With': 'XMLHttpRequest' }
  if (token) authHeaders['Authorization'] = `Bearer ${token}`
  return fetch(url, {
    ...options,
    credentials: 'include',
    headers: { ...authHeaders, ...(options.headers || {}) },
  })
}

export default { get, post, put, del, upload, uploadSSE, cancelAllRequests, invalidateCache }
