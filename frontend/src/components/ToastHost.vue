<script setup>
import { CircleCheck, CircleX, Info, X } from 'lucide-vue-next'
import { useToastStore } from '../stores/toast'

/**
 * V6: renders the toast store's stack in the top-right corner. Each toast slides
 * in, expires on its own (stores/toast.js) and can be closed early.
 */

const toast = useToastStore()
</script>

<template>
  <div class="host" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in toast.items" :key="t.id" class="toast" :class="t.kind" data-testid="toast">
        <component
          :is="t.kind === 'success' ? CircleCheck : t.kind === 'error' ? CircleX : Info"
          :size="15"
          class="t-icon"
        />
        <span>{{ t.text }}</span>
        <button class="close" title="关闭" @click="toast.dismiss(t.id)">
          <X :size="13" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.host {
  position: fixed;
  top: 1rem;
  right: 1rem;
  z-index: 80;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  max-width: 22rem;
  padding: 0.55rem 0.8rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--divider);
  background: var(--glass-bg);
  backdrop-filter: saturate(1.4) blur(12px);
  box-shadow: var(--shadow-md);
  font-size: 0.84rem;
  color: var(--text-1);
  animation: toast-in var(--dur-slow) var(--ease);
}
.toast .t-icon {
  flex: 0 0 auto;
}
.toast.success .t-icon {
  color: var(--success);
}
.toast.error .t-icon {
  color: var(--danger);
}
.toast.info .t-icon {
  color: var(--info);
}
.close {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-3);
  display: inline-flex;
  padding: 0.15rem;
  border-radius: 6px;
}
.close:hover {
  color: var(--text-1);
  background: var(--surface-2);
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(24px);
}
.toast-leave-active {
  transition: all var(--dur) var(--ease);
  position: absolute;
}
</style>
