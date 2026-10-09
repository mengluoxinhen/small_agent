import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vitest reads the `test` block from this same file.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // Backend routes live at the root (/sessions, /runs, /healthz); the dev
      // proxy owns the /api prefix and strips it before forwarding. SSE too.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    restoreMocks: true,
  },
})
