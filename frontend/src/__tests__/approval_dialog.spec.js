import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ApprovalDialog from '../components/ApprovalDialog.vue'

/**
 * P7 red list: the approval dialog shows what the tool is about to do and emits
 * exactly the three decision payloads the backend understands (PLAN §6/§7):
 *   {decision:'approve'} / {decision:'approve',always:true} / {decision:'reject',reason}
 */

const APPROVAL = {
  approval_id: 'a1',
  tool: 'write_text_file',
  arguments: { filename: 'a.txt', content: '机密内容' },
  risk: 'write',
}

function mountDialog() {
  return mount(ApprovalDialog, { props: { approval: APPROVAL } })
}

function emittedDecide(wrapper) {
  const events = wrapper.emitted('decide')
  expect(events, 'decide was never emitted').toHaveLength(1)
  return events[0][0]
}

describe('ApprovalDialog', () => {
  it('shows the tool, its risk and the arguments awaiting confirmation', () => {
    const wrapper = mountDialog()
    expect(wrapper.text()).toContain('write_text_file')
    expect(wrapper.text()).toContain('write')
    expect(wrapper.text()).toContain('a.txt')
    expect(wrapper.text()).toContain('机密内容')
  })

  it('emits the plain approve payload', async () => {
    const wrapper = mountDialog()
    await wrapper.get('[data-testid="approve"]').trigger('click')
    expect(emittedDecide(wrapper)).toEqual({ decision: 'approve' })
  })

  it('emits the always-approve payload', async () => {
    const wrapper = mountDialog()
    await wrapper.get('[data-testid="approve-always"]').trigger('click')
    expect(emittedDecide(wrapper)).toEqual({ decision: 'approve', always: true })
  })

  it('emits the reject payload with the typed reason', async () => {
    const wrapper = mountDialog()
    await wrapper.get('[data-testid="reject-reason"]').setValue('不要动我的文件')
    await wrapper.get('[data-testid="reject"]').trigger('click')
    expect(emittedDecide(wrapper)).toEqual({ decision: 'reject', reason: '不要动我的文件' })
  })

  it('rejects with an empty reason when nothing was typed', async () => {
    const wrapper = mountDialog()
    await wrapper.get('[data-testid="reject"]').trigger('click')
    expect(emittedDecide(wrapper)).toEqual({ decision: 'reject', reason: '' })
  })
})
