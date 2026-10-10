import { defineStore } from 'pinia'

/**
 * V6 global feedback channel. Components push short-lived notifications here
 * instead of the banned window.alert/confirm; ToastHost renders the stack in the
 * top-right corner. Every toast carries its own expiry timer so the corner never
 * accumulates stale state — `dismiss` is for the explicit close button.
 */

let seq = 0

export const DEFAULT_TTL = 4000

export const useToastStore = defineStore('toast', {
  state: () => ({
    items: [], // [{id, kind: 'info'|'success'|'error', text}]
  }),
  actions: {
    push(text, kind = 'info', ttl = DEFAULT_TTL) {
      const id = ++seq
      this.items.push({ id, kind, text })
      setTimeout(() => this.dismiss(id), ttl)
      return id
    },
    dismiss(id) {
      const idx = this.items.findIndex((t) => t.id === id)
      if (idx >= 0) this.items.splice(idx, 1)
    },
  },
})
