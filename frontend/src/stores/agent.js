import { defineStore } from 'pinia'
import { api } from '../api/client'
import { openStream } from '../api/sse'
import { useUiStore } from './ui'

/**
 * The single reducer of the SSE contract (PLAN §6): every persisted event lands
 * here via `applyEvent`, and the status machine is
 * idle -> streaming -> (awaiting -> streaming)* -> done | error | cancelled.
 *
 * The live EventSource handle stays OUTSIDE pinia state (a module-level ref):
 * proxies around a socket-like object only cause surprises, and there is exactly
 * one session stream at a time in this single-user app.
 */

let activeStream = null

export const useAgentStore = defineStore('agent', {
  state: () => ({
    status: 'idle',
    sessionId: null,
    sessionMode: null,
    runId: null,
    messages: [], // [{role, text, streaming?}]
    trace: [], // [{kind:'tool', call_id, tool, risk, args, result|null}]
    argsBuffer: {}, // call_id -> streamed argument deltas (may precede tool_call_start)
    pendingApproval: null,
    usage: null,
    turns: 0,
    error: null,
    lastEventId: 0,
    runAnchor: 0, // messages.length when the current run started; bubbles at/after it belong to this run
    sessions: [],
    attachments: [], // [{filename, bytes}] uploaded into the current session workspace
  }),
  actions: {
    // ---------------------------------------------------------- reducer

    beginLocalRun(runId) {
      this.runId = runId
      this.status = 'streaming'
      this.error = null
      this.pendingApproval = null
    },

    applyEvent(type, payload, seq) {
      if (typeof seq === 'number' && seq > this.lastEventId) this.lastEventId = seq
      switch (type) {
        case 'run_started':
          if (payload.run_id) this.runId = payload.run_id
          if (payload.mode) this.sessionMode = payload.mode
          this.status = 'streaming'
          this.error = null
          this.pendingApproval = null
          this.trace = [] // one run's steps belong to one answer bubble (U3)
          this.runAnchor = this.messages.length // bubbles created at/after this index are this run's
          break
        case 'user_message': {
          // live send() already pushed this bubble locally; history replay pushes here
          const last = this.messages.at(-1)
          if (!(last && last.role === 'user' && last.text === payload.text)) {
            this.messages.push({ role: 'user', text: payload.text ?? '' })
          }
          break
        }
        case 'text_message_content':
          this.appendDelta(payload.delta ?? '')
          break
        case 'tool_call_args': {
          const id = payload.call_id
          this.argsBuffer[id] = (this.argsBuffer[id] ?? '') + (payload.delta ?? '')
          break
        }
        case 'tool_call_start': {
          const step = this.ensureStep(payload.call_id)
          step.tool = payload.tool ?? step.tool
          step.risk = payload.risk ?? step.risk
          step.args = this.argsBuffer[payload.call_id] ?? step.args
          delete this.argsBuffer[payload.call_id]
          break
        }
        case 'tool_call_end':
          this.ensureStep(payload.call_id)
          break
        case 'tool_result': {
          const step = this.ensureStep(payload.call_id)
          step.result = {
            ok: payload.ok !== false,
            output: payload.output ?? '',
            duration_ms: payload.duration_ms ?? 0,
          }
          break
        }
        case 'approval_required':
          this.pendingApproval = payload
          this.status = 'awaiting'
          break
        case 'run_finished':
          this.status = 'done'
          this.usage = payload.usage ?? {}
          this.turns = payload.turns ?? 0
          this.pendingApproval = null
          this.closeStreaming()
          this.flushSteps()
          break
        case 'run_error':
          this.closeStreaming()
          this.flushSteps() // steps of an errored/cancelled run must stay visible too
          if (payload.kind === 'cancelled') {
            this.status = 'cancelled'
            this.error = null
          } else {
            this.status = 'error'
            this.error = `${payload.kind}: ${payload.message}`
          }
          break
        default:
          break
      }
    },

    appendDelta(delta) {
      const last = this.messages.at(-1)
      if (last && last.role === 'assistant' && last.streaming) {
        last.text += delta
      } else {
        this.messages.push({ role: 'assistant', text: delta, streaming: true })
      }
    },

    ensureStep(callId) {
      let step = this.trace.find((t) => t.kind === 'tool' && t.call_id === callId)
      if (!step) {
        step = { kind: 'tool', call_id: callId, tool: '', risk: '', args: '', result: null }
        this.trace.push(step)
      }
      return step
    },

    closeStreaming() {
      for (const m of this.messages) if (m.streaming) m.streaming = false
    },

    /**
     * U3: when a run ends, its tool steps move from the live trace onto the answer
     * bubble they produced, so every assistant message carries its own process.
     * A run that ended without any text still gets a (content-less) bubble to hold them.
     */
    flushSteps() {
      if (!this.trace.length) return
      const steps = this.trace
      this.trace = []
      this.argsBuffer = {}
      const idx = this.messages.length - 1
      const last = this.messages.at(-1)
      // attach only to a bubble THIS run created (index >= the run_started anchor),
      // otherwise a text-less run would graft its steps onto the previous answer
      if (idx >= this.runAnchor && last && last.role === 'assistant') {
        last.steps = steps
      } else {
        this.messages.push({ role: 'assistant', text: '', streaming: false, steps })
      }
    },

    // ---------------------------------------------------------- session plumbing

    resetStreamState() {
      this.status = 'idle'
      this.runId = null
      this.messages = []
      this.trace = []
      this.argsBuffer = {}
      this.attachments = []
      this.pendingApproval = null
      this.usage = null
      this.turns = 0
      this.error = null
      this.lastEventId = 0
      this.runAnchor = 0
    },

    async refreshSessions() {
      this.sessions = await api.listSessions()
    },

    async loadSession(sessionId) {
      if (activeStream) {
        activeStream.close()
        activeStream = null
      }
      const [events, row] = await Promise.all([api.fetchEvents(sessionId), api.getSession(sessionId)])
      this.resetStreamState()
      this.sessionId = sessionId
      for (const e of events) this.applyEvent(e.type, e.payload, e.seq)
      // the session row, not the historical run_started, owns the mode the server
      // will honor NEXT; sync the UI selector so the toggle never lies (P8 polish)
      if (row && row.mode) {
        this.sessionMode = row.mode
        const ui = useUiStore()
        if (ui.mode !== row.mode) ui.setMode(row.mode)
      }
    },

    async selectSession(sessionId) {
      await this.loadSession(sessionId)
    },

    startNewSession() {
      if (activeStream) {
        activeStream.close()
        activeStream = null
      }
      this.sessionId = null
      this.sessionMode = null
      this.resetStreamState()
    },

    connect() {
      if (activeStream) {
        activeStream.close()
        activeStream = null
      }
      if (!this.sessionId) return
      activeStream = openStream(
        this.sessionId,
        (evt) => this.applyEvent(evt.type, evt.payload, evt.seq),
        { lastEventId: this.lastEventId || null },
      )
    },

    // ---------------------------------------------------------- user actions
    //
    // Error boundary (P8): actions never bubble rejections into components.
    // A failed call lands in `store.error`; send/decide also leave the fake
    // "in-flight" state, while a failed cancel keeps the run status honest —
    // the stream is still open and may keep producing events.

    reportError(message) {
      this.error = message
    },

    async send(text) {
      const ui = useUiStore()
      // attachments already landed in the session workspace; tell the model their
      // exact filenames so it can read them with the file tools (U3)
      const note = this.attachments.length
        ? `\n（已上传附件：${this.attachments.map((a) => a.filename).join('、')}，可直接用文件名读取）`
        : ''
      const fullText = text + note
      try {
        if (!this.sessionId) {
          const session = await api.createSession({ title: text.slice(0, 24), mode: ui.mode })
          this.sessionId = session.id
          this.sessionMode = session.mode
        } else if (this.sessionMode !== ui.mode) {
          // the mode toggle only takes effect for the NEXT message: patch, then send
          const patched = await api.patchSession(this.sessionId, { mode: ui.mode })
          this.sessionMode = patched.mode
        }
        this.messages.push({ role: 'user', text: fullText })
        const { run_id: runId } = await api.sendMessage(this.sessionId, fullText)
        this.attachments = []
        this.beginLocalRun(runId)
        this.connect()
      } catch (err) {
        this.status = 'error'
        this.reportError(`发送失败：${err.message}`)
      }
    },

    async decide(decision) {
      if (!this.pendingApproval || !this.runId) return
      const approvalId = this.pendingApproval.approval_id
      try {
        await api.decideApprovals(this.runId, { [approvalId]: decision })
        this.pendingApproval = null
        this.status = 'streaming'
        this.connect() // resume tailing right after the pause event we already saw
      } catch (err) {
        // the pause is stale (e.g. 409: run already finished) — drop the dialog
        this.pendingApproval = null
        this.status = 'error'
        this.reportError(`审批提交失败：${err.message}`)
      }
    },

    async cancel() {
      if (!this.runId) return
      try {
        await api.cancelRun(this.runId)
        // the terminal run_error(kind=cancelled) arrives through the open stream
      } catch (err) {
        this.reportError(`取消未生效：${err.message}`)
      }
    },

    async removeSession(sessionId) {
      try {
        await api.deleteSession(sessionId)
        await this.refreshSessions()
        if (this.sessionId === sessionId) {
          // U3: deleting the current session lands on its neighbour, not on a blank
          const next = this.sessions[0]
          if (next) await this.loadSession(next.id)
          else this.startNewSession()
        }
      } catch (err) {
        this.reportError(`删除会话失败：${err.message}`)
      }
    },

    async renameSession(sessionId, title) {
      try {
        await api.patchSession(sessionId, { title })
        await this.refreshSessions()
      } catch (err) {
        this.reportError(`重命名失败：${err.message}`)
      }
    },

    async togglePin(sessionId, pinned) {
      try {
        // false must go on the wire as-is; the server coerces bool -> INTEGER
        await api.patchSession(sessionId, { pinned })
        await this.refreshSessions()
      } catch (err) {
        this.reportError(`置顶切换失败：${err.message}`)
      }
    },

    async uploadAttachment({ name, base64 }) {
      try {
        if (!this.sessionId) {
          const session = await api.createSession({ title: name.slice(0, 24), mode: useUiStore().mode })
          this.sessionId = session.id
          this.sessionMode = session.mode
        }
        const chip = await api.uploadSessionFile(this.sessionId, { filename: name, content_base64: base64 })
        this.attachments.push(chip)
      } catch (err) {
        this.reportError(`附件上传失败：${err.message}`)
      }
    },

    /** Drop the last answer and re-run its question (U3 重新生成). */
    async regenerate() {
      const idx = this.messages.map((m) => m.role).lastIndexOf('user')
      if (idx === -1 || !this.sessionId) return
      const text = this.messages[idx].text
      this.messages.splice(idx + 1) // keep the question, drop the unsatisfying answer
      try {
        const { run_id: runId } = await api.sendMessage(this.sessionId, text)
        this.beginLocalRun(runId)
        this.connect()
      } catch (err) {
        this.status = 'error'
        this.reportError(`重新生成失败：${err.message}`)
      }
    },
  },
})
