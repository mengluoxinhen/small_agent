import { describe, it, expect } from 'vitest'
import { groupSessions } from '../utils/groups'

/**
 * U3/V3: the sidebar groups sessions by recency (pinned first). Pure function so the
 * grouping rules are tested without any DOM. `updated_at` is a UTC ISO string from
 * the backend; `now` is injected for determinism.
 *
 * V3 refines the buckets to 置顶 / 今天 / 昨天 / 7 天内 / 更早 where 今天/昨天
 * are CALENDAR days in the user's LOCAL timezone against `now` — fixtures are
 * therefore built with local Date constructors so the verdict never depends on
 * the machine's TZ.
 */

const NOW = new Date(2026, 9, 10, 12, 0, 0) // 2026-10-10 12:00, local

function s(id, { pinned = false, hoursAgo = 0 } = {}) {
  return { id, title: id, pinned, updated_at: new Date(NOW - hoursAgo * 3600e3).toISOString() }
}

describe('groupSessions', () => {
  it('returns nothing for an empty list', () => {
    expect(groupSessions([], NOW)).toEqual([])
  })

  it('puts a 置顶 group first and keeps server order inside groups', () => {
    const groups = groupSessions(
      [s('p1', { pinned: true }), s('t1', { hoursAgo: 1 }), s('p2', { pinned: true })],
      NOW,
    )
    expect(groups.map((g) => g.label)).toEqual(['置顶', '今天'])
    expect(groups[0].items.map((x) => x.id)).toEqual(['p1', 'p2'])
  })

  it('splits 今天 / 昨天 / 7 天内 / 更早 by updated_at', () => {
    const groups = groupSessions(
      [
        s('today', { hoursAgo: 3 }),
        s('yday', { hoursAgo: 26 }),
        s('week', { hoursAgo: 80 }),
        s('old', { hoursAgo: 200 }),
      ],
      NOW,
    )
    expect(groups.map((g) => [g.label, g.items.map((x) => x.id)])).toEqual([
      ['今天', ['today']],
      ['昨天', ['yday']],
      ['7 天内', ['week']],
      ['更早', ['old']],
    ])
  })

  it('a session late last night is 昨天 even if <24h ago, and one just past midnight is 今天', () => {
    const groups = groupSessions(
      [
        { id: 'just-after-midnight', updated_at: new Date(2026, 9, 10, 0, 30).toISOString() },
        { id: 'late-last-night', updated_at: new Date(2026, 9, 9, 23, 30).toISOString() },
      ],
      new Date(2026, 9, 10, 1, 0),
    )
    const byId = Object.fromEntries(groups.flatMap((g) => g.items.map((x) => [x.id, g.label])))
    expect(byId['just-after-midnight']).toBe('今天')
    expect(byId['late-last-night']).toBe('昨天')
  })

  it('a pinned session appears only in the pinned group', () => {
    const groups = groupSessions([s('x', { pinned: true, hoursAgo: 100 })], NOW)
    expect(groups).toHaveLength(1)
    expect(groups[0].label).toBe('置顶')
  })

  it('missing or broken timestamps fall back to 更早 without crashing', () => {
    const groups = groupSessions([{ id: 'z', title: 'z', pinned: false }], NOW)
    expect(groups.map((g) => g.label)).toEqual(['更早'])
  })
})
