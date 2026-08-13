import { get, post, put, del, postSSE } from './http.js'

const API = '/api/chat'

// ── 会话管理 ──
export const createConversation = (data) => post(`${API}/conversations`, data)
export const getConversations = (status = 'active') => get(`${API}/conversations?status=${status}`, { noCache: true })
export const getConversation = (id) => get(`${API}/conversations/${id}`)
export const updateTitle = (id, title) => put(`${API}/conversations/${id}/title`, { title })
export const archiveConversation = (id) => put(`${API}/conversations/${id}/archive`)
export const deleteConversation = (id) => del(`${API}/conversations/${id}`)
export const pinConversation = (id) => put(`${API}/conversations/${id}/pin`)

// ── 消息 ──
export const getMessages = (conversationId) => get(`${API}/conversations/${conversationId}/messages`, { noCache: true })

export const cancelTurn = (conversationId, turnId, reason = 'client_stop') => {
  return post(`${API}/conversations/${conversationId}/turns/${turnId}/cancel`, { reason })
}

function createClientRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export const sendMessage = (
  conversationId,
  content,
  onEvent,
  model = null,
  {
    clientRequestId = createClientRequestId(),
    onController,
    regenerateMessageId = null,
    existingUserMessageId = null,
  } = {},
) => {
  const body = regenerateMessageId ? {} : { content }
  if (model) body.model = model
  body.client_request_id = clientRequestId
  if (!regenerateMessageId && existingUserMessageId) {
    body.existing_user_message_id = existingUserMessageId
  }
  return postSSE(
    regenerateMessageId
      ? `${API}/conversations/${conversationId}/messages/${regenerateMessageId}/regenerate`
      : `${API}/conversations/${conversationId}/messages`,
    body,
    onEvent,
    false,
    { onController },
  )
}

// ── 记忆 ──
export const getMemories = (memoryType) => {
  const params = memoryType ? `?memory_type=${memoryType}` : ''
  return get(`${API}/memories${params}`, { noCache: true })
}
export const deleteMemory = (id) => del(`${API}/memories/${id}`)
