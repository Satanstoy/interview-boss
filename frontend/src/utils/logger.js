// frontend/src/utils/logger.js
/**
 * 前端日志工具 — 统一错误上报到后端
 *
 * 用法：
 *   import { logger } from '@/utils/logger'
 *   logger.error('LLM 请求失败', { questionId: 42 })
 *   logger.warn('缓存过期')
 */

class Logger {
  constructor() {
    this._queue = []
    this._timer = null
  }

  error(message, context = {}) {
    const entry = this._build('error', message, context)
    console.error(`[${message}]`, context)
    this._enqueue(entry)
  }

  warn(message, context = {}) {
    console.warn(`[${message}]`, context)
  }

  info(message, context = {}) {
    console.info(`[${message}]`, context)
  }

  _build(level, message, context) {
    return {
      level,
      message,
      timestamp: new Date().toISOString(),
      url: window.location.href,
      userAgent: navigator.userAgent,
      ...context,
    }
  }

  _enqueue(entry) {
    this._queue.push(entry)
    if (this._queue.length >= 5) this._flush()
    if (!this._timer) this._timer = setTimeout(() => this._flush(), 10000)
  }

  _flush() {
    clearTimeout(this._timer)
    this._timer = null
    if (!this._queue.length) return

    const batch = this._queue.splice(0)
    try {
      navigator.sendBeacon?.(
        '/api/error-report',
        new Blob([JSON.stringify({ errors: batch })], { type: 'application/json' })
      )
    } catch {
      // sendBeacon 失败静默忽略
    }
  }
}

export const logger = new Logger()
