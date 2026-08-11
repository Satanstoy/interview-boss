import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { highlightCode, normalizeLanguage } from './highlight.js'

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

// Markdown-it 默认关闭原始 HTML，并限制危险链接协议；DOMPurify 仍作为
// v-html 前的第二道防线，防止未来新增渲染规则时绕过安全边界。
const markdown = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
  highlight(code, language) {
    const lang = normalizeLanguage(language)
    const languageClass = lang ? ` language-${lang}` : ''
    return `<pre class="hljs${languageClass}"><code>${highlightCode(code, lang)}</code></pre>`
  },
})

// 为表格添加响应式包装；表格内容仍由 Markdown-it 负责转义和渲染。
markdown.renderer.rules.table_open = () => '<div class="table-wrapper"><table>'
markdown.renderer.rules.table_close = () => '</table></div>'

// LRU 缓存：避免相同文本反复做 Markdown-it 渲染与 DOMPurify.sanitize
const CACHE_MAX = 200
const cache = new Map()

/**
 * 安全渲染 Markdown 为 HTML（带缓存）
 */
export function renderSafeMarkdown(text) {
  if (!text) return ''
  if (cache.has(text)) return cache.get(text)
  const rawHtml = markdown.render(String(text).replace(/^\uFEFF/, ''))
  const result = DOMPurify.sanitize(rawHtml, purifyConfig)
  // 简易 LRU：满了就删最早的
  if (cache.size >= CACHE_MAX) {
    cache.delete(cache.keys().next().value)
  }
  cache.set(text, result)
  return result
}
