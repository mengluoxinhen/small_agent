<script setup>
import { computed, onMounted, ref } from 'vue'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import { groupSessions } from '../utils/groups'

/**
 * U3 left column (DeepSeek-style): new session + search on top, the session list
 * grouped by recency (pinned first) with per-row pin / rename / delete, and a
 * settings area at the bottom. Collapsed to a slim rail via the ui store.
 */

const agent = useAgentStore()
const ui = useUiStore()

const query = ref('')
const renamingId = ref(null)
const renameDraft = ref('')

onMounted(() => {
  agent.refreshSessions().catch(() => {}) // best effort; rows are useless without a server anyway
})

const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const visible = q
    ? agent.sessions.filter((s) => String(s.title ?? s.id).toLowerCase().includes(q))
    : agent.sessions
  return groupSessions(visible)
})

function choose(s) {
  if (s.id !== agent.sessionId) agent.selectSession(s.id).catch(() => {})
}

function startRename(s) {
  renamingId.value = s.id
  renameDraft.value = s.title ?? ''
}

function cancelRename() {
  renamingId.value = null
}

function confirmRename(s) {
  const title = renameDraft.value.trim()
  if (title) agent.renameSession(s.id, title)
  renamingId.value = null
}
</script>

<template>
  <aside class="sidebar" :class="{ collapsed: ui.sidebarCollapsed }">
    <button
      v-if="ui.sidebarCollapsed"
      class="expand"
      data-testid="expand-toggle"
      title="展开会话栏"
      @click="ui.toggleSidebar()"
    >
      ☰
    </button>
    <template v-else>
      <div class="top">
        <button data-testid="new-session" class="new-session" @click="agent.startNewSession()">
          ＋ 新建会话
        </button>
        <button class="collapse" data-testid="collapse-toggle" title="收起会话栏" @click="ui.toggleSidebar()">
          ⟨
        </button>
      </div>
      <input
        v-model="query"
        class="search"
        data-testid="session-search"
        type="text"
        placeholder="搜索会话"
      />

      <nav class="list">
        <section v-for="g in groups" :key="g.label" :data-testid="`group-${g.label}`">
          <h3>{{ g.label }}</h3>
          <div
            v-for="s in g.items"
            :key="s.id"
            class="session-row"
            :class="{ active: s.id === agent.sessionId }"
          >
            <template v-if="renamingId === s.id">
              <input
                v-model="renameDraft"
                class="rename-input"
                data-testid="rename-input"
                @keydown.esc="cancelRename"
                @keydown.enter="confirmRename(s)"
              />
              <button data-testid="rename-confirm" title="确认" @click="confirmRename(s)">✓</button>
            </template>
            <template v-else>
              <button class="title" :title="s.title" @click="choose(s)">
                <span v-if="s.pinned" class="pin-mark">📌</span>{{ s.title || s.id }}
              </button>
              <span class="row-actions">
                <button
                  data-testid="pin-button"
                  :title="s.pinned ? '取消置顶' : '置顶'"
                  @click="agent.togglePin(s.id, !s.pinned)"
                >
                  {{ s.pinned ? '📌' : '📍' }}
                </button>
                <button data-testid="rename-button" title="重命名" @click="startRename(s)">✎</button>
                <button data-testid="delete-button" class="drop" title="删除" @click="agent.removeSession(s.id)">
                  ✕
                </button>
              </span>
            </template>
          </div>
        </section>
        <p v-if="!groups.length" class="empty">（暂无会话）</p>
      </nav>

      <footer class="foot" data-testid="sidebar-footer">
        <span class="brand">small_dify Agent</span>
        <span class="mode">运行模式 <strong data-testid="mode">{{ ui.mode }}</strong></span>
      </footer>
    </template>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 280px;
  min-width: 280px;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem 0.6rem;
  background: #f9f9fb;
  border-right: 1px solid #ececf1;
  height: 100%;
  box-sizing: border-box;
}
.sidebar.collapsed {
  width: 44px;
  min-width: 44px;
  align-items: center;
  padding-top: 0.75rem;
}
.expand,
.collapse {
  border: none;
  background: none;
  cursor: pointer;
  color: #666;
  font-size: 0.95rem;
  padding: 0.25rem 0.4rem;
  border-radius: 6px;
}
.expand:hover,
.collapse:hover {
  background: #ececf1;
}
.top {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}
.new-session {
  flex: 1;
  padding: 0.45rem 0.6rem;
  border: 1px solid #d8d8e0;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font: inherit;
}
.new-session:hover {
  border-color: #4d6bfe;
  color: #4d6bfe;
}
.search {
  padding: 0.4rem 0.6rem;
  border: 1px solid #e3e3ea;
  border-radius: 8px;
  background: #fff;
  font: inherit;
  font-size: 0.85rem;
}
.list {
  flex: 1;
  overflow-y: auto;
}
.list h3 {
  margin: 0.7rem 0.3rem 0.25rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: #9a9aa5;
}
.session-row {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  border-radius: 8px;
  padding: 0 0.2rem;
}
.session-row:hover {
  background: #efefF4;
}
.session-row.active {
  background: #e8ecff;
}
.session-row.active .title {
  color: #3355cc;
  font-weight: 600;
}
.title {
  flex: 1;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.42rem 0.3rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.86rem;
  color: #333;
}
.row-actions {
  display: none;
  gap: 0.05rem;
}
.session-row:hover .row-actions,
.session-row.active .row-actions {
  display: inline-flex;
}
.row-actions button {
  border: none;
  background: none;
  cursor: pointer;
  padding: 0.15rem 0.25rem;
  border-radius: 5px;
  font-size: 0.8rem;
  color: #777;
}
.row-actions button:hover {
  background: #dcdce6;
}
.row-actions .drop {
  color: #b04a3f;
}
.rename-input {
  flex: 1;
  min-width: 0;
  font: inherit;
  font-size: 0.85rem;
  padding: 0.25rem 0.4rem;
  border: 1px solid #4d6bfe;
  border-radius: 6px;
}
.empty {
  color: #999;
  font-size: 0.82rem;
  padding: 0.4rem;
}
.foot {
  border-top: 1px solid #ececf1;
  padding-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  font-size: 0.78rem;
  color: #777;
}
.foot .brand {
  font-weight: 600;
  color: #444;
}
</style>
