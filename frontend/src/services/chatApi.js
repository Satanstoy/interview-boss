import { get, post, put, del, postSSE, getSSE } from './http.js'

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

/** Replay canonical Harness 2.0 events after a durable sequence cursor. */
export const replayTurnEvents = async (conversationId, turnId, afterSequence = 0) => {
  const events = []
  await getSSE(
    `${API}/conversations/${conversationId}/turns/${turnId}/events?after_sequence=${encodeURIComponent(afterSequence)}&follow=false`,
    (event) => {
      if (event?.event_id || event?.turn_run_id) events.push(event)
    },
  )
  return events
}

function createClientRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function canonicalEventToLegacy(event) {
  const payload = event?.payload && typeof event.payload === 'object' ? event.payload : {}
  const harness = { harness_event: event }
  switch (event?.type) {
    case 'turn.started':
      return { type: 'turn_started', turn_id: event.turn_run_id, ...payload, ...harness }
    case 'turn.queued':
    case 'turn.queue_failed':
    case 'commit.started':
    case 'commit.completed':
    case 'evidence.selected':
      return null
    case 'action.updated':
      return { ...(payload.type ? payload : { type: 'step', ...payload }), ...harness }
    case 'action.started':
      return {
        type: 'step',
        step: payload.call_mode || event.phase || 'action',
        message: `开始执行 ${payload.call_mode || event.phase || '动作'}`,
        action_id: event.action_id,
        ...harness,
      }
    case 'action.completed':
      return {
        type: 'step',
        step: payload.call_mode || event.phase || 'action',
        message: `完成 ${payload.call_mode || event.phase || '动作'}`,
        action_id: event.action_id,
        ...harness,
      }
    case 'action.failed':
      return {
        type: 'step',
        step: payload.call_mode || event.phase || 'action',
        message: `动作失败：${payload.error_code || 'unknown'}`,
        action_id: event.action_id,
        ...harness,
      }
    case 'assistant.delta':
      return { type: 'chunk', ...payload, ...harness }
    case 'assistant.started':
      return null
    case 'assistant.completed':
      return { type: 'chunk', content: payload.content || '', replace: true, ...harness }
    case 'reasoning.started':
      return { type: 'thinking_start', content: '', ...harness }
    case 'reasoning.delta':
      return { type: 'thinking', content: payload.content || '', ...harness }
    case 'reasoning.completed':
      return { type: 'thinking_done', ...payload, ...harness }
    case 'evidence.appended':
      return { type: 'retrieved', questions: payload.questions || [], ...harness }
    case 'reasoning.insight':
      return { type: 'insight', ...payload, ...harness }
    case 'turn.completed':
      return {
        type: 'done',
        metadata: payload.metadata || {},
        content: payload.content || '',
        ...harness,
      }
    case 'turn.cancelled':
      return { type: 'cancelled', turn_id: event.turn_run_id, ...payload, ...harness }
    case 'turn.failed':
      return { type: 'error', code: payload.code, message: payload.message || '面试回合执行失败', ...harness }
    default:
      return null
  }
}

async function sendHarnessMessage(conversationId, body, onEvent, options = {}) {
  const endpoint = options.endpoint || `${API}/conversations/${conversationId}/messages`
  const accepted = await post(endpoint, body)
  const data = accepted?.data || accepted || {}
  const turnId = data.turn_run_id || data.turn_id
  if (!turnId) throw new Error('服务端未返回 TurnRun ID')

  const controller = new AbortController()
  options.onController?.(controller)
  let finalEvent = null
  let sequence = 0
  let terminalSeen = false
  let reconnects = 0
  while (!terminalSeen) {
    try {
      await getSSE(
        `${API}/conversations/${conversationId}/turns/${encodeURIComponent(turnId)}/events?after_sequence=${encodeURIComponent(sequence)}&follow=true`,
        (canonical) => {
          sequence = Math.max(sequence, Number(canonical?.sequence || 0))
          const event = canonicalEventToLegacy(canonical)
          if (!event) return
          if (event.type === 'done') finalEvent = event
          if (['done', 'cancelled', 'error'].includes(event.type)) terminalSeen = true
          onEvent?.(event)
        },
        {
          signal: controller.signal,
          headers: { 'Last-Event-ID': String(sequence) },
        },
      )
      if (terminalSeen) break
      if (reconnects >= 3) break
      reconnects += 1
    } catch (error) {
      if (controller.signal.aborted || reconnects >= 3) throw error
      reconnects += 1
    }
    if (!terminalSeen) await new Promise(resolve => setTimeout(resolve, 300 * reconnects))
  }
  if (!terminalSeen) {
    throw new Error('事件流重连次数已耗尽，TurnRun 状态未知，请重新加载会话')
  }
  return finalEvent || { type: 'error', code: 'MISSING_TERMINAL_EVENT', turn_id: turnId }
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
    revisionOfTurnId = null,
    harnessVersion = '2.0',
  } = {},
) => {
  const body = regenerateMessageId ? {} : { content }
  if (model) body.model = model
  body.client_request_id = clientRequestId
  if (harnessVersion) body.harness_version = harnessVersion
  if (!regenerateMessageId && existingUserMessageId) {
    body.existing_user_message_id = existingUserMessageId
  }
  if (!regenerateMessageId && revisionOfTurnId) {
    body.revision_of_turn_id = revisionOfTurnId
  }
  const endpoint = regenerateMessageId
    ? `${API}/conversations/${conversationId}/messages/${regenerateMessageId}/regenerate`
    : `${API}/conversations/${conversationId}/messages`
  if (harnessVersion === '2.0') {
    return sendHarnessMessage(conversationId, body, onEvent, { endpoint, onController })
  }
  return postSSE(endpoint, body, onEvent, false, { onController })
}

// ── 记忆 ──
export const getMemories = (memoryType) => {
  const params = memoryType ? `?memory_type=${memoryType}` : ''
  return get(`${API}/memories${params}`, { noCache: true })
}
export const deleteMemory = (id) => del(`${API}/memories/${id}`)
