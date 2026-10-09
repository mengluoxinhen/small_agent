<script setup>
import { reactive } from 'vue'

defineProps({
  trace: { type: Array, required: true },
})

// index -> expanded; collapsed by default so a long tool chain stays scannable
const open = reactive({})

function toggle(index) {
  open[index] = !open[index]
}

function isFailed(step) {
  return Boolean(step.result) && step.result.ok === false
}

function formatMs(ms) {
  return typeof ms === 'number' ? `${ms.toFixed(1)} ms` : ''
}
</script>

<template>
  <section class="trace">
    <h2>执行轨迹</h2>
    <p v-if="!trace.length" class="placeholder">（暂无执行步骤）</p>
    <ol v-else>
      <li
        v-for="(step, i) in trace"
        :key="step.call_id || i"
        class="step"
        :class="{ failed: isFailed(step), pending: !step.result }"
        data-testid="trace-step"
        @click="toggle(i)"
      >
        <div class="summary">
          <span class="tool">{{ step.tool || '…' }}</span>
          <span class="risk">{{ step.risk }}</span>
          <span v-if="step.result" class="duration">{{ formatMs(step.result.duration_ms) }}</span>
          <span class="state">{{ step.result ? (step.result.ok ? '成功' : '失败') : '等待结果' }}</span>
        </div>
        <div v-if="open[i]" class="detail">
          <pre class="args">{{ step.args || '(无参数)' }}</pre>
          <pre class="output">{{ step.result ? step.result.output : '(运行中)' }}</pre>
        </div>
      </li>
    </ol>
  </section>
</template>

<style scoped>
.trace {
  border: 1px solid #ddd;
  border-radius: 8px;
  padding: 0.6rem 0.8rem;
  background: #fafafa;
}
.trace h2 {
  margin: 0 0 0.4rem;
  font-size: 0.95rem;
  color: #555;
}
.placeholder {
  color: #999;
  font-size: 0.85rem;
}
ol {
  margin: 0;
  padding: 0;
  list-style: none;
}
.step {
  border-bottom: 1px solid #eee;
  padding: 0.3rem 0;
  cursor: pointer;
}
.step:last-child {
  border-bottom: none;
}
.summary {
  display: flex;
  gap: 0.7rem;
  align-items: baseline;
  font-size: 0.88rem;
}
.tool {
  font-weight: 600;
}
.risk {
  color: #888;
  font-size: 0.78rem;
}
.duration {
  color: #666;
  font-variant-numeric: tabular-nums;
}
.step.failed .state,
.step.failed .tool {
  color: #c0392b;
}
.step.pending .state {
  color: #b9770e;
}
.detail pre {
  margin: 0.3rem 0 0;
  padding: 0.4rem 0.6rem;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.8rem;
  max-height: 12rem;
  overflow: auto;
}
</style>
