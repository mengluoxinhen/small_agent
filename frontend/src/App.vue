<script setup>
import { useUiStore } from './stores/ui'

const ui = useUiStore()
</script>

<template>
  <main class="shell">
    <h1>small_dify Agent</h1>
    <p class="stage">
      P0 脚手架已就绪。对话面板、执行轨迹与审批弹窗在 P7 接入。
    </p>
    <p class="mode">当前运行模式：<strong data-testid="mode">{{ ui.mode }}</strong></p>
  </main>
</template>

<style scoped>
.shell {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  max-width: 720px;
  margin: 3rem auto;
}
.stage {
  color: #666;
}
</style>
