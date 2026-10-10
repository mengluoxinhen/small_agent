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

// P8 打磨：user actions must never bubble unhandled rejections out of the
// components; a failed call lands in store.error and the error status.
function failFetch(status, detail) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: false, status, statusText: 'ERR', json: async () => ({ detail }) })),
  )
}

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

// ---------------------------------------------------------------- U3 会话管理动作

describe('agent store — session management (U3)', () => {
  it('renameSession PATCHes the title and refreshes the list', async () => {
    const calls = routeFetch(({ method, url, body }) => {
      if (method === 'PATCH' && url === '/api/sessions/s1') return { id: 's1', title: body.title, mode: 'review' }
      if (method === 'GET' && url === '/api/sessions') return [{ id: 's1', title: '新标题' }]
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.renameSession('s1', '新标题')
    expect(calls[0]).toEqual({ method: 'PATCH', url: '/api/sessions/s1', body: { title: '新标题' } })
    expect(store.sessions).toEqual([{ id: 's1', title: '新标题' }])
  })

  it('togglePin PATCHes the boolean as-is (false must not be dropped)', async () => {
    let patchedBody = null
    const calls = routeFetch(({ method, url, body }) => {
      if (method === 'PATCH' && url === '/api/sessions/s1') {
        patchedBody = body
        return { id: 's1', mode: 'review', ...body }
      }
      if (method === 'GET' && url === '/api/sessions') return [{ id: 's1', pinned: patchedBody.pinned }]
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.togglePin('s1', false)
    expect(calls[0].body).toEqual({ pinned: false })
    expect(store.sessions[0].pinned).toBe(false)
  })

  it('deleting the current session switches to the next one in the fresh list', async () => {
    routeFetch(({ method, url }) => {
      if (method === 'DELETE' && url === '/api/sessions/s1') return null
      if (method === 'GET' && url === '/api/sessions') return [{ id: 's2' }, { id: 's3' }]
      if (method === 'GET' && url === '/api/sessions/s2') return { id: 's2', mode: 'review' }
      if (method === 'GET' && url === '/api/sessions/s2/events?format=json') return []
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    await store.removeSession('s1')
    expect(store.sessionId).toBe('s2') // 相邻会话，而不是空白新建
    expect(store.messages).toEqual([])
  })

  it('deleting the current session with no neighbours falls back to a blank new session', async () => {
    routeFetch(({ method, url }) => {
      if (method === 'DELETE') return null
      if (method === 'GET' && url === '/api/sessions') return []
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    await store.removeSession('s1')
    expect(store.sessionId).toBeNull()
    expect(store.status).toBe('idle')
  })

  it('uploadAttachment posts base64 into the session workspace and remembers the chip', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions/s1/files') return { filename: 'case.csv', bytes: 7 }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    await store.uploadAttachment({ name: 'case.csv', base64: 'YSwxLDIsMw==' })
    expect(calls[0]).toEqual({
      method: 'POST',
      url: '/api/sessions/s1/files',
      body: { filename: 'case.csv', content_base64: 'YSwxLDIsMw==' },
    })
    expect(store.attachments).toEqual([{ filename: 'case.csv', bytes: 7 }])
  })

  it('uploadAttachment creates a session first when none exists', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions') return NEW_SESSION
      if (method === 'POST' && url === '/api/sessions/s1/files') return { filename: 'n.txt', bytes: 3 }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    await store.uploadAttachment({ name: 'n.txt', base64: 'YWJj' })
    expect(calls.map((c) => c.url)).toEqual(['/api/sessions', '/api/sessions/s1/files'])
    expect(store.sessionId).toBe('s1')
  })

  it('sending with attachments notes them in the message text and clears the chips', async () => {
    const calls = routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions/s1/messages') return { run_id: 'r1' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    store.sessionMode = 'review'
    store.attachments = [{ filename: 'case.csv', bytes: 7 }]
    await store.send('总结一下这个文件')
    expect(calls[0].body.text).toBe('总结一下这个文件\n（已上传附件：case.csv，可直接用文件名读取）')
    expect(store.attachments).toEqual([])
  })

  it('a failed upload reports without adding a phantom chip', async () => {
    failFetch(413, '附件过大')
    const store = useAgentStore()
    store.sessionId = 's1'
    await store.uploadAttachment({ name: 'big.bin', base64: 'AAA=' })
    expect(store.attachments).toEqual([])
    expect(store.error).toContain('附件过大')
  })

  it('regenerate() drops the trailing exchange and resends the last user text', async () => {
    routeFetch(({ method, url }) => {
      if (method === 'POST' && url === '/api/sessions/s1/messages') return { run_id: 'r2' }
      throw new Error(`unexpected call ${method} ${url}`)
    })
    const store = useAgentStore()
    store.sessionId = 's1'
    store.sessionMode = 'review'
    store.$patch({
      status: 'done',
      messages: [
        { role: 'user', text: '第一问' },
        { role: 'assistant', text: '第一个回答', streaming: false },
        { role: 'user', text: '重新生成这句' },
        { role: 'assistant', text: '不满意的答案', streaming: false },
      ],
    })
    await store.regenerate()
    const texts = store.messages.map((m) => m.text)
    expect(texts).toEqual(['第一问', '第一个回答', '重新生成这句']) // 旧答案被摘掉，用户句保留
    expect(store.status).toBe('streaming')
  })
})
