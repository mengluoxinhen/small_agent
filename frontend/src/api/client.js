/**
 * Thin fetch wrapper over the FastAPI contract (PLAN §6), reached through the
 * vite `/api` proxy (which strips the prefix before hitting the backend).
 */

const BASE = '/api'

async function request(path, { method = 'GET', body } = {}) {
  const resp = await fetch(BASE + path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (resp.status === 204) return null
  let data = null
  try {
    data = await resp.json()
  } catch {
    data = null
  }
  if (!resp.ok) {
    const detail = data && typeof data.detail === 'string' ? data.detail : resp.statusText
    throw new Error(`${method} ${path} -> ${resp.status}: ${detail}`)
  }
  return data
}

export const api = {
  listSessions: () => request('/sessions'),
  getSession: (id) => request(`/sessions/${id}`),
  createSession: (payload) => request('/sessions', { method: 'POST', body: payload }),
  patchSession: (id, payload) => request(`/sessions/${id}`, { method: 'PATCH', body: payload }),
  deleteSession: (id) => request(`/sessions/${id}`, { method: 'DELETE' }),
  sendMessage: (id, text) => request(`/sessions/${id}/messages`, { method: 'POST', body: { text } }),
  // body shape the backend expects: { "<approval_id>": {decision, always?, reason?} }
  decideApprovals: (runId, decisions) => request(`/runs/${runId}/approvals`, { method: 'POST', body: decisions }),
  cancelRun: (runId) => request(`/runs/${runId}/cancel`, { method: 'POST' }),
  fetchEvents: (sid) => request(`/sessions/${sid}/events?format=json`),
  // U3 attachment upload: { filename, content_base64 } -> { filename, bytes }
  uploadSessionFile: (sid, payload) => request(`/sessions/${sid}/files`, { method: 'POST', body: payload }),
}
