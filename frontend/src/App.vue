<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useUiStore } from './stores/ui'
import SessionSidebar from './components/SessionSidebar.vue'
import ChatView from './components/ChatView.vue'
import ToastHost from './components/ToastHost.vue'

/**
 * V2 shell: full-height grid (sidebar | drag handle | chat), no page scroll.
 * Desktop: the handle drags the sidebar between 240–360px (persisted in the ui
 * store); collapse keeps a 44px rail. Mobile (<768px): the sidebar becomes an
 * overlay drawer with a blurred scrim and a swipe-left-to-close gesture.
 */

const ui = useUiStore()

const isMobile = ref(false)
const dragging = ref(false)
const mq = typeof window !== 'undefined' ? window.matchMedia?.('(max-width: 767px)') ?? null : null

function syncMobile() {
  if (mq) isMobile.value = mq.matches
}

const gridStyle = computed(() => {
  if (isMobile.value) return { gridTemplateColumns: '1fr' }
  const side = ui.sidebarCollapsed ? '44px' : `${ui.sidebarWidth}px`
  return { gridTemplateColumns: ui.sidebarCollapsed ? `${side} 1fr` : `${side} 5px 1fr` }
})

// ------------------------------------------------------------ resize drag

function onDragStart(event) {
  dragging.value = true
  document.body.style.userSelect = 'none'
  event.currentTarget.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', onDragEnd)
}

function onDragMove(event) {
  if (dragging.value) ui.setSidebarWidth(event.clientX)
}

function onDragEnd() {
  dragging.value = false
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
}

// --------------------------------------------------------------- drawer

let touchX = null

function onTouchStart(event) {
  touchX = event.touches?.[0]?.clientX ?? null
}

function onTouchEnd(event) {
  if (touchX === null) return
  const dx = (event.changedTouches?.[0]?.clientX ?? touchX) - touchX
  touchX = null
  if (dx < -60) ui.closeDrawer() // swipe left closes the drawer
}

onMounted(() => {
  syncMobile()
  mq?.addEventListener?.('change', syncMobile)
})

onBeforeUnmount(() => {
  mq?.removeEventListener?.('change', syncMobile)
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', onDragEnd)
})
</script>

<template>
  <div class="app" :class="{ mobile: isMobile, dragging }" :style="gridStyle">
    <div
      v-if="isMobile && ui.drawerOpen"
      class="scrim"
      data-testid="drawer-scrim"
      @click="ui.closeDrawer()"
    ></div>

    <div class="sidebar-slot" :class="{ open: ui.drawerOpen }" @touchstart="onTouchStart" @touchend="onTouchEnd">
      <SessionSidebar />
    </div>

    <div
      v-if="!isMobile && !ui.sidebarCollapsed"
      class="handle"
      data-testid="resize-handle"
      title="拖拽调整宽度"
      @pointerdown="onDragStart"
    ></div>

    <ChatView />
    <ToastHost />
  </div>
</template>

<style scoped>
.app {
  display: grid;
  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  background: var(--bg-right);
}
.app.dragging {
  cursor: col-resize;
}

.sidebar-slot {
  position: relative;
  min-width: 0;
  height: 100%;
}

.handle {
  cursor: col-resize;
  background: transparent;
  position: relative;
  z-index: 5;
}
.handle::after {
  content: '';
  position: absolute;
  inset: 0 -2px;
  background: var(--divider);
  transition: background var(--dur) var(--ease);
}
.handle:hover::after,
.app.dragging .handle::after {
  background: var(--tint-strong);
}

/* -------------------------------------------------- mobile overlay drawer */

.scrim {
  position: fixed;
  inset: 0;
  z-index: 45;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  animation: fade-up var(--dur) var(--ease);
}

.app.mobile {
  grid-template-columns: 1fr;
}
.app.mobile .sidebar-slot {
  position: fixed;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 50;
  width: min(84vw, 320px);
  transform: translateX(-105%);
  transition: transform var(--dur-slow) var(--ease);
  box-shadow: none;
}
.app.mobile .sidebar-slot :deep(.sidebar) {
  height: 100%;
  width: 100%;
  min-width: 0;
  border-right: 1px solid var(--divider);
}
.app.mobile .sidebar-slot.open {
  transform: none;
  box-shadow: var(--shadow-lg);
}
</style>
