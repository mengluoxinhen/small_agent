import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TracePanel from '../components/TracePanel.vue'

/**
 * P7 red list: TracePanel renders the tool steps collected by the store,
 * collapses details behind a click, and shows per-step duration + ok/fail state.
 */

const OK_STEP = {
  kind: 'tool',
  call_id: 'c1',
  tool: 'calculator',
  risk: 'read',
  args: '{"expression":"6*7"}',
  result: { ok: true, output: '42', duration_ms: 12.3 },
}

const FAILED_STEP = {
  kind: 'tool',
  call_id: 'c2',
  tool: 'write_text_file',
  risk: 'write',
  args: '{"filename":"../evil.txt"}',
  result: { ok: false, output: '工具 write_text_file 调用失败：路径越界。', duration_ms: 3.4 },
}

const PENDING_STEP = { kind: 'tool', call_id: 'c3', tool: 'read_text_file', risk: 'read', args: '', result: null }

function mountPanel(trace) {
  return mount(TracePanel, { props: { trace } })
}

describe('TracePanel', () => {
  it('renders one step per trace entry with the tool name', () => {
    const wrapper = mountPanel([OK_STEP, FAILED_STEP])
    const steps = wrapper.findAll('[data-testid="trace-step"]')
    expect(steps).toHaveLength(2)
    expect(steps[0].text()).toContain('calculator')
    expect(steps[1].text()).toContain('write_text_file')
  })

  it('keeps args and output collapsed until the step is clicked', async () => {
    const wrapper = mountPanel([OK_STEP])
    expect(wrapper.text()).not.toContain('6*7')
    await wrapper.find('[data-testid="trace-step"]').trigger('click')
    expect(wrapper.text()).toContain('{"expression":"6*7"}')
    expect(wrapper.text()).toContain('42')
    await wrapper.find('[data-testid="trace-step"]').trigger('click')
    expect(wrapper.text()).not.toContain('6*7')
  })

  it('formats the duration in milliseconds', () => {
    const wrapper = mountPanel([OK_STEP])
    expect(wrapper.find('[data-testid="trace-step"]').text()).toContain('12.3 ms')
  })

  it('marks failed steps and leaves running steps without a result', () => {
    const wrapper = mountPanel([OK_STEP, FAILED_STEP, PENDING_STEP])
    const steps = wrapper.findAll('[data-testid="trace-step"]')
    expect(steps[1].classes()).toContain('failed')
    expect(steps[0].classes()).not.toContain('failed')
    expect(steps[2].classes()).toContain('pending')
  })

  it('U3: exposes a four-state status per step via data-status', () => {
    const wrapper = mountPanel([
      { kind: 'tool', call_id: 'z', tool: '', risk: '', args: '', result: null }, // 已排队未开跑
      PENDING_STEP, // 有工具名、无结果 → running
      OK_STEP,
      FAILED_STEP,
    ])
    const statuses = wrapper.findAll('[data-testid="trace-step"]').map((n) => n.attributes('data-status'))
    expect(statuses).toEqual(['pending', 'running', 'success', 'error'])
  })

  it('U3: an empty trace can suppress the default title (embedded mode)', () => {
    const wrapper = mount(TracePanel, { props: { trace: [], title: '' } })
    expect(wrapper.text()).not.toContain('执行轨迹')
  })

  it('shows a placeholder when the trace is empty', () => {
    const wrapper = mountPanel([])
    expect(wrapper.findAll('[data-testid="trace-step"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('执行轨迹')
  })
})
