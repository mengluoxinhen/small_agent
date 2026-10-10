<script setup>
import { ref, computed } from 'vue'
import { ShieldAlert } from 'lucide-vue-next'

const props = defineProps({
  approval: { type: Object, required: true },
})

const emit = defineEmits(['decide'])
const reason = ref('')

const prettyArgs = computed(() => JSON.stringify(props.approval.arguments ?? {}, null, 2))

function reject() {
  emit('decide', { decision: 'reject', reason: reason.value })
}
</script>

<template>
  <div class="approval-dialog" data-testid="approval-dialog">
    <h3><ShieldAlert :size="16" class="shield" /> 工具调用需要你的确认</h3>
    <p class="lead">
      模型请求调用 <strong>{{ approval.tool }}</strong>（风险等级：<code>{{ approval.risk }}</code>）。
      下面是它将收到的参数，确认后才会真正执行。
    </p>
    <pre class="args">{{ prettyArgs }}</pre>
    <textarea
      v-model="reason"
      data-testid="reject-reason"
      rows="2"
      placeholder="拒绝理由（可选，会回给模型帮它调整方案）"
    ></textarea>
    <div class="actions">
      <button data-testid="approve" class="primary" @click="emit('decide', { decision: 'approve' })">
        批准本次
      </button>
      <button data-testid="approve-always" @click="emit('decide', { decision: 'approve', always: true })">
        批准并记住
      </button>
      <button data-testid="reject" class="danger" @click="reject">拒绝</button>
    </div>
  </div>
</template>

<style scoped>
/* V1: token-driven glass card, same pop language as ConfirmDialog */
.approval-dialog {
  border: 1px solid rgba(245, 158, 11, 0.45);
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 0.9rem 1.1rem;
  margin: 0.6rem 0;
  align-self: stretch;
  animation: fade-up var(--dur) var(--ease);
}
h3 {
  margin: 0 0 0.3rem;
  font-size: 1rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.shield {
  color: var(--warn);
}
.lead {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
  color: var(--text-2);
}
.lead code {
  background: var(--surface-2);
  border-radius: 6px;
  padding: 0.05rem 0.4rem;
  font-size: 0.82rem;
}
.args {
  margin: 0 0 0.5rem;
  padding: 0.5rem 0.7rem;
  background: var(--surface-2);
  border: 1px solid var(--divider);
  border-radius: var(--radius-sm);
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.82rem;
  max-height: 14rem;
  overflow: auto;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--divider);
  border-radius: var(--radius-sm);
  padding: 0.4rem 0.6rem;
  font: inherit;
  font-size: 0.85rem;
  background: var(--surface);
  color: var(--text-1);
}
textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--tint);
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.6rem;
}
button {
  padding: 0.35rem 0.8rem;
  border-radius: var(--radius-sm);
  border: 1px solid var(--divider);
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  transition: filter var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease);
}
button:hover {
  background: var(--surface-3);
}
button.primary {
  background: var(--gradient);
  border-color: transparent;
  color: #fff;
}
button.primary:hover {
  filter: brightness(1.06);
}
button.danger {
  background: none;
  border-color: var(--danger);
  color: var(--danger);
}
button.danger:hover {
  background: rgba(239, 68, 68, 0.08);
}
</style>
