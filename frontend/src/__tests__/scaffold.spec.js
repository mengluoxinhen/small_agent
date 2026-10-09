import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import App from '../App.vue'
import { useUiStore } from '../stores/ui'

describe('P0 scaffold', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('mounts the app shell and shows the default run mode', () => {
    const wrapper = mount(App, { global: { plugins: [createPinia()] } })
    expect(wrapper.text()).toContain('small_dify Agent')
    expect(wrapper.get('[data-testid="mode"]').text()).toBe('review')
  })

  it('defaults to the safer review mode', () => {
    expect(useUiStore().mode).toBe('review')
  })

  it('switches to full_access and rejects unknown modes', () => {
    const ui = useUiStore()
    ui.setMode('full_access')
    expect(ui.mode).toBe('full_access')
    expect(() => ui.setMode('yolo')).toThrow('unknown run mode')
  })
})
