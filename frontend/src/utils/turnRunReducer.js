/**
 * Canonical Harness 2.0 event reducer used by both live SSE and replay.
 * Events are append-only; duplicate or late events from another TurnRun are
 * ignored so reconnects cannot corrupt the visible run card.
 */

export function createTurnRun(turnId = null) {
  return {
    id: turnId,
    status: 'running',
    terminalReason: '',
    startedAt: null,
    finishedAt: null,
    latestSequence: 0,
    durationMs: 0,
    eventIds: new Set(),
    actions: [],
    actionIndex: new Map(),
    reasoning: '',
    evidence: [],
    assistant: '',
    assistantStatus: 'pending',
  }
}

function getAction(run, event) {
  const actionId = event.action_id || `system:${event.phase || 'runtime'}`
  let index = run.actionIndex.get(actionId)
  if (index === undefined) {
    index = run.actions.length
    run.actionIndex.set(actionId, index)
    run.actions.push({
      id: actionId,
      phase: event.phase || 'runtime',
      status: 'pending',
      reasoning: '',
      evidence: [],
      output: '',
      visible: true,
      reasoningOpen: false,
      open: true,
    })
  }
  return run.actions[index]
}

function getActionById(run, actionId, phase = 'runtime') {
  return getAction(run, { action_id: actionId, phase })
}

function payloadOf(event) {
  return event?.payload && typeof event.payload === 'object' ? event.payload : event || {}
}

export function reduceTurnRun(run, event) {
  if (!run || !event) return run
  if (run.id && event.turn_run_id && event.turn_run_id !== run.id) return run
  if (event.event_id && run.eventIds.has(event.event_id)) return run
  if (event.event_id) run.eventIds.add(event.event_id)
  if (event.sequence != null) run.latestSequence = Math.max(run.latestSequence, Number(event.sequence) || 0)
  if (event.turn_run_id) run.id = event.turn_run_id

  const payload = payloadOf(event)
  const type = event.type || event.event_type || ''
  if (type === 'turn.started') {
    run.status = 'running'
    run.startedAt ||= event.occurred_at || new Date().toISOString()
  } else if (type === 'action.started' || type === 'action.updated') {
    const action = getAction(run, event)
    action.status = payload.status || (type === 'action.started' ? 'started' : action.status)
    action.label = payload.message || payload.label || payload.step || action.label || event.phase || '运行步骤'
  } else if (type === 'action.completed' || type === 'action.failed') {
    const action = getAction(run, event)
    action.status = type === 'action.completed' ? 'completed' : 'failed'
    action.label = payload.label || payload.call_mode || action.label || event.phase || '运行步骤'
  } else if (type === 'reasoning.started') {
    const action = getAction(run, event)
    action.status = action.status === 'pending' ? 'started' : action.status
    action.reasoningOpen = true
  } else if (type === 'reasoning.delta') {
    const content = String(payload.content || '')
    run.reasoning += content
    getAction(run, event).reasoning += content
  } else if (type === 'reasoning.completed') {
    getAction(run, event).status = 'completed'
    if (payload.duration != null) {
      run.durationMs = Math.max(run.durationMs, Number(payload.duration || 0) * 1000)
    }
  } else if (type === 'evidence.appended') {
    const evidence = payload.questions || payload.items || payload
    run.evidence.push(evidence)
    getAction(run, event).evidence.push(evidence)
  } else if (type === 'assistant.started') {
    run.assistantStatus = 'streaming'
    getAction(run, event).status = 'streaming'
  } else if (type === 'assistant.delta') {
    const content = String(payload.content || '')
    if (payload.replace) {
      run.assistant = content
      getAction(run, event).output = content
    } else {
      run.assistant += content
      getAction(run, event).output += content
    }
    run.assistantStatus = 'streaming'
  } else if (type === 'assistant.completed') {
    if (payload.content != null) run.assistant = String(payload.content)
    run.assistantStatus = 'completed'
    getAction(run, event).status = 'completed'
  } else if (type === 'turn.completed' || type === 'turn.failed' || type === 'turn.cancelled' || type === 'turn.timed_out') {
    run.status = type === 'turn.completed' ? 'completed' : type.slice('turn.'.length)
    run.terminalReason = payload.reason || payload.code || run.status
    run.finishedAt = event.occurred_at || new Date().toISOString()
    if (run.startedAt && run.finishedAt) {
    run.durationMs = Math.max(
      run.durationMs,
      new Date(run.finishedAt).getTime() - new Date(run.startedAt).getTime(),
    )
    }
    run.actions.forEach(action => {
      if (action.status === 'pending' || action.status === 'started' || action.status === 'streaming') {
        action.status = run.status === 'completed' ? 'completed' : run.status
      }
      action.open = false
    })
  }
  return run
}

/**
 * Fold the durable done metadata into the same run used by live events.
 * Older servers expose rich traces only on `done`, so this keeps historical
 * runs compatible while the canonical event stream is being adopted.
 */
export function mergeTurnRunMetadata(run, metadata = {}) {
  if (!run || !metadata || typeof metadata !== 'object') return run

  const trace = metadata.reasoning_trace || {}
  for (const step of trace.steps || metadata.steps || []) {
    if (!step || typeof step !== 'object') continue
    const action = getActionById(run, `step:${step.step || step.label || 'runtime'}`, 'observe_propose')
    action.label = step.label || step.message || action.label
    action.status = step.status || 'completed'
    action.reason = step.reason || action.reason || ''
    action.visible = !['loading', 'context'].includes(String(step.step || ''))
  }

  for (const skill of metadata.skill_trace || []) {
    if (!skill || typeof skill !== 'object') continue
    const action = getActionById(run, `skill:${skill.skill_name || skill.label || 'runtime'}`, 'observe_propose')
    action.label = skill.label || skill.skill_name || action.label
    action.status = skill.status === 'loaded' ? 'completed' : (skill.status || 'completed')
    action.reason = skill.reason || action.reason || ''
  }

  for (const tool of metadata.tool_calls_trace || metadata.tool_steps || []) {
    if (!tool || typeof tool !== 'object') continue
    const action = getActionById(run, `tool:${tool.tool_name || tool.step || 'runtime'}`, 'observe_propose')
    action.label = tool.label || tool.message || tool.tool_name || action.label
    action.status = tool.status === 'success' ? 'completed' : (tool.status || 'completed')
    action.evidence.push(tool.result_preview || tool.result || tool)
    if (tool.summary) action.output = tool.summary
  }

  const thinking = Array.isArray(metadata.thinking)
    ? metadata.thinking.flatMap(item => item?.chunks || [])
    : [metadata.thinking]
  const reasoningText = thinking.filter(Boolean).join('')
  if (reasoningText && !run.reasoning) {
    const action = getActionById(run, 'action:observe_propose', 'observe_propose')
    action.reasoning += reasoningText
    action.reasoningOpen = false
    action.status = 'completed'
    run.reasoning = reasoningText
  }
  if (metadata.thinking_duration != null) {
    run.durationMs = Math.max(run.durationMs, Number(metadata.thinking_duration || 0) * 1000)
  } else if (trace.duration_ms != null) {
    run.durationMs = Math.max(run.durationMs, Number(trace.duration_ms || 0))
  }
  if (metadata.turn_id && !run.id) run.id = metadata.turn_id
  if (metadata.assistant || metadata.content) run.assistant ||= String(metadata.assistant || metadata.content)
  return run
}

export function legacyEventToEnvelope(event, turnId, sequence = 0) {
  const type = event?.type || ''
  const mapping = {
    turn_started: 'turn.started',
    step: 'action.updated',
    tool_step: 'evidence.appended',
    thinking_start: 'reasoning.started',
    thinking: 'reasoning.delta',
    thinking_done: 'reasoning.completed',
    chunk: 'assistant.delta',
    done: 'turn.completed',
    cancelled: 'turn.cancelled',
    error: 'turn.failed',
  }
  const channel = type.startsWith('thinking') ? 'reasoning' : type === 'chunk' ? 'assistant' : 'system'
  const data = event?.data || {}
  const actionId = type === 'step'
    ? `step:${event?.step || 'runtime'}`
    : type === 'tool_step'
      ? `tool:${data.tool_name || data.step || 'runtime'}`
      : type.startsWith('thinking')
        ? 'action:observe_propose'
        : type === 'chunk'
          ? 'action:write_response'
          : undefined
  return {
    event_id: `legacy:${turnId}:${sequence}`,
    turn_run_id: event?.turn_id || turnId,
    sequence,
    type: mapping[type] || type,
    action_id: actionId,
    channel,
    phase: type === 'chunk' ? 'write_response' : 'observe_propose',
    occurred_at: new Date().toISOString(),
    payload: event,
  }
}

export function serializeTurnRun(run) {
  if (!run) return null
  return {
    id: run.id,
    status: run.status,
    terminalReason: run.terminalReason,
    startedAt: run.startedAt,
    finishedAt: run.finishedAt,
    latestSequence: run.latestSequence,
    durationMs: run.durationMs,
    reasoning: run.reasoning,
    evidence: run.evidence,
    assistant: run.assistant,
    assistantStatus: run.assistantStatus,
    actions: run.actions.map(action => ({ ...action })),
  }
}
