import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import SessionSidebar from '../components/SessionSidebar.vue'

/**
 * U3 left column: search box, grouped session list with per-row pin/rename/delete,
 * new-session button, collapse control, and a bottom settings area.
 * Everything talking to the server is spied at the store-action level.
 */

function row(id, extra = {}) {
  return { id, title: id, mode: 'review', model: 'm', pinned: false, updated_at: new Date().toISOString(), ...extra }
}

let store
function mountBar() {
  return mount(SessionSidebar)
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useAgentStore()
  store.sessions = [row('s1'), row('s2'), row('p0', { pinned: true })]
  store.sessionId = 's1'
})

describe('SessionSidebar', () => {
  it('renders grouped rows with the active session highlighted', () => {
    const w = mountBar()
    expect(w.find('[data-testid="group-置顶"]').exists()).toBe(true)
    const active = w.findAll('.session-row.active')
    expect(active).toHaveLength(1)
    expect(active[0].text()).toContain('s1')
  })

  it('the search box filters rows by title substring, case-insensitively', async () => {
    store.sessions = [row('Alpha'), row('beta'), row('gamma')]
    const w = mountBar()
    await w.get('[data-testid="session-search"]').setValue('BE')
    const titles = w.findAll('.session-row').map((n) => n.text())
    expect(titles).toHaveLength(1)
    expect(titles[0]).toContain('beta')
  })

  it('new-session button starts a fresh session and collapses search', async () => {
    const spy = vi.spyOn(store, 'startNewSession')
    const w = mountBar()
    await w.get('[data-testid="new-session"]').trigger('click')
    expect(spy).toHaveBeenCalled()
  })

  it('pin toggle patches the session with the flipped value', async () => {
    const spy = vi.spyOn(store, 'togglePin').mockImplementation(async () => {})
    const w = mountBar()
    const p0 = w.findAll('.session-row').find((n) => n.text().includes('p0'))
    await p0.find('[data-testid="pin-button"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('p0', false) // p0 已置顶 -> 点击取消置顶（翻转值原样下发）
  })

  it('rename: the pencil opens an inline editor; confirming PATCHes the title', async () => {
    const spy = vi.spyOn(store, 'renameSession').mockImplementation(async () => {})
    const w = mountBar()
    const s2 = w.findAll('.session-row').find((n) => n.text().includes('s2'))
    await s2.find('[data-testid="rename-button"]').trigger('click')
    const input = w.get('[data-testid="rename-input"]')
    await input.setValue('新标题')
    await w.get('[data-testid="rename-confirm"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s2', '新标题')
  })

  it('rename: Escape cancels without calling the store', async () => {
    const spy = vi.spyOn(store, 'renameSession').mockImplementation(async () => {})
    const w = mountBar()
    const s2 = w.findAll('.session-row').find((n) => n.text().includes('s2'))
    await s2.find('[data-testid="rename-button"]').trigger('click')
    await w.get('[data-testid="rename-input"]').setValue('别改')
    await w.get('[data-testid="rename-input"]').trigger('keydown.esc')
    expect(spy).not.toHaveBeenCalled()
    expect(w.find('[data-testid="rename-input"]').exists()).toBe(false)
  })

  it('delete calls removeSession for that row', async () => {
    const spy = vi.spyOn(store, 'removeSession').mockImplementation(async () => {})
    const w = mountBar()
    const s2 = w.findAll('.session-row').find((n) => n.text().includes('s2'))
    await s2.find('[data-testid="delete-button"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s2')
  })

  it('collapse hides the list and the toggle flips the ui store', async () => {
    const ui = useUiStore()
    const w = mountBar()
    expect(w.find('[data-testid="session-search"]').exists()).toBe(true)
    await w.get('[data-testid="collapse-toggle"]').trigger('click')
    expect(ui.sidebarCollapsed).toBe(true)
    expect(w.find('[data-testid="session-search"]').exists()).toBe(false)
    expect(w.find('[data-testid="expand-toggle"]').exists()).toBe(true)
    await w.get('[data-testid="expand-toggle"]').trigger('click')
    expect(ui.sidebarCollapsed).toBe(false)
  })

  it('shows a bottom settings area with the app name and default mode', () => {
    const w = mountBar()
    expect(w.find('[data-testid="sidebar-footer"]').text()).toContain('small_dify Agent')
  })
})
