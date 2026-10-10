import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useToastStore } from '../stores/toast'

/**
 * V6: one global feedback channel — components push toasts instead of the banned
 * window.alert/confirm. Toasts expire on their own so the corner never accumulates
 * stale notifications.
 */

beforeEach(() => {
  vi.useFakeTimers()
  setActivePinia(createPinia())
})
afterEach(() => {
  vi.useRealTimers()
})

describe('toast store', () => {
  it('push appends an item with a unique id and the requested kind', () => {
    const t = useToastStore()
    const a = t.push('已复制会话链接', 'success')
    const b = t.push('网络开小差了', 'error')
    expect(t.items.map((x) => [x.kind, x.text])).toEqual([
      ['success', '已复制会话链接'],
      ['error', '网络开小差了'],
    ])
    expect(a).not.toBe(b)
  })

  it('dismiss removes just that toast', () => {
    const t = useToastStore()
    const a = t.push('一')
    t.push('二')
    t.dismiss(a)
    expect(t.items.map((x) => x.text)).toEqual(['二'])
  })

  it('toasts auto-expire after their ttl', () => {
    const t = useToastStore()
    t.push('会自动消失', 'info', 2000)
    vi.advanceTimersByTime(1999)
    expect(t.items).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(t.items).toHaveLength(0)
  })

  it('the default ttl still expires', () => {
    const t = useToastStore()
    t.push('默认时长')
    vi.advanceTimersByTime(5000)
    expect(t.items).toHaveLength(0)
  })
})
