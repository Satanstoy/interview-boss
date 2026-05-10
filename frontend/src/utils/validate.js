/**
 * 前端输入验证与消毒工具
 * - 防止 SQL 注入、XSS 攻击
 * - 统一输入长度/格式校验
 * - 所有用户输入在发送 API 前必须经过验证
 */

// ── SQL 注入检测已移除 ──
// 后端使用参数化查询，无需客户端 SQL 注入过滤。
// 之前的正则过于宽泛，会误判合法的中文面试题文本（如包含"SELECT"的数据库八股文）。

/**
 * 输入消毒（XSS 防护）
 * 移除了 SQL 注入检测（后端使用参数化查询），保留 XSS 消毒
 */
export function sanitizeAgainstInjection(str, _fieldName = '输入') {
  if (typeof str !== 'string') return ''
  return str
    .replace(/<[^>]*>/g, '')           // 移除 HTML 标签
    .replace(/javascript:/gi, '')       // 移除 javascript: 协议
    .replace(/on\w+\s*=/gi, '')         // 移除事件处理器
    .replace(/data:/gi, '')             // 移除 data: 协议
}

// ── URL 安全化 ──

/**
 * 安全化 URL：仅允许 http/https 协议，阻止 javascript: / data: 等
 */
export function safeUrl(url) {
  if (!url || typeof url !== 'string') return ''
  const trimmed = url.trim()
  if (/^https?:\/\//i.test(trimmed)) return trimmed
  return ''
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
  return { valid: true, value: s }
}

/**
 * 验证通用文本字段（行内编辑等）
 */
export function validateTextField(value, fieldName, maxLen = 5000) {
  if (typeof value !== 'string') return { valid: true, value: '' }
  const s = sanitizeText(value, maxLen)
  return { valid: true, value: s }
}

/**
 * 验证 API 设置字段（模型名、base URL 等）
 */
export function validateSettingsField(value, fieldName, maxLen = 500) {
  const s = sanitizeText(value, maxLen)
  if (!s) return { valid: false, error: `${fieldName} 不能为空`, value: '' }
  return { valid: true, value: s }
}

/**
 * 验证 API Key（允许更多字符）
 */
export function validateApiKey(value, maxLen = 500) {
  if (!value || !value.trim()) return { valid: true, value: '' }
  const s = value.trim().slice(0, maxLen)
  return { valid: true, value: s }
}

/**
 * 验证 LLM Base URL（必填，必须是合法 HTTP(S) URL）
 */
export function validateBaseUrl(value, fieldName = 'Base URL') {
  const s = sanitizeText(value, 500)
  if (!s) return { valid: false, error: `${fieldName} 不能为空`, value: '' }
  if (!URL_RE.test(s)) return { valid: false, error: `${fieldName} 格式无效，必须以 http:// 或 https:// 开头`, value: '' }
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
