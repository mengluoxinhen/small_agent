import { describe, it, expect, beforeEach, vi } from 'vitest'
import { openStream, EVENT_TYPES, TERMINAL_TYPES } from '../api/sse'

/**
 * P7 red list: the SSE client subscribes to every contract event type (PLAN §6),
 * forwards parsed payloads, and closes the connection on terminal events —
 * approval_required included, since the UI reconnects after deciding.
 */

class FakeEventSource {
  static instances = []

  constructor(url) {
    this.url = url
    this.listeners = {}
    this.closed = false
    FakeEventSource.instances.push(this)
  }

  addEventListener(type, fn) {
    ;(this.listeners[type] ??= []).push(fn)
  }

  emit(type, data, id) {
    for (const fn of this.listeners[type] ?? []) {
      fn({ data, lastEventId: id == null ? '' : String(id) })
    }
  }

  close() {
    this.closed = true
  }
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
})

describe('sse client', () => {
  it('subscribes to all ten contract event types on the session stream URL', () => {
    openStream('s1', vi.fn())
    const es = FakeEventSource.instances[0]
    expect(es.url).toBe('/api/sessions/s1/events')
    expect(EVENT_TYPES).toHaveLength(10)
    for (const type of EVENT_TYPES) {
      expect(es.listeners[type], `missing listener for ${type}`).toBeTruthy()
    }
  })

  it('passes the reconnect cursor as the last_event_id query param', () => {
    // EventSource cannot set headers, so Last-Event-ID rides on the query string
    // (backend T6 proved header and query paths are equivalent).
    openStream('s1', vi.fn(), { lastEventId: 12 })
    expect(FakeEventSource.instances[0].url).toBe('/api/sessions/s1/events?last_event_id=12')
  })

  it('forwards parsed payload and numeric seq to the handler', () => {
    const onEvent = vi.fn()
    openStream('s1', onEvent)
    FakeEventSource.instances[0].emit('tool_result', '{"call_id":"c1","ok":true}', 4)
    expect(onEvent).toHaveBeenCalledWith({ type: 'tool_result', payload: { call_id: 'c1', ok: true }, seq: 4 })
  })

  it('closes on each terminal event and not before', () => {
    const onEvent = vi.fn()
    openStream('s1', onEvent)
    const es = FakeEventSource.instances[0]
    es.emit('text_message_content', '{"delta":"x"}', 1)
    expect(es.closed).toBe(false)
    es.emit('approval_required', '{"approval_id":"a1"}', 2)
    expect(es.closed).toBe(true)
    expect(TERMINAL_TYPES.sort()).toEqual(['approval_required', 'run_error', 'run_finished'])
  })

  it('returns a handle whose close() detaches the stream', () => {
    const handle = openStream('s1', vi.fn())
    const es = FakeEventSource.instances[0]
    handle.close()
    expect(es.closed).toBe(true)
  })
})
