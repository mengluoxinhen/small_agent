import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import ChatView from '../components/ChatView.vue'

/**
 * P7 assembly check: ChatView wires the store into the screen — messages (markdown),
 * the trace panel, and the approval dialog that appears exactly while awaiting.
 * The SSE layer and markstream-vue are stubbed; their own specs cover behaviour.
 */

vi.mock('../api/sse', () => ({
  openStream: vi.fn(() => ({ close: vi.fn() })),
  EVENT_TYPES: [],
  TERMINAL_TYPES: [],
}))

vi.mock('markstream-vue', () => ({
  MarkdownRender: {
    props: ['content', 'final'],
    template: '<div class="md-stub">{{ content }}</div>',
  },
}))

function mountView() {
  return mount(ChatView)
}

beforeEach(() => {
  setActivePinia(createPinia())
  // the sidebar lists sessions on mount; keep that network call inert here
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })))
})

describe('ChatView', () => {
  it('renders user and assistant messages from the store', () => {
    const store = useAgentStore()
    store.$patch({
      status: 'done',
      messages: [
        { role: 'user', text: '6*7 是多少' },
        { role: 'assistant', text: '答案是 42', streaming: false },
      ],
    })
    const wrapper = mountView()
    expect(wrapper.text()).toContain('6*7 是多少')
    expect(wrapper.find('.md-stub').text()).toContain('答案是 42')
  })

  it('shows the approval dialog only while the run awaits a decision', async () => {
    const store = useAgentStore()
    store.$patch({
      status: 'streaming',
      messages: [],
    })
    const wrapper = mountView()
    expect(wrapper.find('[data-testid="approval-dialog"]').exists()).toBe(false)

    store.$patch({
      status: 'awaiting',
      pendingApproval: { approval_id: 'a1', tool: 'write_text_file', arguments: { filename: 'a.txt' }, risk: 'write' },
    })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="approval-dialog"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('write_text_file')
  })

  it('clicking send pushes through to the store action', async () => {
    const store = useAgentStore()
    const spy = vi.spyOn(store, 'send').mockImplementation(async () => {})
    const wrapper = mountView()
    await wrapper.get('[data-testid="chat-input"]').setValue('你好')
    await wrapper.get('[data-testid="send-button"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('你好')
  })

  // ------------------------------------------------------------ U3：会话式右栏

  it('shows an empty state when there is neither a session nor messages', () => {
    const w = mountView()
    expect(w.find('[data-testid="empty-state"]').exists()).toBe(true)
    expect(w.text()).toContain('小助手')
  })

  it('the header shows the current session title', async () => {
    const store = useAgentStore()
    store.$patch({
      sessionId: 's1',
      sessions: [{ id: 's1', title: '会话甲' }],
      messages: [{ role: 'user', text: 'x' }],
    })
    const w = mountView()
    await w.vm.$nextTick()
    expect(w.get('[data-testid="chat-title"]').text()).toBe('会话甲')
  })

  it('Enter sends; Shift+Enter is a plain newline', async () => {
    const store = useAgentStore()
    const spy = vi.spyOn(store, 'send').mockImplementation(async () => {})
    const w = mountView()
    await w.get('[data-testid="chat-input"]').setValue('多行输入')
    await w.get('[data-testid="chat-input"]').trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(spy).not.toHaveBeenCalled()
    await w.get('[data-testid="chat-input"]').trigger('keydown', { key: 'Enter' })
    expect(spy).toHaveBeenCalledWith('多行输入')
  })

  it('the last finished answer offers copy and regenerate', async () => {
    const store = useAgentStore()
    const writeText = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const regen = vi.spyOn(store, 'regenerate').mockImplementation(async () => {})
    store.$patch({
      status: 'done',
      sessionId: 's1',
      messages: [
        { role: 'user', text: '问题一' },
        { role: 'assistant', text: '老答案', streaming: false },
        { role: 'user', text: '问题二' },
        { role: 'assistant', text: '最新答案', streaming: false },
      ],
    })
    const w = mountView()
    await w.vm.$nextTick()
    // 只有最后一条 AI 消息给这两个按钮
    expect(w.findAll('[data-testid="copy-answer"]')).toHaveLength(1)
    await w.get('[data-testid="copy-answer"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith('最新答案')
    await w.get('[data-testid="regenerate-button"]').trigger('click')
    expect(regen).toHaveBeenCalled()
  })

  it('a running answer shows the stop control instead of regenerate', () => {
    const store = useAgentStore()
    store.$patch({
      status: 'streaming',
      sessionId: 's1',
      messages: [{ role: 'assistant', text: '正在想…', streaming: true }],
    })
    const w = mountView()
    expect(w.find('[data-testid="cancel-button"]').exists()).toBe(true)
    expect(w.find('[data-testid="regenerate-button"]').exists()).toBe(false)
  })

  it('steps of the current run are collapsible inside the answer bubble', async () => {
    const store = useAgentStore()
    store.$patch({
      status: 'done',
      sessionId: 's1',
      messages: [
        {
          role: 'assistant',
          text: '答案',
          streaming: false,
          steps: [{ kind: 'tool', call_id: 'c1', tool: 'calculator', risk: 'read', args: '1+1', result: { ok: true, output: '2', duration_ms: 1 } }],
        },
      ],
    })
    const w = mountView()
    expect(w.find('[data-testid="steps-toggle"]').exists()).toBe(true)
    expect(w.find('[data-testid="trace-step"]').exists()).toBe(false) // 默认折叠
    await w.get('[data-testid="steps-toggle"]').trigger('click')
    expect(w.find('[data-testid="trace-step"]').text()).toContain('calculator')
  })

  it('URL carries ?sid= and a fresh mount restores that session', async () => {
    window.history.replaceState({}, '', '/?sid=s9')
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const u = String(url)
        if (u.includes('events')) return { ok: true, status: 200, json: async () => [] }
        if (u.includes('/sessions/s9')) return { ok: true, status: 200, json: async () => ({ id: 's9', mode: 'review' }) }
        return { ok: true, status: 200, json: async () => [] }
      }),
    )
    const store = useAgentStore()
    const w = mountView()
    await w.vm.$nextTick()
    await vi.waitFor(() => expect(store.sessionId).toBe('s9'))
  })

  it('sessionId changes rewrite the URL without a reload', async () => {
    window.history.replaceState({}, '', '/')
    const w = mountView()
    const store = useAgentStore()
    store.$patch({ sessionId: 's42' })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(window.location.search).toBe('?sid=s42')
    store.$patch({ sessionId: null })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(window.location.search).toBe('')
  })

  it('the attach button reads the file and hands base64 to the store', async () => {
    const store = useAgentStore()
    store.sessionId = 's1'
    const up = vi.spyOn(store, 'uploadAttachment').mockImplementation(async () => {})
    const w = mountView()
    const file = new window.File(['abc'], 'case.csv', { type: 'text/csv' })
    const input = w.get('[data-testid="attach-input"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => expect(up).toHaveBeenCalledWith({ name: 'case.csv', base64: 'YWJj' }))
  })
})
