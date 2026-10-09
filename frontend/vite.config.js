import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Vitest reads the `test` block from this same file.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // Backend (uvicorn) owns /api; SSE goes through here too.
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    restoreMocks: true,
  },
})
