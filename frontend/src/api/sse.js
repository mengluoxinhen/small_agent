/**
 * SSE client for the session event stream (PLAN §6 contract).
 *
 * EventSource cannot attach headers, so the resume cursor rides the
 * `last_event_id` query param — T6 on the backend proved header and query
 * paths replay identically. Terminal events close the stream explicitly:
 * `approval_required` is terminal-for-close, the UI reconnects after deciding.
 */

export const EVENT_TYPES = [
  'run_started',
  'user_message',
  'text_message_content',
  'tool_call_args',
  'tool_call_start',
  'tool_call_end',
  'tool_result',
  'approval_required',
  'run_finished',
  'run_error',
]

export const TERMINAL_TYPES = ['run_finished', 'run_error', 'approval_required']

export function openStream(sessionId, onEvent, { lastEventId = null } = {}) {
  const query = lastEventId ? `?last_event_id=${lastEventId}` : ''
  const es = new EventSource(`/api/sessions/${sessionId}/events${query}`)
  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    es.close()
  }

  for (const type of EVENT_TYPES) {
    es.addEventListener(type, (event) => {
      let payload = {}
      try {
        payload = event.data ? JSON.parse(event.data) : {}
      } catch {
        payload = { raw: event.data }
      }
      const seq = event.lastEventId ? Number(event.lastEventId) : null
      onEvent({ type, payload, seq })
      if (TERMINAL_TYPES.includes(type)) close()
    })
  }

  return { close }
}
