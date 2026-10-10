<script setup>
import { CircleAlert } from 'lucide-vue-next'

/**
 * V3: the sanctioned replacement for window.confirm — a small modal Popconfirm.
 * The parent owns the pending action; this dialog only reports ok/cancel.
 */

defineProps({
  title: { type: String, default: '确认操作' },
  message: { type: String, default: '' },
  confirmText: { type: String, default: '删除' },
})
const emit = defineEmits(['ok', 'cancel'])
</script>

<template>
  <div class="layer" data-testid="confirm-dialog" @click.self="emit('cancel')">
    <div class="dialog" role="alertdialog" aria-modal="true">
      <div class="head">
        <CircleAlert :size="18" class="warn-icon" />
        <h3>{{ title }}</h3>
      </div>
      <p v-if="message" class="msg">{{ message }}</p>
      <div class="row">
        <button class="ghost" data-testid="confirm-cancel" @click="emit('cancel')">取消</button>
        <button class="danger" data-testid="confirm-ok" @click="emit('ok')">{{ confirmText }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.layer {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(3px);
  animation: fade-up var(--dur) var(--ease);
}
.dialog {
  width: min(26rem, calc(100vw - 2rem));
  background: var(--surface);
  border: 1px solid var(--divider);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 1.1rem 1.2rem;
  animation: scale-in var(--dur) var(--ease);
}
.head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.head h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-1);
}
.warn-icon {
  color: var(--danger);
}
.msg {
  margin: 0.6rem 0 0;
  font-size: 0.86rem;
  color: var(--text-3);
  line-height: 1.6;
}
.row {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-top: 1rem;
}
.row button {
  border-radius: var(--radius-sm);
  padding: 0.35rem 0.95rem;
  font-size: 0.85rem;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease);
}
.ghost {
  background: var(--surface-2);
  color: var(--text-2);
  border-color: var(--divider);
}
.ghost:hover {
  background: var(--surface-3);
}
.danger {
  background: var(--danger);
  color: #fff;
}
.danger:hover {
  filter: brightness(0.94);
}
</style>
