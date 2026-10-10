import { defineStore } from 'pinia'

/**
 * UI-level state that the backend also cares about.
 *
 * `mode` mirrors the backend's two run modes:
 *   review      - low-risk tools auto-approve, write/dangerous tools pause for confirmation
 *   full_access - every tool executes immediately
 *
 * V1/V2 adds the look-and-feel preferences: `theme` (system|light|dark) and the
 * sidebar geometry. Both persist through localStorage and must survive a reload;
 * the *effective* theme lands synchronously on document.documentElement.dataset
 * so styles/theme.css can flip every token in one paint (no white flash).
 */

export const MIN_SIDEBAR_WIDTH = 240
export const MAX_SIDEBAR_WIDTH = 360

const THEME_KEY = 'ui.theme'
const WIDTH_KEY = 'ui.sidebarWidth'
const THEMES = ['system', 'light', 'dark']

function readTheme() {
  try {
    const t = localStorage.getItem(THEME_KEY)
    return THEMES.includes(t) ? t : 'system'
  } catch {
    return 'system'
  }
}

function clampWidth(w) {
  return Math.max(MIN_SIDEBAR_WIDTH, Math.min(MAX_SIDEBAR_WIDTH, Math.round(w)))
}

function readWidth() {
  try {
    const raw = Number(localStorage.getItem(WIDTH_KEY))
    return Number.isFinite(raw) && raw > 0 ? clampWidth(raw) : 280
  } catch {
    return 280
  }
}

function persist(key, value) {
  try {
    localStorage.setItem(key, String(value))
  } catch {
    /* private mode / storage full: the preference just won't survive a reload */
  }
}

function systemPrefersDark() {
  return Boolean(typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)')?.matches)
}

export const useUiStore = defineStore('ui', {
  state: () => ({
    mode: 'review',
    modes: ['review', 'full_access'],
    sidebarCollapsed: false,
    theme: readTheme(),
    sidebarWidth: readWidth(),
    drawerOpen: false, // mobile <768px overlay drawer, independent of the desktop collapse
  }),
  getters: {
    effectiveTheme: (s) => (s.theme === 'system' ? (systemPrefersDark() ? 'dark' : 'light') : s.theme),
  },
  actions: {
    setMode(mode) {
      if (!this.modes.includes(mode)) {
        throw new Error(`unknown run mode: ${mode}`)
      }
      this.mode = mode
    },
    toggleSidebar() {
      this.sidebarCollapsed = !this.sidebarCollapsed
    },
    applyTheme() {
      document.documentElement.dataset.theme = this.effectiveTheme
    },
    setTheme(theme) {
      if (!THEMES.includes(theme)) {
        throw new Error(`unknown theme: ${theme}`)
      }
      this.theme = theme
      persist(THEME_KEY, theme)
      this.applyTheme()
    },
    toggleTheme() {
      this.setTheme(this.effectiveTheme === 'dark' ? 'light' : 'dark')
    },
    /** Keep an explicit "follow system" honest when the OS flips after boot. */
    watchSystemTheme() {
      window
        .matchMedia?.('(prefers-color-scheme: dark)')
        ?.addEventListener?.('change', () => this.theme === 'system' && this.applyTheme())
    },
    setSidebarWidth(w) {
      this.sidebarWidth = clampWidth(Number(w) || MIN_SIDEBAR_WIDTH)
      persist(WIDTH_KEY, this.sidebarWidth)
    },
    openDrawer() {
      this.drawerOpen = true
    },
    closeDrawer() {
      this.drawerOpen = false
    },
    toggleDrawer() {
      this.drawerOpen = !this.drawerOpen
    },
  },
})
