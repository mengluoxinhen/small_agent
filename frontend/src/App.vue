<script setup>
import SessionSidebar from './components/SessionSidebar.vue'
import ChatView from './components/ChatView.vue'
</script>

<template>
  <div class="app">
    <SessionSidebar />
    <ChatView />
  </div>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}
body {
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif;
  color: #222;
  background: #fff;
}
</style>

<style scoped>
.app {
  display: grid;
  grid-template-columns: auto 1fr;
  height: 100vh;
  overflow: hidden;
}
</style>
