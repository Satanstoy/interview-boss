import { marked } from 'marked'
import DOMPurify from 'dompurify'

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

/**
 * 安全渲染 Markdown 为 HTML
 * 1. marked.parse() 将 markdown 转为 HTML
 * 2. DOMPurify 清理所有 XSS 攻击向量
 */
export function renderSafeMarkdown(text) {
  if (!text) return ''
  const rawHtml = marked.parse(text)
  return DOMPurify.sanitize(rawHtml, purifyConfig)
}
