<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  Check,
  Copy,
  Moon,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  Sun,
  Trash2,
  UserRound,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-vue-next'
import { useAgentStore } from '../stores/agent'
import { useUiStore } from '../stores/ui'
import { useToastStore } from '../stores/toast'
import { groupSessions } from '../utils/groups'
import ConfirmDialog from './ConfirmDialog.vue'

/**
 * V3 left column: gradient new-session CTA, glowing search with hit highlight,
 * calendar-day groups, avatar-initial rows, and a hover overflow menu
 * (rename / pin / copy link / delete). Deletion goes through ConfirmDialog —
 * window.confirm is banned. The footer carries the mode readout, the settings
 * popover, the theme switch and the user avatar. First load shows skeletons.
 */

const agent = useAgentStore()
const ui = useUiStore()
const toast = useToastStore()

const query = ref('')
const renamingId = ref(null)
const renameDraft = ref('')
const openMenuId = ref(null)
const pendingDelete = ref(null)
const settingsOpen = ref(false)

onMounted(() => {
  agent.ensureSessions().catch(() => {}) // best effort; rows are useless without a server anyway
})

const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const visible = q
    ? agent.sessions.filter((s) => String(s.title ?? s.id).toLowerCase().includes(q))
    : agent.sessions
  return groupSessions(visible)
})

/** title split around the first search hit so <mark> can highlight it */
function segments(text) {
  const q = query.value.trim().toLowerCase()
  const t = String(text ?? '')
  if (!q) return [{ hit: false, s: t }]
  const i = t.toLowerCase().indexOf(q)
  if (i === -1) return [{ hit: false, s: t }]
  return [
    { hit: false, s: t.slice(0, i) },
    { hit: true, s: t.slice(i, i + q.length) },
    { hit: false, s: t.slice(i + q.length) },
  ]
}

function initials(s) {
  const t = String(s.title ?? s.id ?? '').trim()
  return t ? Array.from(t)[0].toUpperCase() : '会'
}

/** stable hue per session id -> duotone avatar, same chat always same color */
function hueFor(id) {
  let h = 0
  for (const ch of String(id ?? '?')) h = (h * 31 + ch.codePointAt(0)) % 360
  return h
}

function choose(s) {
  openMenuId.value = null
  if (s.id !== agent.sessionId) agent.selectSession(s.id).catch(() => {})
  ui.closeDrawer()
}

function toggleMenu(id) {
  openMenuId.value = openMenuId.value === id ? null : id
}

function startRename(s) {
  openMenuId.value = null
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

function doPin(s) {
  openMenuId.value = null
  agent.togglePin(s.id, !s.pinned)
}

function copyLink(s) {
  openMenuId.value = null
  const link = `${window.location.origin}/chat/${s.id}`
  if (!navigator.clipboard?.writeText) {
    toast.push('当前环境不支持剪贴板，请手动复制地址栏', 'error')
    return
  }
  // Promise.resolve: some clipboard shims return a bare value, not a thenable
  Promise.resolve(navigator.clipboard.writeText(link))
    .then(() => toast.push('已复制会话链接', 'success'))
    .catch(() => toast.push('复制失败，请手动复制地址栏', 'error'))
}

function askDelete(s) {
  openMenuId.value = null
  pendingDelete.value = s
}

function doDelete() {
  const s = pendingDelete.value
  pendingDelete.value = null
  if (s) agent.removeSession(s.id) // the action is its own error boundary; the list visibly updates
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
      <PanelLeftOpen :size="17" />
    </button>
    <template v-else>
      <div class="top">
        <button class="new-session" data-testid="new-session" @click="agent.startNewSession()">
          <Plus :size="15" />
          <span>新建会话</span>
        </button>
        <button class="collapse" data-testid="collapse-toggle" title="收起会话栏" @click="ui.toggleSidebar()">
          <PanelLeftClose :size="16" />
        </button>
      </div>

      <div class="search-wrap">
        <Search :size="14" class="search-icon" />
        <input
          v-model="query"
          class="search"
          data-testid="session-search"
          type="text"
          placeholder="搜索会话"
        />
      </div>

      <nav class="list">
        <template v-if="!agent.sessionsLoaded">
          <div v-for="n in 4" :key="`sk-${n}`" class="skeleton-row" data-testid="session-skeleton">
            <span class="sk-avatar"></span>
            <span class="sk-line"></span>
          </div>
        </template>
        <template v-else>
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
                <button data-testid="rename-confirm" title="确认" @click="confirmRename(s)">
                  <Check :size="13" />
                </button>
              </template>
              <template v-else>
                <span class="avatar" :style="{ '--av-hue': hueFor(s.id) }">{{ initials(s) }}</span>
                <button class="title" :title="s.title" @click="choose(s)">
                  <template v-for="(seg, k) in segments(s.title || s.id)" :key="k">
                    <mark v-if="seg.hit">{{ seg.s }}</mark>
                    <span v-else>{{ seg.s }}</span>
                  </template>
                  <span v-if="s.pinned" class="pin-mark"><Pin :size="11" /></span>
                </button>
                <button
                  class="menu-button"
                  data-testid="menu-button"
                  title="更多操作"
                  @click.stop="toggleMenu(s.id)"
                >
                  <MoreHorizontal :size="15" />
                </button>
                <div v-if="openMenuId === s.id" class="row-menu" @click.stop>
                  <button data-testid="menu-rename" @click="startRename(s)">
                    <Pencil :size="13" /> 重命名
                  </button>
                  <button data-testid="menu-pin" @click="doPin(s)">
                    <component :is="s.pinned ? PinOff : Pin" :size="13" />
                    {{ s.pinned ? '取消置顶' : '置顶' }}
                  </button>
                  <button data-testid="menu-copy" @click="copyLink(s)">
                    <Copy :size="13" /> 复制链接
                  </button>
                  <button class="drop" data-testid="menu-delete" @click="askDelete(s)">
                    <Trash2 :size="13" /> 删除
                  </button>
                </div>
              </template>
            </div>
          </section>
          <p v-if="!groups.length" class="empty">（暂无会话）</p>
        </template>
      </nav>

      <footer class="foot" data-testid="sidebar-footer">
        <div class="foot-row">
          <span class="avatar me"><UserRound :size="14" /></span>
          <span class="who">
            <span class="brand">small_dify Agent</span>
            <span class="mode-line">运行模式 <strong data-testid="mode">{{ ui.mode }}</strong></span>
          </span>
          <span class="foot-actions">
            <button
              class="icon-btn"
              data-testid="theme-toggle"
              :title="ui.effectiveTheme === 'dark' ? '切换到浅色' : '切换到深色'"
              @click="ui.toggleTheme()"
            >
              <component :is="ui.effectiveTheme === 'dark' ? Sun : Moon" :size="15" />
            </button>
            <button
              class="icon-btn"
              data-testid="settings-button"
              title="设置"
              @click="settingsOpen = !settingsOpen"
            >
              <Settings :size="15" />
            </button>
          </span>
        </div>
        <div v-if="settingsOpen" class="settings-pop">
          <h4>运行模式</h4>
          <button
            v-for="m in ui.modes"
            :key="m"
            :class="{ on: ui.mode === m }"
            data-testid="settings-mode"
            @click="ui.setMode(m)"
          >
            {{ m === 'review' ? '审阅模式（高风险工具需确认）' : '完全访问（全部自动执行）' }}
          </button>
        </div>
      </footer>
    </template>

    <ConfirmDialog
      v-if="pendingDelete"
      title="删除会话"
      :message="`「${pendingDelete.title || pendingDelete.id}」的聊天记录将从本地数据库中移除，此操作不可撤销。`"
      @ok="doDelete"
      @cancel="pendingDelete = null"
    />
  </aside>
</template>

<style scoped>
.sidebar {
  /* 列宽由 App 的 grid 决定（ui.sidebarWidth / 折叠 44px），组件只需铺满 */
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  padding: 0.8rem 0.65rem;
  background: var(--bg-left);
  border-right: 1px solid var(--divider);
  height: 100%;
  box-sizing: border-box;
  transition: background var(--dur) var(--ease);
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
  color: var(--text-3);
  padding: 0.3rem;
  border-radius: var(--radius-sm);
  display: inline-flex;
  transition: background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease);
}
.expand:hover,
.collapse:hover {
  background: var(--surface-3);
  color: var(--text-1);
}

/* ------------------------------------------------------------- top */
.top {
  display: flex;
  gap: 0.35rem;
  align-items: center;
}
.new-session {
  flex: 1;
  position: relative;
  overflow: hidden;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 0.5rem 0.6rem;
  border: none;
  border-radius: var(--radius-md);
  background: var(--gradient);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition: box-shadow var(--dur) var(--ease), transform var(--dur-fast) var(--ease);
}
.new-session::after {
  /* hover light sweep across the gradient */
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(105deg, transparent 40%, rgba(255, 255, 255, 0.35) 50%, transparent 60%);
  transform: translateX(-100%);
}
.new-session:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.new-session:hover::after {
  animation: skeleton-sweep 700ms var(--ease);
}
.new-session:active {
  transform: none;
}

.search-wrap {
  position: relative;
  display: flex;
  align-items: center;
}
.search-icon {
  position: absolute;
  left: 0.55rem;
  color: var(--text-3);
  pointer-events: none;
}
.search {
  width: 100%;
  box-sizing: border-box;
  padding: 0.42rem 0.6rem 0.42rem 1.85rem;
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  background: var(--surface);
  color: var(--text-1);
  font: inherit;
  font-size: 0.84rem;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.search:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--tint), var(--shadow-sm);
}
.search::placeholder {
  color: var(--text-3);
}

/* -------------------------------------------------------------- list */
.list {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.list h3 {
  margin: 0.75rem 0.4rem 0.25rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.02em;
}
.session-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  border-radius: var(--radius-md);
  padding: 0 0.25rem;
  transition: background var(--dur-fast) var(--ease);
}
.session-row:hover {
  background: var(--surface-2);
}
.session-row.active {
  background: var(--tint);
}
.session-row.active::before {
  /* gradient left bar on the selected row */
  content: '';
  position: absolute;
  left: -0.15rem;
  top: 20%;
  bottom: 20%;
  width: 3px;
  border-radius: 2px;
  background: var(--gradient);
}
.session-row.active .title {
  color: var(--text-1);
  font-weight: 600;
}
.avatar {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-pill);
  font-size: 11px;
  font-weight: 700;
  background: hsl(var(--av-hue, 230) 75% 92%);
  color: hsl(var(--av-hue, 230) 55% 42%);
}
html[data-theme='dark'] .avatar {
  background: hsl(var(--av-hue, 230) 40% 24%);
  color: hsl(var(--av-hue, 230) 70% 78%);
}
.avatar.me {
  background: var(--gradient);
  color: #fff;
  width: 26px;
  height: 26px;
}
.title {
  flex: 1;
  min-width: 0;
  text-align: left;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.45rem 0.15rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.86rem;
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.title mark {
  background: transparent;
  color: var(--primary);
  font-weight: 700;
}
.pin-mark {
  display: inline-flex;
  color: var(--warn);
}
.menu-button {
  flex: 0 0 auto;
  border: none;
  background: none;
  cursor: pointer;
  padding: 0.25rem;
  border-radius: 6px;
  color: var(--text-3);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
  display: inline-flex;
}
.session-row:hover .menu-button,
.session-row.active .menu-button {
  opacity: 1;
}
.menu-button:hover {
  background: var(--surface-3);
  color: var(--text-1);
}
.row-menu {
  position: absolute;
  right: 0.3rem;
  top: calc(100% - 4px);
  z-index: 30;
  min-width: 8.6rem;
  display: flex;
  flex-direction: column;
  padding: 0.3rem;
  background: var(--surface);
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  animation: scale-in var(--dur) var(--ease);
}
.row-menu button {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  border: none;
  background: none;
  cursor: pointer;
  text-align: left;
  padding: 0.4rem 0.5rem;
  border-radius: var(--radius-sm);
  font-size: 0.82rem;
  color: var(--text-2);
  transition: background var(--dur-fast) var(--ease);
}
.row-menu button:hover {
  background: var(--surface-2);
}
.row-menu .drop {
  color: var(--danger);
}
.row-menu .drop:hover {
  background: rgba(239, 68, 68, 0.08);
}

.rename-input {
  flex: 1;
  min-width: 0;
  font: inherit;
  font-size: 0.85rem;
  padding: 0.3rem 0.45rem;
  border: 1px solid var(--primary);
  border-radius: var(--radius-sm);
  background: var(--surface);
  color: var(--text-1);
}
.rename-input:focus {
  outline: none;
  box-shadow: 0 0 0 3px var(--tint);
}
[data-testid='rename-confirm'] {
  border: none;
  background: var(--tint);
  color: var(--primary);
  border-radius: var(--radius-sm);
  cursor: pointer;
  padding: 0.2rem 0.45rem;
  font-size: 0.8rem;
}

.skeleton-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  padding: 0.55rem 0.35rem;
}
.sk-avatar,
.sk-line {
  position: relative;
  overflow: hidden;
  background: var(--surface-2);
  border-radius: var(--radius-pill);
}
.sk-avatar {
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
}
.sk-line {
  height: 12px;
  flex: 1;
}
.sk-avatar::after,
.sk-line::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, var(--surface-3), transparent);
  animation: skeleton-sweep 1.1s var(--ease) infinite;
}

.empty {
  color: var(--text-3);
  font-size: 0.82rem;
  padding: 0.4rem;
}

/* -------------------------------------------------------------- foot */
.foot {
  border-top: 1px solid var(--divider);
  padding-top: 0.55rem;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  font-size: 0.78rem;
  color: var(--text-3);
  position: relative;
}
.foot-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.who {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.35;
}
.brand {
  font-weight: 600;
  color: var(--text-1);
  font-size: 0.8rem;
}
.mode-line {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.foot-actions {
  margin-left: auto;
  display: flex;
  gap: 0.2rem;
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
  background: var(--surface-3);
  color: var(--text-1);
}
.settings-pop {
  position: absolute;
  bottom: 100%;
  left: 0.2rem;
  right: 0.2rem;
  z-index: 31;
  background: var(--surface);
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: 0.5rem;
  animation: scale-in var(--dur) var(--ease);
}
.settings-pop h4 {
  margin: 0 0 0.35rem;
  font-size: 0.75rem;
  color: var(--text-3);
  font-weight: 600;
}
.settings-pop button {
  display: block;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 0.8rem;
  color: var(--text-2);
  padding: 0.38rem 0.5rem;
  border-radius: var(--radius-sm);
}
.settings-pop button:hover {
  background: var(--surface-2);
}
.settings-pop button.on {
  background: var(--tint);
  color: var(--primary);
  font-weight: 600;
}
</style>
