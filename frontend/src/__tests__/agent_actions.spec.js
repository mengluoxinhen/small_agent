import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'

/**
 * P7 red list: store actions must hit the exact backend contract (PLAN §6/§7) —
 * the mode toggle rides on a session PATCH before the next message, approvals are
 * keyed by approval_id, and every send/decide reconnects the SSE tail.
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
    for (const fn of this.listeners[type] ?? []) fn({ data, lastEventId: String(id ?? '') })
  }
  close() {
    this.closed = true
  }
}

function routeFetch(handler) {
  const calls = []
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = (init.method ?? 'GET').toUpperCase()
    const body = init.body ? JSON.parse(init.body) : null
    calls.push({ method, url, body })
    const result = handler({ method, url, body })
    if (result === null) return { ok: true, status: 204, json: async () => null }
    return { ok: true, status: 200, json: async () => result }
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

const NEW_SESSION = { id: 's1', title: 't', mode: 'review' }

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource)
  setActivePinia(createPinia())
})

describe('agent store — actions', () => {
  it('send() creates a session, posts the message and opens the stream', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions') return NEW_SESSION
      if (method === 'POST' && url === '/api/sessions/s1/messages') return { run_id: 'r1' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.send('算一下 6*7')

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual(['POST /api/sessions', 'POST /api/sessions/s1/messages'])
    expect(calls[1].body).toEqual({ text: '算一下 6*7' })
    expect(store.sessionId).toBe('s1')
    expect(store.runId).toBe('r1')
    expect(store.status).toBe('streaming')
    expect(store.messages.at(-1)).toMatchObject({ role: 'user', text: '算一下 6*7' })
    expect(FakeEventSource.instances[0].url).toBe('/api/sessions/s1/events')
  })

  it('a mode flip PATCHes the session before the next message goes out', async () => {
    const calls = routeFetch(({ method, url, body }) => {
      if (method === 'POST' && url === '/api/sessions') return NEW_SESSION
      if (method === 'PATCH' && url === '/api/sessions/s1') return { ...NEW_SESSION, ...body }
      if (method === 'POST' && url === '/api/sessions/s1/messages') return { run_id: 'r2' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.send('第一问')
    expect(calls.some((c) => c.method === 'PATCH')).toBe(false) // mode matches: no PATCH
    useUiStore().setMode('full_access')
    await store.send('第二问')

    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch.body).toEqual({ mode: 'full_access' })
    expect(calls.at(-2).method).toBe('PATCH') // the PATCH precedes the second message
    expect(store.sessionMode).toBe('full_access')
  })

  it('send() reconnects the stream from the persisted cursor after a previous terminal', async () => {
    routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions') return NEW_SESSION
      if (method === 'POST' && url === '/api/sessions/s1/messages') return { run_id: 'r2' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.send('第一问')
    const first = FakeEventSource.instances[0]
    first.emit('run_started', JSON.stringify({ run_id: 'r1', mode: 'review', model: 'm' }), 1)
    first.emit('run_finished', JSON.stringify({ usage: {}, turns: 1 }), 5)
    expect(first.closed).toBe(true)

    await store.send('第二问')
    const second = FakeEventSource.instances.at(-1)
    expect(second.url).toBe('/api/sessions/s1/events?last_event_id=5')
  })

  it('decide() posts the approval keyed by approval_id and resumes the tail', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/runs/r1/approvals') return { status: 'resumed' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    store.beginLocalRun('r1')
    store.applyEvent('approval_required', { approval_id: 'a1', tool: 'write_text_file', arguments: {}, risk: 'write' }, 5)
    expect(store.status).toBe('awaiting')

    await store.decide({ decision: 'approve', always: true })
    expect(calls[0]).toEqual({ method: 'POST', url: '/api/runs/r1/approvals', body: { a1: { decision: 'approve', always: true } } })
    expect(store.pendingApproval).toBeNull()
    expect(store.status).toBe('streaming')
    expect(FakeEventSource.instances.at(-1).url).toBe('/api/sessions/s1/events?last_event_id=5')
  })

  it('cancel() hits the run cancel endpoint', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/runs/r1/cancel') return { status: 'cancelled' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.beginLocalRun('r1')
    await store.cancel()
    expect(calls).toEqual([{ method: 'POST', url: '/api/runs/r1/cancel', body: null }])
  })
})

describe('agent store — error boundary', () => {
  // P8 打磨：user actions must never bubble unhandled rejections out of the
  // components; a failed call lands in store.error and the error status.
  function failFetch(status, detail) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({ ok: false, status, statusText: 'ERR', json: async () => ({ detail }) })),
    )
  }

  it('a failed approval lands in store.error instead of an unhandled rejection', async () => {
    failFetch(409, 'run 当前状态为 succeeded，不在等待审批')
    const store = useAgentStore()
    store.sessionId = 's1'
    store.beginLocalRun('r1')
    store.applyEvent('approval_required', { approval_id: 'a1', tool: 'write_text_file', arguments: {}, risk: 'write' }, 5)

    await store.decide({ decision: 'approve' })
    expect(store.status).toBe('error')
    expect(store.error).toContain('不在等待审批')
    expect(store.pendingApproval).toBeNull()
  })

  it('a failed send reports the error without faking a started run', async () => {
    failFetch(500, '服务无响应')
    const store = useAgentStore()
    await store.send('问题')
    expect(store.status).toBe('error')
    expect(store.error).toContain('服务无响应')
    expect(store.runId).toBeNull()
    expect(store.sessionId).toBeNull()
  })

  it('a failed cancel reports but keeps the streaming run alive to watch', async () => {
    failFetch(409, 'run 已结束')
    const store = useAgentStore()
    store.beginLocalRun('r1')
    await store.cancel()
    expect(store.error).toContain('run 已结束')
    expect(store.status).toBe('streaming') // 取消没成功：流还在跑，状态不该谎报 error
  })
})
