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
})
