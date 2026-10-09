import { defineStore } from 'pinia'

/**
 * UI-level state that the backend also cares about.
 *
 * `mode` mirrors the backend's two run modes:
 *   review      - low-risk tools auto-approve, write/dangerous tools pause for confirmation
 *   full_access - every tool executes immediately
 */
export const useUiStore = defineStore('ui', {
  state: () => ({
    mode: 'review',
    modes: ['review', 'full_access'],
  }),
  actions: {
    setMode(mode) {
      if (!this.modes.includes(mode)) {
        throw new Error(`unknown run mode: ${mode}`)
      }
      this.mode = mode
    },
  },
})
