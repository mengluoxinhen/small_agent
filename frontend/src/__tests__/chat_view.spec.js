import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import { useToastStore } from '../stores/toast'
import ChatView from '../components/ChatView.vue'

/**
 * V4 right column: /chat/:sessionId path routing with refresh restore and a
 * recent-session fallback, a sticky header (inline rename, status pill,
 * share/export/clear, mode segments), per-bubble hover actions, streaming
 * affordances (typing dots + blinking cursor), quick prompts, and the composer.
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

function routes(handler) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const data = handler(String(url))
    return { ok: true, status: 200, json: async () => data }
  }))
}

// GET /api/sessions -> list; /sessions/:id -> row; any events -> []
function sessionRoutes(sessions) {
  routes((u) => {
    if (u.includes('/events')) return []
    const m = u.match(/\/api\/sessions\/([^/?]+)/)
    if (m) return { id: m[1], mode: 'review', title: m[1] }
    return sessions
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
  window.history.replaceState({}, '', '/')
  // the shell lists sessions on mount; keep that network call inert by default
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })))
})

describe('ChatView (V4)', () => {
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
    store.$patch({ status: 'streaming', messages: [] })
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

  it('shows an empty welcome with four quick-prompt cards that only fill the input', async () => {
    const store = useAgentStore()
    const spy = vi.spyOn(store, 'send').mockImplementation(async () => {})
    const w = mountView()
    expect(w.find('[data-testid="empty-state"]').exists()).toBe(true)
    expect(w.text()).toContain('小助手')
    const cards = w.findAll('[data-testid="quick-prompt"]')
    expect(cards).toHaveLength(4)
    await cards[0].trigger('click')
    expect(w.get('[data-testid="chat-input"]').element.value).toBeTruthy()
    expect(spy).not.toHaveBeenCalled()
  })

  it('the header shows the current session title', async () => {
    const store = useAgentStore()
    store.sessionsLoaded = true
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

  it('every finished answer offers copy and thumbs; regenerate only on the last', async () => {
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
    expect(w.findAll('[data-testid="copy-answer"]')).toHaveLength(2)
    await w.findAll('[data-testid="copy-answer"]')[0].trigger('click')
    expect(writeText).toHaveBeenCalledWith('老答案')
    // 赞踩挂在每条回答上；重新生成只给最后一条
    expect(w.findAll('[data-testid="thumb-up"]')).toHaveLength(2)
    await w.findAll('[data-testid="thumb-up"]')[1].trigger('click')
    expect(store.messages[3].feedback).toBe('up')
    expect(w.findAll('[data-testid="regenerate-button"]')).toHaveLength(1)
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

  it('shows typing dots while streaming has not produced the first token', () => {
    const store = useAgentStore()
    store.$patch({
      status: 'streaming',
      sessionId: 's1',
      messages: [{ role: 'user', text: '问题' }],
    })
    const w = mountView()
    expect(w.find('[data-testid="typing-dots"]').exists()).toBe(true)
    expect(w.find('[data-testid="stream-cursor"]').exists()).toBe(false)
  })

  it('a streaming bubble carries the blinking cursor instead of the dots', () => {
    const store = useAgentStore()
    store.$patch({
      status: 'streaming',
      sessionId: 's1',
      messages: [{ role: 'assistant', text: '部分输出', streaming: true }],
    })
    const w = mountView()
    expect(w.find('[data-testid="typing-dots"]').exists()).toBe(false)
    expect(w.find('[data-testid="stream-cursor"]').exists()).toBe(true)
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

  it('/chat/:id on mount restores that session', async () => {
    window.history.replaceState({}, '', '/chat/s9')
    sessionRoutes([{ id: 's9', title: '九', updated_at: new Date().toISOString() }])
    const store = useAgentStore()
    const w = mountView()
    await w.vm.$nextTick()
    await vi.waitFor(() => expect(store.sessionId).toBe('s9'))
    expect(w.get('[data-testid="chat-title"]').text()).toContain('九')
  })

  it('a legacy ?sid= link still restores the session (backward compat)', async () => {
    window.history.replaceState({}, '', '/?sid=s9')
    sessionRoutes([{ id: 's9', title: '九', updated_at: new Date().toISOString() }])
    const store = useAgentStore()
    mountView()
    await vi.waitFor(() => expect(store.sessionId).toBe('s9'))
  })

  it('sessionId changes rewrite the path without a reload', async () => {
    const w = mountView()
    const store = useAgentStore()
    store.$patch({ sessionId: 's42' })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(window.location.pathname).toBe('/chat/s42')
    store.$patch({ sessionId: null })
    await w.vm.$nextTick()
    await w.vm.$nextTick()
    expect(window.location.pathname).toBe('/')
  })

  it('mounting "/" with history but no id selects the most recent session', async () => {
    sessionRoutes([
      { id: 'sOld', title: '旧的', updated_at: '2026-01-01T00:00:00Z', pinned: false },
      { id: 'sTop', title: '最近', updated_at: '2026-10-10T09:00:00Z', pinned: true },
    ])
    const store = useAgentStore()
    mountView()
    await vi.waitFor(() => expect(store.sessionId).toBe('sTop'))
  })

  it('the header title renames inline through the store action', async () => {
    const store = useAgentStore()
    store.sessionsLoaded = true
    store.$patch({
      sessionId: 's1',
      sessions: [{ id: 's1', title: '会话甲' }],
      messages: [{ role: 'user', text: 'x' }],
    })
    const spy = vi.spyOn(store, 'renameSession').mockImplementation(async () => {})
    const w = mountView()
    await w.get('[data-testid="title-edit"]').trigger('click')
    await w.get('[data-testid="title-input"]').setValue('新名')
    await w.get('[data-testid="title-confirm"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s1', '新名')
  })

  it('share copies the deep link; export downloads the chat as JSON', async () => {
    const writeText = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const createObjectURL = vi.fn(() => 'blob:export')
    window.URL.createObjectURL = createObjectURL
    window.URL.revokeObjectURL = vi.fn()
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const store = useAgentStore()
    store.$patch({
      sessionId: 's1',
      messages: [
        { role: 'user', text: '问' },
        { role: 'assistant', text: '答', streaming: false },
      ],
    })
    const w = mountView()
    await w.get('[data-testid="share-button"]').trigger('click')
    expect(writeText.mock.calls[0][0]).toContain('/chat/s1')
    await w.get('[data-testid="export-button"]').trigger('click')
    expect(createObjectURL).toHaveBeenCalled()
    expect(anchorClick).toHaveBeenCalled()
  })

  it('clear resets the current view to a blank session and toasts the truth', async () => {
    const store = useAgentStore()
    store.sessionsLoaded = true
    store.$patch({ sessionId: 's1', messages: [{ role: 'user', text: 'x' }] })
    const w = mountView()
    await w.get('[data-testid="clear-button"]').trigger('click')
    expect(store.sessionId).toBeNull()
    expect(store.messages).toEqual([])
    expect(useToastStore().items.length).toBeGreaterThan(0)
  })

  it('an error renders an inline card whose retry re-runs the last question', async () => {
    const store = useAgentStore()
    store.$patch({
      status: 'error',
      sessionId: 's1',
      error: '发送失败：boom',
      messages: [{ role: 'user', text: '问题' }],
    })
    const regen = vi.spyOn(store, 'regenerate').mockImplementation(async () => {})
    const w = mountView()
    expect(w.find('[data-testid="error-card"]').exists()).toBe(true)
    expect(w.text()).toContain('boom')
    await w.get('[data-testid="error-retry"]').trigger('click')
    expect(regen).toHaveBeenCalled()
  })

  it('the mode segments switch the run mode', async () => {
    const ui = useUiStore()
    const w = mountView()
    await w.get('[data-testid="mode-seg-full_access"]').trigger('click')
    expect(ui.mode).toBe('full_access')
    await w.get('[data-testid="mode-seg-review"]').trigger('click')
    expect(ui.mode).toBe('review')
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
