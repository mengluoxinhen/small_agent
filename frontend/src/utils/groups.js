/**
 * V3 sidebar grouping: pinned first, then by *calendar day* recency of
 * `updated_at` (今天/昨天 are local-day boundaries, not rolling 24h windows —
 * a session from 23:30 yesterday is 昨天 even though it is <24h ago).
 * The server already returns sessions ordered pinned-first / newest-first,
 * so this only buckets them and preserves the incoming order inside a bucket.
 */

const DAY_MS = 24 * 60 * 60 * 1000

function startOfDay(ms) {
  const d = new Date(ms)
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()
}

export function groupSessions(sessions, now = new Date()) {
  const buckets = { pinned: [], today: [], yesterday: [], week: [], earlier: [] }
  const today0 = startOfDay(now.getTime())
  for (const s of sessions) {
    if (s.pinned) {
      buckets.pinned.push(s)
      continue
    }
    const touched = Date.parse(s.updated_at ?? '')
    if (Number.isNaN(touched)) {
      buckets.earlier.push(s)
      continue
    }
    const diffDays = Math.floor((today0 - startOfDay(touched)) / DAY_MS)
    if (diffDays <= 0) buckets.today.push(s)
    else if (diffDays === 1) buckets.yesterday.push(s)
    else if (diffDays < 7) buckets.week.push(s)
    else buckets.earlier.push(s)
  }
  return [
    ['置顶', buckets.pinned],
    ['今天', buckets.today],
    ['昨天', buckets.yesterday],
    ['7 天内', buckets.week],
    ['更早', buckets.earlier],
  ]
    .filter(([, items]) => items.length)
    .map(([label, items]) => ({ label, items }))
}
