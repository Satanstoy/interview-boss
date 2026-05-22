import { get, post, put, del, postSSE } from './http.js'

const API = '/api/chat'

// ── 会话管理 ──
export const createConversation = (data) => post(`${API}/conversations`, data)
export const getConversations = (status = 'active') => get(`${API}/conversations?status=${status}`, { noCache: true })
export const getConversation = (id) => get(`${API}/conversations/${id}`)
export const updateTitle = (id, title) => put(`${API}/conversations/${id}/title`, { title })
export const archiveConversation = (id) => put(`${API}/conversations/${id}/archive`)
export const deleteConversation = (id) => del(`${API}/conversations/${id}`)

// ── 消息 ──
export const getMessages = (conversationId) => get(`${API}/conversations/${conversationId}/messages`, { noCache: true })

/**
 * 发送消息并接收 SSE 流式回复
 * @param {string} conversationId
 * @param {string} content
 * @param {function} onEvent - 事件回调: ({type, content?, questions?, message?}) => void
 * @returns {Promise}
 */
export const sendMessage = (conversationId, content, onEvent) =>
  postSSE(`${API}/conversations/${conversationId}/messages`, { content }, onEvent)

// ── 记忆 ──
export const getMemories = (memoryType) => {
  const params = memoryType ? `?memory_type=${memoryType}` : ''
  return get(`${API}/memories${params}`, { noCache: true })
}
export const deleteMemory = (id) => del(`${API}/memories/${id}`)
