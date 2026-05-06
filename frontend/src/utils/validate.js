/**
 * 前端输入验证与消毒工具
 * - 防止 SQL 注入、XSS 攻击
 * - 统一输入长度/格式校验
 * - 所有用户输入在发送 API 前必须经过验证
 */

// ── SQL 注入关键词检测 ──
const SQL_INJECTION_PATTERNS = [
  /(\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|UNION)\b\s)/i,
  /(--|#|\/\*|\*\/)/,
  /(\b(OR|AND)\b\s+\d+\s*=\s*\d+)/i,
  /['"]\s*;\s*(DROP|DELETE|INSERT|UPDATE|ALTER)/i,
  /(\bSLEEP\s*\(|\bBENCHMARK\s*\(|\bWAITFOR\s+DELAY)/i,
  /(0x[0-9a-fA-F]+)/,
]

/**
 * 检测字符串是否包含疑似 SQL 注入
 */
export function containsSqlInjection(str) {
  if (typeof str !== 'string') return false
  return SQL_INJECTION_PATTERNS.some(pattern => pattern.test(str))
}

/**
 * 检测并拒绝 SQL 注入，返回安全字符串
 * @throws 如果检测到注入攻击
 */
export function sanitizeAgainstInjection(str, fieldName = '输入') {
  if (typeof str !== 'string') return str
  if (containsSqlInjection(str)) {
    throw new Error(`${fieldName} 包含非法字符，请移除特殊 SQL 关键词`)
  }
  return str
}

// ── 通用输入消毒 ──

/**
 * 去除首尾空白并限制最大长度
 */
export function sanitizeText(str, maxLen = 10000) {
  if (typeof str !== 'string') return ''
  return str.trim().slice(0, maxLen)
}

/**
 * HTML 实体转义（防 XSS）
 */
export function escapeHtml(str) {
  if (typeof str !== 'string') return ''
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#x27;' }
  return str.replace(/[&<>"']/g, c => map[c])
}

// ── 特定字段验证 ──

const USERNAME_RE = /^[a-zA-Z0-9_一-龥]{2,32}$/
const RESERVED_USERNAMES = ['admin', 'root', 'system', 'null', 'undefined', 'superuser', 'moderator', 'guest', 'test']
const URL_RE = /^https?:\/\/[^\s"'<>]+$/i
const SEASON_RE = /^[一-龥a-zA-Z0-9\s\-_()（）]{1,50}$/

/**
 * 验证用户名：2-32 字符，仅允许字母数字下划线中文
 */
export function validateUsername(username) {
  const s = sanitizeText(username, 32)
  if (!s) return { valid: false, error: '用户名不能为空', value: '' }
  if (!USERNAME_RE.test(s)) return { valid: false, error: '用户名仅允许 2-32 个字母、数字、下划线或中文', value: '' }
  if (RESERVED_USERNAMES.includes(s.toLowerCase())) return { valid: false, error: '该用户名为系统保留，请更换', value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: '用户名包含非法字符', value: '' }
  return { valid: true, value: s }
}

/**
 * 验证密码：至少 8 位，最大 128 位
 */
export function validatePassword(password) {
  if (typeof password !== 'string') return { valid: false, error: '密码不能为空', value: '' }
  if (password.length < 8) return { valid: false, error: '密码至少 8 位', value: '' }
  if (password.length > 128) return { valid: false, error: '密码不能超过 128 位', value: '' }
  return { valid: true, value: password }
}

/**
 * 验证 URL 格式
 */
export function validateUrl(url) {
  if (!url || !url.trim()) return { valid: true, value: '' } // URL 通常可选
  const s = sanitizeText(url, 2048)
  if (!URL_RE.test(s)) return { valid: false, error: '请输入有效的 URL（以 http:// 或 https:// 开头）', value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: 'URL 包含非法字符', value: '' }
  return { valid: true, value: s }
}

/**
 * 验证数字范围
 */
export function validateNumber(val, min, max, fieldName = '数值') {
  const num = Number(val)
  if (isNaN(num)) return { valid: false, error: `${fieldName}必须是数字`, value: null }
  if (num < min || num > max) return { valid: false, error: `${fieldName}必须在 ${min} 到 ${max} 之间`, value: null }
  return { valid: true, value: num }
}

/**
 * 验证招聘季名称
 */
export function validateSeason(season) {
  const s = sanitizeText(season, 50)
  if (!s) return { valid: false, error: '招聘季名称不能为空', value: '' }
  if (!SEASON_RE.test(s)) return { valid: false, error: '招聘季名称仅允许中英文、数字、括号和连字符', value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: '招聘季名称包含非法字符', value: '' }
  return { valid: true, value: s }
}

/**
 * 验证通用文本字段（行内编辑等）
 */
export function validateTextField(value, fieldName, maxLen = 5000) {
  if (typeof value !== 'string') return { valid: true, value: '' }
  const s = sanitizeText(value, maxLen)
  if (containsSqlInjection(s)) return { valid: false, error: `${fieldName} 包含非法字符`, value: '' }
  return { valid: true, value: s }
}

/**
 * 验证 API 设置字段（模型名、base URL 等）
 */
export function validateSettingsField(value, fieldName, maxLen = 500) {
  const s = sanitizeText(value, maxLen)
  if (!s) return { valid: false, error: `${fieldName} 不能为空`, value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: `${fieldName} 包含非法字符`, value: '' }
  return { valid: true, value: s }
}

/**
 * 验证 API Key（允许更多字符，但仍需防注入）
 */
export function validateApiKey(value, maxLen = 500) {
  if (!value || !value.trim()) return { valid: true, value: '' } // API Key 通常可选
  const s = value.trim().slice(0, maxLen)
  // API Key 可能包含特殊字符如 sk-xxx，只检测明确的 SQL 注入模式
  if (containsSqlInjection(s)) return { valid: false, error: 'API Key 包含非法字符', value: '' }
  return { valid: true, value: s }
}

/**
 * 验证 LLM Base URL（必填，必须是合法 HTTP(S) URL）
 */
export function validateBaseUrl(value, fieldName = 'Base URL') {
  const s = sanitizeText(value, 500)
  if (!s) return { valid: false, error: `${fieldName} 不能为空`, value: '' }
  if (!URL_RE.test(s)) return { valid: false, error: `${fieldName} 格式无效，必须以 http:// 或 https:// 开头`, value: '' }
  if (containsSqlInjection(s)) return { valid: false, error: `${fieldName} 包含非法字符`, value: '' }
  // 提示常见错误：用户可能误填 API Key 或模型名
  if (s.startsWith('sk-') || s.startsWith('eyJ')) return { valid: false, error: `${fieldName} 看起来像 API Key 而非 URL，请检查`, value: '' }
  return { valid: true, value: s }
}

/**
 * 验证文件大小和数量
 */
export function validateFiles(files, { maxCount = 20, maxSizeMB = 10 } = {}) {
  if (files.length > maxCount) return { valid: false, error: `最多上传 ${maxCount} 张图片` }
  for (const file of files) {
    if (!file.type.startsWith('image/')) {
      return { valid: false, error: `文件 "${file.name}" 不是图片格式，请选择图片文件` }
    }
    if (file.size > maxSizeMB * 1024 * 1024) {
      return { valid: false, error: `图片 "${file.name}" 超过 ${maxSizeMB}MB 限制` }
    }
  }
  return { valid: true }
}

/**
 * 批量验证对象中所有字符串字段的 SQL 注入
 */
export function validatePayload(obj, fieldLabels = {}) {
  for (const [key, value] of Object.entries(obj)) {
    if (typeof value === 'string' && value.trim()) {
      const label = fieldLabels[key] || key
      const result = sanitizeAgainstInjection(value, label)
      obj[key] = result
    }
  }
  return obj
}
