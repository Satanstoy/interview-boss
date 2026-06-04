import { createApp } from 'vue'
import '@/assets/styles/global.css'
import 'vue-sonner/style.css'
import App from './App.vue'
import { autoAnimatePlugin } from '@formkit/auto-animate/vue'
import { MotionPlugin } from '@vueuse/motion'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import { logger } from '@/utils/logger'

/**
 * 全局错误捕获 & 白屏检测
 * - window.onerror: 捕获 JS 运行时错误
 * - unhandledrejection: 捕获未处理的 Promise 异常
 * - 白屏检测: 页面加载后检测 DOM 是否为空，自动刷新兜底
 */

// 生产环境错误上报（通过 sendBeacon 统一上报到后端）
function reportError(errorInfo) {
  logger.error(errorInfo.message || 'Unknown error', {
    type: errorInfo.type,
    source: errorInfo.source,
    lineno: errorInfo.lineno,
    colno: errorInfo.colno,
    stack: errorInfo.stack,
    componentInfo: errorInfo.componentInfo,
    component: errorInfo.componentName,
  })
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
  const RETRY_DELAY = 3000
  let retries = 0

  function check() {
    // 等待 Vue 应用初始化完成（App.vue 中 initAuth 完成后设置此标记）
    if (!window.__VUE_APP_READY__) {
      if (retries < MAX_RETRIES) {
        retries++
        setTimeout(check, RETRY_DELAY)
      }
      return
    }

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
    setTimeout(check, 2000)
  } else {
    window.addEventListener('load', () => setTimeout(check, 2000))
  }
}

detectBlankScreen()

// 创建并挂载 Vue 应用
const app = createApp(App)
app.use(autoAnimatePlugin)
app.use(MotionPlugin)
app.component('DynamicScroller', DynamicScroller)
app.component('DynamicScrollerItem', DynamicScrollerItem)

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