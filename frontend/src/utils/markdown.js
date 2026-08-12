import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { highlightCode, normalizeLanguage } from './highlight.js'
import { sourceFavicon, sourceHost, sourcePath } from './source.js'
import { escapeHtml } from './validate.js'

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
    'data-material', 'data-source-preview', 'data-slot', 'aria-hidden',
    'src', 'alt', 'width', 'height',
    'colspan', 'rowspan',
  ],
  // 禁止 javascript: 协议
  ALLOWED_URI_REGEXP: /^(?:(?:https?|ftp):\/\/|mailto:|#)/i,
  // 链接自动添加 rel="noopener noreferrer"
  ADD_ATTR: ['target', 'rel'],
}

// DOMPurify 在部分浏览器配置下会移除 target/rel 的值；在 href 已经通过
// ALLOWED_URI_REGEXP 校验后，再补回外部链接的安全打开属性。
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node?.tagName !== 'A') return
  const href = node.getAttribute('href') || ''
  if (/^https?:\/\//i.test(href)) {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

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

// 搜索增强答案里的 Markdown 链接采用紧凑的 citation pill：左侧是目标网站
// favicon，右侧沿用 Markdown 链接标题，并保留原始 href 供用户打开。
const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const href = token.attrGet('href') || ''
  if (/^https?:\/\//i.test(href)) {
    const host = sourceHost({ url: href })
    const path = sourcePath({ url: href })
    const preview = `${host}${path}` || href
    token.attrJoin('class', 'answer-source-link')
    token.attrSet('data-material', 'glass')
    token.attrSet('data-source-preview', preview)
    token.attrSet('title', preview)
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
    const favicon = sourceFavicon({ url: href })
    const linkOpen = defaultLinkOpen
      ? defaultLinkOpen(tokens, index, options, env, self)
      : self.renderToken(tokens, index, options)
    return `${linkOpen}<img class="answer-source-favicon" src="${escapeHtml(favicon)}" alt="" loading="lazy"><span class="answer-source-label">`
  }
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

const defaultLinkClose = markdown.renderer.rules.link_close
markdown.renderer.rules.link_close = (tokens, index, options, env, self) => {
  const openToken = tokens.slice(0, index).reverse().find(token => token.type === 'link_open')
  const href = openToken?.attrGet('href') || ''
  if (/^https?:\/\//i.test(href)) {
    const host = sourceHost({ url: href })
    const path = sourcePath({ url: href })
    const preview = escapeHtml(`${host}${path}` || href)
    const favicon = escapeHtml(sourceFavicon({ url: href }))
    const closeTag = defaultLinkClose
      ? defaultLinkClose(tokens, index, options, env, self)
      : self.renderToken(tokens, index, options)
    return `</span><span class="answer-source-preview rounded-lg px-2.5 py-1.5 text-xs leading-relaxed" data-slot="tooltip-content" data-material="glass" aria-hidden="true"><img class="answer-source-preview__favicon" src="${favicon}" alt=""><span class="answer-source-preview__copy"><strong>打开原文</strong><span>${preview}</span></span></span>${closeTag}`
  }
  return defaultLinkClose
    ? defaultLinkClose(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options)
}

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
