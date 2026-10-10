<script setup>
import { reactive } from 'vue'
import { Circle, CircleCheck, CircleX, Loader, ChevronDown } from 'lucide-vue-next'

/**
 * V5 agent-step cards: a vertical timeline where each tool gets a status-icon
 * card — spinner while running (with a flowing gradient border), check on
 * success, x on failure, hollow dot while queued. Clicking a card expands the
 * pretty-printed arguments and the tool output. The four-state data-status
 * contract from U3 is untouched: the store snapshot tests and ChatView embed
 * rely on it.
 */

defineProps({
  trace: { type: Array, required: true },
  // embedded mode (steps inside an answer bubble) passes title="" to drop the heading
  title: { type: String, default: '执行轨迹' },
})

const STATE_LABELS = { pending: '排队中', running: '运行中', success: '成功', error: '失败' }

// index -> expanded; collapsed by default so a long tool chain stays scannable
const open = reactive({})

function toggle(index) {
  open[index] = !open[index]
}

function isFailed(step) {
  return Boolean(step.result) && step.result.ok === false
}

/** U3 four-state view of a step: queued -> running -> success | error. */
function statusFor(step) {
  if (!step.tool) return 'pending'
  if (!step.result) return 'running'
  return step.result.ok ? 'success' : 'error'
}

const ICONS = { pending: Circle, running: Loader, success: CircleCheck, error: CircleX }

function formatMs(ms) {
  return typeof ms === 'number' ? `${ms.toFixed(1)} ms` : ''
}

/** JSON args/output, pretty-printed when parseable, raw text otherwise. */
function pretty(value) {
  if (value === null || value === undefined || value === '') return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
</script>

<template>
  <section class="trace">
    <h2 v-if="title">{{ title }}</h2>
    <p v-if="!trace.length" class="placeholder">（暂无执行步骤）</p>
    <ol v-else class="timeline">
      <li
        v-for="(step, i) in trace"
        :key="step.call_id || i"
        class="step"
        :class="[
          `status-${statusFor(step)}`,
          { failed: isFailed(step), pending: !step.result, open: open[i] },
        ]"
        :data-status="statusFor(step)"
        data-testid="trace-step"
        @click="toggle(i)"
      >
        <span class="node">
          <component
            :is="ICONS[statusFor(step)]"
            :size="15"
            :class="['status-icon', { spin: statusFor(step) === 'running' }]"
          />
        </span>
        <div class="card">
          <div class="summary">
            <span class="tool">{{ step.tool || '…' }}</span>
            <span v-if="step.risk" class="risk">{{ step.risk }}</span>
            <span v-if="step.result" class="duration">{{ formatMs(step.result.duration_ms) }}</span>
            <span class="state">{{ STATE_LABELS[statusFor(step)] }}</span>
            <ChevronDown :size="14" class="chev" />
          </div>
          <div v-if="open[i]" class="detail">
            <div class="seg">
              <h4>参数</h4>
              <pre class="args">{{ pretty(step.args) || '(无参数)' }}</pre>
            </div>
            <div class="seg">
              <h4>结果</h4>
              <pre class="output">{{ pretty(step.result ? step.result.output : '') || '(运行中)' }}</pre>
            </div>
          </div>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.trace {
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  padding: 0.7rem 0.9rem;
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
.trace h2 {
  margin: 0 0 0.5rem;
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--text-2);
}
.placeholder {
  color: var(--text-3);
  font-size: 0.85rem;
}

/* ------------------------------------------------------------ timeline */

ol.timeline {
  margin: 0;
  padding: 0;
  list-style: none;
  position: relative;
}
ol.timeline::before {
  /* connector line behind the nodes */
  content: '';
  position: absolute;
  left: 10px;
  top: 14px;
  bottom: 14px;
  width: 2px;
  background: var(--divider);
  border-radius: 2px;
}
.step {
  display: flex;
  align-items: flex-start;
  gap: 0.55rem;
  padding: 0.25rem 0;
  cursor: pointer;
  position: relative;
}
.node {
  flex: 0 0 auto;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface);
  border: 1px solid var(--divider);
  z-index: 1;
  color: var(--text-3);
}
.status-success .node {
  color: var(--success);
  border-color: rgba(16, 185, 129, 0.4);
}
.status-error .node {
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.4);
}
.status-running .node {
  color: var(--info);
  border-color: rgba(59, 130, 246, 0.4);
}
.status-icon.spin {
  animation: spin 0.9s linear infinite;
}

.card {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--divider);
  border-radius: var(--radius-md);
  background: var(--surface);
  padding: 0.42rem 0.7rem;
  transition: box-shadow var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.step:hover .card {
  box-shadow: var(--shadow-md);
}
.status-error .card {
  border-color: rgba(239, 68, 68, 0.35);
}

/* flowing gradient border while the tool is executing */
.status-running .card {
  border: 1px solid transparent;
  background: linear-gradient(var(--surface), var(--surface)) padding-box,
    linear-gradient(90deg, #4d6bfe, #7c5cff, #3b82f6, #4d6bfe) border-box;
  background-size: 100% 100%, 200% 100%;
  animation: border-flow 1.8s linear infinite;
}

.summary {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  font-size: 0.85rem;
  color: var(--text-1);
}
.tool {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.risk {
  color: var(--text-3);
  font-size: 0.72rem;
  background: var(--surface-2);
  border-radius: var(--radius-pill);
  padding: 0.02rem 0.5rem;
}
.duration {
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  font-size: 0.78rem;
}
.state {
  margin-left: auto;
  font-size: 0.75rem;
  color: var(--text-3);
}
.status-success .state {
  color: var(--success);
}
.status-running .state {
  color: var(--info);
}
.status-pending .state {
  color: var(--warn);
}
.step.failed .state,
.step.failed .tool,
.status-error .state {
  color: var(--danger);
}
.chev {
  color: var(--text-3);
  transition: transform var(--dur) var(--ease);
  flex: 0 0 auto;
}
.step.open .chev {
  transform: rotate(180deg);
}

.detail {
  margin-top: 0.45rem;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--divider);
  animation: fade-up var(--dur) var(--ease);
}
.seg h4 {
  margin: 0.3rem 0 0.15rem;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-3);
}
.detail pre {
  margin: 0;
  padding: 0.45rem 0.6rem;
  background: var(--surface-2);
  border: 1px solid var(--divider);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.78rem;
  line-height: 1.5;
  max-height: 12rem;
  overflow: auto;
  color: var(--text-2);
}
.detail pre.output {
  background: var(--surface-3);
}
</style>
