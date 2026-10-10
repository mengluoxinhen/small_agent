import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useUiStore } from '../stores/ui'

/**
 * V1/V2: theme and sidebar geometry live in the ui store and survive a reload
 * through localStorage. The *effective* theme lands synchronously on
 * document.documentElement.dataset.theme — that is what prevents the white flash
 * on switch, and what styles/theme.css keys off.
 */

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  setActivePinia(createPinia())
})

describe('ui store — theme', () => {
  it('defaults to the system choice with a 280px sidebar', () => {
    const ui = useUiStore()
    expect(ui.theme).toBe('system')
    expect(ui.sidebarWidth).toBe(280)
  })

  it('explicit dark/light applies to the document and persists', () => {
    const ui = useUiStore()
    ui.setTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('ui.theme')).toBe('dark')
    ui.setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('ui.theme')).toBe('light')
  })

  it('system falls back to light in jsdom (no matchMedia) and persists as system', () => {
    const ui = useUiStore()
    ui.setTheme('system')
    expect(localStorage.getItem('ui.theme')).toBe('system')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('toggleTheme flips light <-> dark from the effective value', () => {
    const ui = useUiStore()
    ui.setTheme('system')
    ui.toggleTheme() // 有效值 light -> 显式 dark
    expect(ui.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    ui.toggleTheme()
    expect(ui.theme).toBe('light')
  })

  it('rejects unknown themes', () => {
    const ui = useUiStore()
    expect(() => ui.setTheme('neon')).toThrow('unknown theme')
  })

  it('restores persisted prefs on a fresh store (reload simulation)', () => {
    localStorage.setItem('ui.theme', 'dark')
    localStorage.setItem('ui.sidebarWidth', '320')
    setActivePinia(createPinia())
    const ui = useUiStore()
    expect(ui.theme).toBe('dark')
    expect(ui.sidebarWidth).toBe(320)
    ui.applyTheme()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})

describe('ui store — sidebar geometry & drawer', () => {
  it('clamps the width to 240..360 and persists', () => {
    const ui = useUiStore()
    ui.setSidebarWidth(500)
    expect(ui.sidebarWidth).toBe(360)
    expect(localStorage.getItem('ui.sidebarWidth')).toBe('360')
    ui.setSidebarWidth(100)
    expect(ui.sidebarWidth).toBe(240)
    ui.setSidebarWidth(312.7)
    expect(ui.sidebarWidth).toBe(313)
  })

  it('a corrupted stored width falls back to 280', () => {
    localStorage.setItem('ui.sidebarWidth', 'wide')
    setActivePinia(createPinia())
    const ui = useUiStore()
    expect(ui.sidebarWidth).toBe(280)
  })

  it('drawer open state is separate from desktop collapse', () => {
    const ui = useUiStore()
    expect(ui.drawerOpen).toBe(false)
    ui.openDrawer()
    expect(ui.drawerOpen).toBe(true)
    ui.closeDrawer()
    ui.toggleDrawer()
    expect(ui.drawerOpen).toBe(true)
  })
})
