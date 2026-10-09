<script setup>
import { ref, computed } from 'vue'

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
    <h3>工具调用需要你的确认</h3>
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
.approval-dialog {
  border: 1px solid #e6b422;
  background: #fffbe8;
  border-radius: 8px;
  padding: 0.8rem 1rem;
  margin: 0.6rem 0;
}
h3 {
  margin: 0 0 0.3rem;
  font-size: 1rem;
}
.lead {
  margin: 0 0 0.5rem;
  font-size: 0.9rem;
}
.args {
  margin: 0 0 0.5rem;
  padding: 0.5rem 0.7rem;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-all;
  font-size: 0.82rem;
  max-height: 14rem;
  overflow: auto;
}
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 0.4rem 0.6rem;
  font: inherit;
  font-size: 0.85rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.6rem;
}
button {
  padding: 0.35rem 0.8rem;
  border-radius: 6px;
  border: 1px solid #ccc;
  background: #fff;
  cursor: pointer;
}
button.primary {
  background: #2e7d32;
  border-color: #2e7d32;
  color: #fff;
}
button.danger {
  background: #c0392b;
  border-color: #c0392b;
  color: #fff;
}
</style>
