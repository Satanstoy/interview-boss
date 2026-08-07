// 管理员 AI 助手 API（聚合质量审查，仅管理员）
import http from './http.js'

// 发送消息给 AI 助手（写操作只暂存为待确认，不执行）。
// message === '' 表示确认执行后的续接（后端会把 [已执行操作] 回执喂回 LLM）。
export function sendAssistantMessage(sessionId, message = '') {
  return http.post('/api/admin/assistant/chat', {
    session_id: sessionId,
    message,
  })
}

// 确认并执行 AI 助手暂存的写操作（approve/reject/batch_approve）。
export function confirmAssistantAction(sessionId, confirmId, tool, arguments_) {
  return http.post('/api/admin/assistant/confirm', {
    session_id: sessionId,
    confirm_id: confirmId,
    tool,
    arguments: arguments_,
  })
}

// 读取当前管理员的助手会话日志。必须绕过 http.js 的 GET 30s 缓存，
// 否则每次对话后拉到的历史是旧数据。
export function fetchAssistantHistory(sessionId) {
  return http.get(
    `/api/admin/assistant/history?session_id=${encodeURIComponent(sessionId)}`,
    { ttl: 0 },
  )
}
