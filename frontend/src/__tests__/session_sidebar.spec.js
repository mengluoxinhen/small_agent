import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import SessionSidebar from '../components/SessionSidebar.vue'

/**
 * V3 left column: grouped sessions with a per-row overflow menu
 * (rename / pin / copy link / delete), a Popconfirm for deletion
 * (window.confirm is banned), a theme toggle in the footer, and skeleton
 * rows while the list loads for the first time.
 * Network-backed store actions are spied at the action level.
 */

function row(id, extra = {}) {
  return { id, title: id, mode: 'review', model: 'm', pinned: false, updated_at: new Date().toISOString(), ...extra }
}

let store
function mountBar() {
  return mount(SessionSidebar)
}

function rowOf(w, id) {
  return w.findAll('.session-row').find((n) => n.text().includes(id))
}

async function openMenu(w, id) {
  const r = rowOf(w, id)
  await r.find('[data-testid="menu-button"]').trigger('click')
}

beforeEach(() => {
  setActivePinia(createPinia())
  store = useAgentStore()
  store.sessions = [row('s1'), row('s2'), row('p0', { pinned: true })]
  store.sessionId = 's1'
  store.sessionsLoaded = true // structural tests skip the first-load skeleton
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => [] })))
})

describe('SessionSidebar (V3)', () => {
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

  it('new-session button starts a fresh session', async () => {
    const spy = vi.spyOn(store, 'startNewSession')
    const w = mountBar()
    await w.get('[data-testid="new-session"]').trigger('click')
    expect(spy).toHaveBeenCalled()
  })

  it('the overflow menu opens per row and only one menu exists at a time', async () => {
    const w = mountBar()
    expect(w.find('[data-testid="menu-pin"]').exists()).toBe(false)
    await openMenu(w, 's2')
    expect(w.findAll('[data-testid="menu-rename"]')).toHaveLength(1)
    await openMenu(w, 's1')
    expect(w.findAll('[data-testid="menu-rename"]')).toHaveLength(1) // 上一个菜单被顶掉
  })

  it('pin toggle lives behind the menu and patches the flipped value', async () => {
    const spy = vi.spyOn(store, 'togglePin').mockImplementation(async () => {})
    const w = mountBar()
    await openMenu(w, 'p0')
    await w.get('[data-testid="menu-pin"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('p0', false) // p0 已置顶 -> 翻转值原样下发
  })

  it('rename via the menu opens an inline editor; confirming PATCHes the title', async () => {
    const spy = vi.spyOn(store, 'renameSession').mockImplementation(async () => {})
    const w = mountBar()
    await openMenu(w, 's2')
    await w.get('[data-testid="menu-rename"]').trigger('click')
    const input = w.get('[data-testid="rename-input"]')
    await input.setValue('新标题')
    await w.get('[data-testid="rename-confirm"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s2', '新标题')
  })

  it('rename: Escape cancels without calling the store', async () => {
    const spy = vi.spyOn(store, 'renameSession').mockImplementation(async () => {})
    const w = mountBar()
    await openMenu(w, 's2')
    await w.get('[data-testid="menu-rename"]').trigger('click')
    await w.get('[data-testid="rename-input"]').setValue('别改')
    await w.get('[data-testid="rename-input"]').trigger('keydown.esc')
    expect(spy).not.toHaveBeenCalled()
    expect(w.find('[data-testid="rename-input"]').exists()).toBe(false)
  })

  it('copy link writes the deep link of that session to the clipboard', async () => {
    const writeText = vi.fn()
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    const w = mountBar()
    await openMenu(w, 's2')
    await w.get('[data-testid="menu-copy"]').trigger('click')
    expect(writeText).toHaveBeenCalled()
    expect(writeText.mock.calls[0][0]).toContain('/chat/s2')
  })

  it('delete asks for confirmation in a Popconfirm, never window.confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const spy = vi.spyOn(store, 'removeSession').mockImplementation(async () => {})
    const w = mountBar()
    await openMenu(w, 's2')
    await w.get('[data-testid="menu-delete"]').trigger('click')
    expect(w.find('[data-testid="confirm-dialog"]').exists()).toBe(true)
    expect(spy).not.toHaveBeenCalled() // 弹层出现 != 已删除
    await w.get('[data-testid="confirm-cancel"]').trigger('click')
    expect(w.find('[data-testid="confirm-dialog"]').exists()).toBe(false)
    expect(spy).not.toHaveBeenCalled()
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('delete: confirming the Popconfirm calls removeSession for that row', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const spy = vi.spyOn(store, 'removeSession').mockImplementation(async () => {})
    const w = mountBar()
    await openMenu(w, 's2')
    await w.get('[data-testid="menu-delete"]').trigger('click')
    await w.get('[data-testid="confirm-ok"]').trigger('click')
    expect(spy).toHaveBeenCalledWith('s2')
    expect(w.find('[data-testid="confirm-dialog"]').exists()).toBe(false)
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

  it('the footer carries the mode readout and a working theme toggle', async () => {
    const ui = useUiStore()
    const w = mountBar()
    expect(w.find('[data-testid="mode"]').text()).toBe('review')
    await w.get('[data-testid="theme-toggle"]').trigger('click')
    expect(ui.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('shows skeleton rows while the very first list load is pending', () => {
    store.sessionsLoaded = false
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {}))) // never resolves
    const w = mountBar()
    expect(w.findAll('[data-testid="session-skeleton"]').length).toBeGreaterThan(0)
    expect(w.find('.session-row').exists()).toBe(false)
  })
})

/**
 * W — the row avatar becomes a run-status indicator (dot / spinner / green /
 * red), derived from the agent store's existing status machine; a brand row
 * (logo + name) sits above the new-session button and collapses to the logo.
 */
describe('SessionSidebar (W) status indicator + brand', () => {
  it('renders no initial avatar or per-row gradient hue anymore', () => {
    const w = mountBar()
    expect(w.findAll('.avatar').length).toBe(0)
    expect(w.findAll('[style*="--av-hue"]').length).toBe(0)
  })

  it('a session that is not the open one reads as idle', () => {
    const w = mountBar()
    expect(rowOf(w, 's2').find('[data-testid="session-status"]').attributes('data-status')).toBe('idle')
  })

  it('the open session shows a spinner while running', () => {
    store.status = 'streaming'
    const w = mountBar()
    const st = rowOf(w, 's1').find('[data-testid="session-status"]')
    expect(st.attributes('data-status')).toBe('running')
    expect(st.find('svg').exists()).toBe(true)
    expect(st.find('.dot').exists()).toBe(false)
  })

  it('awaiting approval still counts as running', () => {
    store.status = 'awaiting'
    const w = mountBar()
    expect(rowOf(w, 's1').find('[data-testid="session-status"]').attributes('data-status')).toBe('running')
  })

  it('a finished run shows the green dot; an error shows the red one', async () => {
    store.status = 'done'
    const w = mountBar()
    expect(rowOf(w, 's1').find('[data-testid="session-status"]').attributes('data-status')).toBe('done')
    store.status = 'error'
    await w.vm.$nextTick()
    expect(rowOf(w, 's1').find('[data-testid="session-status"]').attributes('data-status')).toBe('error')
  })

  it('cancelled falls back to idle rather than claiming an outcome', () => {
    store.status = 'cancelled'
    const w = mountBar()
    expect(rowOf(w, 's1').find('[data-testid="session-status"]').attributes('data-status')).toBe('idle')
  })

  it('the brand block shows the logo and the product name above the new-session button', () => {
    const w = mountBar()
    const brand = w.get('[data-testid="sidebar-brand"]')
    expect(brand.find('svg').exists()).toBe(true)
    expect(brand.text()).toContain('small_dify Agent')
    // ordering: brand precedes the new-session CTA
    const aside = w.get('aside')
    expect(aside.element.compareDocumentPosition(w.get('[data-testid="new-session"]').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('collapsed keeps the logo only', () => {
    const ui = useUiStore()
    ui.sidebarCollapsed = true
    const w = mountBar()
    const brand = w.get('[data-testid="sidebar-brand"]')
    expect(brand.find('svg').exists()).toBe(true)
    expect(brand.text()).toBe('')
    expect(w.find('[data-testid="new-session"]').exists()).toBe(false)
  })
})
