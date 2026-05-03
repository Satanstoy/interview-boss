import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

/**
 * 全局错误捕获 & 白屏检测
 * - window.onerror: 捕获 JS 运行时错误
 * - unhandledrejection: 捕获未处理的 Promise 异常
 * - 白屏检测: 页面加载后检测 DOM 是否为空，自动刷新兜底
 */

// 生产环境错误上报（可对接 Sentry 等）
function reportError(errorInfo) {
  // 开发环境 verbose 输出，生产环境只报 error
  if (import.meta.env.DEV) {
    console.error('[Global Error]', errorInfo)
  } else {
    console.error('[Global Error]', errorInfo.message || errorInfo)
    // TODO: 接入真实上报服务
    // navigator.sendBeacon('/api/error-report', JSON.stringify(errorInfo))
  }
}

// 捕获 JS 运行时错误
window.onerror = (message, source, lineno, colno, error) => {
  reportError({
    type: 'runtime',
    message,
    source,
    lineno,
    colno,
    stack: error?.stack,
  })
  // 返回 true 阻止浏览器默认行为（如控制台重复输出）
  return true
}

// 捕获未处理的 Promise rejection（如 fetch 失败未 catch）
window.addEventListener('unhandledrejection', (event) => {
  reportError({
    type: 'unhandledrejection',
    message: event.reason?.message || String(event.reason),
    stack: event.reason?.stack,
  })
  // 阻止浏览器默认的 console.error 输出
  event.preventDefault()
})

// 白屏检测：页面加载完成后检查关键 DOM 节点是否存在
function detectBlankScreen() {
  const MAX_RETRIES = 3
  const RETRY_DELAY = 2000
  let retries = 0

  function check() {
    const app = document.getElementById('app')
    // 检查 #app 是否有实际内容（子元素数量）
    const hasContent = app && app.children.length > 0 && app.innerHTML.trim().length > 100

    if (!hasContent) {
      retries++
      if (retries < MAX_RETRIES) {
        setTimeout(check, RETRY_DELAY)
      } else {
        reportError({
          type: 'blank_screen',
          message: '白屏检测：页面加载后无有效内容，尝试自动刷新',
        })
        // 自动刷新兜底（仅一次，避免无限刷新）
        if (!sessionStorage.getItem('_blank_screen_refreshed')) {
          sessionStorage.setItem('_blank_screen_refreshed', '1')
          location.reload()
        }
      }
    } else {
      // 页面正常加载，清除刷新标记
      sessionStorage.removeItem('_blank_screen_refreshed')
    }
  }

  // 等待 DOM 渲染完成后再检测
  if (document.readyState === 'complete') {
    setTimeout(check, 1000)
  } else {
    window.addEventListener('load', () => setTimeout(check, 1000))
  }
}

detectBlankScreen()

// 创建并挂载 Vue 应用
const app = createApp(App)

// Vue 全局错误处理器
app.config.errorHandler = (err, instance, info) => {
  reportError({
    type: 'vue',
    message: err.message,
    stack: err.stack,
    componentInfo: info,
    componentName: instance?.$options?.name || instance?.$?.type?.name || 'unknown',
  })
}

app.mount('#app')