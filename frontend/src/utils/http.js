/**
 * 统一 HTTP 请求封装
 * - 超时控制（默认 10s，文件上传 60s）
 * - 自动重试（网络错误重试 2 次，间隔 1s/3s）
 * - 请求取消（组件卸载自动取消）
 * - 统一错误拦截（401/403/500/502/503/504）
 */

const DEFAULT_TIMEOUT = 10_000
const UPLOAD_TIMEOUT = 60_000
const MAX_RETRIES = 2
const RETRY_DELAYS = [1000, 3000]

// 全局 AbortController 管理，用于组件卸载时批量取消
const pendingControllers = new Set()

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
  // 网络断开、DNS 失败等
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
 * @returns {Promise<any>} - 解析后的 JSON 数据
 */
async function request(url, options = {}) {
  const {
    timeout = DEFAULT_TIMEOUT,
    retries = MAX_RETRIES,
    noRetry = false,
    ...fetchOptions
  } = options

  let lastError = null

  for (let attempt = 0; attempt <= (noRetry ? 0 : retries); attempt++) {
    const { controller, timer } = createTimeoutController(timeout)

    try {
      const res = await fetch(url, {
        ...fetchOptions,
        signal: controller.signal,
      })

      cleanup(controller, timer)

      // 解析响应
      let data
      const contentType = res.headers.get('content-type') || ''
      if (contentType.includes('application/json')) {
        data = await res.json()
      } else {
        const text = await res.text()
        // 尝试 JSON 解析（后端可能不返回 content-type）
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

export default { get, post, put, del, upload, cancelAllRequests }