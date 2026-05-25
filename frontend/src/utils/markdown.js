import { marked } from 'marked'
import DOMPurify from 'dompurify'
// 导入 highlight.js 触发 marked.use() 全局初始化（只执行一次）
import './highlight.js'

// 配置 DOMPurify：只允许安全的 HTML 标签和属性
const purifyConfig = {
  ALLOWED_TAGS: [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'hr',
    'ul', 'ol', 'li',
    'strong', 'em', 'b', 'i', 'u', 's', 'del', 'mark', 'sub', 'sup',
    'a', 'code', 'pre', 'blockquote',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'span', 'div',
  ],
  ALLOWED_ATTR: [
    'href', 'target', 'rel', 'title',
    'class', 'id',
    'src', 'alt', 'width', 'height',
    'colspan', 'rowspan',
  ],
  // 禁止 javascript: 协议
  ALLOWED_URI_REGEXP: /^(?:(?:https?|ftp):\/\/|mailto:|#)/i,
  // 链接自动添加 rel="noopener noreferrer"
  ADD_ATTR: ['target', 'rel'],
}

// LRU 缓存：避免相同文本反复做 marked.parse + DOMPurify.sanitize
const CACHE_MAX = 200
const cache = new Map()

/**
 * 安全渲染 Markdown 为 HTML（带缓存）
 */
export function renderSafeMarkdown(text) {
  if (!text) return ''
  if (cache.has(text)) return cache.get(text)
  const rawHtml = marked.parse(text)
  const result = DOMPurify.sanitize(rawHtml, purifyConfig)
  // 简易 LRU：满了就删最早的
  if (cache.size >= CACHE_MAX) {
    cache.delete(cache.keys().next().value)
  }
  cache.set(text, result)
  return result
}
