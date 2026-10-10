/**
 * U3 sidebar grouping: pinned first, then by recency of `updated_at`.
 * The server already returns sessions ordered pinned-first / newest-first,
 * so this only buckets them and preserves the incoming order inside a bucket.
 */

const DAY_MS = 24 * 60 * 60 * 1000

export function groupSessions(sessions, now = new Date()) {
  const buckets = { pinned: [], today: [], week: [], earlier: [] }
  for (const s of sessions) {
    if (s.pinned) {
      buckets.pinned.push(s)
      continue
    }
    const touched = Date.parse(s.updated_at ?? '')
    if (Number.isNaN(touched)) buckets.earlier.push(s)
    else if (now - touched < DAY_MS) buckets.today.push(s)
    else if (now - touched < 7 * DAY_MS) buckets.week.push(s)
    else buckets.earlier.push(s)
  }
  return [
    ['置顶', buckets.pinned],
    ['今天', buckets.today],
    ['7 天内', buckets.week],
    ['更早', buckets.earlier],
  ]
    .filter(([, items]) => items.length)
    .map(([label, items]) => ({ label, items }))
}
