import { describe, it, expect, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'

/**
 * P7 red list: the store is the single reducer of the SSE contract (PLAN §6) —
 * one `applyEvent` per event type, status machine idle/streaming/awaiting/cancelled,
 * history replay, and the mode toggle riding on the session PATCH before the next send.
 */

function ev(type, payload, seq) {
  return { type, payload, seq }
}

const CALC_START = { call_id: 'c1', tool: 'calculator', risk: 'read' }
const WRITE_PAUSE = { approval_id: 'a1', tool: 'write_text_file', arguments: { filename: 'a.txt' }, risk: 'write' }

describe('agent store — event reducer', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useAgentStore()
    store.beginLocalRun('run_1') // no network: drive the reducer directly
  })

  it('starts idle and goes streaming on run_started', () => {
    // A fresh pinia: within one pinia, useAgentStore() returns the SAME instance,
    // so re-calling it here would otherwise observe the beforeEach's beginLocalRun.
    setActivePinia(createPinia())
    const fresh = useAgentStore()
    expect(fresh.status).toBe('idle')
    fresh.applyEvent('run_started', { run_id: 'r9', mode: 'review', model: 'deepseek-chat' }, 1)
    expect(fresh.status).toBe('streaming')
    expect(fresh.runId).toBe('r9')
  })

  it('assembles text deltas into one assistant message per stream', () => {
    store.applyEvent('text_message_content', { delta: '你好' }, 2)
    store.applyEvent('text_message_content', { delta: '，世界' }, 3)
    const assistants = store.messages.filter((m) => m.role === 'assistant')
    expect(assistants).toHaveLength(1)
    expect(assistants[0].text).toBe('你好，世界')
    store.applyEvent('run_finished', { usage: { requests: 1 }, turns: 1 }, 4)
    expect(store.messages.at(-1).streaming).toBe(false)
  })

  it('buffers tool_call_args that arrive before tool_call_start', () => {
    store.applyEvent('tool_call_args', { call_id: 'c1', delta: '{"exp' }, 2)
    store.applyEvent('tool_call_args', { call_id: 'c1', delta: 'ression":"1+1"}' }, 3)
    store.applyEvent('tool_call_start', CALC_START, 4)
    store.applyEvent('tool_call_end', { call_id: 'c1' }, 5)
    const step = store.trace.find((t) => t.kind === 'tool' && t.call_id === 'c1')
    expect(step.args).toBe('{"expression":"1+1"}')
    expect(step.risk).toBe('read')
  })

  it('joins tool_result onto its step with ok flag and duration', () => {
    store.applyEvent('tool_call_start', CALC_START, 2)
    store.applyEvent('tool_result', { call_id: 'c1', ok: true, output: '2', duration_ms: 12.3 }, 3)
    const step = store.trace.find((t) => t.call_id === 'c1')
    expect(step.result).toEqual({ ok: true, output: '2', duration_ms: 12.3 })
  })

  it('marks failed tool outputs via the ok flag', () => {
    store.applyEvent('tool_call_start', { call_id: 'c2', tool: 'calculator', risk: 'read' }, 2)
    store.applyEvent(
      'tool_result',
      { call_id: 'c2', ok: false, output: '工具 calculator 调用失败：表达式不合法。请修正后重新调用。', duration_ms: 1 },
      3,
    )
    expect(store.trace.find((t) => t.call_id === 'c2').result.ok).toBe(false)
  })

  it('pause: approval_required flips status to awaiting and keeps the payload', () => {
    store.applyEvent('tool_call_start', { call_id: 'c3', tool: 'write_text_file', risk: 'write' }, 2)
    store.applyEvent('approval_required', WRITE_PAUSE, 3)
    expect(store.status).toBe('awaiting')
    expect(store.pendingApproval).toMatchObject({ approval_id: 'a1', tool: 'write_text_file' })
  })

  it('finish: run_finished records usage and turns', () => {
    store.applyEvent('run_finished', { usage: { requests: 2, total_tokens: 36 }, turns: 2 }, 9)
    expect(store.status).toBe('done')
    expect(store.usage).toEqual({ requests: 2, total_tokens: 36 })
    expect(store.turns).toBe(2)
  })

  it('run_error distinguishes cancellation from error', () => {
    store.applyEvent('run_error', { kind: 'cancelled', message: '运行已取消' }, 5)
    expect(store.status).toBe('cancelled')
    expect(store.error).toBeNull()

    const other = useAgentStore()
    other.beginLocalRun('r2')
    other.applyEvent('run_error', { kind: 'model', message: 'boom' }, 5)
    expect(other.status).toBe('error')
    expect(other.error).toContain('boom')
  })

  it('tracks the last event seq for reconnects', () => {
    store.applyEvent('text_message_content', { delta: 'x' }, 7)
    expect(store.lastEventId).toBe(7)
  })

  it('user_message replays into a user bubble without duplicating the local push', () => {
    store.applyEvent('user_message', { text: '算 6*7' }, 2)
    expect(store.messages).toEqual([{ role: 'user', text: '算 6*7' }])
    // live path: send() pushed the same text locally before the event landed
    store.applyEvent('user_message', { text: '算 6*7' }, 2)
    expect(store.messages.filter((m) => m.role === 'user')).toHaveLength(1)
  })
})

describe('agent store — history replay', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('loadSession rebuilds messages and trace from the persisted json events', async () => {
    const persisted = [
      { type: 'run_started', payload: { run_id: 'r1', mode: 'full_access', model: 'm' }, seq: 1 },
      { type: 'user_message', payload: { text: '6*7 是多少' }, seq: 2 },
      { type: 'text_message_content', payload: { delta: '答案是 ' }, seq: 3 },
      { type: 'tool_call_args', payload: { call_id: 'c1', delta: '{"expression":"6*7"}' }, seq: 4 },
      { type: 'tool_call_start', payload: { call_id: 'c1', tool: 'calculator', risk: 'read' }, seq: 5 },
      { type: 'tool_result', payload: { call_id: 'c1', ok: true, output: '42', duration_ms: 0.5 }, seq: 6 },
      { type: 'text_message_content', payload: { delta: '42' }, seq: 7 },
      { type: 'run_finished', payload: { usage: { requests: 1 }, turns: 2 }, seq: 8 },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        json: async () => persisted,
      })),
    )
    const store = useAgentStore()
    await store.loadSession('sess_old')
    expect(store.sessionId).toBe('sess_old')
    expect(store.status).toBe('done')
    expect(store.trace.find((t) => t.call_id === 'c1').result.output).toBe('42')
    expect(store.messages.some((m) => m.role === 'user' && m.text === '6*7 是多少')).toBe(true)
    expect(store.messages.some((m) => m.role === 'assistant' && m.text.includes('42'))).toBe(true)
    expect(store.lastEventId).toBe(8)
    vi.unstubAllGlobals()
  })

  it('a paused history restores status awaiting with the approval payload', async () => {
    const persisted = [
      { type: 'run_started', payload: { run_id: 'r2', mode: 'review', model: 'm' }, seq: 1 },
      { type: 'approval_required', payload: WRITE_PAUSE, seq: 2 },
    ]
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => persisted })))
    const store = useAgentStore()
    await store.loadSession('sess_paused')
    expect(store.status).toBe('awaiting')
    expect(store.pendingApproval.approval_id).toBe('a1')
    vi.unstubAllGlobals()
  })

  it('loading a session syncs the mode selector with what the server will honor', async () => {
    // P8 polish: the header toggle must reflect the loaded session's mode,
    // otherwise it lies about what the NEXT message will do.
    const events = [
      { type: 'run_started', payload: { run_id: 'r', mode: 'full_access', model: 'm' }, seq: 1 },
      { type: 'run_finished', payload: { usage: {}, turns: 1 }, seq: 2 },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => ({
        ok: true,
        status: 200,
        json: async () => (String(url).includes('format=json') ? events : { id: 'sess_x', mode: 'full_access' }),
      })),
    )
    const store = useAgentStore()
    expect(useUiStore().mode).toBe('review')
    await store.loadSession('sess_x')
    expect(store.sessionMode).toBe('full_access')
    expect(useUiStore().mode).toBe('full_access')
    vi.unstubAllGlobals()
  })
})
