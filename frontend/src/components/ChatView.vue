<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { MarkdownRender } from 'markstream-vue'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import TracePanel from './TracePanel.vue'
import ApprovalDialog from './ApprovalDialog.vue'
import { fileToBase64 } from '../utils/attachment'

/**
 * U3 right column: session header + scrolling messages (markdown, per-answer
 * collapsible steps, copy/regenerate) + a sticky composer with attachments.
 * The URL carries the session as ?sid= so a refresh restores the same chat.
 */

const agent = useAgentStore()
const ui = useUiStore()
const draft = ref('')
const scroller = ref(null)
const fileInput = ref(null)
const expandedSteps = reactive({}) // message index -> bool

const sessionRow = computed(() => agent.sessions.find((s) => s.id === agent.sessionId) ?? null)
const title = computed(() => sessionRow.value?.title || '新会话')
const isEmpty = computed(() => !agent.sessionId && !agent.messages.length)

onMounted(async () => {
  const sid = new URLSearchParams(window.location.search).get('sid')
  if (sid && sid !== agent.sessionId) {
    try {
      await agent.selectSession(sid)
    } catch (err) {
      console.warn('历史加载失败：', err.message)
    }
  }
})

// deep-link sync without a router: the address bar always mirrors the session
watch(
  () => agent.sessionId,
  (sid) => {
    window.history.replaceState({}, '', sid ? `/?sid=${sid}` : '/')
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

async function submit() {
  const text = draft.value.trim()
  if (!text || agent.status === 'streaming') return
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

async function copyAnswer(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* clipboard unavailable: nothing to report beyond the failed click */
  }
}

function isLastFinishedAnswer(index) {
  const msg = agent.messages[index]
  return (
    msg.role === 'assistant' &&
    msg.streaming === false &&
    index === agent.messages.length - 1 &&
    agent.status === 'done'
  )
}

async function onPickFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  try {
    const base64 = await fileToBase64(file)
    await agent.uploadAttachment({ name: file.name, base64 })
  } finally {
    event.target.value = '' // 允许再次选择同一文件
  }
}
</script>

<template>
  <main class="panel">
    <header class="chat-head">
      <h2 data-testid="chat-title">{{ title }}</h2>
      <span class="status" :data-status="agent.status">{{ agent.status }}</span>
      <span v-if="agent.usage && agent.usage.total_tokens" class="usage">
        tokens {{ agent.usage.total_tokens }} · turns {{ agent.turns }}
      </span>
      <span class="modes">
        <label v-for="m in ui.modes" :key="m">
          <input type="radio" name="mode" :checked="ui.mode === m" @change="ui.setMode(m)" />
          {{ m === 'review' ? '审阅模式' : '完全访问' }}
        </label>
      </span>
    </header>

    <div ref="scroller" class="messages">
      <div v-if="isEmpty" data-testid="empty-state" class="empty-state">
        <h3>small_dify 小助手</h3>
        <p>用自然语言描述你要做的事，我会调用工具去完成。新建会话或从左侧选择历史会话。</p>
      </div>

      <div v-for="(msg, i) in agent.messages" :key="i" class="msg" :class="msg.role">
        <span v-if="msg.role === 'user'" class="user-text">{{ msg.text }}</span>
        <template v-else>
          <div v-if="msg.steps && msg.steps.length" class="steps">
            <button
              data-testid="steps-toggle"
              class="steps-toggle"
              @click="expandedSteps[i] = !expandedSteps[i]"
            >
              {{ expandedSteps[i] ? '▾' : '▸' }} 执行过程（{{ msg.steps.length }} 步）
            </button>
            <TracePanel v-if="expandedSteps[i]" :trace="msg.steps" title="" />
          </div>
          <MarkdownRender v-if="msg.text" :content="msg.text" :final="msg.streaming === false" />
          <div v-if="isLastFinishedAnswer(i)" class="answer-actions">
            <button data-testid="copy-answer" title="复制回答" @click="copyAnswer(msg.text)">复制</button>
            <button data-testid="regenerate-button" title="重新生成" @click="agent.regenerate()">
              重新生成
            </button>
          </div>
        </template>
      </div>

      <TracePanel v-if="agent.trace.length" :trace="agent.trace" />
      <p v-if="agent.error" class="error">{{ agent.error }}</p>
    </div>

    <ApprovalDialog
      v-if="agent.status === 'awaiting' && agent.pendingApproval"
      :approval="agent.pendingApproval"
      @decide="agent.decide"
    />

    <form class="composer" @submit.prevent="submit">
      <div v-if="agent.attachments.length" class="chips">
        <span v-for="a in agent.attachments" :key="a.filename" class="chip">
          📎 {{ a.filename }}（{{ a.bytes }} B）
        </span>
      </div>
      <div class="composer-row">
        <button type="button" class="attach-button" title="添加附件" @click="fileInput.click()">＋</button>
        <input
          ref="fileInput"
          data-testid="attach-input"
          type="file"
          class="attach-input"
          @change="onPickFile"
        />
        <textarea
          v-model="draft"
          data-testid="chat-input"
          rows="2"
          :disabled="agent.status === 'streaming'"
          placeholder="用自然语言描述你要做的事…（Enter 发送，Shift+Enter 换行）"
          @keydown.enter.exact.prevent="onEnter"
        />
        <div class="composer-buttons">
          <button
            v-if="agent.status === 'streaming'"
            type="button"
            data-testid="cancel-button"
            @click="agent.cancel()"
          >
            停止
          </button>
          <button
            v-else
            type="button"
            data-testid="send-button"
            :disabled="!draft.trim()"
            @click="submit"
          >
            发送
          </button>
        </div>
      </div>
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
  background: #fff;
}
.chat-head {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.7rem 1.2rem;
  border-bottom: 1px solid #f0f0f4;
  flex: 0 0 auto;
}
.chat-head h2 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status::before {
  content: '● ';
}
.status[data-status='streaming'] {
  color: #1f6b3b;
}
.status[data-status='awaiting'] {
  color: #b9770e;
}
.status[data-status='error'] {
  color: #c0392b;
}
.usage {
  font-size: 0.78rem;
  color: #888;
}
.modes {
  margin-left: auto;
  display: flex;
  gap: 0.8rem;
  font-size: 0.8rem;
  color: #555;
}
.messages {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 1rem 1.2rem;
}
.empty-state {
  max-width: 34rem;
  margin: 18vh auto 0;
  text-align: center;
  color: #777;
}
.empty-state h3 {
  font-size: 1.25rem;
  color: #333;
  margin: 0 0 0.5rem;
}
.msg {
  margin-bottom: 0.9rem;
  font-size: 0.92rem;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.35rem;
}
.msg.user {
  align-items: flex-end;
}
.msg.user .user-text {
  display: inline-block;
  background: #e8ecff;
  border-radius: 12px;
  padding: 0.45rem 0.8rem;
  white-space: pre-wrap;
  max-width: 85%;
}
.msg.assistant {
  align-self: stretch;
  width: 100%;
}
.steps {
  width: min(42rem, 100%);
}
.steps-toggle {
  border: 1px solid #e3e3ea;
  background: #f9f9fb;
  border-radius: 8px;
  padding: 0.25rem 0.6rem;
  font-size: 0.78rem;
  color: #666;
  cursor: pointer;
}
.steps-toggle:hover {
  color: #4d6bfe;
  border-color: #c9d3ff;
}
.answer-actions {
  display: flex;
  gap: 0.4rem;
}
.answer-actions button {
  border: 1px solid #e3e3ea;
  background: #fff;
  border-radius: 7px;
  padding: 0.18rem 0.55rem;
  font-size: 0.76rem;
  color: #666;
  cursor: pointer;
}
.answer-actions button:hover {
  color: #4d6bfe;
  border-color: #c9d3ff;
}
.error {
  color: #c0392b;
}
.composer {
  flex: 0 0 auto;
  border-top: 1px solid #f0f0f4;
  padding: 0.7rem 1.2rem 0.9rem;
  background: #fff;
}
.chips {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.chip {
  font-size: 0.75rem;
  background: #f2f4ff;
  border: 1px solid #dfe4ff;
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
  color: #445;
}
.composer-row {
  display: flex;
  align-items: flex-end;
  gap: 0.5rem;
  border: 1px solid #e3e3ea;
  border-radius: 12px;
  padding: 0.45rem 0.6rem;
  background: #fbfbfd;
}
.composer-row:focus-within {
  border-color: #b7c4ff;
}
.attach-button {
  border: none;
  background: none;
  font-size: 1.15rem;
  color: #888;
  cursor: pointer;
  padding: 0.15rem 0.3rem;
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
  font-size: 0.9rem;
  padding: 0.25rem 0.2rem;
  outline: none;
}
.composer-buttons button {
  padding: 0.35rem 0.95rem;
  border-radius: 9px;
  border: 1px solid #4d6bfe;
  background: #4d6bfe;
  color: #fff;
  cursor: pointer;
}
.composer-buttons button:disabled {
  opacity: 0.5;
  cursor: default;
}
.composer-buttons [data-testid='cancel-button'] {
  background: #fff;
  color: #c0392b;
  border-color: #c0392b;
}
</style>
