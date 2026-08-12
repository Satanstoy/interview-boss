import { safeUrl } from './validate.js'

export function sourceUrl(source) {
  return safeUrl(source?.url || source)
}

export function sourceHost(source) {
  const url = sourceUrl(source)
  if (!url) return ''
  try {
    return new URL(url).hostname.replace(/^www\./i, '')
  } catch {
    return ''
  }
}

export function sourceTitle(source) {
  return String(source?.title || '').trim() || sourceHost(source) || '参考来源'
}

export function sourceFavicon(source) {
  const host = sourceHost(source)
  return host
    ? `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=64`
    : ''
}

export function sourcePath(source) {
  const url = sourceUrl(source)
  if (!url) return ''
  try {
    const parsed = new URL(url)
    return parsed.pathname === '/' ? '' : `${parsed.pathname}${parsed.search}`
  } catch {
    return ''
  }
}
