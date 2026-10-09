<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { MarkdownRender } from 'markstream-vue'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import TracePanel from './TracePanel.vue'
import ApprovalDialog from './ApprovalDialog.vue'

const agent = useAgentStore()
const ui = useUiStore()
const draft = ref('')
const scroller = ref(null)

onMounted(async () => {
  try {
    await agent.refreshSessions()
  } catch (err) {
    console.warn('会话列表加载失败：', err.message)
  }
})

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

function chooseSession(id) {
  agent.selectSession(id).catch((err) => console.warn('历史加载失败：', err.message))
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <button data-testid="new-session" @click="agent.startNewSession()">＋ 新会话</button>
      <ul>
        <li v-for="s in agent.sessions" :key="s.id" :class="{ active: s.id === agent.sessionId }">
          <button class="title" @click="chooseSession(s.id)">{{ s.title }}</button>
          <button class="drop" title="删除会话" @click="agent.removeSession(s.id)">✕</button>
        </li>
      </ul>
    </aside>

    <main class="panel">
      <div class="topline">
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
      </div>

      <div ref="scroller" class="messages">
        <div v-for="(msg, i) in agent.messages" :key="i" class="msg" :class="msg.role">
          <span v-if="msg.role === 'user'" class="user-text">{{ msg.text }}</span>
          <MarkdownRender v-else :content="msg.text" :final="msg.streaming === false" />
        </div>
        <p v-if="agent.error" class="error">{{ agent.error }}</p>
      </div>

      <ApprovalDialog
        v-if="agent.status === 'awaiting' && agent.pendingApproval"
        :approval="agent.pendingApproval"
        @decide="agent.decide"
      />

      <TracePanel :trace="agent.trace" />

      <form class="composer" @submit.prevent="submit">
        <input
          v-model="draft"
          data-testid="chat-input"
          :disabled="agent.status === 'streaming'"
          placeholder="用自然语言描述你要做的事…"
        />
        <button
          type="button"
          data-testid="send-button"
          :disabled="!draft.trim() || agent.status === 'streaming'"
          @click="submit"
        >
          发送
        </button>
        <button
          v-if="agent.status === 'streaming'"
          type="button"
          data-testid="cancel-button"
          @click="agent.cancel()"
        >
          取消
        </button>
      </form>
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 220px 1fr;
  gap: 1rem;
  max-width: 1080px;
  margin: 1rem auto;
  padding: 0 1rem;
}
.sidebar {
  border-right: 1px solid #eee;
  padding-right: 0.8rem;
}
.sidebar > button {
  width: 100%;
  padding: 0.4rem;
  border: 1px dashed #bbb;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  margin-bottom: 0.6rem;
}
.sidebar ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sidebar li {
  display: flex;
  align-items: center;
  gap: 0.3rem;
}
.sidebar li.active .title {
  font-weight: 700;
}
.sidebar .title {
  flex: 1;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.3rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.85rem;
}
.sidebar .drop {
  border: none;
  background: none;
  color: #b04a3f;
  cursor: pointer;
}
.panel {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  min-width: 0;
}
.topline {
  display: flex;
  gap: 1rem;
  align-items: center;
  font-size: 0.82rem;
  color: #666;
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
.modes {
  margin-left: auto;
  display: flex;
  gap: 0.8rem;
}
.messages {
  border: 1px solid #eee;
  border-radius: 8px;
  padding: 0.8rem;
  height: 46vh;
  overflow-y: auto;
  background: #fff;
}
.msg {
  margin-bottom: 0.7rem;
  font-size: 0.92rem;
}
.msg.user .user-text {
  display: inline-block;
  background: #eef3fb;
  border-radius: 8px;
  padding: 0.35rem 0.6rem;
  white-space: pre-wrap;
}
.msg.assistant {
  color: #222;
}
.error {
  color: #c0392b;
}
.composer {
  display: flex;
  gap: 0.5rem;
}
.composer input {
  flex: 1;
  padding: 0.5rem 0.7rem;
  border: 1px solid #ccc;
  border-radius: 8px;
  font: inherit;
}
.composer button {
  padding: 0.5rem 1rem;
  border-radius: 8px;
  border: 1px solid #2e7d32;
  background: #2e7d32;
  color: #fff;
  cursor: pointer;
}
.composer button:disabled {
  opacity: 0.5;
  cursor: default;
}
.composer [data-testid='cancel-button'] {
  background: #fff;
  color: #c0392b;
  border-color: #c0392b;
}
</style>
