<script setup>
import { useUiStore } from './stores/ui'
import ChatView from './components/ChatView.vue'

const ui = useUiStore()
</script>

<template>
  <header class="bar">
    <h1>small_dify Agent</h1>
    <p class="mode-line">
      运行模式：<strong data-testid="mode">{{ ui.mode }}</strong>
      <span class="hint">（切换开关在右下角对话面板顶栏，作用于下一条消息）</span>
    </p>
  </header>
  <ChatView />
</template>

<style scoped>
.bar {
  max-width: 1080px;
  margin: 1rem auto 0;
  padding: 0 1rem;
}
.bar h1 {
  margin: 0;
  font-size: 1.3rem;
}
.mode-line {
  margin: 0.3rem 0 0;
  font-size: 0.82rem;
  color: #666;
}
.hint {
  color: #999;
}
</style>
