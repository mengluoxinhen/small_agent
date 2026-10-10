<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { MarkdownRender } from 'markstream-vue'
import {
  ArrowUp,
  Check,
  ChevronRight,
  Copy,
  Download,
  Eraser,
  PanelLeftOpen,
  Paperclip,
  Pencil,
  RotateCcw,
  Share2,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-vue-next'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import { useToastStore } from '../stores/toast'
import TracePanel from './TracePanel.vue'
import ApprovalDialog from './ApprovalDialog.vue'
import { fileToBase64 } from '../utils/attachment'

/**
 * V4 right column: sticky glass header (inline title rename, breathing status
 * pill, share/export/clear, mode segments), chat stream with per-bubble hover
 * actions (copy / regenerate / 赞 / 踩), streaming affordances (typing dots
 * before the first token, a blinking cursor while tokens arrive), a welcome
 * empty state with quick-prompt cards, and the autogrow glass composer.
 * Routing moved to /chat/:sessionId (legacy ?sid= links still restore).
 */

const agent = useAgentStore()
const ui = useUiStore()
const toast = useToastStore()

const draft = ref('')
const scroller = ref(null)
const inputRef = ref(null)
const fileInput = ref(null)
const expandedSteps = reactive({}) // message index -> bool
const editingTitle = ref(false)
const titleDraft = ref('')

const sessionRow = computed(() => agent.sessions.find((s) => s.id === agent.sessionId) ?? null)
const title = computed(() => sessionRow.value?.title || '新会话')
const isEmpty = computed(() => !agent.sessionId && !agent.messages.length)
const running = computed(() => agent.status === 'streaming')
const lastIsAssistant = computed(() => agent.messages.at(-1)?.role === 'assistant')
const showTypingDots = computed(() => running.value && !lastIsAssistant.value)

const STATUS_LABELS = {
  idle: '空闲',
  streaming: '运行中',
  awaiting: '等待审批',
  done: '完成',
  error: '出错',
  cancelled: '已取消',
}

const QUICK_PROMPTS = [
  { title: '总结文件', text: '读取我上传的文件，用要点总结其主要内容' },
  { title: '写脚本并运行', text: '写一个 Python 脚本计算 1 到 100 的平方和，运行后告诉我结果' },
  { title: '解释这段代码', text: '帮我分析一段代码的执行逻辑和潜在问题（把代码粘贴进来）' },
  { title: '整理会议纪要', text: '把下面这些零散记录整理成结构化会议纪要（记录粘贴进来）' },
]

function sidFromLocation() {
  const m = window.location.pathname.match(/^\/chat\/([^/]+)/)
  if (m) return m[1]
  return new URLSearchParams(window.location.search).get('sid') // 旧链接兼容
}

function mostRecent(sessions) {
  return [...sessions].sort((a, b) => String(b.updated_at ?? '').localeCompare(String(a.updated_at ?? '')))[0] ?? null
}

onMounted(async () => {
  try {
    await agent.ensureSessions()
  } catch {
    /* 无服务器时列表为空，界面照常可用 */
  }
  const sid = sidFromLocation()
  if (sid && sid !== agent.sessionId) {
    try {
      await agent.selectSession(sid)
    } catch (err) {
      console.warn('历史加载失败：', err.message)
      toast.push('历史会话加载失败，请检查后端是否在运行', 'error')
    }
  } else if (!sid && !agent.sessionId && agent.sessions.length) {
    // 打开根路径：落到最近一次的会话，而不是空白页
    const recent = mostRecent(agent.sessions)
    if (recent) {
      try {
        await agent.selectSession(recent.id)
      } catch {
        /* 保持空态 */
      }
    }
  }
})

// deep-link sync without a router: the address bar always mirrors the session
watch(
  () => agent.sessionId,
  (sid) => {
    window.history.replaceState({}, '', sid ? `/chat/${sid}` : '/')
  },
)

// 新内容落地就贴到底部（流式输出时的基本体验）
watch(
  () => [agent.messages.length, agent.messages.at(-1)?.text?.length ?? 0],
  async () => {
    await nextTick()
    if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
  },
)

// autogrow: 1 -> 6 rows, then scroll internally
watch(draft, async () => {
  await nextTick()
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(Math.max(el.scrollHeight, 24), 6 * 24)}px`
})

async function submit() {
  const text = draft.value.trim()
  if (!text || running.value) return
  draft.value = ''
  // store actions are their own error boundary; only the sidebar refresh is optional
  await agent.send(text)
  agent.refreshSessions().catch(() => {})
}

function onEnter(event) {
  // Enter 发送，Shift+Enter 换行
  if (event.isComposing) return
  submit()
  event.preventDefault()
}

async function copyText(text, okMsg = '已复制') {
  try {
    await navigator.clipboard.writeText(text)
    toast.push(okMsg, 'success')
  } catch {
    toast.push('复制失败，请手动选择文本', 'error')
  }
}

function canRegenerate(index) {
  const msg = agent.messages[index]
  return msg.role === 'assistant' && msg.streaming !== true && index === agent.messages.length - 1
}

function feedback(msg, value) {
  msg.feedback = msg.feedback === value ? null : value
}

function startTitleEdit() {
  if (!agent.sessionId) return
  titleDraft.value = title.value === '新会话' ? '' : title.value
  editingTitle.value = true
}

function confirmTitleEdit() {
  const t = titleDraft.value.trim()
  if (t && agent.sessionId) agent.renameSession(agent.sessionId, t)
  editingTitle.value = false
}

function shareLink() {
  if (!agent.sessionId) {
    toast.push('还没有会话可分享，先发送一条消息', 'info')
    return
  }
  copyText(`${window.location.origin}/chat/${agent.sessionId}`, '已复制分享链接')
}

function exportChat() {
  if (!agent.messages.length) {
    toast.push('当前没有可导出的消息', 'info')
    return
  }
  const payload = {
    session_id: agent.sessionId,
    mode: agent.sessionMode,
    exported_at: new Date().toISOString(),
    messages: agent.messages.map(({ role, text, steps, feedback: fb }) => ({ role, text, steps, feedback: fb })),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `small-dify-${agent.sessionId ?? 'chat'}.json`
  a.click()
  URL.revokeObjectURL(url)
  toast.push('已导出会话 JSON', 'success')
}

function clearChat() {
  agent.startNewSession()
  toast.push('已清空当前视图，原会话仍保留在左侧列表', 'info')
}

function retryError() {
  if (agent.messages.some((m) => m.role === 'user')) agent.regenerate()
  else agent.error = null
}

function onPickFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  fileToBase64(file)
    .then((base64) => agent.uploadAttachment({ name: file.name, base64 }))
    .finally(() => {
      event.target.value = '' // 允许再次选择同一文件
    })
}
</script>

<template>
  <main class="panel">
    <header class="chat-head glass">
      <button
        class="drawer-toggle"
        data-testid="drawer-toggle"
        title="打开会话列表"
        @click="ui.openDrawer()"
      >
        <PanelLeftOpen :size="17" />
      </button>

      <div class="title-zone">
        <template v-if="editingTitle">
          <input
            v-model="titleDraft"
            class="title-input"
            data-testid="title-input"
            placeholder="会话标题"
            @keydown.esc="editingTitle = false"
            @keydown.enter="confirmTitleEdit"
          />
          <button data-testid="title-confirm" title="确认" @click="confirmTitleEdit">
            <Check :size="13" />
          </button>
        </template>
        <template v-else>
          <h2 data-testid="chat-title" :title="title" @dblclick="startTitleEdit">{{ title }}</h2>
          <button
            v-if="agent.sessionId"
            class="icon-btn title-edit"
            data-testid="title-edit"
            title="重命名会话"
            @click="startTitleEdit"
          >
            <Pencil :size="13" />
          </button>
        </template>
      </div>

      <span class="pill" :data-status="agent.status">
        <i class="dot"></i>{{ STATUS_LABELS[agent.status] ?? agent.status }}
      </span>
      <span v-if="agent.usage && agent.usage.total_tokens" class="meta usage">
        tokens {{ agent.usage.total_tokens }} · turns {{ agent.turns }}
      </span>

      <span class="spacer"></span>

      <span class="modes">
        <button
          v-for="m in ui.modes"
          :key="m"
          class="mode-seg"
          :class="{ on: ui.mode === m }"
          :data-testid="`mode-seg-${m}`"
          :title="m === 'review' ? '高风险工具需人工确认' : '所有工具立即执行'"
          @click="ui.setMode(m)"
        >
          {{ m === 'review' ? '审阅' : '完全访问' }}
        </button>
      </span>
      <span class="head-actions">
        <button class="icon-btn" data-testid="share-button" title="复制分享链接" @click="shareLink">
          <Share2 :size="15" />
        </button>
        <button class="icon-btn" data-testid="export-button" title="导出为 JSON" @click="exportChat">
          <Download :size="15" />
        </button>
        <button class="icon-btn" data-testid="clear-button" title="清空当前视图" @click="clearChat">
          <Eraser :size="15" />
        </button>
      </span>
    </header>

    <div ref="scroller" class="messages">
      <div v-if="isEmpty" data-testid="empty-state" class="empty-state">
        <div class="welcome-icon"><Sparkles :size="26" /></div>
        <h3>small_dify 小助手</h3>
        <p>用自然语言描述你要做的事，我会调用工具去完成。换个话题就从左侧新建会话。</p>
        <div class="quick-grid">
          <button
            v-for="q in QUICK_PROMPTS"
            :key="q.title"
            class="quick-card"
            data-testid="quick-prompt"
            @click="draft = q.text"
          >
            <strong>{{ q.title }}</strong>
            <span>{{ q.text }}</span>
          </button>
        </div>
      </div>

      <div v-for="(msg, i) in agent.messages" :key="i" class="msg msg-enter" :class="msg.role">
        <template v-if="msg.role === 'user'">
          <div class="bubble user-bubble">{{ msg.text }}</div>
        </template>
        <template v-else>
          <span class="ai-avatar"><Sparkles :size="14" /></span>
          <div class="ai-body">
            <div v-if="msg.steps && msg.steps.length" class="steps">
              <button
                data-testid="steps-toggle"
                class="steps-toggle"
                :class="{ open: expandedSteps[i] }"
                @click="expandedSteps[i] = !expandedSteps[i]"
              >
                <ChevronRight :size="13" class="chev" /> 执行过程（{{ msg.steps.length }} 步）
              </button>
              <div v-if="expandedSteps[i]" class="steps-body">
                <TracePanel :trace="msg.steps" title="" />
              </div>
            </div>
            <MarkdownRender v-if="msg.text" :content="msg.text" :final="msg.streaming === false" />
            <span
              v-if="msg.streaming"
              class="stream-cursor"
              data-testid="stream-cursor"
              aria-hidden="true"
            ></span>
            <div class="answer-actions">
              <button class="act" data-testid="copy-answer" title="复制回答" @click="copyText(msg.text)">
                <Copy :size="13" />
              </button>
              <button
                class="act"
                :class="{ on: msg.feedback === 'up' }"
                data-testid="thumb-up"
                title="有帮助"
                @click="feedback(msg, 'up')"
              >
                <ThumbsUp :size="13" />
              </button>
              <button
                class="act"
                :class="{ on: msg.feedback === 'down' }"
                data-testid="thumb-down"
                title="待改进"
                @click="feedback(msg, 'down')"
              >
                <ThumbsDown :size="13" />
              </button>
              <button
                v-if="canRegenerate(i)"
                class="act"
                data-testid="regenerate-button"
                title="重新生成"
                @click="agent.regenerate()"
              >
                <RotateCcw :size="13" />
              </button>
            </div>
          </div>
        </template>
      </div>

      <div v-if="showTypingDots" class="typing" data-testid="typing-dots">
        <span></span><span></span><span></span>
      </div>

      <TracePanel v-if="agent.trace.length" :trace="agent.trace" />

      <div v-if="agent.error" class="error-card" data-testid="error-card">
        <p>{{ agent.error }}</p>
        <button data-testid="error-retry" @click="retryError">重试</button>
      </div>
    </div>

    <ApprovalDialog
      v-if="agent.status === 'awaiting' && agent.pendingApproval"
      :approval="agent.pendingApproval"
      @decide="agent.decide"
    />

    <form class="composer" @submit.prevent="submit">
      <div v-if="agent.attachments.length" class="chips">
        <span v-for="a in agent.attachments" :key="a.filename" class="chip">
          <Paperclip :size="11" /> {{ a.filename }}（{{ a.bytes }} B）
        </span>
      </div>
      <div class="composer-row glass">
        <button type="button" class="attach-button" title="添加附件" @click="fileInput.click()">
          <Paperclip :size="16" />
        </button>
        <input
          ref="fileInput"
          data-testid="attach-input"
          type="file"
          class="attach-input"
          @change="onPickFile"
        />
        <textarea
          ref="inputRef"
          v-model="draft"
          data-testid="chat-input"
          rows="1"
          placeholder="用自然语言描述你要做的事…（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="onEnter"
        />
        <button
          v-if="running"
          type="button"
          class="stop"
          data-testid="cancel-button"
          title="停止生成"
          @click="agent.cancel()"
        >
          <Square :size="15" />
        </button>
        <button
          v-else
          type="button"
          class="send"
          data-testid="send-button"
          :disabled="!draft.trim()"
          title="发送"
          @click="submit"
        >
          <ArrowUp :size="16" />
        </button>
      </div>
      <p class="meta composer-meta">Enter 发送 · Shift+Enter 换行 · 附件上传后模型可直接按文件名读取</p>
    </form>
  </main>
</template>

<style scoped>
.panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  background: var(--bg-right);
}

/* ------------------------------------------------------------------ head */

.chat-head {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.55rem 1.1rem;
  border-bottom: 1px solid var(--divider);
  flex: 0 0 auto;
}
.drawer-toggle {
  display: none;
}
@media (max-width: 767px) {
  .drawer-toggle {
    display: inline-flex;
  }
}
.title-zone {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  min-width: 0;
}
.chat-head h2 {
  margin: 0;
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 22rem;
}
.title-input {
  font: inherit;
  font-size: 0.9rem;
  padding: 0.25rem 0.5rem;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-1);
  width: 14rem;
}
[data-testid='title-confirm'] {
  border: none;
  background: var(--tint);
  color: var(--primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  padding: 0.15rem 0.4rem;
}

.pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 12px;
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px solid var(--divider);
  border-radius: var(--radius-pill);
  padding: 0.12rem 0.6rem;
  white-space: nowrap;
}
.pill .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
}
.pill[data-status='streaming'] .dot,
.pill[data-status='awaiting'] .dot {
  animation: breathe 1.4s var(--ease) infinite;
}
.pill[data-status='streaming'] {
  color: var(--success);
}
.pill[data-status='streaming'] .dot {
  background: var(--success);
}
.pill[data-status='awaiting'] {
  color: var(--warn);
}
.pill[data-status='awaiting'] .dot {
  background: var(--warn);
}
.pill[data-status='done'] .dot {
  background: var(--success);
}
.pill[data-status='error'] {
  color: var(--danger);
}
.pill[data-status='error'] .dot {
  background: var(--danger);
}

.spacer {
  flex: 1;
}
.usage {
  white-space: nowrap;
}
.modes {
  display: inline-flex;
  border: 1px solid var(--divider);
  border-radius: var(--radius-pill);
  overflow: hidden;
}
.mode-seg {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.75rem;
  color: var(--text-3);
  padding: 0.22rem 0.7rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.mode-seg:hover {
  color: var(--text-1);
}
.mode-seg.on {
  background: var(--tint);
  color: var(--primary);
  font-weight: 600;
}
.head-actions {
  display: inline-flex;
  gap: 0.15rem;
}
.icon-btn {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-3);
  padding: 0.3rem;
  border-radius: var(--radius-sm);
  display: inline-flex;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.icon-btn:hover {
  background: var(--surface-2);
  color: var(--text-1);
}

/* -------------------------------------------------------------- messages */

.messages {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 1.1rem 1.2rem 1.4rem;
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.empty-state {
  max-width: 44rem;
  margin: auto;
  text-align: center;
  color: var(--text-3);
  padding: 2rem 0.5rem;
}
.welcome-icon {
  width: 52px;
  height: 52px;
  margin: 0 auto 0.8rem;
  border-radius: var(--radius-lg);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--gradient);
  box-shadow: var(--shadow-md);
}
.empty-state h3 {
  font-size: 1.3rem;
  color: var(--text-1);
  margin: 0 0 0.35rem;
}
.empty-state > p {
  font-size: 0.88rem;
  margin: 0 0 1.3rem;
}
.quick-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
  gap: 0.7rem;
}
.quick-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  text-align: left;
  padding: 0.8rem 0.9rem;
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  background: var(--surface);
  cursor: pointer;
  transition: transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}
.quick-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: transparent;
  background: linear-gradient(var(--surface), var(--surface)) padding-box,
    var(--gradient) border-box;
  border: 1px solid transparent;
}
.quick-card strong {
  font-size: 0.85rem;
  color: var(--text-1);
}
.quick-card span {
  font-size: 0.76rem;
  color: var(--text-3);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.msg {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  font-size: 0.94rem;
}
.msg.user {
  justify-content: flex-end;
}
.user-bubble {
  background: var(--tint-strong);
  color: var(--text-1);
  border-radius: var(--radius-lg) var(--radius-lg) 4px var(--radius-lg);
  padding: 0.55rem 0.9rem;
  white-space: pre-wrap;
  max-width: 70%;
  box-shadow: var(--shadow-sm);
}
.ai-avatar {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  border-radius: var(--radius-pill);
  background: var(--gradient);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}
.ai-body {
  min-width: 0;
  max-width: min(46rem, 100%);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.stream-cursor {
  display: inline-block;
  width: 7px;
  height: 1.05em;
  margin-top: 2px;
  background: var(--primary);
  border-radius: 2px;
  animation: blink 1s steps(2, start) infinite;
}

.typing {
  display: inline-flex;
  gap: 4px;
  align-self: flex-start;
  padding: 0.55rem 0.8rem;
  margin-left: 2rem;
  background: var(--surface-2);
  border-radius: var(--radius-lg);
}
.typing span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  animation: typing-bounce 1.1s var(--ease) infinite;
}
.typing span:nth-child(2) {
  animation-delay: 0.15s;
}
.typing span:nth-child(3) {
  animation-delay: 0.3s;
}

/* ---------------------------------------------------------------- steps */

.steps-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  border: 1px dashed var(--border-soft);
  background: none;
  border-radius: var(--radius-pill);
  padding: 0.22rem 0.7rem;
  font-size: 0.76rem;
  font-style: italic;
  color: var(--text-3);
  cursor: pointer;
  transition: color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.steps-toggle:hover {
  color: var(--primary);
  border-color: var(--primary);
}
.steps-toggle .chev {
  font-style: normal;
  transition: transform var(--dur) var(--ease);
  display: inline-block;
}
.steps-toggle.open .chev {
  transform: rotate(90deg);
}
.steps-body {
  border-left: 2px dashed var(--border-soft);
  margin: 0.4rem 0 0 0.6rem;
  padding-left: 0.7rem;
  animation: fade-up var(--dur) var(--ease);
}

.answer-actions {
  display: flex;
  gap: 0.15rem;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}
.msg.assistant:hover .answer-actions,
.msg.assistant:focus-within .answer-actions {
  opacity: 1;
}
.act {
  border: 1px solid transparent;
  background: none;
  cursor: pointer;
  color: var(--text-3);
  padding: 0.25rem 0.4rem;
  border-radius: var(--radius-sm);
  display: inline-flex;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.act:hover {
  background: var(--surface-2);
  color: var(--text-1);
}
.act.on {
  color: var(--primary);
  background: var(--tint);
}

/* ----------------------------------------------------------------- error */

.error-card {
  align-self: stretch;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.8rem;
  padding: 0.6rem 0.9rem;
  border: 1px solid rgba(239, 68, 68, 0.35);
  border-radius: var(--radius-md);
  background: rgba(239, 68, 68, 0.07);
  color: var(--danger);
  font-size: 0.84rem;
  animation: fade-up var(--dur) var(--ease);
}
.error-card p {
  margin: 0;
  min-width: 0;
}
.error-card button {
  flex: 0 0 auto;
  border: 1px solid var(--danger);
  background: none;
  color: var(--danger);
  border-radius: var(--radius-pill);
  cursor: pointer;
  font-size: 0.78rem;
  padding: 0.18rem 0.75rem;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.error-card button:hover {
  background: var(--danger);
  color: #fff;
}

/* -------------------------------------------------------------- composer */

.composer {
  flex: 0 0 auto;
  padding: 0.6rem 1.2rem 0.7rem;
  background: linear-gradient(to bottom, transparent, var(--bg-right) 30%);
}
.chips {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-bottom: 0.45rem;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.75rem;
  background: var(--tint);
  border: 1px solid var(--divider);
  border-radius: var(--radius-pill);
  padding: 0.15rem 0.65rem;
  color: var(--text-2);
}
.composer-row {
  display: flex;
  align-items: flex-end;
  gap: 0.4rem;
  border: 1px solid var(--divider);
  border-radius: var(--radius-lg);
  padding: 0.5rem 0.55rem 0.5rem 0.7rem;
  box-shadow: var(--shadow-md);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.composer-row:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--tint), var(--shadow-md);
}
.attach-button {
  border: none;
  background: none;
  color: var(--text-3);
  cursor: pointer;
  padding: 0.3rem;
  border-radius: var(--radius-sm);
  display: inline-flex;
  transition: color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
.attach-button:hover {
  color: var(--primary);
  background: var(--tint);
}
.attach-input {
  display: none;
}
.composer-row textarea {
  flex: 1;
  resize: none;
  border: none;
  background: none;
  font: inherit;
  font-size: 0.92rem;
  line-height: 1.55;
  padding: 0.28rem 0.2rem;
  outline: none;
  color: var(--text-1);
  max-height: 144px;
}
.send,
.stop {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-md);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  background: var(--gradient);
  transition: opacity var(--dur-fast) var(--ease), transform var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}
.send:hover:not(:disabled) {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.send:disabled {
  opacity: 0.35;
  cursor: default;
}
.stop {
  background: var(--surface-2);
  color: var(--danger);
  border: 1px solid rgba(239, 68, 68, 0.4);
  animation: stop-ring 1.6s var(--ease) infinite;
}
.stop:hover {
  background: rgba(239, 68, 68, 0.1);
}
.composer-meta {
  margin: 0.4rem 0.2rem 0;
  text-align: center;
}

@media (max-width: 640px) {
  .chat-head {
    padding: 0.5rem 0.7rem;
    gap: 0.4rem;
  }
  .usage,
  .modes {
    display: none;
  }
  .messages {
    padding: 0.8rem 0.7rem 1rem;
  }
  .composer {
    padding: 0.5rem 0.7rem 0.6rem;
  }
  .user-bubble {
    max-width: 85%;
  }
}
</style>
